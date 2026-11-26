"""Run validated native programs in isolated working directories.

Subprocess separation is for reliability, not an OS sandbox. Only fixed
native API calls are exposed; no eval, exec, imports or arbitrary paths.
"""
import importlib.util
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from .native_program import PPProgram, Program
from .plugins import CATALOG, available, installed_metadata, launch
from .workspace import artifact_folder, load_object

ADAPTER = TypeAdapter(Program)


def available_backends(root=None):
    from importlib.metadata import PackageNotFoundError, version

    capabilities = {
        "andes": {"operations": ["power_flow", "fault", "eigen", "scenario_flow", "governor_eigen", "governor_fault"],
                  "units": ["s", "p.u.", "rad"], "evaluator": "modal and voltage metrics"},
        "pandapower": {"operations": ["power_flow", "short_circuit", "scenario_outage"],
                       "units": ["kV", "MW", "Mvar", "kA"], "evaluator": "independent numerical checks"},
        "pypsa": {"operations": ["dispatch"], "units": ["MW", "MWh", "hour"],
                  "evaluator": "nodal and storage balance and transmission limits"},
    }
    rows = []
    for name in ("andes", "pandapower", "highspy", "control", *CATALOG):
        installed = available(name) if name in CATALOG else importlib.util.find_spec(name) is not None
        managed = installed_metadata(name) if name in CATALOG else {}
        plugin_versions = managed.get("versions", {})
        try:
            installed_version = version(name) if installed else None
        except PackageNotFoundError:
            installed_version = next(iter(plugin_versions.values()), None)
        if plugin_versions:
            installed_version = plugin_versions.get(CATALOG[name]["modules"][0], installed_version)
        rows.append({"name": name, "installed": installed, "version": installed_version,
                     "capabilities": capabilities.get(name, {"operations": CATALOG.get(name, {}).get("tools", [])})})
    if root is not None:
        from .external_runtime import CAPABILITY, runtime_status

        runtime = runtime_status(root)
        rows.append({"name": "ngspice", "installed": runtime is not None,
                     "version": runtime["version"] if runtime else None, "capabilities": CAPABILITY})
    return rows


def run_program(root, program, timeout_s=300, *, run_id=None, cancelled=None):
    program = ADAPTER.validate_python(program)
    request = program.model_dump(mode="json")
    parent = None
    if isinstance(program, PPProgram) and program.parent_run:
        prior = artifact_folder(Path(root), "runs", program.parent_run)
        previous_result = load_object(prior / "result.json")
        if previous_result.get("backend") != "pandapower" or previous_result.get("status") != "ok":
            raise ValueError("Parent must be a pandapower run")
        previous = PPProgram.model_validate(load_object(prior / "request.json"))
        if previous.parent_run is not None:
            raise ValueError("Parent program must have been flattened")
        parent = program.parent_run
        request["base"] = previous.base
        request["steps"] = [*previous.model_dump(mode="json")["steps"], *request["steps"]]
        request["parent_run"] = None
        request = PPProgram.model_validate(request).model_dump(mode="json")
    if run_id is not None and not re.fullmatch(r"[a-f0-9]{32}", run_id):
        raise ValueError("Invalid run ID")
    folder = Path(root).resolve() / "runs" / (run_id or uuid4().hex)
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
        "LD_LIBRARY_PATH", "LANG", "LC_ALL", "VIRTUAL_ENV", "LOCALAPPDATA", "APPDATA",
        "PROCESSOR_ARCHITECTURE", "PROCESSOR_ARCHITEW6432", "PROCESSOR_IDENTIFIER",
        "NUMBER_OF_PROCESSORS", "COMSPEC", "PATHEXT"
    }}
    env.update({"PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1"})
    result_path = folder / "result.json"
    result = {"backend": request["backend"], "operation": request.get("analysis", "dispatch"),
              "status": "failed", "reason": "Native solver failed"}
    try:
        if request["backend"] == "pypsa":
            proc = launch("pypsa", "gridagent.native_worker", folder, timeout_s)
        else:
            with (folder / "solver.log").open("w", encoding="utf-8") as log:
                args = [sys.executable, "-m", "gridagent.native_worker"]
                with subprocess.Popen(args, cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT) as proc:
                    try:
                        deadline = time.monotonic() + timeout_s
                        while proc.poll() is None:
                            if cancelled is not None and cancelled():
                                result["reason"] = "cancelled"
                                break
                            if time.monotonic() >= deadline:
                                raise subprocess.TimeoutExpired(args, timeout_s)
                            try:
                                proc.wait(timeout=0.25)
                            except subprocess.TimeoutExpired:
                                continue
                    finally:
                        if proc.poll() is None:
                            proc.kill()
                            proc.wait()
        if proc.returncode == 0 and result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        result["reason"] = "Native solver timeout"
    except OSError:
        result["reason"] = "Native solver could not start"
    except ValueError as exc:
        result["reason"] = str(exc)[:200]
    from .model_quality import evaluate_run

    quality = evaluate_run(folder, request, result)
    result["quality"] = quality
    (folder / "quality.json").write_text(json.dumps(quality, allow_nan=False), encoding="utf-8")
    result["run_id"] = folder.name
    if parent:
        result["parent_run"] = parent
    final = folder / "result.final.tmp"
    final.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    final.replace(result_path)
    return result
