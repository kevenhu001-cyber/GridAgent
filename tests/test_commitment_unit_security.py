import copy

import pytest
from pydantic import ValidationError

from gridagent.commitment_compiler import UNIT_SECURITY_COMPILER, compile_commitment, variable
from gridagent.commitment_ir import UnitCommitment
from gridagent.commitment_security import security_variable
from gridagent.commitment_solver import physical_checks
from gridagent.math_program_router import reservation_for, solve, verify
from gridagent.math_program_tasks import resume_program, start_program
from gridagent.optimization_benchmark import network_example, run_benchmark


def problem():
    raw = network_example()
    raw["network"]["security"] = {"outage_units": ["cheap"]}
    return raw


def test_generator_outage_requires_surviving_reserve():
    spec = UnitCommitment.model_validate(problem())
    compiled = compile_commitment(spec)
    assert len(compiled.variables) == 18
    assert len(compiled.constraints) == 31
    result = solve(spec)
    assert result["compiler"] == UNIT_SECURITY_COMPILER
    assert result["objective"] == pytest.approx(220)
    verdict = verify(spec, result)
    assert verdict["primal"]["passed"]
    physical = verdict["commitment"]["physical"]
    assert physical["passed"]
    security = physical["schedule"]["security"]
    assert not security["all_thermal_units_covered"]
    assert not security["all_network_lines_covered"]
    hour = security["unit_cases"]["cheap"]["hours"][0]
    assert hour["units"]["cheap"]["generation_mw"] == pytest.approx(0)
    assert hour["units"]["cheap"]["outaged"]
    assert hour["units"]["cheap"]["usable_upward_reserve_mw"] == 0
    assert hour["units"]["local"]["generation_mw"] == pytest.approx(6)
    assert hour["units"]["local"]["redispatch_mw"] == pytest.approx(2)
    assert hour["lines"]["AB"]["flow_mw"] == pytest.approx(0)


def test_failed_unit_reserve_cannot_cover_its_own_trip():
    raw = problem()
    raw["network"]["unit_reserve_capability_mw"] = {"cheap": 4, "local": 0}
    # The failed unit must be online and producing at least 1 MW. The
    # survivor has enough nameplate capacity but no authorized upward reserve.
    raw["units"][0].update(minimum_mw=1, initial_mw=1, min_up_hours=2, initial_state_hours=1)
    base = copy.deepcopy(raw)
    base["network"].pop("security")
    assert verify(base, solve(base))["primal"]["passed"]
    result = solve(raw)
    assert result["status"] == "infeasible_reported"
    assert not verify(raw, result)["primal"]["passed"]


def test_generator_trip_can_be_blocked_by_transmission_even_with_reserve():
    raw = problem()
    raw["network"]["security"] = {"outage_units": ["local"]}
    raw["network"]["unit_reserve_capability_mw"]["cheap"] = 4
    base = copy.deepcopy(raw)
    base["network"].pop("security")
    assert verify(base, solve(base))["primal"]["passed"]
    assert solve(raw)["status"] == "infeasible_reported"


def test_all_units_covered_and_recourse_independent():
    raw = problem()
    raw["demand_mw"] = [4]
    net = raw["network"]
    net["buses"][1]["demand_mw"] = [4]
    net["unit_reserve_capability_mw"]["cheap"] = 2
    net["security"]["outage_units"] = ["local", "cheap"]
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    assert result["objective"] == pytest.approx(120)
    security = verify(spec, result)["commitment"]["physical"]["schedule"]["security"]
    assert security["all_thermal_units_covered"]
    assert security["unit_cases"]["local"]["hours"][0]["lines"]["AB"]["flow_mw"] == pytest.approx(4)
    assert security["unit_cases"]["cheap"]["hours"][0]["lines"]["AB"]["flow_mw"] == pytest.approx(0)
    raw["network"]["security"]["outage_units"].reverse()
    assert UnitCommitment.model_validate(raw).sha256() == spec.sha256()


def test_mixed_cases_persist_and_use_distinct_keys(tmp_path):
    raw = problem()
    raw["network"]["security"]["outage_lines"] = ["AB"]
    spec = UnitCommitment.model_validate(raw)
    assert reservation_for(spec)["compiler"] == UNIT_SECURITY_COMPILER
    identifier = start_program(tmp_path, spec)
    report = resume_program(tmp_path, identifier)
    assert report["completed"]
    security = report["verification"]["commitment"]["physical"]["schedule"]["security"]
    assert set(security["cases"]) == {"AB"}
    assert set(security["unit_cases"]) == {"cheap"}
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Repeated solve")) == report
    raw["network"]["security"].pop("outage_units")
    legacy = UnitCommitment.model_validate(raw)
    assert "outage_units" not in legacy.canonical()["network"]["security"]
    assert reservation_for(legacy)["compiler"] == "dc-line-security-commitment-milp-v1"


@pytest.mark.parametrize("fault", ["unknown", "duplicate", "empty", "combined_budget"])
def test_invalid_unit_contingencies(fault):
    raw = problem()
    if fault == "unknown":
        raw["network"]["security"]["outage_units"] = ["missing"]
    elif fault == "duplicate":
        raw["network"]["security"]["outage_units"] = ["cheap", "cheap"]
    elif fault == "empty":
        raw["network"]["security"]["outage_units"] = []
    else:
        raw["demand_mw"] = [6]*12
        raw["network"]["buses"][0]["demand_mw"] = [0]*12
        raw["network"]["buses"][1]["demand_mw"] = [6]*12
        raw["network"]["reserve_requirement_mw"] = [1]*12
    with pytest.raises(ValidationError):
        UnitCommitment.model_validate(raw)


def test_independent_check_detects_failed_generation_and_unreserved_redispatch():
    spec = UnitCommitment.model_validate(problem())
    values = copy.deepcopy(solve(spec)["values"])
    values[security_variable(0, "g", 0, 0, "p")] = 1
    values[security_variable(0, "g", 1, 0, "p")] = 7
    values[variable("g", 1, 0, "reserve")] = 2
    physical = physical_checks(spec, values)
    failures = {row["id"] for row in physical["checks"] if not row["passed"]}
    assert {"unit-security:cheap:0:unit:cheap:outage", "unit-security:cheap:0:unit:local:up"} <= failures


def test_synthetic_benchmark_checks_analytic_references():
    report = run_benchmark()
    assert report["passed"], report
    assert len(report["observations"]) == 6
    assert all(row["solve_seconds"] >= 0 and row["verify_seconds"] >= 0 for row in report["observations"])
