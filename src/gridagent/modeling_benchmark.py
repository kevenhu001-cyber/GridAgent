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
    "source-short-circuit": ("Create an empty pandapower network with buses 0 and 1 at 110 kV. "
                             "External grid at bus 0, vm_pu=1, maximum short-circuit power 1000 MVA, "
                             "rx_max=0.1. Line index 0 from 0 to 1, length 10 km, r=0.1 ohm/km, "
                             "x=0.4 ohm/km, c=0 nF/km, current rating 0.5 kA. No other devices. "
                             "Compute IEC 60909 maximum three-phase initial symmetrical fault current at bus 0."),
    "lossy-storage": ("Build a four-hour single-bus PyPSA system: bus b, load load "
                      "at b at 5 MW every hour, generator grid at b rated 15 MW with hourly "
                      "costs 10,10,100,100 per MWh, storage battery at b rated 5 MW, max_hours=2, "
                      "charge efficiency 0.8 and discharge efficiency 1, zero marginal cost, "
                      "cyclic SOC. No other devices or links. Optimize dispatch."),
    "lossy-link": ("Build a two-hour fixed-capacity PyPSA network with buses source and sink. "
                   "Load load at sink is 4 MW in both hours. Generator solar at source has "
                   "10 MW capacity, availability [0.5,1], marginal cost 10 per MWh. "
                   "Generator backup at sink has 5 MW capacity, marginal cost 100 per MWh. "
                   "Directional link transfer from source to sink has 5 MW capacity and "
                   "efficiency 0.8. No storage or other components. Optimize dispatch."),
    "storage-dispatch": ("Build a PyPSA four-hour fixed-capacity system, bus b, load load at b "
                         "with 5 MW each hour. Generator grid at b, 15 MW nominal, marginal costs "
                         "10,10,100,100 per MWh. Storage battery at b, 5 MW, max_hours=2, "
                         "charge/discharge efficiencies both 1, zero marginal cost, cyclic SOC. "
                         "No other devices or links. Optimize dispatch."),
}


def expected_program(task):
    if task == "source-short-circuit":
        return PPProgram.model_validate({"backend": "pandapower", "analysis": "short_circuit", "fault_bus": 0,
            "steps": [{"op": "create_bus", "index": 0, "vn_kv": 110},
                      {"op": "create_bus", "index": 1, "vn_kv": 110},
                      {"op": "create_ext_grid", "bus": 0, "s_sc_max_mva": 1000},
                      {"op": "create_line_from_parameters", "index": 0, "from_bus": 0, "to_bus": 1,
                       "length_km": 10, "r_ohm_per_km": 0.1, "x_ohm_per_km": 0.4, "max_i_ka": 0.5}]})
    if task == "lossy-link":
        return DispatchProgram.model_validate({"backend": "pypsa", "hours": 2,
            "buses": [{"name": "source"}, {"name": "sink"}],
            "loads": [{"name": "load", "bus": "sink", "p_set_mw": [4, 4]}],
            "generators": [{"name": "solar", "bus": "source", "p_nom_mw": 10,
                            "marginal_cost": 10, "p_max_pu": [0.5, 1]},
                           {"name": "backup", "bus": "sink", "p_nom_mw": 5, "marginal_cost": 100}],
            "links": [{"name": "transfer", "bus0": "source", "bus1": "sink",
                       "p_nom_mw": 5, "efficiency": 0.8}]})
    if task == "two-bus":
        return PPProgram.model_validate({"backend": "pandapower", "steps": [
            {"op": "create_bus", "index": 0, "vn_kv": 110},
            {"op": "create_bus", "index": 1, "vn_kv": 110},
            {"op": "create_ext_grid", "bus": 0},
            {"op": "create_line_from_parameters", "index": 0, "from_bus": 0, "to_bus": 1,
             "length_km": 10, "r_ohm_per_km": 0.1, "x_ohm_per_km": 0.4, "max_i_ka": 0.5},
            {"op": "create_load", "index": 0, "bus": 1, "p_mw": 20, "q_mvar": 5}]})
    if task in {"storage-dispatch", "lossy-storage"}:
        return DispatchProgram.model_validate({"backend": "pypsa", "hours": 4, "buses": [{"name": "b"}],
            "loads": [{"name": "load", "bus": "b", "p_set_mw": [5]*4}],
            "generators": [{"name": "grid", "bus": "b", "p_nom_mw": 15, "marginal_cost": [10,10,100,100]}],
            "storage": [{"name": "battery", "bus": "b", "p_nom_mw": 5, "max_hours": 2,
                         "efficiency_store": 0.8 if task == "lossy-storage" else 1, "efficiency_dispatch": 1}]})
    raise ValueError("Unknown modeling task")


def fidelity(task, program):
    expected = expected_program(task).model_dump(mode="json")
    actual = program.model_dump(mode="json")
    if set(expected) != set(actual):
        return False
    # Permit different valid construction order without permitting extra devices.
    if isinstance(program, PPProgram) and "steps" in expected:
        for item in (expected, actual):
            item["steps"] = sorted(item["steps"], key=lambda x: json.dumps(x, sort_keys=True))
    if isinstance(program, DispatchProgram) and "buses" in expected:
        for item in (expected, actual):
            for group in ("buses", "loads", "generators", "storage", "links"):
                item[group] = sorted(item[group], key=lambda x: x["name"])
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
            elif task == "source-short-circuit":
                folder = artifact_folder(Path(root), "runs", result["run_id"])
                measured = float(pd.read_csv(folder / "res_bus_sc.csv", index_col=0).at[0, "ikss_ka"])
                # At the source bus IEC voltage factor cancels in the source impedance.
                numerical = math.isclose(measured, 1000 / (math.sqrt(3)*110), rel_tol=1e-5)
            elif task == "lossy-link":
                folder = artifact_folder(Path(root), "runs", result["run_id"])
                flow = pd.read_csv(folder / "link_mw.csv", index_col=0)["transfer"]
                generation = pd.read_csv(folder / "generation_mw.csv", index_col=0)
                numerical = (abs(result["metrics"]["objective"]-100) <= 1e-4
                             and bool((flow-5).abs().le(1e-5).all())
                             and bool(generation["backup"].abs().le(1e-5).all()))
            elif task == "lossy-storage":
                metrics = result["metrics"]
                # 10 MWh charged in cheap hours, 8 delivered later; 2 MWh expensive generation.
                numerical = (abs(metrics["objective"]-400) <= 1e-4
                             and abs(metrics["storage_discharge_mwh"]-8) <= 1e-5
                             and abs(metrics["storage_charge_mwh"]-10) <= 1e-5)
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
    schema = type(expected_program(task))
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
