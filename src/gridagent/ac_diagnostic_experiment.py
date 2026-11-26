"""Replay-verified AC counterfactual probes; no original model edits."""

import math
from pathlib import Path
from uuid import uuid4

from .ac_check import PROTOCOL as AC_PROTOCOL
from .ac_check import observe
from .ac_check import prepare as prepare_ac
from .ac_diagnostic_ir import ACDiagnosticExperiment, compile_probes
from .diagnosis import diagnose_study
from .dsr import Study
from .engineering_ir import fingerprint
from .native_backends import run_program

PROTOCOL = "ac-diagnostic-experiment-v1"


def finite_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def measure(spec, row, acceptance):
    """Use only comparable, identity-checked observations; never infer missing Q."""
    evidence = row["native_evidence"]
    if evidence["status"] not in {"verified", "rejected"} or not evidence["solver_version"]:
        return None
    native = row["native_verdict"]["checks"]
    required = {c["id"]: c["passed"] for c in native}
    if not all(required.get(key) is True for key in (
            "model_input_fidelity", "solver_success", "active_bus_coverage", "power_balance_mva")):
        return None
    if spec.target_scope == "ac_native":
        rows = native
    else:
        if evidence["status"] != "verified":
            return None
        rows = (row.get("physical") or {}).get("checks", [])
    target = next((c for c in rows if c["id"] == spec.target_check), None)
    if target is None:
        return None
    if spec.target_check == "voltage_operating_range":
        observed = target.get("observed")
        if not isinstance(observed, list) or len(observed) != 2 or not all(map(finite_number, observed)):
            return None
        low, high = observed
        if low > high:
            return None
        violation = max(0.0, acceptance.voltage_min_pu-low, high-acceptance.voltage_max_pu)
        unit = "p.u."
    elif spec.target_check == "res_line_loading":
        observed = target.get("observed")
        if not finite_number(observed):
            return None
        violation = max(0.0, observed-acceptance.loading_max_percent)
        unit = "percentage_points"
    else:
        observed = target.get("violation")
        if not finite_number(observed):
            return None
        violation = observed
        unit = "MVAr" if spec.target_check.startswith("reactive:") else "MW"
    return {"passed": target["passed"], "violation": violation, "unit": unit, "observed": observed,
            "solver_version": evidence["solver_version"]}


def prepare(root, spec):
    diagnosis = diagnose_study(root, spec.source_study_id)
    if diagnosis["source_protocol"] != AC_PROTOCOL or diagnosis["source_report_sha256"] != spec.source_report_sha256:
        raise ValueError("AC diagnostic authorization does not match committed source")
    source = Study.reopen(root / "studies", spec.source_study_id)
    report = source.read("report")
    if fingerprint(report) != spec.source_report_sha256:
        raise ValueError("AC source report changed")
    original = source.read("manifest")["spec"]
    planned = []
    variants = compile_probes(spec, original)
    baseline_spec = variants[0][1]
    source_row = next((row for row in report["snapshots"]
                       if row["snapshot"] == spec.snapshot.model_dump(mode="json")), None)
    source_metric = measure(spec, source_row, baseline_spec.acceptance) if source_row else None
    if not source_metric or source_metric["passed"]:
        raise ValueError("Target must be an observed, comparable failed check in the selected snapshot")
    for job, variant in variants:
        commitment, cases, dc_sha = prepare_ac(root, variant)
        if dc_sha != report["dc_report_sha256"]:
            raise ValueError("AC diagnostic DC schedule changed")
        case = cases[0]
        if job["change"] and job["change"]["device"] not in {d.id for d in case[1].model.devices}:
            raise ValueError("Diagnostic device is offline in the selected snapshot")
        planned.append(({**job, "request_sha256": fingerprint(case[-1])}, variant, commitment, case))
    if len({job["request_sha256"] for job, *_ in planned}) != len(planned):
        raise ValueError("Duplicate or ineffective compiled diagnostic requests")
    return planned, source_metric


