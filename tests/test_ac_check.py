import copy

import pytest

from gridagent.ac_check import resume_ac_check, start_ac_check
from gridagent.ac_check_ir import ACCheckSpec, snapshot_study, validate_mapping
from gridagent.math_program_tasks import resume_program, start_program


def unit(identifier, cost):
    return {"id": identifier, "minimum_mw": 0, "maximum_mw": 10,
            "marginal_cost_per_mwh": cost, "ramp_up_mw": 8, "ramp_down_mw": 10,
            "startup_limit_mw": 10, "shutdown_limit_mw": 10, "min_up_hours": 1,
            "min_down_hours": 1, "initially_on": True, "initial_mw": 0,
            "initial_state_hours": 2}


def dc_input():
    return {"family": "unit_commitment", "description": "Two bus schedule", "currency": "CNY",
            "demand_mw": [6], "units": [unit("cheap", 10), unit("local", 50)],
            "network": {
                "buses": [{"id": "A", "demand_mw": [0]}, {"id": "B", "demand_mw": [6]}],
                "lines": [{"id": "AB", "from_bus": "A", "to_bus": "B",
                           "susceptance_mw_per_rad": 100, "limit_mw": 10,
                           "max_angle_difference_rad": 0.3}],
                "reference_bus": "A", "angle_bound_rad": 0.5,
                "unit_buses": {"cheap": "A", "local": "B"},
                "reserve_requirement_mw": [1], "reserve_response_minutes": 15,
                "unit_reserve_capability_mw": {"cheap": 0, "local": 4}}}


def ac_input(identifier):
    return {
        "commitment_study_id": identifier,
        "model": {"model_id": "ac-grid",
                  "buses": [{"id": "A", "nominal_kv": 10}, {"id": "B", "nominal_kv": 10}],
                  "devices": [
                      {"kind": "slack", "id": "slackA", "bus": "A", "voltage_pu": 1},
                      {"kind": "generator", "id": "genB", "bus": "B", "active_mw": 0, "voltage_pu": 1},
                      {"kind": "load", "id": "loadA", "bus": "A", "active_mw": 0},
                      {"kind": "load", "id": "loadB", "bus": "B", "active_mw": 0},
                      {"kind": "line", "id": "AB", "from_bus": "A", "to_bus": "B", "length_km": 1,
                       "resistance_ohm_per_km": 0.05, "reactance_ohm_per_km": 1,
                       "current_limit_ka": 2}]},
        "unit_devices": {"cheap": "slackA", "local": "genB"}, "slack_unit": "cheap",
        "unit_reactive_limits": {"cheap": {"minimum_mvar": -10, "maximum_mvar": 10},
                                 "local": {"minimum_mvar": -10, "maximum_mvar": 10}},
        "reactive_demand_mvar": {"A": [0], "B": [1]},
        "snapshots": [{"hour": 0}], "slack_max_deviation_mw": 0.2,
    }


@pytest.fixture
def completed(tmp_path):
    identifier = start_program(tmp_path, dc_input())
    report = resume_program(tmp_path, identifier)
    assert report["completed"]
    return identifier, report["verification"]["commitment"]["physical"]["schedule"]


def test_snapshot_mapping_preserves_voltage_and_impedance(completed):
    identifier, schedule = completed
    spec = ACCheckSpec.model_validate(ac_input(identifier))
    dc = validate_mapping(spec, dc_input())
    source, expected = snapshot_study(spec, dc, schedule, spec.snapshots[0])
    devices = {row.id: row for row in source.model.devices}
    assert devices["loadB"].active_mw == 6
    assert devices["loadB"].reactive_mvar == 1
    assert devices["AB"].resistance_ohm_per_km == 0.05
    assert devices["slackA"].voltage_pu == 1
    assert expected["cheap"]["p_mw"] == pytest.approx(6)
    assert devices["genB"].active_mw == pytest.approx(0)


@pytest.mark.parametrize("fault", ["reactance", "mapping", "load", "reactive", "duplicate", "unknown_outage"])
def test_mapping_rejects_unapproved_input(fault):
    raw = ac_input("a"*32)
    if fault == "reactance":
        raw["model"]["devices"][-1]["reactance_ohm_per_km"] = 2
    elif fault == "mapping":
        raw["unit_devices"]["local"] = "slackA"
    elif fault == "load":
        raw["model"]["devices"].pop(2)
    elif fault == "reactive":
        raw["reactive_demand_mvar"].pop("A")
    elif fault == "duplicate":
        raw["snapshots"].append({"hour": 0})
    else:
        raw["snapshots"][0]["outage_line"] = "AB"
    with pytest.raises(ValueError):
        validate_mapping(ACCheckSpec.model_validate(raw), dc_input())


