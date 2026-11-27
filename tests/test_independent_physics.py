import numpy as np
import pytest

from gridagent.ac_reference import compare_solution, solve_reference
from gridagent.dynamic_control_benchmark import run_benchmark, verify


def two_bus():
    bus = np.zeros((2, 13))
    bus[:, 0] = [1, 2]
    bus[:, 1] = [3, 1]
    bus[1, 3] = 10
    bus[:, 7] = 1
    gen = np.zeros((1, 10))
    gen[0, [0, 5, 7]] = [1, 1, 1]
    branch = np.zeros((1, 13))
    branch[0, [0, 1, 3, 10]] = [1, 2, 0.1, 1]
    return {"baseMVA": 100, "bus": bus, "gen": gen, "branch": branch}


def test_two_bus_analytic_high_voltage_solution():
    result = solve_reference(two_bus())
    # Q_load = V(1-V)/X, in p.u.; use the high-voltage branch.
    expected = (1+np.sqrt(1-4*.1*.1))/2
    assert result["vm_pu"] == pytest.approx([1, expected], abs=1e-9)
    assert result["va_degree"] == pytest.approx([0, 0], abs=1e-9)
    assert compare_solution(result, {0: (1, 12), 1: (expected, 12)}, {0: 1, 1: 2})["passed"]
    assert not compare_solution(result, {0: (1, 0), 1: (expected-.01, 0)}, {0: 1, 1: 2})["passed"]


def test_reject_missing_bus():
    with pytest.raises(ValueError, match="coverage"):
        compare_solution(solve_reference(two_bus()), {0: (1, 0)}, {0: 1})


def test_dynamic_independent_verification():
    result = verify((4, 1, .4, .08), (3, .8))
    assert result["stable"] and result["numerically_verified"]


def test_dynamic_budget_and_holdout():
    result = run_benchmark(4)
    assert result["candidate_plant_evaluations"] == 12
    assert len(result["candidates"]) == 4
    assert len(result["evaluations"]["selected"]["heldout"]) == 2
    assert result["selected_gains"] == min(result["candidates"], key=lambda x: x["training_score"])["gains"]
    with pytest.raises(ValueError):
        run_benchmark(61)


@pytest.mark.integration
@pytest.mark.parametrize("network", ["case14", "case39", "case118"])
def test_public_reference(network, tmp_path):
    pytest.importorskip("pandapower")
    from gridagent.ac_reference import compare_public_run
    from gridagent.native_backends import run_program

    for scale in (1, 1.1):
        run = run_program(tmp_path, {"backend": "pandapower", "base": network, "load_scale": scale})
        assert run["status"] == "ok", run
        comparison = compare_public_run(tmp_path, network, scale, run["run_id"])
        assert comparison["passed"], comparison
