import json

import pytest
from pydantic import ValidationError

from gridagent.math_program_ir import MathematicalProgram
from gridagent.math_program_solver import solve_program, verify_primal, verify_result
from gridagent.math_program_tasks import resume_program, start_program


def problem(*, integer=False):
    return MathematicalProgram.model_validate({
        "description": "Allocate generation and commitment",
        "variables": [
            {"id": "x", "kind": "binary" if integer else "continuous",
             "lower": 0, "upper": 1 if integer else 2, "unit": "1"},
            {"id": "y", "lower": 0, "upper": 3, "unit": "1"},
        ],
        "constraints": [{"id": "capacity", "terms": [
            {"variable": "x", "coefficient": 1}, {"variable": "y", "coefficient": 1}],
            "upper": 2.5 if integer else 4, "unit": "1"}],
        "objective": {"sense": "maximize", "constant": 5, "unit": "CNY",
                      "terms": [{"variable": "x", "coefficient": 3}, {"variable": "y", "coefficient": 2}]},
    })


def test_lp_route_primal_and_dual():
    spec = problem()
    result = solve_program(spec)
    assert result["route"] == "scipy-highs-lp"
    assert result["values"] == pytest.approx({"x": 2, "y": 2})
    assert result["objective"] == pytest.approx(15)
    verdict = verify_result(spec, result)
    assert verdict["primal"]["passed"]
    assert verdict["optimality_independently_checked"]
    assert verdict["lp_certificate"]["primal_dual_gap"] == pytest.approx(0, abs=1e-6)


def test_milp_route_does_not_claim_independent_optimality():
    spec = problem(integer=True)
    result = solve_program(spec)
    assert result["route"] == "scipy-highs-milp"
    assert result["values"] == pytest.approx({"x": 1, "y": 1.5})
    assert result["objective"] == pytest.approx(11)
    verdict = verify_result(spec, result)
    assert verdict["classification"] == "verified_feasible_candidate"
    assert not verdict["optimality_independently_checked"]
    assert result["status"] == "optimal_reported"


def test_verification_rejects_wrong_values_and_objective():
    spec = problem(integer=True)
    assert not verify_primal(spec, {"x": 0.5, "y": 2}, 10.5)["passed"]
    assert not verify_primal(spec, {"x": 1, "y": 2}, 12)["passed"]
    assert not verify_primal(spec, {"x": 1, "y": 1.5}, 99)["passed"]
    assert not verify_primal(spec, {"x": float("nan"), "y": 2}, 10)["passed"]


def test_invalid_dual_certificate_is_not_optimality():
    spec = problem()
    result = solve_program(spec)
    result["lp_certificate"]["inequality"]["capacity:upper"] = 100
    verdict = verify_result(spec, result)
    assert verdict["primal"]["passed"]
    assert not verdict["optimality_independently_checked"]


def test_equalities_two_sided_rows_and_negative_bounds():
    raw = problem().model_dump(mode="json")
    raw["variables"][0].update(lower=-2, upper=2)
    raw["constraints"] = [
        {"id": "balance", "terms": [{"variable": "x", "coefficient": 1},
                                    {"variable": "y", "coefficient": 1}],
         "lower": 1, "upper": 1, "unit": "1"},
        {"id": "range", "terms": [{"variable": "x", "coefficient": 1}],
         "lower": -1, "upper": 0.5, "unit": "1"},
    ]
    spec = MathematicalProgram.model_validate(raw)
    result = solve_program(spec)
    assert result["values"] == pytest.approx({"x": 0.5, "y": 0.5})
    assert verify_result(spec, result)["optimality_independently_checked"]


def test_infeasible_program_is_not_verified():
    raw = problem().model_dump(mode="json")
    raw["constraints"][0].update(lower=6, upper=None)
    spec = MathematicalProgram.model_validate(raw)
    result = solve_program(spec)
    assert result["status"] == "infeasible_reported"
    assert verify_result(spec, result)["classification"] == "no_verified_candidate"


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "bounds", "binary", "empty_row"])
def test_program_rejects_invalid_contract(fault):
    raw = problem().model_dump(mode="json")
    if fault == "unknown":
        raw["objective"]["terms"][0]["variable"] = "missing"
    elif fault == "duplicate":
        raw["objective"]["terms"].append(raw["objective"]["terms"][0])
    elif fault == "bounds":
        raw["variables"][0]["lower"] = 3
    elif fault == "binary":
        raw["variables"][0]["kind"] = "binary"
    else:
        raw["constraints"][0]["upper"] = None
    with pytest.raises(ValidationError):
        MathematicalProgram.model_validate(raw)


def test_canonical_hash_is_order_independent():
    spec = problem()
    raw = spec.model_dump(mode="json")
    raw["variables"].reverse()
    raw["constraints"][0]["terms"].reverse()
    raw["objective"]["terms"].reverse()
    assert MathematicalProgram.model_validate(raw).sha256() == spec.sha256()


def test_persisted_program_is_rechecked_without_rerun(tmp_path):
    identifier = start_program(tmp_path, problem())
    first = resume_program(tmp_path, identifier)
    assert first["completed"]
    assert first["verification"]["optimality_independently_checked"]
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Duplicate solve")) == first
    file = tmp_path / "studies" / identifier / "result.json"
    result = json.loads(file.read_text(encoding="utf-8"))
    result["objective"] = 999
    file.write_text(json.dumps(result), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        resume_program(tmp_path, identifier)


def test_interruption_never_replays_reserved_solver_call(tmp_path):
    identifier = start_program(tmp_path, problem())

    def interrupted(_):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        resume_program(tmp_path, identifier, solver=interrupted)
    report = resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Duplicate solve"))
    assert report["reserved_solver_calls"] == 1
    assert report["solver_result"]["status"] == "unknown_reserved_call"
    assert not report["completed"]
