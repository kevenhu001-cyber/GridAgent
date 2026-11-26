"""Fixed-input modeling tasks with independent analytic reference checks.

Public developer benchmarks, not hidden official paper tasks. Never give the
policy the expected numeric outputs; feedback names the failed checks.
"""
import json
import math
from pathlib import Path

import pandas as pd
from langchain_core.messages import HumanMessage, SystemMessage

from .dsr import Study, digest
from .model_quality import check
from .native_backends import ADAPTER, run_program
from .native_program import DispatchProgram, PPProgram
from .workspace import artifact_folder

TASKS = {
    "two-bus": ("Create an empty pandapower network. Bus indices 0 and 1, both 110 kV. "
                "External grid at bus 0 with 1 p.u. voltage. One line index 0 from 0 to 1, "
                "length 10 km, r=0.1 ohm/km, x=0.4 ohm/km, c=0 nF/km, "
                "current rating 0.5 kA. One load index 0 at bus 1, 20 MW and 5 Mvar. "
                "Solve AC power flow. No extra devices or edits."),
    "storage-dispatch": ("Build a PyPSA four-hour fixed-capacity system, bus b, load load at b "
                         "with 5 MW each hour. Generator grid at b, 15 MW nominal, marginal costs "
                         "10,10,100,100 per MWh. Storage battery at b, 5 MW, max_hours=2, "
                         "charge/discharge efficiencies both 1, zero marginal cost, cyclic SOC. "
                         "No other devices or links. Optimize dispatch."),
}


def expected_program(task):
    if task == "two-bus":
        return PPProgram.model_validate({"backend": "pandapower", "steps": [
            {"op": "create_bus", "index": 0, "vn_kv": 110},
            {"op": "create_bus", "index": 1, "vn_kv": 110},
            {"op": "create_ext_grid", "bus": 0},
            {"op": "create_line_from_parameters", "index": 0, "from_bus": 0, "to_bus": 1,
             "length_km": 10, "r_ohm_per_km": 0.1, "x_ohm_per_km": 0.4, "max_i_ka": 0.5},
            {"op": "create_load", "index": 0, "bus": 1, "p_mw": 20, "q_mvar": 5}]})
    if task == "storage-dispatch":
        return DispatchProgram.model_validate({"backend": "pypsa", "hours": 4, "buses": [{"name": "b"}],
            "loads": [{"name": "load", "bus": "b", "p_set_mw": [5]*4}],
            "generators": [{"name": "grid", "bus": "b", "p_nom_mw": 15, "marginal_cost": [10,10,100,100]}],
            "storage": [{"name": "battery", "bus": "b", "p_nom_mw": 5, "max_hours": 2,
                         "efficiency_store": 1, "efficiency_dispatch": 1}]})
    raise ValueError("Unknown modeling task")


def fidelity(task, program):
    expected = expected_program(task).model_dump(mode="json")
    actual = program.model_dump(mode="json")
    if set(expected) != set(actual):
        return False
    # Permit different valid construction order without permitting extra devices.
    if task == "two-bus":
        for item in (expected, actual):
            item["steps"] = sorted(item["steps"], key=lambda x: json.dumps(x, sort_keys=True))
    return actual == expected


def evaluate(task, root, candidate, result):
    same = fidelity(task, candidate)
    tests = [check("fixed_task_input_fidelity", same, None, "Exact task model inputs"),
             check("native_quality", result.get("quality", {}).get("passed") is True)]
    numerical = False
    if same and result.get("status") == "ok":
        try:
            if task == "two-bus":
                folder = artifact_folder(Path(root), "runs", result["run_id"])
                measured = float(pd.read_csv(folder / "res_bus.csv", index_col=0).at[1, "vm_pu"])
                # Balanced three-phase receiving-end voltage (kV line-line), no shunt.
                a = 110**2 - 2*(1*20 + 4*5)
                v2 = (a + math.sqrt(a*a - 4*(1**2+4**2)*(20**2+5**2)))/2
                numerical = abs(measured-math.sqrt(v2)/110) <= 1e-5
            else:
                metrics = result["metrics"]
                # 20 MWh produced in cheap hours at cost 10/MWh, 10 MWh shifted losslessly.
                numerical = (abs(metrics["objective"]-200) <= 1e-4
                             and abs(metrics["storage_discharge_mwh"]-10) <= 1e-5
                             and abs(metrics["storage_charge_mwh"]-10) <= 1e-5)
        except (OSError, ValueError, TypeError, KeyError):
            numerical = False
    tests.append(check("independent_analytic_reference", numerical, None, "Fixed numerical reference"))
    return tests


