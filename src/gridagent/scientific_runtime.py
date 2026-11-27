"""General Python runner using Windows Sandbox, with no unrestricted host fallback."""
import json
import subprocess
import time
from contextlib import nullcontext
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from filelock import FileLock

from . import plugins
from . import scientific_workspace as ws
from .verified_python import require_runtime

PROTOCOL = "scientific-python-v1"
TIMEOUT = 120
BOOTSTRAP = r"""
import os
import runpy
import shutil
import sys
from pathlib import Path

project = Path(r"C:\GridAgentWork")
shutil.copytree(r"C:\GridAgentInput\project", project)
entry = sys.argv[1]
sys.path.insert(0, str(project))
plugin = Path(r"C:\GridAgentPlugin")
if plugin.is_dir():
    sys.path.insert(0, str(plugin))
os.environ["GRIDAGENT_PROJECT_DIR"] = str(project)
os.environ["GRIDAGENT_OUTPUT_DIR"] = r"C:\GridAgentOutput"
os.chdir(project)
sys.argv = [str(project / entry)]
runpy.run_path(str(project / entry), run_name="__main__")
"""


def configuration(runtime, inputs, output, plugin=None):
    config = ET.Element("Configuration")
    for name in ("Networking", "VGpu", "ClipboardRedirection", "PrinterRedirection", "AudioInput", "VideoInput"):
        ET.SubElement(config, name).text = "Disable"
    ET.SubElement(config, "MemoryInMB").text = "4096"
    mappings = ET.SubElement(config, "MappedFolders")
    folders = [(runtime, r"C:\GridAgentRuntime", True), (inputs, r"C:\GridAgentInput", True),
               (output, r"C:\GridAgentOutput", False)]
    if plugin is not None:
        folders.append((plugin, r"C:\GridAgentPlugin", True))
    for host, guest, readonly in folders:
        row = ET.SubElement(mappings, "MappedFolder")
        ET.SubElement(row, "HostFolder").text = str(host)
        ET.SubElement(row, "SandboxFolder").text = guest
        ET.SubElement(row, "ReadOnly").text = str(readonly).lower()
    ET.SubElement(ET.SubElement(config, "LogonCommand"), "Command").text = (
        r"cmd.exe /c C:\GridAgentInput\launch.cmd")
    return ET.tostring(config, encoding="unicode")


def status(root):
    try:
        require_runtime()
        available = True
    except ValueError:
        available = False
    return {"status": "ok", "enabled": ws.enabled(root), "sandbox_available": available,
            "backend": "Windows Sandbox CLI", "timeout_seconds": TIMEOUT,
            "plugins": [{"id": row["id"], "versions": row["versions"],
                         "managed_available": plugins.installed_target(row["id"]) is not None}
                        for row in plugins.status()],
            "scope": "one optional managed plugin per run; no host fallback; no network"}


