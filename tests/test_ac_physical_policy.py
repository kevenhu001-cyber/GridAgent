import copy

import pytest

from gridagent.ac_diagnostic_ir import ACDiagnosticExperiment
from gridagent.ac_physical_features import physical_features, physical_similarity
from gridagent.ac_policy_benchmark import evaluate_policy, replay_fixed
from gridagent.dsr import Study


def ac_spec():
    return {"commitment_study_id": "a"*32,
            "model": {"model_id": "grid", "buses": [{"id": "A", "nominal_kv": 10},
                                                     {"id": "B", "nominal_kv": 10}],
                      "devices": [{"kind": "slack", "id": "g", "bus": "A"},
                                  {"kind": "load", "id": "load", "bus": "B", "active_mw": 1},
                                  {"kind": "line", "id": "ab", "from_bus": "A", "to_bus": "B",
                                   "length_km": 1, "resistance_ohm_per_km": 0.1,
                                   "reactance_ohm_per_km": 1, "current_limit_ka": 1}]},
            "unit_devices": {"g": "g"}, "slack_unit": "g",
            "unit_reactive_limits": {"g": {"minimum_mvar": -2, "maximum_mvar": 2}},
            "reactive_demand_mvar": {"A": [0], "B": [1]}, "snapshots": [{"hour": 0}],
            "slack_max_deviation_mw": 0.2}


def observation(status="verified"):
    return {"snapshot": {"hour": 0}, "native_evidence": {"status": status},
            "native_verdict": {"checks": [
                *[{"id": key, "passed": True} for key in (
                    "model_input_fidelity", "solver_success", "active_bus_coverage", "power_balance_mva")],
                {"id": "voltage_operating_range", "observed": [0.88, 1.02], "passed": False},
                {"id": "res_line_loading", "observed": 80, "passed": True}]},
            "physical": {"units": {"g": {"reactive_mvar": 1}}}}


def test_physical_features_radial_and_parallel_topology():
    raw = ac_spec()
    report = {"snapshots": [observation()]}
    radial = physical_features(raw, report, "base")
    features = radial["descriptors"]
    assert features["mean_degree"] == 1
    assert features["cycle_rank_per_bus"] == 0
    assert features["bridge_fraction"] == 1
    assert features["median_r_over_x"] == pytest.approx(0.1)
    assert features["median_x_pu_100mva"] == pytest.approx(1)
    assert features["voltage_margin_pu"] == pytest.approx(-0.02)
    assert features["loading_margin_fraction"] == pytest.approx(0.2)
    assert features["reactive_margin_fraction"] == pytest.approx(0.25)
    raw["model"]["devices"].append({**raw["model"]["devices"][-1], "id": "ab2"})
    parallel = physical_features(raw, report, "base")
    assert parallel["descriptors"]["cycle_rank_per_bus"] == 0.5
    assert parallel["descriptors"]["bridge_fraction"] == 0
    assert physical_similarity(radial, parallel)["score"] < 1
    assert physical_similarity(radial, radial)["score"] == 1


def test_missing_or_noncomparable_evidence_not_inferred():
    raw = ac_spec()
    report = {"snapshots": [observation("unavailable")]}
    result = physical_features(raw, report, "base")
    assert result["selected_snapshots"] == 1
    assert result["comparable_snapshots"] == 0
    for key in ("voltage_margin_pu", "loading_margin_fraction", "reactive_margin_fraction"):
        assert result["descriptors"][key] is None
    complete = physical_features(raw, {"snapshots": [observation()]}, "base")
    compared = physical_similarity(result, complete)
    assert compared["compared_features"] == 5
    assert compared["possible_features"] == 8
    assert compared["score"] < 1
    rejected = physical_features(raw, {"snapshots": [observation("rejected")]}, "base")
    assert rejected["descriptors"]["reactive_margin_fraction"] is None
    assert rejected["descriptors"]["voltage_margin_pu"] == pytest.approx(-0.02)
    assert physical_features(raw, {"snapshots": [observation()]}, "outage")["selected_snapshots"] == 0


def test_features_independent_of_equipment_order():
    raw = ac_spec()
    report = {"snapshots": [observation()]}
    expected = physical_features(raw, report, "base")
    raw["model"]["devices"].reverse()
    raw["model"]["buses"].reverse()
    assert physical_features(raw, report, "base") == expected


def policy_fixture():
    spec = ACDiagnosticExperiment.model_validate({
        "source_study_id": "a"*32, "source_report_sha256": "b"*64,
        "snapshot": {"hour": 0}, "target_scope": "ac_native",
        "target_check": "voltage_operating_range",
        "probes": [{"kind": "voltage_setpoint", "device": "g", "value_pu": v}
                   for v in (0.87, 0.90, 0.94)], "max_solver_runs": 4})
    jobs = [{"index": 0, "probe": None, "change": None}]
    for i, probe in enumerate(spec.probes, 1):
        jobs.append({"index": i, "probe": probe.model_dump(mode="json"),
                     "change": {"device": "g", "before": 0.89, "after": probe.value_pu}})
    metrics = [0.01, 0.03, 0.005, 0]
    rows = [{**job, "measurement": {"passed": i == 3, "violation": metrics[i],
                                    "solver_version": "3", "unit": "p.u."},
             "observation": {"passed": i == 3}} for i, job in enumerate(jobs)]
    report = {"source_measurement": rows[0]["measurement"], "observations": rows}
    return spec, jobs, report


def test_equal_budget_policy_comparison():
    spec, jobs, report = policy_fixture()
    original = copy.deepcopy(report)
    fixed = evaluate_policy(spec, jobs, report, 3, adaptive=False)
    adaptive = evaluate_policy(spec, jobs, report, 3, adaptive=True)
    assert fixed["selected_indices"] == [0, 1, 2]
    assert fixed["termination"] == "budget_exhausted"
    assert adaptive["selected_indices"] == [0, 2, 3]
    assert adaptive["success"]
    assert adaptive["projected_solver_calls"] == fixed["projected_solver_calls"] == 3
    assert report == original


def test_policy_does_not_count_target_only_pass_as_success():
    spec, jobs, report = policy_fixture()
    report["observations"][3]["observation"]["passed"] = False
    result = evaluate_policy(spec, jobs, report, 3, adaptive=True)
    assert not result["success"]
    assert result["termination"] == "budget_exhausted"


def test_incomplete_pool_and_invalid_budget_rejected():
    spec, jobs, report = policy_fixture()
    with pytest.raises(ValueError, match="budget"):
        evaluate_policy(spec, jobs, report, 5, adaptive=True)
    report["observations"].pop()
    with pytest.raises(ValueError, match="Incomplete"):
        evaluate_policy(spec, jobs, report, 3, adaptive=True)


def test_unfinished_fixed_study_not_replayed(tmp_path):
    study = Study(tmp_path / "studies")
    study.write("manifest", {"protocol": "ac-diagnostic-experiment-v1"})
    with pytest.raises(ValueError, match="committed"):
        replay_fixed(tmp_path, study.id)
