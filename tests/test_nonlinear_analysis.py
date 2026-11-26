import copy

import pytest
from pydantic import ValidationError

from gridagent.math_program_router import reservation_for, solve, verify
from gridagent.math_program_tasks import resume_program, start_program
from gridagent.nonlinear_analysis import kkt_diagnostic, planned_runs
from gridagent.nonlinear_ir import NonlinearProgram


def quadratic():
    return {
        "description": "Quadratic cost with a fixed balance",
        "variables": [
            {"id": "x", "lower": 0, "upper": 4, "unit": "MW"},
            {"id": "y", "lower": 0, "upper": 4, "unit": "MW"},
        ],
        "initial": {"x": 1, "y": 2},
        "constraints": [{"id": "balance", "lower": 3, "upper": 3, "unit": "MW", "terms": [
            {"coefficient": 1, "powers": [{"variable": "x", "exponent": 1}]},
            {"coefficient": 1, "powers": [{"variable": "y", "exponent": 1}]},
        ]}],
        "objective": {"unit": "CNY/h", "terms": [
            {"coefficient": 1, "powers": [{"variable": "x", "exponent": 2}]},
            {"coefficient": 1, "powers": [{"variable": "y", "exponent": 2}]},
        ]},
        "analysis": {"additional_initials": [{"x": 2, "y": 1}],
                     "rhs_scan": [{"constraint": "balance", "side": "equality", "delta": 0.1}]},
        "max_evaluations": 2000,
    }


def double_well():
    return NonlinearProgram.model_validate({
        "description": "Asymmetric double-well polynomial",
        "variables": [{"id": "x", "lower": -2, "upper": 2, "unit": "1"}],
        "initial": {"x": 1},
        "objective": {"unit": "1", "terms": [
            {"coefficient": 1, "powers": [{"variable": "x", "exponent": 4}]},
            {"coefficient": -2, "powers": [{"variable": "x", "exponent": 2}]},
            {"coefficient": 0.2, "powers": [{"variable": "x", "exponent": 1}]},
        ]},
        "analysis": {"additional_initials": [{"x": -1}]},
        "max_evaluations": 1000,
    })


def test_multistart_finds_better_feasible_well():
    spec = double_well()
    result = solve(spec)
    verdict = verify(spec, result)
    assert result["values"]["x"] < 0
    starts = result["analysis_runs"]
    assert starts[0]["result"]["values"]["x"] > 0
    assert result["objective"] < starts[0]["result"]["objective"]
    assert verdict["advanced_analysis"]["baseline_selected_start"] == 2
    assert verdict["advanced_analysis"]["baseline_feasible_starts"] == 2
    assert verdict["advanced_analysis"]["kkt"]["passed"]
    assert not verdict["optimality_independently_checked"]


def test_rhs_reoptimization_and_independent_kkt():
    spec = NonlinearProgram.model_validate(quadratic())
    result = solve(spec)
    verdict = verify(spec, result)
    advanced = verdict["advanced_analysis"]
    assert result["values"] == pytest.approx({"x": 1.5, "y": 1.5})
    assert advanced["kkt"]["passed"]
    assert advanced["kkt"]["stationarity_inf"] <= 1e-5
    scan = advanced["rhs_scan"][0]
    assert scan["values"] == pytest.approx({"x": 1.55, "y": 1.55})
    assert scan["objective"] == pytest.approx(4.805)
    assert scan["objective_change_per_rhs_unit"] == pytest.approx(3.05)
    assert scan["kkt"]["passed"]
    assert "not_proven" in scan["slope_kind"]
    assert advanced["subsolves"] == 4
    assert advanced["callback_evaluations"] <= spec.max_evaluations


def test_stationarity_distinguishes_feasible_nonstationary_point():
    spec = NonlinearProgram.model_validate(quadratic())
    assert not kkt_diagnostic(spec, {"x": 1, "y": 2})["passed"]
    assert not kkt_diagnostic(spec, {"x": 1, "y": 1})["passed"]
    assert kkt_diagnostic(spec, {"x": 1.5, "y": 1.5})["passed"]


