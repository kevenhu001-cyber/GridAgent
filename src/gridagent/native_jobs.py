"""Durable first-party scientific job control; worker never runs arbitrary host code."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from threading import Thread

from filelock import FileLock

from . import scientific_workspace as ws

ID = re.compile(r"[a-f0-9]{32}")
TERMINAL = {"ok", "failed", "cancelled", "timeout", "cleanup_unconfirmed", "recovered_incomplete"}


def _base(root):
    return ws.directory(root, "native-jobs")


def _folder(root, job_id):
    if not isinstance(job_id, str) or not ID.fullmatch(job_id):
        raise ValueError("Invalid native job ID")
    folder = _base(root) / job_id
    ws.plain(folder, directory=True)
    return folder


def _read(path):
    return json.loads(ws.bounded_bytes(path, ws.MAX_FILE))


def _save(folder, name, value):
    ws.atomic_bytes(folder / name, json.dumps(value, allow_nan=False).encode())


def status(root, job_id):
    folder = _folder(root, job_id)
    result = _read(folder / "state.json")
    result["cancellation_requested"] = (folder / "cancel-requested").exists()
    return result


def latest(root):
    """Read the workspace's last committed job pointer without starting a worker."""
    base = Path(root).resolve() / "native-jobs"
    try:
        ws.plain(base, directory=True)
        job_id = _read(base / "active.json")["job_id"]
    except FileNotFoundError:
        return {"job": None}
    saved = status(root, job_id)
    return {"job": {
        "job_id": job_id,
        "status": saved["status"],
        "outcome": "recorded_terminal" if saved["status"] in TERMINAL else "unconfirmed",
        "run_id": saved.get("run_id"),
        "cancellation_requested": saved["cancellation_requested"],
    }}


def _launch_worker(root, job_id):
    from .plugins import clean_env

    env = clean_env()
    for key in ("GRIDAGENT_SANDBOX_RUNTIME", "GRIDAGENT_PLUGIN_ROOT"):
        if key in os.environ:
            env[key] = os.environ[key]
    options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS} if (
        os.name == "nt") else {"start_new_session": True}
    child = subprocess.Popen(
        [sys.executable, "-I", "-X", "utf8", "-m", "gridagent.native_jobs", str(root), job_id],
        cwd=Path(sys.executable).parent, env=env, stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **options,
    )
    Thread(target=child.wait, daemon=True).start()


def submit(root, job_id, entry, arguments, plugin_ids, *, launch=_launch_worker, shell_command=None, kernel_cells=None):
    ws.require_grant(root)
    ws.safe_parts(entry)
    if not entry.endswith(".py"):
        raise ValueError("Entry must be Python")
    if not isinstance(job_id, str) or not ID.fullmatch(job_id):
        raise ValueError("Invalid native job ID")
    base = _base(root)
    folder = base / job_id
    request = {"entry": entry, "arguments": arguments, "plugin_ids": plugin_ids}
    if shell_command is not None:
        from .scientific_runtime import isolated_shell_source

        isolated_shell_source(shell_command["shell"], shell_command["command"])
        request["shell_command"] = shell_command
    if kernel_cells is not None:
        from .kernel_batch import validate_cells

        validate_cells(kernel_cells)
        if shell_command is not None or plugin_ids or arguments:
            raise ValueError("Kernel batch cannot be combined with shell, plugins or script arguments")
        request["kernel_cells"] = kernel_cells
    with FileLock(str(base / "submit.lock"), timeout=2):
        if folder.exists():
            folder = _folder(root, job_id)
            if _read(folder / "request.json") != request:
                raise ValueError("Job ID already bound to another request")
            return status(root, job_id)
        active_path = base / "active.json"
        if active_path.exists():
            prior = _read(active_path)["job_id"]
            if status(root, prior)["status"] not in TERMINAL:
                raise ValueError("Native job already active or interrupted; explicit recovery required")
        folder.mkdir()
        _save(folder, "request.json", request)
        _save(folder, "state.json", {"job_id": job_id, "status": "queued"})
        _save(base, "active.json", {"job_id": job_id})
        try:
            launch(root, job_id)
        except OSError:
            _save(folder, "state.json", {"job_id": job_id, "status": "failed",
                                         "reason": "Worker could not start"})
        return status(root, job_id)


def submit_shell(root, job_id, shell, command):
    return submit(root, job_id, "internal-shell.py", [], [],
                  shell_command={"shell": shell, "command": command})


def cancel(root, job_id):
    folder = _folder(root, job_id)
    if status(root, job_id)["status"] not in TERMINAL:
        ws.atomic_bytes(folder / "cancel-requested", b"1")
    return status(root, job_id)


def run_worker(root, job_id, *, execute=None):
    from .scientific_runtime import execute as run

    folder = _folder(root, job_id)
    # No job can be automatically relaunched after a crash. An exclusive
    # per-job lock also prevents duplicate workers from running concurrently.
    with FileLock(str(folder / "worker.lock"), timeout=0):
        if status(root, job_id)["status"] != "queued":
            return
        request = _read(folder / "request.json")
        _save(folder, "state.json", {"job_id": job_id, "status": "running"})
        def cancelled():
            return (folder / "cancel-requested").exists() or not ws.enabled(root)

        try:
            if cancelled():
                result = {"status": "cancelled", "reason": "Cancelled before execution"}
            else:
                result = (execute or run)(root, **request, run_id=job_id, cancelled=cancelled)
            final = {"job_id": job_id, "status": result["status"], "reason": result.get("reason"),
                     "run_id": result.get("run_id"), "verification": result.get("verification"),
                     "exit_code": result.get("exit_code"),
                     "stdout_stderr_tail": result.get("stdout_stderr_tail", "")}
            if final["status"] not in TERMINAL:
                final["status"] = "failed"
        except Exception as exc:  # noqa: BLE001 - job boundary, no host path disclosure
            final = {"job_id": job_id, "status": "failed", "reason": type(exc).__name__}
        _save(folder, "state.json", final)


def main():
    if len(sys.argv) != 3:
        return 2
    root = Path(sys.argv[1]).resolve()
    if not root.is_dir():
        return 2
    run_worker(root, sys.argv[2])
    return 0


if __name__ == "__main__":
    sys.exit(main())
