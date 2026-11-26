import pytest
from pydantic import ValidationError

from gridagent.math_program_router import parse_program, reservation_for, solve, verify
from gridagent.math_program_tasks import resume_program, start_program
from gridagent.nonlinear_ir import NonlinearProgram
from gridagent.nonlinear_solver import CompiledPolynomial, sensitivity


def problem():
    return NonlinearProgram.model_validate({
        "description": "Convex quadratic generation cost with fixed demand",
        "variables": [
            {"id": "x", "lower": 0, "upper": 3, "unit": "MW"},
            {"id": "y", "lower": 0, "upper": 3, "unit": "MW"},
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
    })


def test_router_solves_quadratic_and_verifies_without_claiming_global_optimum():
    spec = parse_program(problem().model_dump(mode="json"))
    result = solve(spec)
    assert result["route"] == "scipy-slsqp-polynomial"
    assert result["values"] == pytest.approx({"x": 1.5, "y": 1.5}, abs=1e-5)
    assert result["objective"] == pytest.approx(4.5)
    report = verify(spec, result)
    assert report["primal"]["passed"]
    assert not report["optimality_independently_checked"]
    assert report["sensitivity"]["all_derivatives_agree"]
    assert report["classification"] == "verified_feasible_candidate"


def test_nonlinear_inequality_and_maximization():
    raw = problem().model_dump(mode="json")
    raw["initial"] = {"x": 0, "y": 0}
    raw["constraints"][0].update(lower=None, upper=1, terms=raw["objective"]["terms"])
    raw["objective"].update(sense="maximize", terms=[
        {"coefficient": 1, "powers": [{"variable": "x", "exponent": 1}]}])
    spec = NonlinearProgram.model_validate(raw)
    result = solve(spec)
    assert result["values"] == pytest.approx({"x": 1, "y": 0}, abs=1e-5)
    assert verify(spec, result)["primal"]["passed"]


def test_mixed_polynomial_gradient_at_zero_and_bound():
    raw = problem().model_dump(mode="json")
    raw["objective"]["terms"] = [
        {"coefficient": 2, "powers": [{"variable": "x", "exponent": 1},
                                      {"variable": "y", "exponent": 2}]},
        {"coefficient": 3, "powers": []},
    ]
    spec = NonlinearProgram.model_validate(raw)
    compiled = CompiledPolynomial(spec.objective, ["x", "y"])
    assert compiled.gradient([0.0, 3.0]) == pytest.approx([18, 0])
    rows = sensitivity(spec, {"x": 0, "y": 3})["rows"]
    x = next(row for row in rows if row["expression"] == "objective" and row["variable"] == "x")
    assert x["analytic"] == pytest.approx(18)
    assert x["agreement"]
    assert x["method"] == "bounded_secant"


@pytest.mark.parametrize("fault", ["unknown_variable", "degree", "integer", "initial", "duplicate", "fixed"])
def test_nlp_rejects_unsupported_or_invalid_contract(fault):
    raw = problem().model_dump(mode="json")
    if fault == "unknown_variable":
        raw["objective"]["terms"][0]["powers"][0]["variable"] = "z"
    elif fault == "degree":
        raw["objective"]["terms"][0]["powers"].append({"variable": "y", "exponent": 3})
    elif fault == "integer":
        raw["variables"][0]["kind"] = "integer"
    elif fault == "initial":
        raw["initial"]["x"] = 4
    elif fault == "duplicate":
        raw["objective"]["terms"].append(raw["objective"]["terms"][0])
    else:
        raw["variables"][0]["upper"] = raw["variables"][0]["lower"]
    with pytest.raises(ValidationError):
        NonlinearProgram.model_validate(raw)


def test_independent_verifier_rejects_bad_claims():
    spec = problem()
    result = solve(spec)
    result["values"] = {"x": 0, "y": 0}
    result["objective"] = 0
    assert not verify(spec, result)["primal"]["passed"]
    result["values"] = {"x": 1.5, "y": 1.5}
    assert not verify(spec, result)["primal"]["passed"]


def test_callback_budget_and_resume(tmp_path):
    raw = problem().model_dump(mode="json")
    raw["max_evaluations"] = 1
    spec = NonlinearProgram.model_validate(raw)
    result = solve(spec)
    assert result["status"] == "evaluation_or_time_limit"
    assert result["callback_evaluations"] <= 1
    assert reservation_for(spec)["max_evaluations"] == 1
    identifier = start_program(tmp_path, problem())
    first = resume_program(tmp_path, identifier)
    assert first["completed"]
    assert first["verification"]["sensitivity"]["all_derivatives_agree"]
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Duplicate solve")) == first


def test_canonical_hash_reorders_polynomial_terms():
    spec = problem()
    raw = spec.model_dump(mode="json")
    raw["objective"]["terms"].reverse()
    raw["variables"].reverse()
    raw["constraints"][0]["terms"].reverse()
    assert NonlinearProgram.model_validate(raw).sha256() == spec.sha256()
