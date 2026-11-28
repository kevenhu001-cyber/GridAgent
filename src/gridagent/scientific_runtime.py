"""General Python runner using Windows Sandbox, with no unrestricted host fallback."""
import json
import subprocess
import time
from pathlib import Path
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from filelock import FileLock

from . import plugins
from . import scientific_workspace as ws
from .scientific_library import MAX_PLUGINS, environment_inventory, managed_targets, preflight, selected_plugins
from .verified_python import require_runtime

PROTOCOL = "scientific-python-v1"
TIMEOUT = 120
ACTIVE = "scientific-active.json"
BOOTSTRAP = r"""
import json
import os
import runpy
import shutil
import sys
from pathlib import Path

project = Path(r"C:\GridAgentWork")
shutil.copytree(r"C:\GridAgentInput\project", project)
entry = sys.argv[1]
plugin_paths = [Path(r"C:\GridAgentPlugin" + str(index)) for index in range(4)]
sys.path[0:0] = [str(project), *(str(path) for path in plugin_paths if path.is_dir())]
os.environ["GRIDAGENT_PROJECT_DIR"] = str(project)
os.environ["GRIDAGENT_OUTPUT_DIR"] = r"C:\GridAgentOutput"
os.chdir(project)
sys.argv = [str(project / entry), *json.loads(Path(r"C:\GridAgentInput\arguments.json").read_text(encoding="utf-8"))]
runpy.run_path(str(project / entry), run_name="__main__")
"""


def configuration(runtime, inputs, output, plugin=None, *, plugin_targets=()):
    config = ET.Element("Configuration")
    for name in ("Networking", "VGpu", "ClipboardRedirection", "PrinterRedirection", "AudioInput", "VideoInput"):
        ET.SubElement(config, name).text = "Disable"
    ET.SubElement(config, "MemoryInMB").text = "4096"
    mappings = ET.SubElement(config, "MappedFolders")
    folders = [(runtime, r"C:\GridAgentRuntime", True), (inputs, r"C:\GridAgentInput", True),
               (output, r"C:\GridAgentOutput", False)]
    targets = (plugin,) if plugin is not None else tuple(plugin_targets)
    if len(targets) > MAX_PLUGINS:
        raise ValueError("Too many plugin mappings")
    for index, target in enumerate(targets):
        folders.append((target, r"C:\GridAgentPlugin" + str(index), True))
    for host, guest, readonly in folders:
        row = ET.SubElement(mappings, "MappedFolder")
        ET.SubElement(row, "HostFolder").text = str(host)
        ET.SubElement(row, "SandboxFolder").text = guest
        ET.SubElement(row, "ReadOnly").text = str(readonly).lower()
    ET.SubElement(ET.SubElement(config, "LogonCommand"), "Command").text = (
        r"cmd.exe /c C:\GridAgentInput\launch.cmd")
    return ET.tostring(config, encoding="unicode")


def active_session(root):
    path = Path(root).resolve() / ACTIVE
    try:
        value = json.loads(ws.bounded_bytes(path, 2048))
    except FileNotFoundError:
        return None
    try:
        identifier, session = value["run_id"], value["session_id"]
        if str(UUID(session)) != session:
            raise ValueError("Invalid sandbox session ID")
        ws.job_directory(root, identifier)
    except (KeyError, TypeError, AttributeError, OSError, ValueError) as exc:
        raise ValueError("Invalid active scientific session journal; execution blocked") from exc
    return {"run_id": identifier, "session_id": session}


def _clear_active(root, record):
    if active_session(root) != record:
        raise ValueError("Active scientific session changed; execution blocked")
    (Path(root).resolve() / ACTIVE).unlink()


