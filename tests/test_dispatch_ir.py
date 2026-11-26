import json

import pandas as pd
import pytest
from pydantic import ValidationError

from gridagent.dispatch_ir import DispatchModelIR, DispatchStudy, DispatchStudySpec, compile_dispatch
from gridagent.dispatch_tasks import DispatchTasks
from gridagent.model_quality import evaluate_run
from gridagent.native_program import EnergyStorage
from gridagent.task_contracts import TaskStatus


def raw_model():
    return {
        "model_id": "battery_dispatch", "hours": 2, "currency": "CNY",
        "buses": [{"id": "bus", "nominal_kv": 20}],
        "loads": [{"id": "demand", "bus": "bus", "demand_mw": [1, 1]}],
        "generators": [{"id": "supply", "bus": "bus", "capacity_mw": 2,
                        "marginal_cost_per_mwh": [10, 100]}],
        "storage": [{"id": "battery", "bus": "bus", "power_capacity_mw": 1,
                     "energy_capacity_mwh": 1, "charge_efficiency": 1, "discharge_efficiency": 1,
                     "soc_boundary": "fixed_initial", "initial_soc_mwh": 0, "terminal_soc_mwh": 0}],
    }


def source(raw=None):
    model = DispatchModelIR.model_validate(raw or raw_model())
    return DispatchStudy(model=model, study=DispatchStudySpec(
        description="Minimize two-hour operating cost", model_sha256=model.sha256(),
    ))


def test_compile_preserves_profiles_efficiency_and_soc():
    spec = source()
    program, provenance = compile_dispatch(spec)
    storage = program.storage[0]
    assert not storage.cyclic_soc
    assert storage.initial_soc_mwh == storage.terminal_soc_mwh == 0
    assert storage.max_hours == 1
    assert storage.p_nom_mw == 1
    assert program.generators[0].marginal_cost == [10, 100]
    assert program.loads[0].p_set_mw == [1, 1]
    assert provenance["currency"] == "CNY"
    assert provenance["model_sha256"] == spec.model.sha256()
    assert compile_dispatch(spec)[1] == provenance


@pytest.mark.parametrize("fault", ["unknown_bus", "duplicate", "wrong_hours", "invalid_soc",
                                  "conflicting_soc", "missing_initial", "invalid_efficiency"])
def test_dispatch_rejects_invalid_contracts(fault):
    raw = raw_model()
    if fault == "unknown_bus":
        raw["loads"][0]["bus"] = "missing"
    elif fault == "duplicate":
        raw["generators"][0]["id"] = "demand"
    elif fault == "wrong_hours":
        raw["loads"][0]["demand_mw"] = [1]
    elif fault == "invalid_soc":
        raw["storage"][0]["initial_soc_mwh"] = 2
    elif fault == "conflicting_soc":
        raw["storage"][0]["soc_boundary"] = "cyclic"
    elif fault == "missing_initial":
        del raw["storage"][0]["initial_soc_mwh"]
    else:
        raw["storage"][0]["charge_efficiency"] = 0
    with pytest.raises(ValidationError):
        source(raw)


def test_legacy_storage_default_is_still_cyclic():
    item = EnergyStorage(name="s", bus="b", p_nom_mw=2, max_hours=3)
    assert item.cyclic_soc and item.initial_soc_mwh is None
    raw = raw_model()
    raw["storage"][0].update(soc_boundary="cyclic", initial_soc_mwh=None, terminal_soc_mwh=None)
    assert compile_dispatch(source(raw))[0].storage[0].cyclic_soc


