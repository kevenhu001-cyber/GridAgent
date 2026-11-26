"""Revalidate evidence-backed AC repair candidates across the original authorized scope."""

from pathlib import Path
from uuid import uuid4

from .ac_check import observe
from .ac_check import prepare as prepare_ac
from .ac_check_ir import ACCheckSpec
from .ac_diagnostic_experiment import PROTOCOL as DIAGNOSTIC_PROTOCOL
from .ac_diagnostic_experiment import resume_experiment
from .ac_diagnostic_ir import ACDiagnosticExperiment
from .ac_repair_ir import ACRepairAuthorization, compile_candidates, storage_capacity_check
from .dsr import Study
from .engineering_ir import fingerprint
from .native_backends import run_program

PROTOCOL = "ac-evidence-repair-v1"


def no_solver(*args, **kwargs):
    raise AssertionError("Committed diagnostic evidence must not launch a solver")


def prepare(root, auth):
    diagnostic = Study.reopen(root / "studies", auth.diagnostic_study_id)
    if not diagnostic.exists("report"):
        raise ValueError("Repair requires committed AC diagnostic evidence")
    frozen = diagnostic.read("manifest")
    if frozen.get("protocol") != DIAGNOSTIC_PROTOCOL:
        raise ValueError("Repair requires AC diagnostic experiment protocol")
    spec = ACDiagnosticExperiment.model_validate(frozen["spec"])
    if not all(diagnostic.exists(f"reservation-{i}") and diagnostic.exists(f"evaluation-{i}")
               for i in range(len(spec.probes)+1)):
        raise ValueError("Diagnostic reservations or observations missing")
    report = resume_experiment(root, diagnostic.id, solver=no_solver)
    if fingerprint(report) != auth.diagnostic_report_sha256:
        raise ValueError("Repair authorization differs from diagnostic report")
    source = Study.reopen(root / "studies", spec.source_study_id)
    source_report = source.read("report")
    if fingerprint(source_report) != spec.source_report_sha256:
        raise ValueError("Original AC evidence changed")
    original = ACCheckSpec.model_validate(source.read("manifest")["spec"])
    candidates = compile_candidates(auth, spec, original, report)
    version = report["source_measurement"]["solver_version"]
    jobs = []
    for candidate, variant in candidates:
        commitment, cases, dc_sha = prepare_ac(root, variant)
        if dc_sha != source_report["dc_report_sha256"]:
            raise ValueError("Original DC schedule changed")
        for index, case in enumerate(cases):
            capacity = storage_capacity_check(auth, candidate, variant, case)
            if capacity is not None and not capacity["passed"]:
                raise ValueError("Selected storage candidate exceeds authorized apparent power in original scope")
            job = {"index": len(jobs), "candidate_index": candidate["index"], "snapshot_index": index,
                   "snapshot": case[0].model_dump(mode="json"), "request_sha256": fingerprint(case[-1]),
                   "full_ac_spec_sha256": variant.sha256(), "storage_capacity": capacity}
            jobs.append((job, variant, commitment, case))
    return candidates, jobs, version, source_report["full_dc_schedule_coverage"]


def start_repair(root, auth):
    root = Path(root).resolve()
    auth = ACRepairAuthorization.model_validate(auth)
    candidates, jobs, version, full = prepare(root, auth)
    study = Study(root / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": auth.canonical(), "sha256": auth.sha256(),
                             "candidates": [row for row, _ in candidates], "jobs": [row for row, *_ in jobs],
                             "solver_version": version, "full_dc_schedule_coverage": full})
    return study.id


def summarize_candidates(candidates, rows, version, snapshot_count):
    summary = []
    for candidate, variant in candidates:
        selected = [row for row in rows if row["candidate_index"] == candidate["index"]]
        passed = sum(row["observation"]["passed"] is True
                     and row["observation"]["native_evidence"]["solver_version"] == version
                     for row in selected)
        verified = len(selected) == snapshot_count and passed == snapshot_count
        summary.append({"candidate_index": candidate["index"], "change": candidate["change"],
                        "full_ac_spec_sha256": variant.sha256(), "verified_snapshots": passed,
                        "required_snapshots": snapshot_count, "verified": verified,
                        "proposed_ac_spec": variant.canonical() if verified else None})
    return summary


def resume_repair(root, identifier, *, solver=run_program):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    with study.lock():
        frozen = study.read("manifest")
        auth = ACRepairAuthorization.model_validate(frozen["spec"])
        if frozen.get("protocol") != PROTOCOL or frozen["sha256"] != auth.sha256():
            raise ValueError("Frozen repair authorization changed")
        candidates, jobs, version, full = prepare(root, auth)
        if (frozen["candidates"] != [row for row, _ in candidates]
                or frozen["jobs"] != [row for row, *_ in jobs]
                or frozen["solver_version"] != version or frozen["full_dc_schedule_coverage"] != full):
            raise ValueError("Frozen repair plan changed")
        rows, seen = [], set()
        for job, variant, commitment, case in jobs:
            index = job["index"]
            reservation, output = f"reservation-{index}", f"evaluation-{index}"
            fresh = not study.exists(reservation)
            if fresh:
                if study.exists(output) or study.exists("report"):
                    raise ValueError("Repair evidence without reservation")
                study.write(reservation, {"run_id": uuid4().hex, **job})
            reserved = study.read(reservation)
            if {key: reserved.get(key) for key in job} != job or reserved["run_id"] in seen:
                raise ValueError("Repair reservation changed or duplicated")
            seen.add(reserved["run_id"])
            if fresh:
                try:
                    solver(root, case[-1], run_id=reserved["run_id"], timeout_s=variant.timeout_s)
                except Exception as exc:  # noqa: BLE001 - preserve charged reservation
                    study.write(f"launch-error-{index}", {"error_type": type(exc).__name__})
            observation = observe(root, variant, commitment, case, reserved)
            row = {**job, "observation": observation}
            if study.exists(f"launch-error-{index}"):
                row["launch_error_type"] = study.read(f"launch-error-{index}")["error_type"]
            if study.exists(output):
                if study.read(output) != row:
                    raise ValueError("Committed repair evidence changed")
            else:
                study.write(output, row)
            rows.append(row)
        summaries = summarize_candidates(candidates, rows, version, len(candidates[0][1].snapshots))
        winner = next((row["candidate_index"] for row in summaries if row["verified"]), None)
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "ac_evidence_repair_finished",
                  "diagnostic_study_id": auth.diagnostic_study_id,
                  "diagnostic_report_sha256": auth.diagnostic_report_sha256,
                  "authorization_sha256": auth.sha256(), "reserved_solver_runs": len(rows),
                  "max_solver_runs": auth.max_solver_runs, "observations": rows, "candidates": summaries,
                  "recommended_candidate_index": winner, "selection_policy": "first_verified_in_authorized_order",
                  "full_dc_schedule_coverage": full, "completed": winner is not None,
                  "original_model_modified": False, "root_cause_confirmed": False,
                  "scope": "verified_original_ac_snapshot_scope_not_applied_or_dynamic_security"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed repair report changed")
        else:
            study.write("report", report)
        return report