def test_islanded_ac_outage_rejected():
    dc = dc_input()
    dc["network"]["security"] = {"outage_lines": ["AB"]}
    raw = ac_input("a"*32)
    raw["snapshots"] = [{"hour": 0, "outage_line": "AB"}]
    with pytest.raises(ValueError, match="per-island slack"):
        validate_mapping(ACCheckSpec.model_validate(raw), dc)


def test_unknown_reserved_snapshot_not_replayed(tmp_path, completed):
    identifier, _ = completed
    study = start_ac_check(tmp_path, ac_input(identifier))
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(kwargs["run_id"])
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        resume_ac_check(tmp_path, study, solver=interrupted)
    report = resume_ac_check(tmp_path, study, solver=lambda *a, **kw: pytest.fail("Duplicate solve"))
    assert len(calls) == 1
    assert not report["completed"]
    assert report["snapshots"][0]["native_evidence"]["status"] == "unavailable"
    assert resume_ac_check(tmp_path, study) == report


def test_pending_dc_study_not_executed(tmp_path):
    identifier = start_program(tmp_path, dc_input())
    with pytest.raises(ValueError, match="completed commitment"):
        start_ac_check(tmp_path, ac_input(identifier))


@pytest.mark.integration
def test_native_cross_check_and_reactive_rejection(tmp_path, completed):
    pytest.importorskip("pandapower")
    identifier, _ = completed
    raw = ac_input(identifier)
    study = start_ac_check(tmp_path, raw)
    report = resume_ac_check(tmp_path, study)
    assert report["completed"], report
    assert report["full_dc_schedule_coverage"]
    snapshot = report["snapshots"][0]
    assert snapshot["physical"]["network_loss_mw"] > 0
    assert snapshot["physical"]["slack_deviation_mw"] == pytest.approx(
        snapshot["physical"]["network_loss_mw"], abs=1e-5)
    assert len(snapshot["supplementary_artifacts"]) == 4
    assert resume_ac_check(tmp_path, study, solver=lambda *a, **kw: pytest.fail("Duplicate solve")) == report
    constrained = copy.deepcopy(raw)
    constrained["unit_reactive_limits"]["local"] = {"minimum_mvar": 0, "maximum_mvar": 0}
    rejected = resume_ac_check(tmp_path, start_ac_check(tmp_path, constrained))
    assert not rejected["completed"]
    assert not rejected["snapshots"][0]["physical"]["passed"]



def test_base_ac_snapshot_cannot_claim_full_generator_contingency_coverage(tmp_path):
    raw = dc_input()
    raw["network"]["security"] = {"outage_units": ["cheap"]}
    identifier = start_program(tmp_path, raw)
    assert resume_program(tmp_path, identifier)["completed"]
    study = start_ac_check(tmp_path, ac_input(identifier))
    report = resume_ac_check(tmp_path, study, solver=lambda *args, **kwargs: None)
    assert not report["full_dc_schedule_coverage"]
    assert not report["completed"]



def diagnostic_input(identifier="a"*32, digest="b"*64):
    return {"source_study_id": identifier, "source_report_sha256": digest,
            "snapshot": {"hour": 0}, "target_scope": "ac_native",
            "target_check": "voltage_operating_range",
            "probes": [{"kind": "voltage_setpoint", "device": "slackA", "value_pu": 0.98}],
            "max_solver_runs": 2}


def test_ac_probe_preserves_locked_inputs():
    from gridagent.ac_diagnostic_ir import ACDiagnosticExperiment, compile_probes

    spec = ACDiagnosticExperiment.model_validate(diagnostic_input())
    original = ACCheckSpec.model_validate(ac_input("a"*32))
    cases = compile_probes(spec, original)
    assert cases[0][1].canonical() == original.canonical()
    job, variant = cases[1]
    assert job["change"] == {"device": "slackA", "field": "voltage_pu", "before": 1, "after": 0.98}
    expected = original.canonical()
    expected["model"]["revision"] += 1
    next(d for d in expected["model"]["devices"] if d["id"] == "slackA")["voltage_pu"] = 0.98
    assert variant.canonical() == expected


@pytest.mark.parametrize("fault", ["unknown", "load", "unchanged", "duplicate", "budget", "wrong_snapshot",
                                   "target", "range", "nonstorage"])
