import copy

import pytest
from pydantic import ValidationError

from gridagent.commitment_compiler import compile_commitment, variable
from gridagent.commitment_ir import UnitCommitment
from gridagent.commitment_solver import physical_checks
from gridagent.math_program_router import parse_program, reservation_for, solve, verify
from gridagent.math_program_tasks import resume_program, start_program


def unit(identifier="cheap", **changes):
    return {"id": identifier, "minimum_mw": 2, "maximum_mw": 4,
            "marginal_cost_per_mwh": 10, "startup_cost": 5, "ramp_up_mw": 4,
            "ramp_down_mw": 4, "startup_limit_mw": 4, "shutdown_limit_mw": 4,
            "min_up_hours": 2, "min_down_hours": 1, "initially_on": False,
            "initial_mw": 0, "initial_state_hours": 3, **changes}


def problem():
    return {"family": "unit_commitment", "description": "Three-hour single-area dispatch",
            "currency": "CNY", "demand_mw": [3, 3, 0],
            "units": [unit(), unit("expensive", minimum_mw=0, maximum_mw=10,
                                  marginal_cost_per_mwh=40, ramp_up_mw=10, ramp_down_mw=10,
                                  startup_limit_mw=10, shutdown_limit_mw=10, min_up_hours=1)]}


def test_compile_and_solve_commitment():
    spec = parse_program(problem())
    program = compile_commitment(spec)
    assert program.route() == "scipy-highs-milp"
    assert len(program.variables) == 24
    assert len(program.constraints) == 51
    result = solve(spec)
    verdict = verify(spec, result)
    assert result["status"] == "optimal_reported"
    assert result["objective"] == pytest.approx(65)
    assert verdict["primal"]["passed"]
    physical = verdict["commitment"]["physical"]
    assert physical["passed"]
    schedule = physical["schedule"]["units"]["cheap"]["hours"]
    assert [row["on"] for row in schedule] == [1, 1, 0]
    assert [row["startup"] for row in schedule] == [1, 0, 0]
    assert [row["generation_mw"] for row in schedule] == pytest.approx([3, 3, 0])
    assert not verdict["optimality_independently_checked"]


def test_storage_arbitrage_and_exclusive_modes():
    raw = problem()
    raw["demand_mw"] = [1, 4]
    raw["units"] = [unit(minimum_mw=0, maximum_mw=2, startup_limit_mw=2, shutdown_limit_mw=2,
                         initially_on=True, initial_state_hours=3, startup_cost=0),
                    unit("expensive", minimum_mw=0, maximum_mw=10, marginal_cost_per_mwh=50,
                         startup_limit_mw=10, shutdown_limit_mw=10, ramp_up_mw=10, ramp_down_mw=10,
                         min_up_hours=1, startup_cost=0)]
    raw["storage"] = [{"id": "battery", "power_mw": 1, "energy_mwh": 1,
                       "initial_mwh": 0, "terminal_mwh": 0,
                       "charge_efficiency": 1, "discharge_efficiency": 1}]
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    physical = verify(spec, result)["commitment"]["physical"]
    assert physical["passed"]
    assert result["objective"] == pytest.approx(90)
    rows = physical["schedule"]["storage"]["battery"]
    assert [row["charge_mw"] for row in rows] == pytest.approx([1, 0])
    assert [row["discharge_mw"] for row in rows] == pytest.approx([0, 1])
    assert [row["soc_mwh"] for row in rows] == pytest.approx([1, 0])
    assert physical["power_balance_residual_mw"] == pytest.approx([0, 0])


def test_minimum_up_obligation_carried_beyond_horizon():
    raw = problem()
    raw["units"] = [unit()]
    raw["demand_mw"] = [0, 3]
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    schedule = verify(spec, result)["commitment"]["physical"]["schedule"]["units"]["cheap"]
    assert schedule["terminal_on"]
    assert schedule["terminal_state_hours"] == 1
    assert schedule["remaining_minimum_state_hours"] == 1


@pytest.mark.parametrize("case", ["initial_up", "initial_down", "shutdown_ramp", "startup_ramp", "online_ramp"])
def test_initial_state_and_ramp_constraints_can_make_problem_infeasible(case):
    raw = problem()
    if case == "initial_up":
        raw["units"] = [unit(initially_on=True, initial_mw=2, initial_state_hours=1)]
        raw["demand_mw"] = [0]
    elif case == "initial_down":
        raw["units"] = [unit(min_down_hours=3, initial_state_hours=1)]
        raw["demand_mw"] = [3]
    elif case == "shutdown_ramp":
        raw["units"] = [unit(initially_on=True, initial_mw=3, ramp_down_mw=1, shutdown_limit_mw=2)]
        raw["demand_mw"] = [0]
    elif case == "startup_ramp":
        raw["units"] = [unit(startup_limit_mw=2)]
        raw["demand_mw"] = [3]
    else:
        raw["units"] = [unit(initially_on=True, initial_mw=2, ramp_up_mw=1)]
        raw["demand_mw"] = [4]
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    assert result["status"] == "infeasible_reported"
    assert not verify(spec, result)["primal"]["passed"]


@pytest.mark.parametrize("case", ["duplicate", "bad_initial", "bad_capacity", "large", "soc"])
def test_invalid_commitment_source(case):
    raw = problem()
    if case == "duplicate":
        raw["units"].append(raw["units"][0])
    elif case == "bad_initial":
        raw["units"][0]["initial_mw"] = 1
    elif case == "bad_capacity":
        raw["units"][0]["minimum_mw"] = 6
    elif case == "large":
        raw["demand_mw"] = [1]*24
        raw["units"].append(unit("third"))
    else:
        raw["storage"] = [{"id": "bad", "power_mw": 1, "energy_mwh": 1,
                           "initial_mwh": 2, "terminal_mwh": 0,
                           "charge_efficiency": 1, "discharge_efficiency": 1}]
    with pytest.raises(ValidationError):
        UnitCommitment.model_validate(raw)


def test_source_order_and_compiler_fingerprint():
    raw = problem()
    spec = UnitCommitment.model_validate(raw)
    raw["units"].reverse()
    other = UnitCommitment.model_validate(raw)
    assert spec.sha256() == other.sha256()
    assert compile_commitment(spec).sha256() == compile_commitment(other).sha256()
    assert reservation_for(spec)["compiled_program_sha256"] == compile_commitment(spec).sha256()


def test_physical_checks_and_compiler_identity_reject_tampering():
    spec = UnitCommitment.model_validate(problem())
    result = solve(spec)
    bad = copy.deepcopy(result)
    bad["compiled_program_sha256"] = "0"*64
    with pytest.raises(ValueError, match="compiled program"):
        verify(spec, bad)
    bad = copy.deepcopy(result["values"])
    bad[variable("g", 0, 0, "p")] = 0
    physical = physical_checks(spec, bad)
    assert not physical["passed"]
    assert any(not row["passed"] and row["id"] == "balance:0" for row in physical["checks"])


def test_persisted_commitment_report_rechecks_without_solving(tmp_path):
    spec = UnitCommitment.model_validate(problem())
    identifier = start_program(tmp_path, spec)
    first = resume_program(tmp_path, identifier)
    assert first["completed"]
    assert first["objective_unit"] == "CNY"
    assert first["verification"]["commitment"]["physical"]["passed"]
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Repeated solve")) == first
