"""Opt-in Windows Sandbox execution with independent native verification."""
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field

from .dsr import Study, digest
from .model_quality import table
from .native_backends import run_program
from .native_program import Strict
from .plugins import clean_env
from .research_spec import ResearchManifest, evaluate
from .workspace import artifact_folder

TIMEOUT_SECONDS = 120
MAX_RESULT_BYTES = 1_000_000


class SourceDraft(Strict):
    source: str = Field(min_length=1, max_length=65536)


class BusEvidence(Strict):
    vm_pu: float
    va_degree: float
    p_mw: float
    q_mvar: float


class ScriptEvidence(Strict):
    buses: dict[int, BusEvidence] = Field(min_length=1, max_length=500)


def sandbox_enabled(root):
    try:
        return (Path(root) / "script-execution.json").read_text(encoding="utf-8") == '{"enabled":true}'
    except FileNotFoundError:
        return False


def set_sandbox_enabled(root, enabled):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    stage = root / (".script-execution-" + uuid4().hex)
    try:
        stage.write_text('{"enabled":true}' if enabled else '{"enabled":false}', encoding="utf-8")
        stage.replace(root / "script-execution.json")
    finally:
        stage.unlink(missing_ok=True)


def require_runtime():
    executable = shutil.which("wsb") if os.name == "nt" else None
    runtime = Path(os.environ.get("GRIDAGENT_SANDBOX_RUNTIME", Path(sys.executable).parent)).resolve()
    if not executable or not (runtime / "python.exe").is_file() or not list(runtime.glob("python*._pth")):
        raise ValueError("Automatic execution requires Windows Sandbox CLI and an embedded Python runtime")
    return executable, runtime


def sandbox_config(runtime, inputs, output):
    config = ET.Element("Configuration")
    for name in ("Networking", "VGpu", "ClipboardRedirection", "PrinterRedirection", "AudioInput", "VideoInput"):
        ET.SubElement(config, name).text = "Disable"
    ET.SubElement(config, "MemoryInMB").text = "4096"
    folders = ET.SubElement(config, "MappedFolders")
    for host, guest, readonly in ((runtime, r"C:\GridAgentRuntime", True),
                                   (inputs, r"C:\GridAgentInput", True),
                                   (output, r"C:\GridAgentOutput", False)):
        mapping = ET.SubElement(folders, "MappedFolder")
        ET.SubElement(mapping, "HostFolder").text = str(host)
        ET.SubElement(mapping, "SandboxFolder").text = guest
        ET.SubElement(mapping, "ReadOnly").text = str(readonly).lower()
    ET.SubElement(ET.SubElement(config, "LogonCommand"), "Command").text = r"cmd.exe /c C:\GridAgentInput\launch.cmd"
    return ET.tostring(config, encoding="unicode")


