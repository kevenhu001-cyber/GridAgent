"""Mixed-variable optimization: authorization, budgets and native verification."""

import pytest
from pydantic import ValidationError

from gridagent.engineering_ir import EngineeringStudy, ModelIR, StudySpec
from gridagent.engineering_optimization import resume_optimization, start_optimization
from gridagent.optimization_ir import ACOptimizationSpec, next_candidate


def specification(*, budget=3, mixed=False):
    model = ModelIR(
        model_id="optimization-grid",
        buses=[{"id": "bus", "nominal_kv": 20}],
        devices=[
            {"kind": "slack", "id": "grid", "bus": "bus", "voltage_pu": 1.04},
            {"kind": "load", "id": "demand", "bus": "bus", "active_mw": 1, "reactive_mvar": 0.2},
            {"kind": "storage", "id": "battery", "bus": "bus", "charging_mw": 0,
             "energy_capacity_mwh": 2, "initial_soc_percent": 50, "reactive_mvar": 0},
        ],
    )
    study = StudySpec(objective="Compare AC operating points", model_sha256=model.sha256(),
                      scenarios=[{"name": "base"}], max_runs=1)
    variables = [{"kind": "continuous", "device_id": "grid", "parameter": "voltage_pu",
                  "minimum": 0.96, "maximum": 1.08}]
    if mixed:
        variables.append({"kind": "discrete", "device_id": "battery", "parameter": "reactive_mvar",
                          "choices": [-0.1, 0, 0.1]})
    return ACOptimizationSpec(source=EngineeringStudy(model=model, study=study), variables=variables,
                              objective="minimize_worst_voltage_deviation", max_solver_runs=budget)


def test_mixed_authorization_preserves_locked_model():
    spec = specification(mixed=True)
    candidate = spec.candidate((1.01, 0.1))
    before, after = spec.source.model.canonical(), candidate.model.canonical()
    assert after["revision"] == before["revision"] + 1
    for row in after["devices"]:
        if row["id"] == "grid":
            row["voltage_pu"] = 1.04
        elif row["id"] == "battery":
            row["reactive_mvar"] = 0
    after["revision"] = before["revision"]
    assert after == before
    assert candidate.study.model_sha256 == candidate.model.sha256()
    with pytest.raises(ValueError, match="outside authorized"):
        spec.candidate((1.01, 0.05))


@pytest.mark.parametrize("change", ["load", "range", "duplicate", "budget", "discrete"])
def test_invalid_authorization_is_rejected(change):
    raw = specification(mixed=True).model_dump(mode="json")
    if change == "load":
        raw["variables"][0].update(device_id="demand", parameter="active_mw", minimum=0, maximum=2)
    elif change == "range":
        raw["variables"][0]["maximum"] = 2
    elif change == "duplicate":
        raw["variables"].append(raw["variables"][0])
    elif change == "budget":
        raw["max_solver_runs"] = 2
    else:
        raw["variables"][1]["choices"] = [0.1, 0]
    with pytest.raises(ValidationError):
        ACOptimizationSpec.model_validate(raw)


def test_search_is_deterministic_and_does_not_repeat_candidates():
    spec = specification(mixed=True, budget=10)
    observations = []
    for _ in range(8):
        values = next_candidate(spec, observations)
        assert values is not None
        assert values not in [tuple(row["values"]) for row in observations]
        assert values == next_candidate(spec, observations)
        spec.candidate(values)
        observations.append({"values": list(values), "status": "feasible",
                             "objective": abs(values[0] - 1) + abs(values[1])})
    assert len(observations) == 8
    assert any(row["values"][1] != 0 for row in observations)


def test_interrupted_reservation_is_charged_and_not_replayed(tmp_path):
    spec = specification()
    identifier = start_optimization(tmp_path, spec)
    calls = []

    def interrupted(*args, **kwargs):
        calls.append(kwargs["run_id"])
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        list(resume_optimization(tmp_path, identifier, solver=interrupted))

    def no_result(*args, **kwargs):
        calls.append(kwargs["run_id"])

    report = list(resume_optimization(tmp_path, identifier, solver=no_result))[-1]
    assert len(calls) == len(set(calls)) == 2
    assert report["reserved_solver_runs"] == 2
    assert report["termination"] == "no_feasible_candidate"
    assert not report["completed"]
    assert report["verification"] is None
    assert list(resume_optimization(tmp_path, identifier, solver=no_result)) == [report]
    assert len(calls) == 2


@pytest.mark.integration
def test_native_optimizer_improves_and_freshly_verifies(tmp_path, monkeypatch):
    pytest.importorskip("pandapower")
    monkeypatch.setenv("GRIDAGENT_VERIFIED_CACHE", "1")
    spec = specification()
    report = list(resume_optimization(tmp_path, start_optimization(tmp_path, spec)))[-1]
    assert report["completed"], report
    assert report["reserved_solver_runs"] == report["budget"] == 3
    assert report["best_observed"]["objective"] < report["baseline"]["objective"]
    assert report["verification"]["objective"] == pytest.approx(report["best_observed"]["objective"])
    assert set(report["verification"]["run_ids"]).isdisjoint(report["best_observed"]["run_ids"])
    assert report["verification"]["evidence_sha256"]
    assert not report["global_optimality_proven"]
