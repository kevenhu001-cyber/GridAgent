"""Internal GridAgent scientific IPC. No MCP or model provider dependency.

One trusted desktop-owned process per selected workspace. The first protocol
version provides metadata and bounded reads, plus explicitly enabled developer
job control. No execution is performed on the IPC reader thread.
"""
import json
import re
import sys
from contextlib import redirect_stdout
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import scientific_workspace as ws

VERSION = 1
MAX_REQUEST = 64 * 1024
MAX_RESPONSE = 4 * 1024 * 1024


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Empty(Strict):
    pass


class RunPage(Strict):
    limit: int = Field(default=20, ge=1, le=50)


class ArtifactPage(Strict):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    path: str = Field(min_length=1, max_length=240)
    offset: int = Field(default=0, ge=0, le=64 * 1024 * 1024)
    limit: int = Field(default=12000, ge=1, le=12000)


class NativeTable(Strict):
    run_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    table: str = Field(min_length=1, max_length=80)
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=20, ge=1, le=50)


class ProjectRead(Strict):
    path: str = Field(min_length=1, max_length=240)
    offset: int = Field(default=0, ge=0, le=ws.MAX_FILE)
    limit: int = Field(default=12000, ge=1, le=12000)


class ProjectWrite(Strict):
    path: str = Field(min_length=1, max_length=240)
    text: str = Field(max_length=48000)
    expected_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


class JobRef(Strict):
    job_id: str = Field(pattern=r"^[a-f0-9]{32}$")


class JobSubmit(JobRef):
    entry: str = Field(min_length=1, max_length=240)
    arguments: list[str] = Field(default_factory=list, max_length=32)
    plugin_ids: list[str] = Field(default_factory=list, max_length=4)


class Frame(Strict):
    version: int
    id: str = Field(pattern=r"^[a-f0-9]{32}$")
    method: str = Field(max_length=64)
    params: dict


METHODS = {
    "hello": Empty,
    "scientific.status": Empty,
    "scientific.runs": RunPage,
    "scientific.artifact": ArtifactPage,
    "solver.backends": Empty,
    "solver.table": NativeTable,
    "workspace.files": Empty,
    "workspace.read": ProjectRead,
    "job.status": JobRef,
}


TASK_METHODS = {"workspace.write": ProjectWrite, "job.submit": JobSubmit, "job.cancel": JobRef}


def dispatch(root: Path, method: str, params: dict, *, allow_tasks=False):
    schema = METHODS.get(method) or (TASK_METHODS.get(method) if allow_tasks else None)
    if schema is None:
        raise ValueError("Unknown native method")
    args = schema.model_validate(params).model_dump()
    if method == "hello":
        return {"protocol": VERSION, "methods": sorted(METHODS | (TASK_METHODS if allow_tasks else {})),
                "mode": "developer-tasks" if allow_tasks else "read-only"}
    if method == "scientific.status":
        from .scientific_runtime import status

        return status(root)
    if method == "solver.backends":
        from .native_backends import available_backends

        return available_backends(root)
    ws.require_grant(root)
    if method == "workspace.files":
        return ws.list_project(root)
    if method == "workspace.read":
        return ws.read_project(root, **args)
    if method == "workspace.write":
        return ws.write_project(root, **args)
    if method.startswith("job."):
        from . import native_jobs

        handler = {"job.status": native_jobs.status, "job.submit": native_jobs.submit,
                   "job.cancel": native_jobs.cancel}[method]
        return handler(root, **args)
    if method == "scientific.runs":
        return ws.list_scientific_runs(root, **args)
    if method == "scientific.artifact":
        return ws.read_artifact(root, **args)
    if method == "solver.table":
        from .native_results import read_table

        return read_table(root, **args)
    raise ValueError("Unknown native method")


def serve(root, source, output, *, allow_tasks=False):
    """Bounded line frames; never replay an operation after a broken connection."""
    def send(identifier, **payload):
        frame = {"version": VERSION, "id": identifier, **payload}
        encoded = json.dumps(frame, ensure_ascii=True, allow_nan=False)
        if len(encoded) > MAX_RESPONSE:
            encoded = json.dumps({"version": VERSION, "id": identifier, "ok": False,
                                  "error": {"code": "response_too_large"}})
        print(encoded, file=output, flush=True)

    while True:
        line = source.readline(MAX_REQUEST + 1)
        if not line or len(line) > MAX_REQUEST or not line.endswith("\n"):
            return
        try:
            raw = json.loads(line)
            identifier = raw["id"]
            if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{32}", identifier):
                return
        except (ValueError, KeyError, TypeError):
            return
        try:
            frame = Frame.model_validate(raw)
            if frame.version != VERSION:
                raise ValueError("Unsupported protocol version")
            with redirect_stdout(sys.stderr):
                result = dispatch(root, frame.method, frame.params, allow_tasks=allow_tasks)
            send(identifier, ok=True, result=result)
        except (ValidationError, ValueError, OSError, TypeError) as exc:
            code = "invalid_request" if isinstance(exc, (ValidationError, ValueError, TypeError)) else "io_failure"
            send(identifier, ok=False, error={"code": code})
        except Exception:  # noqa: BLE001 - protocol boundary; never leak host paths
            send(identifier, ok=False, error={"code": "runtime_failure"})


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--tasks"):
        return 2
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        return 2
    serve(root, sys.stdin, sys.stdout, allow_tasks=len(sys.argv) == 3)
    return 0


if __name__ == "__main__":
    sys.exit(main())