def sandbox_run(root, folder, source, request):
    if not sandbox_enabled(root):
        raise ValueError("Automatic script execution is disabled for this workspace")
    executable, runtime = require_runtime()
    encoding = source.encode("utf-8")
    if len(encoding) > 65536:
        raise ValueError("Script exceeds 64 KiB")
    compile(source, "research.py", "exec", dont_inherit=True)
    inputs, output = folder / "input", folder / "output"
    inputs.mkdir(parents=True)
    output.mkdir()
    (inputs / "research.py").write_bytes(encoding)
    (inputs / "request.json").write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
    (inputs / "launch.cmd").write_bytes(
        b"@echo off\r\ncd /d C:\\GridAgentOutput\r\n"
        b"set OMP_NUM_THREADS=1\r\nset OPENBLAS_NUM_THREADS=1\r\n"
        b"C:\\GridAgentRuntime\\python.exe -I -B C:\\GridAgentInput\\research.py > NUL 2>&1\r\n"
        b"echo %errorlevel% > exit.tmp\r\nmove /y exit.tmp exit-code.txt > NUL\r\n"
    )
    config = sandbox_config(runtime, inputs, output)
    (folder / "sandbox.wsb").write_text(config, encoding="utf-8")
    session = str(uuid4())
    (folder / "session-id.txt").write_text(session, encoding="ascii")
    kwargs = {"env": clean_env(), "stdin": subprocess.DEVNULL, "stdout": subprocess.DEVNULL,
              "stderr": subprocess.DEVNULL, "creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        subprocess.run([executable, "start", "--id", session, "--config", config], timeout=60, check=True, **kwargs)
        deadline = time.monotonic() + TIMEOUT_SECONDS
        status = output / "exit-code.txt"
        while not status.is_file():
            if time.monotonic() >= deadline:
                raise TimeoutError("Sandbox script exceeded its time limit")
            if not sandbox_enabled(root):
                raise ValueError("Workspace script execution was disabled")
            time.sleep(0.25)
    finally:
        try:
            subprocess.run([executable, "stop", "--id", session], timeout=30, check=True, **kwargs)
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("Sandbox cleanup could not be confirmed") from exc
    if status.resolve().parent != output.resolve() or status.is_symlink():
        raise ValueError("Invalid sandbox exit record")
    with status.open("rb") as handle:
        if handle.read(32).strip() != b"0":
            raise ValueError("Python script exited unsuccessfully")
    result = output / "result.json"
    if result.resolve().parent != output.resolve() or result.is_symlink() or not result.is_file():
        raise ValueError("The sandbox did not return an admissible result file")
    with result.open("rb") as handle:
        raw = handle.read(MAX_RESULT_BYTES + 1)
    if len(raw) > MAX_RESULT_BYTES:
        raise ValueError("Sandbox result exceeds the result size limit")
    return ScriptEvidence.model_validate_json(raw)


def verify(root, reference, evidence):
    folder = artifact_folder(root, "runs", reference["run_id"])
    columns = ["vm_pu", "va_degree", "p_mw", "q_mvar"]
    rows = table(folder, "res_bus")[columns].dropna()
    if set(rows.index) != set(evidence.buses):
        return False
    for bus, values in rows.iterrows():
        for field in columns:
            if not math.isclose(float(values[field]), getattr(evidence.buses[bus], field),
                                rel_tol=1e-6, abs_tol=1e-5):
                return False
    return True


def run_script_study(root, manifest, model):
    root = Path(root).resolve()
    manifest = ResearchManifest.model_validate(manifest)
    if not sandbox_enabled(root):
        raise ValueError("Enable automatic script execution in this workspace first")
    require_runtime()
    if manifest.max_runs < 2*len(manifest.scenarios):
        raise ValueError("The budget must cover a native reference and one script attempt per scenario")
    study = Study(root / "studies")
    bound = model.with_structured_output(SourceDraft, method="function_calling")
    results = []
    used = 0
    with study.lock():
        frozen = manifest.model_dump(mode="json")
        study.write("manifest", {"protocol": "gridagent-verified-python-v1", "specification": frozen,
                                 "manifest_sha256": digest(frozen)})
        for index, scenario in enumerate(manifest.scenarios):
            yield f"Study {study.id} · scenario {scenario.name} · independent native reference"
            request = scenario.materialize(frozen["program"])
            reference = run_program(root, request)
            used += 1
            evaluation = evaluate(root, reference, request, manifest.limits)
            study.write(f"reference-{index}", {"run_id": reference["run_id"], "evaluation": evaluation})
            row = {"scenario": scenario.name, "reference_run": reference["run_id"], "passed": False, "attempts": []}
            # Reserve one native reference and one script run for each outstanding scenario.
            available = manifest.max_runs - used - 2*(len(manifest.scenarios)-index-1)
            if not evaluation["passed"]:
                row["reason"] = "independent_reference_failed"
            for attempt in range(min(available, 1+manifest.max_repairs) if evaluation["passed"] else 0):
                if not sandbox_enabled(root):
                    row["reason"] = "workspace_execution_disabled"
                    break
                job = study.path / f"script-{index}-{attempt}"
                row["reason"] = "script_evidence_differed_from_reference"
                source = None
                used += 1
                try:
                    reply = bound.invoke([
                        SystemMessage(content="Write standalone Python for the exact pandapower AC request. "
                                      "Read C:/GridAgentInput/request.json and apply the exact device data and edits. "
                                      "Do not use the network, install dependencies or change engineering values. "
                                      "Write result.json in the current output directory with a buses object keyed "
                                      "by active bus index. Each value needs vm_pu, va_degree, p_mw and q_mvar. "
                                      "Use only the packaged libraries."),
                        HumanMessage(content=json.dumps({"request": request, "previous": row["attempts"][-1:]})),
                    ])
                    source = SourceDraft.model_validate(reply).source
                    actual = sandbox_run(root, job, source, request)
                    row["passed"] = verify(root, reference, actual)
                except (ValueError, OSError, SyntaxError, subprocess.SubprocessError) as exc:
                    row["reason"] = type(exc).__name__
                entry = {"attempt": attempt+1, "passed": row["passed"], "reason": row["reason"]}
                if row["passed"]:
                    entry["reason"] = "independently_verified"
                if source is not None:
                    entry["source_sha256"] = hashlib.sha256(source.encode()).hexdigest()
                row["attempts"].append(entry)
                study.write(f"attempt-{index}-{attempt}", entry)
                if row["passed"]:
                    row["reason"] = "independently_verified"
                    break
            results.append(row)
            yield f"{scenario.name} · {row['reason']} · {used}/{manifest.max_runs} attempts"
        report = {"study_id": study.id, "phase": "verified_python_finished", "passed": all(r["passed"] for r in results),
                  "runs_used": used, "scenarios": results}
        study.write("report", report)
        yield json.dumps(report, ensure_ascii=False)
