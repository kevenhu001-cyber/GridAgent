import json

import pytest
from pydantic import ValidationError

from gridagent.engineering_compiler import compile_study
from gridagent.engineering_ir import EngineeringStudy, ModelIR, StudySpec


def model_input():
    return {
        "model_id": "feeder",
        "buses": [{"id": "source", "nominal_kv": 20}, {"id": "loadbus", "nominal_kv": 20}],
        "devices": [
            {"kind": "slack", "id": "grid", "bus": "source"},
            {"kind": "line", "id": "feederline", "from_bus": "source", "to_bus": "loadbus",
             "length_km": 2, "resistance_ohm_per_km": 0.2, "reactance_ohm_per_km": 0.3,
             "current_limit_ka": 0.4},
            {"kind": "load", "id": "demand", "bus": "loadbus", "active_mw": 1, "reactive_mvar": 0.2},
            {"kind": "storage", "id": "battery", "bus": "loadbus", "charging_mw": -0.1,
             "energy_capacity_mwh": 2, "initial_soc_percent": 50},
        ],
    }


def study_input(model=None, scenarios=None):
    model = model or ModelIR.model_validate(model_input())
    return EngineeringStudy(model=model, study=StudySpec(
        objective="Check steady-state feeder voltage",
        model_sha256=model.sha256(),
        scenarios=scenarios or ({"name": "base"}, {"name": "peak", "load_scale": 1.2}),
    ))


def test_stable_fingerprint_and_index_mapping_independent_of_input_order():
    first = study_input()
    raw = model_input()
    raw["buses"].reverse()
    raw["devices"].reverse()
    second = study_input(ModelIR.model_validate(raw))
    a, b = compile_study(first), compile_study(second)
    assert first.model.sha256() == second.model.sha256()
    assert a.manifest == b.manifest
    assert a.provenance == b.provenance
    assert a.provenance["device_indices"]["loadbus"]["index"] == 0
    assert a.provenance["device_indices"]["source"]["index"] == 1
    battery = next(step for step in a.manifest.program.steps if step.op == "create_storage")
    assert battery.p_mw == -0.1
    assert battery.max_e_mwh == 2
    assert a.manifest.max_repairs == 0


def test_compiler_resolves_contingency_stable_id_and_preserves_limits():
    source = study_input(scenarios=({"name": "outage", "outage_device": "feederline"},))
    compiled = compile_study(source)
    outage = compiled.manifest.scenarios[0].outage
    assert outage.element == "line"
    assert outage.index == compiled.provenance["device_indices"]["feederline"]["index"]
    assert compiled.manifest.limits.voltage_min_pu == source.study.acceptance.voltage_min_pu
    assert compiled.manifest.editable == []


@pytest.mark.parametrize("fault", ["duplicate", "unknown_bus", "different_voltage", "no_slack", "self_loop"])
def test_model_rejects_invalid_baseline_topology(fault):
    raw = model_input()
    if fault == "duplicate":
        raw["devices"][0]["id"] = raw["buses"][0]["id"]
    elif fault == "unknown_bus":
        raw["devices"][2]["bus"] = "missing"
    elif fault == "different_voltage":
        raw["buses"][1]["nominal_kv"] = 10
    elif fault == "no_slack":
        raw["devices"].pop(0)
    else:
        raw["devices"][1]["to_bus"] = "source"
    with pytest.raises(ValidationError):
        ModelIR.model_validate(raw)


def test_rejects_unsupported_model_and_contingency():
    raw = model_input()
    raw["family"] = "emt"
    with pytest.raises(ValidationError):
        ModelIR.model_validate(raw)
    source = study_input(scenarios=({"name": "bad", "outage_device": "demand"},))
    with pytest.raises(ValueError, match="Contingency"):
        compile_study(source)


def test_rejects_changed_model_revision():
    source = study_input()
    raw = source.model.model_dump(mode="json")
    raw["revision"] += 1
    with pytest.raises(ValidationError, match="fingerprint"):
        EngineeringStudy(model=ModelIR.model_validate(raw), study=source.study)


