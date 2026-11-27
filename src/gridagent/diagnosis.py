"""Read-only diagnosis of committed, replay-verified mathematical and AC studies."""

from pathlib import Path

from .ac_check import PROTOCOL as AC_PROTOCOL
from .ac_check import resume_ac_check
from .diagnosis_rules import RULES, VERSION, rule_for
from .dsr import Study
from .engineering_ir import fingerprint
from .math_program_tasks import PROTOCOL as MATH_PROTOCOL
from .math_program_tasks import resume_program
from .official_knowledge import official_rows

MAX_EXAMPLES = 5


def summarize(report):
    """Classify evidence, not causes; bounded examples preserve total counts."""
    findings = {}

    def add(rule, scope, key, context, detail, evidence_kind="independent_check"):
        entry = findings.setdefault(rule, {"rule_id": rule, "count": 0, "evidence": []})
        entry["count"] += 1
        if len(entry["evidence"]) < MAX_EXAMPLES:
            entry["evidence"].append({"scope": scope, "check_id": key, "context": context,
                                      "detail": detail, "evidence_kind": evidence_kind})

    def checks(rows, scope, context):
        for row in rows:
            if row.get("passed") is False:
                add(rule_for(scope, row["id"]), scope, row["id"], context,
                    {key: row[key] for key in ("observed", "limit", "violation", "tolerance", "activity")
                     if key in row})

    def solver_status(status, context):
        if status == "infeasible_reported":
            rule = "infeasibility_reported"
        elif status in {"limit_reached", "evaluation_or_time_limit"}:
            rule = "solver_limit"
        elif status == "unknown_reserved_call":
            rule = "missing_evidence"
        elif status in {"solver_error", "solver_exception", "solver_stopped", "no_feasible_baseline"}:
            rule = "solver_nonconvergence"
        else:
            rule = "unclassified"
        add(rule, "solver", status, context, {}, "solver_report_not_causal_proof")

    if report["protocol"] == MATH_PROTOCOL:
        verdict = report["verification"]
        primal = verdict["primal"]
        checks(primal.get("checks", []), "mathematical", "baseline")
        commitment = verdict.get("commitment") or {}
        physical = commitment.get("physical") or {}
        checks(physical.get("checks", []), "commitment", "baseline")
        if not primal["passed"] and not findings:
            solver_status(report["solver_result"]["status"], "baseline")
        certificate = verdict.get("lp_certificate")
        if primal["passed"] and certificate and not certificate["passed"]:
            add("optimality", "mathematical", "lp_certificate", "baseline", certificate)
        advanced = verdict.get("advanced_analysis") or {}
        if advanced.get("kkt") and not advanced["kkt"]["passed"]:
            add("optimality", "mathematical", "kkt", "baseline",
                {"status": advanced["kkt"]["status"]})
        for row in advanced.get("rhs_scan", []):
            if row["status"] != "verified_feasible_candidate":
                add("missing_evidence", "mathematical", "rhs_scan", row["case"],
                    {"status": row["status"]})
            elif row.get("kkt") and not row["kkt"]["passed"]:
                add("optimality", "mathematical", "kkt", row["case"], {"status": row["kkt"]["status"]})
    elif report["protocol"] == AC_PROTOCOL:
        for row in report["snapshots"]:
            context = {"snapshot": row["snapshot"], "run_id": row["run_id"]}
            status = row["native_evidence"]["status"]
            if status == "unavailable":
                add("missing_evidence", "ac_native", "native_evidence", context,
                    {"status": status, "category": row["native_verdict"].get("category")},
                    "availability_not_physical_failure")
                continue
            checks(row["native_verdict"]["checks"], "ac_native", context)
            physical = row.get("physical")
            if status == "verified" and (not physical or "checks" not in physical):
                add("missing_evidence", "ac_physical", "supplementary_evidence", context,
                    {"reason": physical.get("reason") if physical else None}, "availability_not_physical_failure")
            elif physical:
                checks(physical.get("checks", []), "ac_physical", context)
    else:
        raise ValueError("Unsupported diagnostic study protocol")

    references = {row["id"]: row for row in official_rows()}
    for key, entry in findings.items():
        rule = RULES[key]
        entry.update(category=rule.category, observed_symptom=rule.symptom,
                     hypotheses=[{"description": hypothesis, "status": "untested"} for hypothesis in rule.hypotheses],
                     suggested_experiments=[{"description": item, "execution": "not_executed",
                                             "requires_separate_authorization": True}
                                            for item in rule.discriminate],
                     references=[{field: references[ref][field] for field in ("id", "source", "version", "authority")}
                                 for ref in rule.references if ref in references],
                     omitted_examples=max(0, entry["count"]-len(entry["evidence"])))
    status = "findings_present" if findings else (
        "no_failed_checks_observed" if report["completed"] else "insufficient_evidence")
    return {"protocol": VERSION, "source_study_id": report["study_id"],
            "source_protocol": report["protocol"], "source_report_sha256": fingerprint(report),
            "source_completed": report["completed"], "diagnosis_status": status,
            "findings": list(findings.values()), "root_cause_confirmed": False,
            "solver_calls": 0, "automatic_changes": False,
            "scope": "heuristic diagnosis of recorded checks only; not a safety certification"}


def _no_solver(*args, **kwargs):
    raise AssertionError("Diagnosis must never launch a solver")


def diagnose_study(root, identifier):
    root = Path(root).resolve()
    source = Study.reopen(root / "studies", identifier)
    if not source.exists("report"):
        raise ValueError("Diagnosis requires a committed source report")
    manifest = source.read("manifest")
    protocol = manifest.get("protocol")
    if protocol == MATH_PROTOCOL:
        if not source.exists("reservation-1"):
            raise ValueError("Missing mathematical reservation")
        report = resume_program(root, identifier, solver=_no_solver)
    elif protocol == AC_PROTOCOL:
        count = len(manifest["spec"]["snapshots"])
        if not all(source.exists(f"reservation-{i}") and source.exists(f"evaluation-{i}")
                   for i in range(1, count+1)):
            raise ValueError("Missing committed AC snapshot evidence")
        report = resume_ac_check(root, identifier, solver=_no_solver)
    else:
        raise ValueError("Unsupported diagnostic study protocol")
    return summarize(report)
