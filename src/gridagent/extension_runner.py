"""Persist extension requests and results using the common run artifact layout."""
import json
import subprocess
from pathlib import Path
from uuid import uuid4

from .extension_program import Battery, Feeder
from .plugins import launch

SCHEMAS = {"opendss": Feeder, "pybamm": Battery}


def run_extension(root, backend, parameters):
    if backend not in SCHEMAS:
        raise ValueError("Unknown extension backend")
    request = {"backend": backend, "parameters": SCHEMAS[backend].model_validate(parameters).model_dump()}
    folder = Path(root).resolve() / "runs" / uuid4().hex
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
    result = {"backend": backend, "status": "failed", "reason": "Extension worker failed"}
    try:
        process = launch(backend, "gridagent.extension_worker", folder)
        if process.returncode == 0 and (folder / "result.json").is_file():
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        result["reason"] = type(exc).__name__
    result.update({"run_id": folder.name, "operation": "feeder" if backend == "opendss" else "discharge",
                   "validation_scope": "solver and finite output checks only; no independent benchmark yet"})
    (folder / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return result