def _stop(executable, session):
    subprocess.run([executable, "stop", "--id", session], timeout=30, check=True,
                   env=plugins.clean_env(), stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def recover(root):
    """Explicit recovery of an interrupted run. Never relaunch its code."""
    root = Path(root).resolve()
    with FileLock(str(root / "scientific-execution.lock"), timeout=0):
        record = active_session(root)
        if record is None:
            return {"status": "ok", "reason": "No unresolved sandbox session"}
        executable, _ = require_runtime()
        folder = ws.job_directory(root, record["run_id"])
        try:
            _stop(executable, record["session_id"])
        except (OSError, subprocess.SubprocessError):
            return {"status": "cleanup_unconfirmed", "run_id": record["run_id"],
                    "reason": "Could not confirm sandbox stop; execution remains blocked"}
        recovery = {"status": "recovered_incomplete", "reason": "Sandbox stop confirmed; outputs discarded",
                    "run_id": record["run_id"], "session_id": record["session_id"]}
        ws.atomic_bytes(folder / "recovery.json", json.dumps(recovery).encode())
        _clear_active(root, record)
        return recovery


def kernel_dependencies_present(environment):
    names = {row["distribution"].lower().replace("_", "-")
             for row in environment["distributions"] if row["scope"] == "core"}
    return {"jupyter-client", "ipykernel"} <= names


def status(root):
    from importlib.metadata import PackageNotFoundError, version

    kernel_present = False
    try:
        _, runtime = require_runtime()
        available = True
        try:
            kernel_present = kernel_dependencies_present(environment_inventory(runtime, {}))
        except (OSError, ValueError):
            # Metadata may be incomplete; do not advertise a ready kernel.
            pass
    except ValueError:
        available = False
    try:
        notebook_version = version("nbformat")
    except PackageNotFoundError:
        notebook_version = None
    try:
        active = active_session(root)
        blocked = active is not None
    except (OSError, ValueError):
        active, blocked = None, True
    return {"status": "ok", "enabled": ws.enabled(root), "sandbox_available": available,
            "execution_blocked_by_session": blocked, "active_run_id": active["run_id"] if active else None,
            "backend": "Windows Sandbox CLI", "timeout_seconds": TIMEOUT,
            "plugins": [{"id": row["id"], "versions": row["versions"],
                         "managed_available": plugins.installed_target(row["id"]) is not None}
                        for row in plugins.status()],
            "max_plugins_per_run": MAX_PLUGINS,
            "research_features": {
                "kernel_dependencies_present": kernel_present,
                "kernel_scope": "single isolated job; VM execution not certified by metadata",
                "notebook_dependency_version": notebook_version,
                "notebook_scope": "successful ordinary script run; export only",
            },
            "scope": "compatible managed plugins only; no host fallback; no network"}


def _launch(root, folder, executable, config, *, cancelled=None):
    if cancelled is not None and cancelled():
        return "cancelled", "Cancellation requested before sandbox startup"
    session = str(uuid4())
    ws.atomic_bytes(folder / "session-id.txt", session.encode("ascii"))
    record = {"run_id": folder.name, "session_id": session}
    if active_session(root) is not None:
        raise ValueError("Unresolved sandbox session; user must recover it before executing")
    # Journal is outside all guest mappings and committed before the start command.
    ws.atomic_bytes(Path(root) / ACTIVE, json.dumps(record).encode())
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
            if (not ws.enabled(root) or (folder / "cancel-requested").exists()
                    or (cancelled is not None and cancelled())):
                state, reason = "cancelled", "Cancellation or authorization revoked"
                break
            if time.monotonic() >= deadline:
                state, reason = "timeout", "Execution exceeded time budget"
                break
            try:
                ws.scan(output, limit=ws.MAX_OUTPUT, per_file=ws.MAX_OUTPUT)
            except FileNotFoundError:
                # A guest may legitimately rename or remove an intermediate output.
                continue
            if marker.exists():
                state, reason = "finished", None
                break
            time.sleep(.25)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        reason = type(exc).__name__
    finally:
        try:
            _stop(executable, session)
        except (OSError, subprocess.SubprocessError):
            state, reason = "cleanup_unconfirmed", "Sandbox shutdown could not be confirmed"
        else:
            _clear_active(root, record)
    return state, reason


def isolated_shell_source(shell, command):
    """Generate trusted guest-only launcher. Never execute this on the host."""
    if shell not in {"bash", "powershell"} or not isinstance(command, str) or not 1 <= len(command) <= 8000:
        raise ValueError("Unsupported shell or command length")
    if "\x00" in command:
        raise ValueError("Invalid command")
    return (
        "import shutil, subprocess, sys\n"
        f"shell = {shell!r}\n"
        f"command = {command!r}\n"
        "program = shutil.which('powershell.exe' if shell == 'powershell' else 'bash')\n"
        "if not program:\n"
        "    print('Requested shell unavailable inside scientific sandbox', file=sys.stderr)\n"
        "    sys.exit(127)\n"
        "args = [program, '-NoProfile', '-NonInteractive', '-Command', command] if shell == 'powershell' "
        "else [program, '--noprofile', '--norc', '-c', command]\n"
        "sys.exit(subprocess.run(args, stdin=subprocess.DEVNULL, check=False).returncode)\n"
    ).encode()


def execute(root, entry, plugin=None, arguments=None, *, probe=None, plugin_ids=None,
            run_id=None, cancelled=None, shell_command=None, kernel_cells=None):
    if sum(item is not None for item in (shell_command, probe, kernel_cells)) > 1:
        raise ValueError("Cannot combine special scientific execution modes")
    ws.require_grant(root)
    if kernel_cells is not None:
        from .kernel_batch import validate_cells

        validate_cells(kernel_cells)
        if plugin is not None or plugin_ids:
            raise ValueError("Kernel batch currently uses the bundled scientific environment only")
    ws.safe_parts(entry)
    if not entry.endswith(".py"):
        raise ValueError("Entry must be a project Python file")
    arguments = [] if arguments is None else arguments
    if not isinstance(arguments, list) or len(arguments) > 32 or any(
            not isinstance(arg, str) or len(arg) > 1024 or "\x00" in arg for arg in arguments):
        raise ValueError("Invalid Python arguments")
    executable, runtime = require_runtime()
    root = Path(root).resolve()
    ids = selected_plugins(plugin, plugin_ids)
    with FileLock(str(root / "scientific-execution.lock"), timeout=0), managed_targets(ids) as targets:
        ws.require_grant(root)
        if active_session(root) is not None:
            raise ValueError("Unresolved sandbox session; ask the user to run scientific recovery")
        environment = preflight(runtime, targets)
        if kernel_cells is not None and not kernel_dependencies_present(environment):
            raise ValueError("Install the optional kernel extra into the trusted sandbox runtime first")
        identifier = uuid4().hex if run_id is None else run_id
        from re import fullmatch

        if not isinstance(identifier, str) or not fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Invalid scientific run ID")
        if cancelled is not None and cancelled():
            return {"run_id": identifier, "status": "cancelled", "artifacts": [],
                    "reason": "Cancellation requested before preparation"}
        folder = ws.directory(root, "scientific-runs") / identifier
        folder.mkdir()
        inputs = folder / "input"
        snapshot = ws.snapshot(root, inputs / "project")
        if shell_command is not None:
            source = isolated_shell_source(shell_command['shell'], shell_command['command'])
            entry = "gridagent_shell_" + identifier + ".py"
            path = ws.scoped(inputs / "project", entry)
            if path.exists():
                raise ValueError("Internal shell launcher filename collision")
            path.write_bytes(source)
            snapshot.append({"path": entry, "size_bytes": len(source), "sha256": ws.sha(source)})
        if kernel_cells is not None:
            from .kernel_batch import launcher_source

            source = launcher_source(kernel_cells)
            entry = "gridagent_kernel_" + identifier + ".py"
            path = ws.scoped(inputs / "project", entry)
            if path.exists():
                raise ValueError("Internal kernel launcher filename collision")
            path.write_bytes(source)
            snapshot.append({"path": entry, "size_bytes": len(source), "sha256": ws.sha(source)})
        if probe is not None:
            from .scientific_library import probe_source

            source = probe_source(probe["module"], probe.get("symbol")).encode("utf-8")
            entry = "gridagent_api_" + identifier + ".py"
            path = ws.scoped(inputs / "project", entry)
            if path.exists():
                raise ValueError("Internal probe filename collision")
            path.write_bytes(source)
            snapshot.append({"path": entry, "size_bytes": len(source), "sha256": ws.sha(source)})
        if entry not in {row["path"] for row in snapshot}:
            raise ValueError("Entry not found in project snapshot")
        compile(ws.bounded_bytes(ws.scoped(inputs / "project", entry), ws.MAX_FILE),
                entry, "exec", dont_inherit=True)
        output = folder / "output"
        output.mkdir()
        (inputs / "bootstrap.py").write_text(BOOTSTRAP, encoding="utf-8")
        (inputs / "arguments.json").write_text(json.dumps(arguments, ensure_ascii=False), encoding="utf-8")
        (inputs / "launch.cmd").write_text(
            "@echo off\r\nset OMP_NUM_THREADS=1\r\nset OPENBLAS_NUM_THREADS=1\r\n"
            "set MKL_NUM_THREADS=1\r\n"
            'C:\\GridAgentRuntime\\python.exe -I -B C:\\GridAgentInput\\bootstrap.py "' + entry +
            '" > C:\\GridAgentOutput\\stdout.log 2>&1\r\n'
            "echo %errorlevel% > C:\\GridAgentOutput\\exit.tmp\r\n"
            "move /y C:\\GridAgentOutput\\exit.tmp C:\\GridAgentOutput\\exit-code.txt > NUL\r\n",
            encoding="ascii")
        plan = {"protocol": PROTOCOL, "run_id": identifier, "entry": entry, "inputs": snapshot,
                "arguments": arguments, "api_probe": probe, "shell": shell_command["shell"] if shell_command else None, "plugin": ids[0] if len(ids) == 1 else None,
                "plugin_ids": list(ids),
                "plugin_versions": plugins.installed_metadata(ids[0]).get("versions", {}) if len(ids) == 1 else {},
                "environment": environment, "timeout_seconds": TIMEOUT}
        if kernel_cells is not None:
            plan["kernel"] = {"mode": "single_job_batch", "cell_count": len(kernel_cells),
                              "source_sha256": ws.sha(source)}
        ws.atomic_bytes(folder / "manifest.json", json.dumps(plan, allow_nan=False).encode())
        config = configuration(runtime, inputs, output, plugin_targets=targets.values())
        ws.atomic_bytes(folder / "sandbox.wsb", config.encode())
        if cancelled is None:
            state, reason = _launch(root, folder, executable, config)
        else:
            state, reason = _launch(root, folder, executable, config, cancelled=cancelled)
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