def test_active_bound_multiplier_sign():
    spec = NonlinearProgram.model_validate({
        "description": "Minimize a linear objective on a box",
        "variables": [{"id": "x", "lower": 0, "upper": 2, "unit": "1"}],
        "initial": {"x": 0},
        "objective": {"unit": "1", "terms": [
            {"coefficient": 1, "powers": [{"variable": "x", "exponent": 1}]}]},
        "analysis": {},
    })
    diagnostic = kkt_diagnostic(spec, {"x": 0})
    assert diagnostic["passed"]
    assert diagnostic["multipliers"][0]["constraint"] == "bound:x:lower"
    assert diagnostic["multipliers"][0]["value"] == pytest.approx(1)
    assert not kkt_diagnostic(spec, {"x": 2})["passed"]


def test_budget_is_shared_and_never_multiplied_by_start_count():
    raw = quadratic()
    raw["max_evaluations"] = 7
    spec = NonlinearProgram.model_validate(raw)
    jobs = planned_runs(spec)
    assert [job["callback_limit"] for job, _ in jobs] == [2, 2, 2, 1]
    result = solve(spec)
    assert result["callback_evaluations"] <= 7
    assert len(result["analysis_runs"]) == 4
    verify(spec, result)
    assert reservation_for(spec)["analysis_version"] == 1


@pytest.mark.parametrize("fault", ["duplicate_initial", "bad_initial", "unknown_constraint",
                                   "wrong_side", "zero_delta", "budget", "duplicate_scan"])
def test_analysis_rejects_invalid_schedule(fault):
    raw = quadratic()
    analysis = raw["analysis"]
    if fault == "duplicate_initial":
        analysis["additional_initials"] = [raw["initial"]]
    elif fault == "bad_initial":
        analysis["additional_initials"] = [{"x": 5, "y": 0}]
    elif fault == "unknown_constraint":
        analysis["rhs_scan"][0]["constraint"] = "missing"
    elif fault == "wrong_side":
        analysis["rhs_scan"][0]["side"] = "lower"
    elif fault == "zero_delta":
        analysis["rhs_scan"][0]["delta"] = 0
    elif fault == "budget":
        raw["max_evaluations"] = 3
    else:
        analysis["rhs_scan"].append(analysis["rhs_scan"][0])
    with pytest.raises(ValidationError):
        NonlinearProgram.model_validate(raw)


def test_result_schedule_and_winner_tampering_rejected():
    spec = NonlinearProgram.model_validate(quadratic())
    result = solve(spec)
    modified = copy.deepcopy(result)
    modified["analysis_runs"][0]["callback_limit"] += 1
    with pytest.raises(ValueError, match="frozen solve schedule"):
        verify(spec, modified)
    modified = copy.deepcopy(result)
    modified["values"] = {"x": 0, "y": 3}
    with pytest.raises(ValueError, match="selected candidate"):
        verify(spec, modified)
    modified = copy.deepcopy(result)
    modified["analysis_runs"][0]["result"]["callback_evaluations"] = 99999
    with pytest.raises(ValueError, match="reserved callback budget"):
        verify(spec, modified)


def test_persisted_advanced_report_rechecks_and_single_start_fingerprint_compatible(tmp_path):
    spec = NonlinearProgram.model_validate(quadratic())
    identifier = start_program(tmp_path, spec)
    first = resume_program(tmp_path, identifier)
    assert first["completed"]
    assert first["verification"]["advanced_analysis"]["kkt"]["passed"]
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Repeated solve")) == first
    raw = quadratic()
    raw.pop("analysis")
    legacy = NonlinearProgram.model_validate(raw)
    assert "analysis" not in legacy.canonical()
    assert "analysis_version" not in reservation_for(legacy)
    assert "advanced_analysis" not in verify(legacy, solve(legacy))