def model_candidate(model, task):
    if task not in TASKS:
        raise ValueError("Unknown modeling task")
    schema = PPProgram if task == "two-bus" else DispatchProgram
    structured = model.with_structured_output(schema, method="function_calling")

    def propose(observation):
        return structured.invoke([
            SystemMessage(content="Generate a native simulation program from the fixed modeling task. "
                          "After each evaluation correct the candidate while preserving the required inputs. "
                          "Do not change the task or invent numeric results."),
            HumanMessage(content=json.dumps(observation, allow_nan=False)),
        ])
    return propose


def benchmark_updates(root, task, propose, solver=run_program, max_attempts=6):
    if task not in TASKS or not 1 <= max_attempts <= 6:
        raise ValueError("Invalid modeling benchmark")
    study = Study(Path(root) / "studies")
    spec = {"task": task, "instruction": TASKS[task], "max_attempts": max_attempts}
    study.write("manifest", {"protocol": "gridagent-modeling-benchmark-v1", "manifest": spec,
                             "manifest_sha256": digest(spec)})
    history = []
    best = None
    seen = set()
    with study.lock():
        yield f"Modeling benchmark · {task} · {study.id}"
        for index in range(1, max_attempts+1):
            study.write(f"reservation-{index}", {"attempt": index})
            try:
                proposal = propose({"task": TASKS[task], "history": history, "remaining": max_attempts-index+1})
                candidate = ADAPTER.validate_python(proposal)
                data = candidate.model_dump(mode="json")
                if isinstance(candidate, PPProgram) and candidate.parent_run:
                    raise ValueError("Only self-contained benchmark models")
                key = digest(data)
                if key in seen:
                    raise ValueError("Repeated program")
                seen.add(key)
                study.write(f"candidate-{index}", data)
                if not fidelity(task, candidate):
                    result = {"status": "denied", "reason": "Fixed task inputs do not match"}
                else:
                    result = solver(root, candidate)
                checks = evaluate(task, root, candidate, result)
            except Exception as exc:  # noqa: BLE001 - preserve every attempted benchmark
                data, result = None, {"status": "failed", "reason": type(exc).__name__}
                checks = [check(name, False) for name in
                          ("fixed_task_input_fidelity", "native_quality", "independent_analytic_reference")]
            row = {"attempt": index, "program": data, "run_id": result.get("run_id"),
                   "checks": checks, "reason": result.get("reason"),
                   "quality_feedback": result.get("quality")}
            study.write(f"iteration-{index}", row)
            history.append(row)
            score = sum(c["passed"] for c in checks)
            if best is None or score > sum(c["passed"] for c in best["checks"]):
                best = row
            yield f"Modeling attempt {index}/{max_attempts} · {score}/{len(checks)} checks passed"
            if all(c["passed"] for c in checks):
                break
        passed = all(c["passed"] for c in best["checks"])
        report = {"study_id": study.id, "phase": "modeling_benchmark_finished", "task": task,
                  "completed": passed, "passed": passed, "attempts": len(history),
                  "best_run_id": best["run_id"], "best_checks": best["checks"],
                  "termination": "passed" if passed else "budget_exhausted"}
        study.write("report", report)
        yield f"Benchmark {study.id} · {report['termination']} · best run {report['best_run_id']}"