def start_experiment(root, spec):
    root = Path(root).resolve()
    spec = ACDiagnosticExperiment.model_validate(spec)
    cases, metric = prepare(root, spec)
    study = Study(root / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": spec.canonical(), "sha256": spec.sha256(),
                             "source_metric": metric, "cases": [job for job, *_ in cases]})
    return study.id


def interpret(spec, source, rows):
    baseline = rows[0]["measurement"]
    # An unexpected pass or material drift in the fresh baseline precludes attribution.
    comparable = bool(baseline and baseline["solver_version"] == source["solver_version"]
                      and not baseline["passed"] and math.isclose(
                          baseline["violation"], source["violation"], rel_tol=1e-4, abs_tol=1e-6))
    updates = []
    for row in rows[1:]:
        metric = row["measurement"]
        delta = None
        status = "inconclusive"
        if comparable and metric and metric["solver_version"] == baseline["solver_version"]:
            delta = baseline["violation"]-metric["violation"]
            if metric["passed"]:
                status = "target_resolved_in_counterfactual"
            elif delta > 1e-6:
                status = "target_violation_reduced"
            elif delta < -1e-6:
                status = "target_violation_increased"
            else:
                status = "no_material_target_change"
        updates.append({"probe": row["probe"], "status": status, "reduction": delta,
                        "unit": source["unit"], "target_check": spec.target_check,
                        "all_snapshot_checks_passed": row["observation"]["passed"],
                        "root_cause_confirmed": False})
    return comparable, updates


def resume_experiment(root, identifier, *, solver=run_program):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    with study.lock():
        frozen = study.read("manifest")
        spec = ACDiagnosticExperiment.model_validate(frozen["spec"])
        if frozen.get("protocol") != PROTOCOL or frozen["sha256"] != spec.sha256():
            raise ValueError("Frozen AC diagnostic authorization changed")
        cases, metric = prepare(root, spec)
        if frozen["cases"] != [job for job, *_ in cases] or frozen["source_metric"] != metric:
            raise ValueError("Frozen AC diagnostic plan changed")
        rows, seen = [], set()
        for job, variant, commitment, case in cases:
            index = job["index"]
            reservation, output = f"reservation-{index}", f"evaluation-{index}"
            fresh = not study.exists(reservation)
            if fresh:
                if study.exists(output) or study.exists("report"):
                    raise ValueError("AC diagnostic evidence without reservation")
                study.write(reservation, {"run_id": uuid4().hex, **job})
            reserved = study.read(reservation)
            if {key: reserved.get(key) for key in job} != job or reserved["run_id"] in seen:
                raise ValueError("AC diagnostic reservation changed or duplicated")
            seen.add(reserved["run_id"])
            if fresh:
                try:
                    solver(root, case[-1], run_id=reserved["run_id"], timeout_s=variant.timeout_s)
                except Exception as exc:  # noqa: BLE001 - preserve charged reservation
                    study.write(f"launch-error-{index}", {"error_type": type(exc).__name__})
            observation = observe(root, variant, commitment, case, reserved)
            row = {**job, "observation": observation, "measurement": measure(spec, observation, variant.acceptance)}
            if study.exists(f"launch-error-{index}"):
                row["launch_error_type"] = study.read(f"launch-error-{index}")["error_type"]
            if study.exists(output):
                if study.read(output) != row:
                    raise ValueError("Committed AC diagnostic evidence changed")
            else:
                study.write(output, row)
            rows.append(row)
        comparable, updates = interpret(spec, metric, rows)
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "ac_diagnostic_experiment_finished",
                  "source_study_id": spec.source_study_id, "source_report_sha256": spec.source_report_sha256,
                  "authorization_sha256": spec.sha256(), "reserved_solver_runs": len(rows),
                  "max_solver_runs": spec.max_solver_runs, "source_measurement": metric,
                  "baseline_reproduced": comparable, "observations": rows, "hypothesis_updates": updates,
                  "completed": comparable and all(r["status"] != "inconclusive" for r in updates),
                  "root_cause_confirmed": False, "original_model_modified": False,
                  "scope": "single_snapshot_counterfactual_sensitivity_not_repair_or_safety_certificate"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed AC diagnostic report changed")
        else:
            study.write("report", report)
        return report
