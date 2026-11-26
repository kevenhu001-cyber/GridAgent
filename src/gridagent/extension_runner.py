"""Persist extension requests and results using the common run artifact layout."""
import json
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from .advanced_programs import FluidState, PowerFlowCase, PowSyBlCase, RainflowSeries, TrackingQP, TransmissionLine
from .extension_program import Battery, ControlResponse, Feeder, Solar
from .extra_programs import Commitment, EconomicDispatch, EquivalentCell, Wind
from .plugins import clean_env, launch

SCHEMAS = {"opendss": Feeder, "pybamm": Battery, "pvlib": Solar, "control": ControlResponse,
           "windpowerlib": Wind, "cvxpy": EconomicDispatch, "pyomo": Commitment, "casadi": EquivalentCell,
           "pypower": PowerFlowCase, "pypowsybl": PowSyBlCase, "osqp": TrackingQP,
           "scikit-rf": TransmissionLine, "coolprop": FluidState, "rainflow": RainflowSeries}
OPERATIONS = {"opendss": "feeder", "pybamm": "discharge", "pvlib": "solar_dc", "control": "step_response",
              "windpowerlib": "power_curve", "cvxpy": "economic_dispatch",
              "pyomo": "unit_commitment", "casadi": "equivalent_cell",
              "pypower": "ac_flow", "pypowsybl": "ac_flow", "osqp": "tracking_qp",
              "scikit-rf": "sparameters", "coolprop": "fluid_state", "rainflow": "cycle_count"}


def run_extension(root, backend, parameters):
    if backend not in SCHEMAS:
        raise ValueError("Unknown extension backend")
    request = {"backend": backend, "parameters": SCHEMAS[backend].model_validate(parameters).model_dump()}
    folder = Path(root).resolve() / "runs" / uuid4().hex
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
    result = {"backend": backend, "status": "failed", "reason": "Extension worker failed"}
    try:
        if backend == "control":
            with (folder / "solver.log").open("w", encoding="utf-8") as log:
                process = subprocess.run([sys.executable, "-I", "-B", "-m", "gridagent.extension_worker"],
                                         cwd=folder, env=clean_env(), stdout=log, stderr=subprocess.STDOUT,
                                         timeout=300, check=False)
        else:
            process = launch(backend, "gridagent.extension_worker", folder)
        if process.returncode == 0 and (folder / "result.json").is_file():
            result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        result["reason"] = type(exc).__name__
    result.update({"run_id": folder.name, "operation": OPERATIONS[backend],
                   "validation_scope": "solver and finite output checks only; no independent benchmark yet"})
    (folder / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    return result