def test_transformer_compiles_explicit_rating_and_phase_shift():
    raw = model_input()
    raw["buses"][0]["nominal_kv"] = 110
    raw["devices"][1] = {
        "kind": "transformer", "id": "trafo", "hv_bus": "source", "lv_bus": "loadbus",
        "rated_mva": 10, "rated_hv_kv": 110, "rated_lv_kv": 20, "resistance_percent": 0.5,
        "impedance_percent": 7, "iron_loss_kw": 2, "no_load_current_percent": 0.1,
        "phase_shift_degree": 30,
    }
    result = compile_study(study_input(ModelIR.model_validate(raw)))
    step = next(step for step in result.manifest.program.steps if step.op == "create_transformer_from_parameters")
    assert step.sn_mva == 10
    assert step.shift_degree == 30


def test_ir_task_persists_provenance_and_reopens(tmp_path):
    from gridagent.research import ResearchTasks

    tasks = ResearchTasks(tmp_path)
    source = study_input()
    identifier = tasks.start_ir(source)
    reopened = ResearchTasks(tmp_path)
    report = reopened.summary(identifier, full=True)
    assert report["stage"] == "ready"
    assert report["engineering_status"] == "planned"
    assert report["engineering_model_revision"] == source.model.sha256()
    from gridagent.execution_plan import ExecutionPlan

    plan = ExecutionPlan.model_validate(report["record"]["execution_plan"])
    assert plan.sha256() == report["record"]["execution_plan_sha256"]
    assert [n.scenario for n in plan.ready()] == ["base", "peak"]
    assert len(report["execution_nodes"]) == 5
    assert all(node["status"] == "pending" for node in report["execution_nodes"])
    assert report["record"]["engineering_ir"]["model_sha256"] == source.model.sha256()
    assert report["record"]["engineering_ir"]["device_indices"]["grid"]["table"] == "ext_grid"
    assert json.loads(json.dumps(report))["record"]["manifest"]["max_repairs"] == 0


@pytest.mark.integration
def test_compiled_ir_executes_with_native_verification(tmp_path):
    pytest.importorskip("pandapower")
    from gridagent.research import ResearchTasks

    tasks = ResearchTasks(tmp_path)
    identifier = tasks.start_ir(study_input())
    report = list(tasks.resume(identifier))[-1]
    assert report["stage"] == "passed", report
    assert report["engineering_status"] == "completed"
    assert report["runs_used"] == 2
    nodes = {node["node_id"]: node for node in report["execution_nodes"]}
    assert all(node["status"] == "done" for node in nodes.values())
    assert nodes["aggregate"]["outcome"] == "verified"
    assert all(run["evaluation"]["passed"] for run in report["best_runs"])
    from gridagent.evidence import EvidenceRecord, verify_artifacts

    for run in report["best_runs"]:
        evidence = EvidenceRecord.model_validate(run["evidence_record"])
        assert evidence.status == "verified"
        assert verify_artifacts(tmp_path, evidence)


def test_resume_rejects_changed_ir_provenance_before_solver(tmp_path):
    from gridagent.research import ResearchTasks

    tasks = ResearchTasks(tmp_path)
    identifier = tasks.start_ir(study_input())
    state = tasks.get(identifier)["state"]
    state["engineering_ir"]["device_indices"]["grid"]["index"] = 9
    tasks.save(identifier, state, "ready")
    with pytest.raises(ValueError, match="provenance changed"):
        list(tasks.resume(identifier, solver=lambda *a, **k: pytest.fail("Unexpected solve")))


@pytest.mark.integration
def test_parallel_ir_and_verified_cache_reuse(tmp_path, monkeypatch):
    pytest.importorskip("pandapower")
    from gridagent.research import ResearchTasks

    monkeypatch.setenv("GRIDAGENT_AC_WORKERS", "2")
    monkeypatch.setenv("GRIDAGENT_VERIFIED_CACHE", "1")
    tasks = ResearchTasks(tmp_path)
    first = list(tasks.resume(tasks.start_ir(study_input())))[-1]
    assert first["stage"] == "passed", first
    assert first["native_launches_observed"] == 2
    assert first["cache_hits"] == 0
    second = list(tasks.resume(tasks.start_ir(study_input())))[-1]
    assert second["stage"] == "passed", second
    assert second["cache_hits"] == 2
    assert second["native_launches_observed"] == 0
    assert second["runs_used"] == 2
    assert [r["cache_origin_run_id"] for r in second["best_runs"]] == [
        r["run_id"] for r in first["best_runs"]]
    assert {r["run_id"] for r in second["best_runs"]}.isdisjoint(
        {r["run_id"] for r in first["best_runs"]})
