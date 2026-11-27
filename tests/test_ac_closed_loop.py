import pytest

from gridagent.ac_closed_loop import ClosedLoopSpec, next_index, resume_loop, start_loop
from gridagent.engineering_ir import EngineeringStudy, ModelIR, StudySpec
from gridagent.optimization_ir import ACOptimizationSpec


def spec():
    model = ModelIR(model_id="loop-grid", buses=[{"id": "bus", "nominal_kv": 20}],
                    devices=[{"kind": "slack", "id": "grid", "bus": "bus", "voltage_pu": .88},
                             {"kind": "load", "id": "load", "bus": "bus", "active_mw": 1}])
    source = EngineeringStudy(model=model, study=StudySpec(objective="Restore voltage within fixed limits",
                              model_sha256=model.sha256(), scenarios=[{"name": "base"}], max_runs=1))
    opt = ACOptimizationSpec(source=source, variables=[{"kind": "continuous", "device_id": "grid",
                             "parameter": "voltage_pu", "minimum": .85, "maximum": 1.05}],
                             objective="minimize_worst_voltage_deviation", max_solver_runs=3)
    return ClosedLoopSpec(optimization=opt, candidates=[(.85,), (1.,)])


def test_directional_policy_and_authorization():
    auth = spec()
    assert next_index(auth, []) == 0
    baseline = {"candidate_index": 0, "status": "physical_violation", "findings": [
        {"check_id": "voltage_operating_range", "observed": [.88, .88], "criterion": [.9, 1.1]}]}
    assert next_index(auth, [baseline]) == 2
    assert next_index(auth, [{**baseline, "status": "unavailable"}]) is None
    with pytest.raises(ValueError, match="outside authorized"):
        ClosedLoopSpec(optimization=auth.optimization, candidates=[(1.2,)])
    with pytest.raises(ValueError, match="exclude the baseline"):
        ClosedLoopSpec(optimization=auth.optimization, candidates=[(.88,)])


def test_interrupted_run_not_relaunched(tmp_path):
    identifier = start_loop(tmp_path, spec())
    calls = []

    def stop(*args, **kwargs):
        calls.append(kwargs["run_id"])
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        resume_loop(tmp_path, identifier, solver=stop)

    def forbidden(*args, **kwargs):
        pytest.fail("Unknown solver reservation must not be relaunched")

    result = resume_loop(tmp_path, identifier, solver=forbidden)
    assert not result["completed"]
    assert result["reserved_solver_runs"] == 1 and len(calls) == 1
    assert resume_loop(tmp_path, identifier, solver=forbidden) == result


@pytest.mark.integration
def test_native_closed_loop_repairs_and_replays(tmp_path):
    pytest.importorskip("pandapower")
    identifier = start_loop(tmp_path, spec())
    result = resume_loop(tmp_path, identifier)
    assert result["completed"], result
    assert result["observations"][0]["status"] == "physical_violation"
    assert result["verified_candidate"] == 2
    assert result["reserved_solver_runs"] == 3
    assert set(result["verification"]["run_ids"]).isdisjoint(result["observations"][1]["run_ids"])

    def forbidden(*args, **kwargs):
        pytest.fail("Committed report must replay without running solver")

    assert resume_loop(tmp_path, identifier, solver=forbidden) == result