def fake_solver(root, request, *, run_id):
    folder = root / "runs" / run_id
    folder.mkdir(parents=True)
    (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
    data = {
        "generation_mw": {"supply": [2, 0]}, "load_mw": {"demand": [1, 1]},
        "storage_soc_mwh": {"battery": [1, 0]},
        "storage_charge_mw": {"battery": [1, 0]}, "storage_discharge_mw": {"battery": [0, 1]},
        "link_mw": {}, "link_destination_mw": {},
    }
    for key, columns in data.items():
        pd.DataFrame(columns, index=["t0", "t1"]).to_csv(folder / (key + ".csv"))
    result = {"backend": "pypsa", "version": "fixture", "run_id": run_id,
              "status": "ok", "solver_status": "ok", "termination_condition": "optimal",
              "metrics": {"objective": 20}}
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")


def test_native_evidence_checks_initial_terminal_soc_and_cost(tmp_path):
    program, _ = compile_dispatch(source())
    request = program.model_dump(mode="json")
    identifier = "a" * 32
    fake_solver(tmp_path, request, run_id=identifier)
    folder = tmp_path / "runs" / identifier
    result = {"status": "ok", "metrics": {"objective": 20}}
    assert evaluate_run(folder, request, result)["passed"]
    request["storage"][0]["initial_soc_mwh"] = 0.5
    request["storage"][0]["terminal_soc_mwh"] = 0.5
    result["metrics"]["objective"] = 99
    checks = {row["id"]: row["passed"] for row in evaluate_run(folder, request, result)["tests"]}
    assert not checks["storage_energy_balance"]
    assert not checks["terminal_soc"]
    assert not checks["operating_cost_reconciliation"]


def test_dispatch_uses_canonical_lifecycle_and_recovers_committed_evidence(tmp_path):
    tasks = DispatchTasks(tmp_path)
    identifier = tasks.start(source())
    assert tasks.repository.get(identifier).status == TaskStatus.PLANNED
    with pytest.raises(ValueError, match="Dispatch-managed"):
        tasks.repository.transition(identifier, 1, TaskStatus.RUNNING)

    def interrupted(root, request, *, run_id):
        fake_solver(root, request, run_id=run_id)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tasks.resume(identifier, solver=interrupted)
    reopened = DispatchTasks(tmp_path)
    assert reopened.summary(identifier)["status"] == "running"
    final = reopened.resume(identifier, solver=lambda *a, **k: pytest.fail("Duplicate native run"))
    assert final["status"] == "completed", final
    assert final["evidence"]["passed"]
    nodes = {node["node_id"]: node for node in final["execution_nodes"]}
    assert nodes["solve-001"]["run_id"] == final["run_id"]
    assert nodes["verify-001"]["outcome"] == nodes["aggregate"]["outcome"] == "verified"
    from gridagent.evidence import EvidenceRecord, verify_artifacts

    evidence = EvidenceRecord.model_validate(final["evidence"]["evidence_record"])
    assert evidence.status == "verified"
    assert evidence.plan_sha256 == final["source"]["execution_plan_sha256"]
    assert verify_artifacts(tmp_path, evidence)
    assert reopened.resume(identifier) == final
    assert [event.to_status.value for event in reopened.repository.events(identifier)] == [
        "planned", "running", "verifying", "completed"]


def test_unknown_reserved_dispatch_is_not_rerun(tmp_path):
    tasks = DispatchTasks(tmp_path)
    identifier = tasks.start(source())

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        tasks.resume(identifier, solver=interrupted)
    final = DispatchTasks(tmp_path).resume(
        identifier, solver=lambda *a, **k: pytest.fail("Duplicate native run"))
    assert final["status"] == "failed"
    assert final["reason"] == "unknown_or_missing_native_result"
    nodes = {node["node_id"]: node for node in final["execution_nodes"]}
    assert nodes["solve-001"]["outcome"] == "unknown"
    assert nodes["verify-001"]["outcome"] == "unavailable"
    assert nodes["aggregate"]["outcome"] == "rejected"


def test_dispatch_cancellation_before_launch(tmp_path):
    tasks = DispatchTasks(tmp_path)
    identifier = tasks.start(source())
    final = tasks.cancel(identifier)
    assert final["status"] == "cancelled"
    assert all(node["status"] == "cancelled" for node in final["execution_nodes"])
    assert tasks.resume(identifier, solver=lambda *a, **k: pytest.fail("Unexpected solve"))["run_id"] is None


@pytest.mark.integration
def test_real_fixed_soc_dispatch_matches_analytic_optimum(tmp_path):
    pytest.importorskip("pypsa")
    pytest.importorskip("highspy")
    tasks = DispatchTasks(tmp_path)
    final = tasks.resume(tasks.start(source()))
    assert final["status"] == "completed", final
    assert final["evidence"]["metrics"]["objective"] == pytest.approx(20)
    folder = tmp_path / "runs" / final["run_id"]
    soc = pd.read_csv(folder / "storage_soc_mwh.csv", index_col=0)["battery"].tolist()
    assert soc == pytest.approx([1, 0], abs=1e-6)


def test_dispatch_rejects_changed_frozen_study_before_launch(tmp_path):
    tasks = DispatchTasks(tmp_path)
    identifier = tasks.start(source())
    with tasks.connect() as db:
        row = db.execute("SELECT source FROM dispatch_tasks WHERE id=?", (identifier,)).fetchone()
        data = json.loads(row["source"])
        model = DispatchModelIR.model_validate(data["provenance"]["model"])
        study = DispatchStudySpec(description="Changed objective description", model_sha256=model.sha256())
        program, provenance = compile_dispatch(DispatchStudy(model=model, study=study))
        db.execute("UPDATE dispatch_tasks SET source=? WHERE id=?", (
            json.dumps({"provenance": provenance, "program": program.model_dump(mode="json")}), identifier))
    with pytest.raises(ValueError, match="provenance changed"):
        tasks.resume(identifier, solver=lambda *a, **k: pytest.fail("Unexpected native run"))
    assert tasks.summary(identifier)["status"] == "planned"


def test_solver_exception_is_recorded_without_provider_payload(tmp_path):
    tasks = DispatchTasks(tmp_path)
    identifier = tasks.start(source())

    def fail(*args, **kwargs):
        raise RuntimeError("private solver diagnostic")

    final = tasks.resume(identifier, solver=fail)
    assert final["status"] == "failed"
    assert final["evidence"]["launch_error_type"] == "RuntimeError"
    assert "private solver diagnostic" not in json.dumps(final)
    assert final["evidence"]["evidence_record"]["status"] == "unavailable"
