import json

import pytest

from gridagent.diagnosis import diagnose_study, summarize
from gridagent.diagnosis_rules import rule_for
from gridagent.math_program_tasks import resume_program, start_program


def lp():
    return {"description": "A bounded dispatch",
            "variables": [{"id": "x", "lower": 0, "upper": 2, "unit": "MW"}],
            "constraints": [{"id": "balance", "lower": 3, "upper": 3, "unit": "MW",
                             "terms": [{"variable": "x", "coefficient": 1}]}],
            "objective": {"unit": "CNY/h", "terms": [{"variable": "x", "coefficient": 1}]}}


def test_infeasible_math_report_remains_uncertified(tmp_path):
    identifier = start_program(tmp_path, lp())
    report = resume_program(tmp_path, identifier)
    assert report["solver_result"]["status"] == "infeasible_reported"
    diagnosis = diagnose_study(tmp_path, identifier)
    assert diagnosis["diagnosis_status"] == "findings_present"
    assert diagnosis["findings"][0]["rule_id"] == "infeasibility_reported"
    assert diagnosis["findings"][0]["evidence"][0]["evidence_kind"] == "solver_report_not_causal_proof"
    assert not diagnosis["root_cause_confirmed"]
    assert diagnosis["solver_calls"] == 0
    assert all(item["status"] == "untested" for item in diagnosis["findings"][0]["hypotheses"])
    assert all(item["requires_separate_authorization"]
               for item in diagnosis["findings"][0]["suggested_experiments"])
    assert diagnose_study(tmp_path, identifier) == diagnosis


def test_verified_lp_is_not_a_safety_certificate(tmp_path):
    raw = lp()
    raw["constraints"][0].update(lower=1, upper=1)
    identifier = start_program(tmp_path, raw)
    assert resume_program(tmp_path, identifier)["completed"]
    diagnosis = diagnose_study(tmp_path, identifier)
    assert diagnosis["diagnosis_status"] == "no_failed_checks_observed"
    assert diagnosis["findings"] == []
    assert not diagnosis["root_cause_confirmed"]
    assert not diagnosis["automatic_changes"]


def test_unfinished_study_is_not_executed(tmp_path):
    identifier = start_program(tmp_path, lp())
    with pytest.raises(ValueError, match="committed source report"):
        diagnose_study(tmp_path, identifier)
    assert not (tmp_path / "studies" / identifier / "reservation-1.json").exists()


def test_diagnosis_rejects_modified_report(tmp_path):
    identifier = start_program(tmp_path, lp())
    resume_program(tmp_path, identifier)
    path = tmp_path / "studies" / identifier / "report.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    report["completed"] = True
    path.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        diagnose_study(tmp_path, identifier)


def test_generic_user_row_names_are_not_physical_diagnoses():
    assert rule_for("mathematical", "row:voltage_operating_range") == "primal_row"
    assert rule_for("mathematical", "row:reserve:unit") == "primal_row"
    assert rule_for("ac_native", "voltage_operating_range") == "voltage"
    assert rule_for("ac_physical", "reactive:g1") == "reactive"
    assert rule_for("commitment", "unit-security:g1:0:unit:g1:outage") == "outage"
    assert rule_for("commitment", "unit-security:g1:0:unit:g2:up") == "reserve"


def test_ac_evidence_distinguishes_voltage_reactive_and_unavailable():
    # Synthetic verifier-output fixture, not a native solver result.
    report = {"protocol": "dc-ac-cross-check-v1", "study_id": "a"*32,
              "completed": False, "snapshots": [
                  {"snapshot": {"hour": 0}, "run_id": "b"*32,
                   "native_evidence": {"status": "rejected"},
                   "native_verdict": {"checks": [{"id": "voltage_operating_range", "passed": False,
                                                  "observed": [0.82, 1], "limit": [0.9, 1.1]}]},
                   "physical": None},
                  {"snapshot": {"hour": 1}, "run_id": "c"*32,
                   "native_evidence": {"status": "verified"},
                   "native_verdict": {"checks": [{"id": "voltage_operating_range", "passed": True}]},
                   "physical": {"checks": [{"id": "reactive:g1", "passed": False, "violation": 2}]}},
                  {"snapshot": {"hour": 2}, "run_id": "d"*32,
                   "native_evidence": {"status": "unavailable"},
                   "native_verdict": {"category": "interrupted_run", "checks": [
                       {"id": "solver_success", "passed": False}]}, "physical": None}]}
    diagnosis = summarize(report)
    findings = {row["rule_id"]: row for row in diagnosis["findings"]}
    assert set(findings) == {"voltage", "reactive", "missing_evidence"}
    assert len(findings["voltage"]["hypotheses"]) >= 2
    assert findings["voltage"]["evidence"][0]["context"]["run_id"] == "b"*32
    assert findings["missing_evidence"]["evidence"][0]["evidence_kind"] == "availability_not_physical_failure"
    assert not diagnosis["root_cause_confirmed"]


def test_evidence_examples_bounded_without_losing_total_count():
    report = {"protocol": "mathematical-program-v1", "study_id": "a"*32,
              "completed": False, "solver_result": {"status": "optimal_reported"},
              "verification": {"primal": {"passed": False, "checks": [
                  {"id": f"row:c{i}", "passed": False, "violation": 1} for i in range(20)]}}}
    finding = summarize(report)["findings"][0]
    assert finding["rule_id"] == "primal_row"
    assert finding["count"] == 20
    assert len(finding["evidence"]) == 5
    assert finding["omitted_examples"] == 15


def test_interrupted_result_is_not_relaunched(tmp_path):
    identifier = start_program(tmp_path, lp())

    def interrupt(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        resume_program(tmp_path, identifier, solver=interrupt)
    resume_program(tmp_path, identifier)
    diagnosis = diagnose_study(tmp_path, identifier)
    assert diagnosis["findings"][0]["rule_id"] == "missing_evidence"
    assert diagnosis["solver_calls"] == 0
    assert not (tmp_path / "studies" / identifier / "result.json").exists()
