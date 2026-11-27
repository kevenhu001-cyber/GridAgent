"""Budgeted diagnostic experiments over committed infeasible security studies."""

from pathlib import Path

from .diagnosis import diagnose_study
from .diagnostic_experiment_ir import DiagnosticExperiment, compile_probes
from .dsr import Study
from .engineering_ir import fingerprint
from .math_program_router import solve
from .math_program_tasks import PROTOCOL as MATH_PROTOCOL
from .math_program_tasks import resume_program, start_program

PROTOCOL = "security-diagnostic-experiment-v1"


def prepare(root, spec):
    diagnosis = diagnose_study(root, spec.source_study_id)
    if diagnosis["source_protocol"] != MATH_PROTOCOL or diagnosis["source_report_sha256"] != spec.source_report_sha256:
        raise ValueError("Diagnostic authorization does not match committed source")
    source = Study.reopen(root / "studies", spec.source_study_id)
    report = source.read("report")
    result = report["solver_result"]
    if report["completed"] or result["status"] != "infeasible_reported":
        raise ValueError("Source must report infeasibility without a verified candidate")
    if fingerprint(report) != spec.source_report_sha256:
        raise ValueError("Source report changed")
    if not result.get("scipy_version"):
        raise ValueError("Source solver version unavailable")
    cases = compile_probes(spec, source.read("manifest")["spec"])
    return cases, result["scipy_version"]


def start_experiment(root, spec):
    root = Path(root).resolve()
    spec = DiagnosticExperiment.model_validate(spec)
    cases, version = prepare(root, spec)
    study = Study(root / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": spec.canonical(), "sha256": spec.sha256(),
                             "source_solver_version": version, "cases": [job for job, _ in cases]})
    return study.id


def no_solver(*args, **kwargs):
    raise AssertionError("A reserved diagnostic child cannot be relaunched")


def observe(root, study, job, variant, source_version, *, fresh, solver):
    index = job["index"]
    link_name = f"child-{index}"
    if fresh:
        child = start_program(root, variant)
        study.write(link_name, {"study_id": child, "program_sha256": variant.sha256()})
    if not study.exists(link_name):
        return {**job, "child_study_id": None, "status": "unknown_reserved_call", "comparable": False}
    link = study.read(link_name)
    child = Study.reopen(root / "studies", link["study_id"])
    expected_manifest = {"protocol": MATH_PROTOCOL, "spec": variant.canonical(), "sha256": variant.sha256()}
    if link["program_sha256"] != variant.sha256() or child.read("manifest") != expected_manifest:
        raise ValueError("Diagnostic child differs from frozen variant")
    if fresh:
        report = resume_program(root, child.id, solver=solver)
    elif child.exists("report") and child.exists("reservation-1"):
        report = resume_program(root, child.id, solver=no_solver)
    else:
        return {**job, "child_study_id": child.id, "status": "unknown_reserved_call", "comparable": False}
    result = report["solver_result"]
    comparable = result.get("scipy_version") == source_version
    status = ("verified_feasible_candidate" if report["completed"] else
              "infeasible_reported" if result["status"] == "infeasible_reported" else "inconclusive")
    return {**job, "child_study_id": child.id, "child_report_sha256": fingerprint(report),
            "status": status, "comparable": comparable, "solver_status": result["status"],
            "solver_version": result.get("scipy_version"), "objective": report["verification"]["primal"]["objective"]}


def interpret(rows):
    base = rows[0]
    base_feasible = base["comparable"] and base["status"] == "verified_feasible_candidate"
    findings = []
    for row in rows[1:]:
        if not base_feasible or not row["comparable"]:
            status = "inconclusive"
        elif row["status"] == "infeasible_reported":
            status = "supports_contingency_conflict_hypothesis"
        elif row["status"] == "verified_feasible_candidate":
            status = "single_contingency_feasible_in_isolation"
        else:
            status = "inconclusive"
        findings.append({"probe": row["probe"], "status": status,
                         "child_study_id": row["child_study_id"], "root_cause_confirmed": False})
    if not base["comparable"]:
        conclusion = "base_evidence_unavailable_or_version_mismatch"
    elif base["status"] == "infeasible_reported":
        conclusion = "base_infeasibility_reported_contingency_isolation_inconclusive"
    elif not base_feasible:
        conclusion = "base_feasibility_not_established"
    elif any(row["status"] == "supports_contingency_conflict_hypothesis" for row in findings):
        conclusion = "one_or_more_contingency_conflict_hypotheses_supported"
    elif all(row["status"] == "single_contingency_feasible_in_isolation" for row in findings):
        conclusion = "selected_contingencies_feasible_in_isolation_joint_conflict_not_excluded"
    else:
        conclusion = "contingency_isolation_inconclusive"
    return conclusion, findings


def resume_experiment(root, identifier, *, solver=solve):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    with study.lock():
        frozen = study.read("manifest")
        spec = DiagnosticExperiment.model_validate(frozen["spec"])
        if frozen.get("protocol") != PROTOCOL or frozen["sha256"] != spec.sha256():
            raise ValueError("Frozen diagnostic authorization changed")
        cases, version = prepare(root, spec)
        if frozen["cases"] != [job for job, _ in cases] or frozen["source_solver_version"] != version:
            raise ValueError("Frozen diagnostic case plan changed")
        rows = []
        children = set()
        for job, variant in cases:
            i = job["index"]
            reservation, output = f"reservation-{i}", f"evaluation-{i}"
            fresh = not study.exists(reservation)
            if fresh:
                if any(study.exists(name) for name in (output, f"child-{i}", "report")):
                    raise ValueError("Diagnostic evidence without reservation")
                study.write(reservation, job)
            elif study.read(reservation) != job:
                raise ValueError("Diagnostic reservation changed")
            row = observe(root, study, job, variant, version, fresh=fresh, solver=solver)
            child = row["child_study_id"]
            if child is not None:
                if child in children or child == spec.source_study_id:
                    raise ValueError("Diagnostic child must be unique and distinct from source")
                children.add(child)
            if study.exists(output):
                if study.read(output) != row:
                    raise ValueError("Committed diagnostic evidence changed")
            else:
                study.write(output, row)
            rows.append(row)
        conclusion, findings = interpret(rows)
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "diagnostic_experiment_finished",
                  "source_study_id": spec.source_study_id, "source_report_sha256": spec.source_report_sha256,
                  "authorization_sha256": spec.sha256(), "reserved_solver_calls": len(rows),
                  "max_solver_calls": spec.max_solver_calls, "observations": rows,
                  "conclusion": conclusion, "hypothesis_updates": findings,
                  "completed": all(row["comparable"] and row["status"] in {
                      "verified_feasible_candidate", "infeasible_reported"} for row in rows),
                  "root_cause_confirmed": False, "original_model_modified": False,
                  "scope": "counterfactual diagnostic models only; not original security feasibility or repair"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed diagnostic report changed")
        else:
            study.write("report", report)
        return report
