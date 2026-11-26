import copy

import pytest
from pydantic import ValidationError

from gridagent.commitment_compiler import SECURITY_COMPILER, compile_commitment, variable
from gridagent.commitment_ir import UnitCommitment
from gridagent.commitment_security import security_variable
from gridagent.commitment_solver import physical_checks
from gridagent.math_program_router import reservation_for, solve, verify
from gridagent.math_program_tasks import resume_program, start_program


def unit(identifier, cost):
    return {"id": identifier, "minimum_mw": 0, "maximum_mw": 10,
            "marginal_cost_per_mwh": cost, "ramp_up_mw": 8, "ramp_down_mw": 10,
            "startup_limit_mw": 10, "shutdown_limit_mw": 10,
            "min_up_hours": 1, "min_down_hours": 1, "initially_on": True,
            "initial_mw": 0, "initial_state_hours": 2}


def problem():
    return {
        "description": "Corrective single-line outage schedule",
        "currency": "CNY", "demand_mw": [6],
        "units": [unit("cheap", 10), unit("local", 50)],
        "network": {
            "buses": [{"id": "A", "demand_mw": [0]}, {"id": "B", "demand_mw": [6]}],
            "lines": [{"id": "AB", "from_bus": "A", "to_bus": "B",
                       "susceptance_mw_per_rad": 20, "limit_mw": 4,
                       "max_angle_difference_rad": 0.3}],
            "reference_bus": "A", "angle_bound_rad": 0.5,
            "unit_buses": {"cheap": "A", "local": "B"},
            "reserve_requirement_mw": [1], "reserve_response_minutes": 15,
            "unit_reserve_capability_mw": {"cheap": 0, "local": 4},
            "security": {"outage_lines": ["AB"]},
        },
    }


def test_security_redispatch_changes_base_commitment_and_balances_islands():
    raw = problem()
    base = copy.deepcopy(raw)
    base["network"].pop("security")
    assert solve(base)["objective"] == pytest.approx(140)
    spec = UnitCommitment.model_validate(raw)
    compiled = compile_commitment(spec)
    assert len(compiled.variables) == 18
    assert len(compiled.constraints) == 33
    result = solve(spec)
    assert result["compiler"] == SECURITY_COMPILER
    assert result["objective"] == pytest.approx(220)
    verdict = verify(spec, result)
    assert verdict["primal"]["passed"]
    assert not verdict["optimality_independently_checked"]
    physical = verdict["commitment"]["physical"]
    assert physical["passed"]
    schedule = physical["schedule"]
    assert schedule["units"]["cheap"]["hours"][0]["generation_mw"] == pytest.approx(2)
    assert schedule["units"]["local"]["hours"][0]["generation_mw"] == pytest.approx(4)
    security = schedule["security"]
    assert security["all_network_lines_covered"]
    outage = security["cases"]["AB"]
    assert outage["reference_buses"] == ["A", "B"]
    hour = outage["hours"][0]
    assert hour["lines"]["AB"] == {"flow_mw": 0, "outaged": True}
    assert hour["units"]["local"]["generation_mw"] == pytest.approx(6)
    assert hour["units"]["local"]["redispatch_mw"] == pytest.approx(2)
    assert hour["nodal_residual_mw"] == pytest.approx({"A": 0, "B": 0})


def test_parallel_lines_all_contingencies_and_canonical_order():
    raw = problem()
    line = raw["network"]["lines"][0]
    line["limit_mw"] = 2
    raw["network"]["lines"].append({**line, "id": "AB2"})
    raw["network"]["security"]["outage_lines"] = ["AB2", "AB"]
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    assert result["objective"] == pytest.approx(140)
    verdict = verify(spec, result)
    assert verdict["primal"]["passed"]
    security = verdict["commitment"]["physical"]["schedule"]["security"]
    assert security["all_network_lines_covered"]
    for failed, surviving in (("AB", "AB2"), ("AB2", "AB")):
        case = security["cases"][failed]
        assert case["reference_buses"] == ["A"]
        hour = case["hours"][0]
        assert hour["lines"][failed]["flow_mw"] == pytest.approx(0)
        assert hour["lines"][surviving]["flow_mw"] == pytest.approx(2)
    raw["network"]["lines"].reverse()
    raw["network"]["security"]["outage_lines"].reverse()
    other = UnitCommitment.model_validate(raw)
    assert other.sha256() == spec.sha256()
    assert compile_commitment(other).sha256() == compiled_sha(spec)


def compiled_sha(spec):
    return compile_commitment(spec).sha256()


def test_partial_line_coverage_explicitly_reported():
    raw = problem()
    raw["network"]["lines"].append({**raw["network"]["lines"][0], "id": "AB2"})
    spec = UnitCommitment.model_validate(raw)
    verdict = verify(spec, solve(spec))
    assert verdict["primal"]["passed"]
    assert not verdict["commitment"]["physical"]["schedule"]["security"]["all_network_lines_covered"]


def test_base_feasible_but_security_infeasible_when_island_cannot_supply_demand():
    raw = problem()
    raw["units"][1].update(maximum_mw=5, startup_limit_mw=5, shutdown_limit_mw=5)
    base = copy.deepcopy(raw)
    base["network"].pop("security")
    assert verify(base, solve(base))["primal"]["passed"]
    result = solve(raw)
    assert result["status"] == "infeasible_reported"
    assert not verify(raw, result)["primal"]["passed"]


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "empty", "budget"])
def test_invalid_security_scope(fault):
    raw = problem()
    if fault == "unknown":
        raw["network"]["security"]["outage_lines"] = ["missing"]
    elif fault == "duplicate":
        raw["network"]["security"]["outage_lines"] = ["AB", "AB"]
    elif fault == "empty":
        raw["network"]["security"]["outage_lines"] = []
    else:
        raw["demand_mw"] = [6]*12
        raw["network"]["buses"][0]["demand_mw"] = [0]*12
        raw["network"]["buses"][1]["demand_mw"] = [6]*12
        raw["network"]["reserve_requirement_mw"] = [1]*12
    with pytest.raises(ValidationError):
        UnitCommitment.model_validate(raw)


def test_independent_verifier_rejects_outage_flow_and_excess_redispatch():
    spec = UnitCommitment.model_validate(problem())
    result = solve(spec)
    changed = copy.deepcopy(result["values"])
    changed[security_variable(0, "l", 0, 0, "flow")] = 1
    changed[security_variable(0, "g", 1, 0, "p")] = 7
    changed[variable("g", 1, 0, "reserve")] = 2
    physical = physical_checks(spec, changed)
    failed = {row["id"] for row in physical["checks"] if not row["passed"]}
    assert {"security:AB:0:line:AB:outage", "security:AB:0:unit:local:up",
            "security:AB:0:node:A:balance", "security:AB:0:node:B:balance"} <= failed


def test_security_reservation_and_resume(tmp_path):
    spec = UnitCommitment.model_validate(problem())
    reservation = reservation_for(spec)
    assert reservation["compiler"] == SECURITY_COMPILER
    assert reservation["compiled_program_sha256"] == compiled_sha(spec)
    identifier = start_program(tmp_path, spec)
    report = resume_program(tmp_path, identifier)
    assert report["completed"]
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Repeated solve")) == report
    raw = problem()
    raw["network"].pop("security")
    legacy = UnitCommitment.model_validate(raw)
    assert "security" not in legacy.canonical()["network"]
    assert reservation_for(legacy)["compiler"] == "dc-network-commitment-milp-v1"