def test_ac_probe_rejects_unauthorized_fields(fault):
    from gridagent.ac_diagnostic_ir import ACDiagnosticExperiment, compile_probes

    raw = diagnostic_input()
    if fault == "unknown":
        raw["probes"][0]["device"] = "missing"
    elif fault == "load":
        raw["probes"][0]["device"] = "loadB"
    elif fault == "unchanged":
        raw["probes"][0]["value_pu"] = 1
    elif fault == "duplicate":
        raw["probes"].append(raw["probes"][0])
        raw["max_solver_runs"] = 3
    elif fault == "budget":
        raw["probes"].append({**raw["probes"][0], "value_pu": 0.99})
    elif fault == "wrong_snapshot":
        raw["snapshot"]["hour"] = 1
    elif fault == "target":
        raw["target_check"] = "model_input_fidelity"
    elif fault == "range":
        raw["probes"][0]["value_pu"] = 1.4
    else:
        raw["probes"] = [{"kind": "storage_reactive", "device": "loadB", "value_mvar": -1,
                          "minimum_mvar": -2, "maximum_mvar": 2}]
    with pytest.raises(ValueError):
        compile_probes(ACDiagnosticExperiment.model_validate(raw), ac_input("a"*32))


def test_storage_reactive_probe_consumption_sign_and_range():
    from gridagent.ac_diagnostic_ir import ACDiagnosticExperiment, compile_probes

    original = ac_input("a"*32)
    original["model"]["devices"].append({"kind": "storage", "id": "battery", "bus": "B",
        "charging_mw": 0, "reactive_mvar": 0, "energy_capacity_mwh": 2, "initial_soc_percent": 50})
    raw = diagnostic_input()
    raw["probes"] = [{"kind": "storage_reactive", "device": "battery", "value_mvar": -1,
                      "minimum_mvar": -2, "maximum_mvar": 2}]
    _, variant = compile_probes(ACDiagnosticExperiment.model_validate(raw), original)[1]
    battery = next(d for d in variant.model.devices if d.id == "battery")
    assert battery.reactive_mvar == -1
    assert battery.charging_mw == 0
    assert battery.initial_soc_percent == 50
    raw["probes"][0]["maximum_mvar"] = -0.5
    with pytest.raises(ValueError, match="Original storage Q"):
        compile_probes(ACDiagnosticExperiment.model_validate(raw), original)


def test_ac_diagnostic_interpretation_abstains_on_baseline_drift_and_version():
    from gridagent.ac_diagnostic_experiment import interpret, measure
    from gridagent.ac_diagnostic_ir import ACDiagnosticExperiment
    from gridagent.engineering_ir import AcceptanceIR

    spec = ACDiagnosticExperiment.model_validate(diagnostic_input())
    observation = {"native_evidence": {"status": "rejected", "solver_version": "3"},
                   "native_verdict": {"checks": [
                       *[{"id": k, "passed": True} for k in ("model_input_fidelity", "solver_success",
                                                             "active_bus_coverage", "power_balance_mva")],
                       {"id": "voltage_operating_range", "passed": False, "observed": [0.82, 1]}]},
                   "passed": False}
    source = measure(spec, observation, AcceptanceIR())
    assert source["violation"] == pytest.approx(0.08)
    rows = [{"measurement": source}, {"measurement": {**source, "violation": 0.04},
                                      "probe": {}, "observation": {"passed": False}}]
    comparable, updates = interpret(spec, source, rows)
    assert comparable
    assert updates[0]["status"] == "target_violation_reduced"
    assert not updates[0]["all_snapshot_checks_passed"]
    rows[1]["measurement"]["solver_version"] = "4"
    assert interpret(spec, source, rows)[1][0]["status"] == "inconclusive"
    rows[0]["measurement"] = {**source, "violation": 0.03}
    assert not interpret(spec, source, rows)[0]
    observation["native_evidence"]["status"] = "unavailable"
    assert measure(spec, observation, AcceptanceIR()) is None


@pytest.mark.integration
def test_native_voltage_diagnostic_reproduces_failure_and_resolves_target(tmp_path, completed):
    pytest.importorskip("pandapower")
    from gridagent.ac_diagnostic_experiment import resume_experiment, start_experiment
    from gridagent.diagnosis import diagnose_study

    identifier, _ = completed
    original = ac_input(identifier)
    original["model"]["devices"][0]["voltage_pu"] = 0.89
    source = start_ac_check(tmp_path, original)
    before = resume_ac_check(tmp_path, source)
    assert not before["completed"]
    digest = diagnose_study(tmp_path, source)["source_report_sha256"]
    raw = diagnostic_input(source, digest)
    raw["probes"][0]["value_pu"] = 1
    experiment = start_experiment(tmp_path, raw)
    report = resume_experiment(tmp_path, experiment)
    assert report["baseline_reproduced"], report
    assert report["hypothesis_updates"][0]["status"] == "target_resolved_in_counterfactual"
    assert report["hypothesis_updates"][0]["all_snapshot_checks_passed"]
    assert report["completed"]
    assert not report["root_cause_confirmed"]
    assert resume_experiment(tmp_path, experiment, solver=lambda *a, **kw: pytest.fail("Repeated solve")) == report
    assert diagnose_study(tmp_path, source)["source_report_sha256"] == digest
