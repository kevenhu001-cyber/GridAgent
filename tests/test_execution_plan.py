import json

import pytest
from pydantic import ValidationError

from gridagent.evidence import EvidenceRecord, capture_evidence, verify_artifacts, verify_record
from gridagent.execution_plan import ExecutionPlan, fixed_plan

MODEL = "a" * 64
STUDY = "b" * 64
REQUEST = {"backend": "pypsa", "hours": 1, "lines": []}
VERDICT = {"passed": True, "tests": [{"id": "balance", "passed": True}]}


def plan():
    return fixed_plan(family="hourly_linear_dispatch", model_sha256=MODEL, study_sha256=STUDY,
                      requests=[("dispatch", REQUEST)], max_solver_runs=1)


def test_dag_dependencies_and_deterministic_order():
    p = fixed_plan(family="ac_steady_state", model_sha256=MODEL, study_sha256=STUDY,
                   requests=[("base", {"a": 1}), ("peak", {"a": 2})], max_solver_runs=2)
    assert [n.id for n in p.ready()] == ["solve-001", "solve-002"]
    assert [n.id for n in p.ready(["solve-001"])] == ["solve-002", "verify-001"]
    completed = ["solve-001", "solve-002", "verify-001", "verify-002"]
    assert [n.id for n in p.ready(completed)] == ["aggregate"]
    assert p.ready([*completed, "aggregate"]) == ()
    assert p.sha256() == ExecutionPlan.model_validate_json(p.model_dump_json()).sha256()


@pytest.mark.parametrize("fault", ["budget", "duplicate", "unknown", "cycle", "input", "aggregate"])
def test_reject_invalid_graph(fault):
    raw = plan().model_dump(mode="json")
    if fault == "budget":
        raw["max_solver_runs"] = 0
    elif fault == "duplicate":
        raw["nodes"][1]["id"] = raw["nodes"][0]["id"]
    elif fault == "unknown":
        raw["nodes"][1]["depends_on"] = ["missing"]
    elif fault == "cycle":
        raw["nodes"][1]["depends_on"] = ["aggregate"]
    elif fault == "input":
        raw["nodes"][1]["request_sha256"] = "c" * 64
    else:
        raw["nodes"][2]["depends_on"] = ["solve-001"]
    with pytest.raises(ValidationError):
        ExecutionPlan.model_validate(raw)


def test_wrong_input_and_inconsistent_completed_set():
    p = plan()
    with pytest.raises(ValueError, match="frozen execution plan"):
        p.solve_for("dispatch", {"backend": "pypsa", "hours": 2})
    with pytest.raises(ValueError, match="completed node set"):
        p.ready(["verify-001"])


def fake_artifacts(root):
    run_id = "d" * 32
    folder = root / "runs" / run_id
    folder.mkdir(parents=True)
    from gridagent.evidence import DISPATCH_FILES

    for name in DISPATCH_FILES:
        (folder / name).write_text("fixture", encoding="utf-8")
    (folder / "request.json").write_text(json.dumps(REQUEST), encoding="utf-8")
    result = {"run_id": run_id, "backend": "pypsa", "status": "ok", "version": "fixture"}
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    return folder, run_id


def test_evidence_identity_and_artifact_mutation(tmp_path):
    folder, run_id = fake_artifacts(tmp_path)
    p = plan()
    record = capture_evidence(tmp_path, p, "dispatch", run_id, REQUEST, version="fixture", verdict=VERDICT)
    assert record.status == "verified"
    assert verify_artifacts(tmp_path, record)
    assert verify_record(tmp_path, record, p, "dispatch", run_id, REQUEST, VERDICT) == record
    (folder / "load_mw.csv").write_text("changed", encoding="utf-8")
    assert not verify_artifacts(tmp_path, record)
    with pytest.raises(ValueError, match="artifacts changed"):
        verify_record(tmp_path, record, p, "dispatch", run_id, REQUEST, VERDICT)


def test_incomplete_evidence_never_passes(tmp_path):
    folder, run_id = fake_artifacts(tmp_path)
    (folder / "storage_soc_mwh.csv").unlink()
    record = capture_evidence(tmp_path, plan(), "dispatch", run_id, REQUEST, version="fixture", verdict=VERDICT)
    assert record.status == "unavailable"
    raw = record.model_dump(mode="json")
    raw["status"] = "verified"
    with pytest.raises(ValidationError):
        EvidenceRecord.model_validate(raw)


def test_evidence_rejects_changed_verdict(tmp_path):
    _, run_id = fake_artifacts(tmp_path)
    p = plan()
    record = capture_evidence(tmp_path, p, "dispatch", run_id, REQUEST, version="fixture", verdict=VERDICT)
    with pytest.raises(ValueError, match="frozen plan or verdict"):
        verify_record(tmp_path, record, p, "dispatch", run_id, REQUEST, {"passed": False})