def _launch(root, folder, executable, config):
    session = str(uuid4())
    ws.atomic_bytes(folder / "session-id.txt", session.encode("ascii"))
    kwargs = {"env": plugins.clean_env(), "stdin": subprocess.DEVNULL,
              "stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    output = folder / "output"
    marker = output / "exit-code.txt"
    state, reason = "failed", "Sandbox launch failed"
    try:
        subprocess.run([executable, "start", "--id", session, "--config", config],
                       timeout=60, check=True, **kwargs)
        deadline = time.monotonic() + TIMEOUT
        while True:
            if not ws.enabled(root) or (folder / "cancel-requested").exists():
                state, reason = "cancelled", "Cancellation or authorization revoked"
                break
            if time.monotonic() >= deadline:
                state, reason = "timeout", "Execution exceeded time budget"
                break
            ws.scan(output, limit=ws.MAX_OUTPUT, per_file=ws.MAX_OUTPUT)
            if marker.exists():
                state, reason = "finished", None
                break
            time.sleep(.25)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = type(exc).__name__
    finally:
        try:
            subprocess.run([executable, "stop", "--id", session], timeout=30, check=True, **kwargs)
        except (OSError, subprocess.SubprocessError):
            return "cleanup_unconfirmed", "Sandbox shutdown could not be confirmed"
    return state, reason


def execute(root, entry, plugin=None):
    ws.require_grant(root)
    ws.safe_parts(entry)
    if not entry.endswith(".py"):
        raise ValueError("Entry must be a project Python file")
    executable, runtime = require_runtime()
    root = Path(root).resolve()
    plugin_lock = nullcontext()
    if plugin is not None:
        plugins.spec(plugin)
        plugin_lock = FileLock(str(plugins.plugin_root() / (plugin + ".lock")), timeout=0)
    with FileLock(str(root / "scientific-execution.lock"), timeout=0), plugin_lock:
        target = plugins.installed_target(plugin) if plugin is not None else None
        if plugin is not None and target is None:
            raise ValueError("Install this managed plugin before using its native API")
        identifier = uuid4().hex
        folder = ws.directory(root, "scientific-runs") / identifier
        folder.mkdir()
        inputs = folder / "input"
        snapshot = ws.snapshot(root, inputs / "project")
        if entry not in {row["path"] for row in snapshot}:
            raise ValueError("Entry not found in project snapshot")
        compile(ws.bounded_bytes(ws.scoped(inputs / "project", entry), ws.MAX_FILE),
                entry, "exec", dont_inherit=True)
        output = folder / "output"
        output.mkdir()
        (inputs / "bootstrap.py").write_text(BOOTSTRAP, encoding="utf-8")
        (inputs / "launch.cmd").write_text(
            "@echo off\r\nset OMP_NUM_THREADS=1\r\nset OPENBLAS_NUM_THREADS=1\r\n"
            "set MKL_NUM_THREADS=1\r\n"
            'C:\\GridAgentRuntime\\python.exe -I -B C:\\GridAgentInput\\bootstrap.py "' + entry +
            '" > C:\\GridAgentOutput\\stdout.log 2>&1\r\n'
            "echo %errorlevel% > C:\\GridAgentOutput\\exit.tmp\r\n"
            "move /y C:\\GridAgentOutput\\exit.tmp C:\\GridAgentOutput\\exit-code.txt > NUL\r\n",
            encoding="ascii")
        plan = {"protocol": PROTOCOL, "run_id": identifier, "entry": entry, "inputs": snapshot,
                "plugin": plugin, "plugin_versions": plugins.installed_metadata(plugin).get("versions", {})
                if plugin else {}, "timeout_seconds": TIMEOUT}
        ws.atomic_bytes(folder / "manifest.json", json.dumps(plan, allow_nan=False).encode())
        config = configuration(runtime, inputs, output, target)
        ws.atomic_bytes(folder / "sandbox.wsb", config.encode())
        state, reason = _launch(root, folder, executable, config)
        result = {**plan, "status": state, "reason": reason, "artifacts": [], "exit_code": None,
                  "verification": "unverified_script_output"}
        if state != "cleanup_unconfirmed":
            try:
                rows = ws.scan(output, limit=ws.MAX_OUTPUT, per_file=ws.MAX_OUTPUT)
                for row in rows:
                    data = ws.bounded_bytes(ws.scoped(output, row["path"]), ws.MAX_OUTPUT)
                    result["artifacts"].append({**row, "sha256": ws.sha(data)})
                if state == "finished":
                    code = int(ws.bounded_bytes(output / "exit-code.txt", 32).strip())
                    result.update(status="ok" if code == 0 else "failed", exit_code=code,
                                  reason=None if code == 0 else "Python exited unsuccessfully")
                if (output / "stdout.log").exists():
                    # The guest can generate misleading output; this is not a verifier.
                    with ws.scoped(output, "stdout.log").open("rb") as handle:
                        handle.seek(max(0, (output / "stdout.log").stat().st_size-12000))
                        result["stdout_stderr_tail"] = handle.read(12000).decode("utf-8", errors="replace")
            except (OSError, ValueError):
                result.update(status="failed", reason="Unsafe or oversized output", artifacts=[])
        ws.atomic_bytes(folder / "report.json", json.dumps(result, allow_nan=False).encode())
        return result
