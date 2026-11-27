"""Internal GridAgent scientific IPC. No MCP or model provider dependency.

One trusted desktop-owned process per selected workspace. The first protocol
version provides metadata and bounded read operations; mutation and execution
lanes require a separate host-controlled authorization and cancellation design.
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
}


def dispatch(root: Path, method: str, params: dict):
    schema = METHODS.get(method)
    if schema is None:
        raise ValueError("Unknown native method")
    args = schema.model_validate(params).model_dump()
    if method == "hello":
        return {"protocol": VERSION, "methods": sorted(METHODS), "mode": "read-only"}
    if method == "scientific.status":
        from .scientific_runtime import status

        return status(root)
    if method == "solver.backends":
        from .native_backends import available_backends

        return available_backends(root)
    ws.require_grant(root)
    if method == "workspace.files":
        return ws.list_project(root)
    if method == "scientific.runs":
        return ws.list_scientific_runs(root, **args)
    if method == "scientific.artifact":
        return ws.read_artifact(root, **args)
    if method == "solver.table":
        from .native_results import read_table

        return read_table(root, **args)
    raise ValueError("Unknown native method")


def serve(root, source, output):
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
                result = dispatch(root, frame.method, frame.params)
            send(identifier, ok=True, result=result)
        except (ValidationError, ValueError, OSError, TypeError) as exc:
            code = "invalid_request" if isinstance(exc, (ValidationError, ValueError, TypeError)) else "io_failure"
            send(identifier, ok=False, error={"code": code})
        except Exception:  # noqa: BLE001 - protocol boundary; never leak host paths
            send(identifier, ok=False, error={"code": "runtime_failure"})


def main():
    if len(sys.argv) != 2:
        return 2
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        return 2
    serve(root, sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
