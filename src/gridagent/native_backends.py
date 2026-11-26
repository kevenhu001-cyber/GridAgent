"""Run validated native programs in isolated working directories.

Subprocess separation is for reliability, not an OS sandbox. Only fixed
native API calls are exposed; no eval, exec, imports or arbitrary paths.
"""
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from pydantic import TypeAdapter

from .native_program import Program

ADAPTER = TypeAdapter(Program)


def available_backends():
    return [{"name": name, "installed": importlib.util.find_spec(name) is not None}
            for name in ("andes", "pandapower", "pypsa", "highspy")]


def run_program(root, program, timeout_s=300):
    program = ADAPTER.validate_python(program)
    request = program.model_dump(mode="json")
    folder = Path(root).resolve() / "runs" / uuid4().hex
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps(request, allow_nan=False), encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
        "LD_LIBRARY_PATH", "LANG", "LC_ALL", "VIRTUAL_ENV", "LOCALAPPDATA", "APPDATA"
    }}
    env.update({"PYTHONNOUSERSITE": "1", "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1"})
    result_path = folder / "result.json"
    result = {"backend": request["backend"], "operation": request.get("analysis", "dispatch"),
              "status": "failed", "reason": "Native solver failed"}
    try:
        with (folder / "solver.log").open("w", encoding="utf-8") as log:
            proc = subprocess.run([sys.executable, "-m", "gridagent.native_worker"],
                                  cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                  timeout=timeout_s, check=False)
        if proc.returncode == 0 and result_path.is_file():
            result = json.loads(result_path.read_text(encoding="utf-8"))
    except subprocess.TimeoutExpired:
        result["reason"] = "Native solver timeout"
    except OSError:
        result["reason"] = "Native solver could not start"
    result["run_id"] = folder.name
    result_path.write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return result
