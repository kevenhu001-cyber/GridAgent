import copy

import pytest
from pydantic import ValidationError

from gridagent.commitment_compiler import NETWORK_COMPILER, compile_commitment, variable
from gridagent.commitment_ir import UnitCommitment
from gridagent.commitment_solver import physical_checks
from gridagent.math_program_router import reservation_for, solve, verify
from gridagent.math_program_tasks import resume_program, start_program


def unit(identifier, cost, **changes):
    return {"id": identifier, "minimum_mw": 0, "maximum_mw": 10,
            "marginal_cost_per_mwh": cost, "ramp_up_mw": 8, "ramp_down_mw": 10,
            "startup_limit_mw": 10, "shutdown_limit_mw": 10, "min_up_hours": 1,
            "min_down_hours": 1, "initially_on": True, "initial_mw": 0,
            "initial_state_hours": 2, **changes}


def problem():
    return {
        "description": "Two-bus congestion and reserve example",
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
        },
    }


def test_congested_network_dispatch_and_reserve():
    spec = UnitCommitment.model_validate(problem())
    program = compile_commitment(spec)
    assert len(program.variables) == 13
    assert len(program.constraints) == 23
    result = solve(spec)
    assert result["compiler"] == NETWORK_COMPILER
    assert result["objective"] == pytest.approx(140)
    verdict = verify(spec, result)
    assert verdict["primal"]["passed"]
    assert verdict["commitment"]["network_model"] == "lossless_dc_base_topology"
    assert not verdict["optimality_independently_checked"]
    physical = verdict["commitment"]["physical"]
    schedule = physical["schedule"]
    assert schedule["units"]["cheap"]["hours"][0]["generation_mw"] == pytest.approx(4)
    assert schedule["units"]["local"]["hours"][0]["generation_mw"] == pytest.approx(2)
    assert 1-1e-6 <= schedule["units"]["local"]["hours"][0]["reserve_mw"] <= 2+1e-6
    assert schedule["network"]["lines"]["AB"][0]["flow_mw"] == pytest.approx(4)
    assert schedule["network"]["buses"]["B"][0]["angle_rad"] == pytest.approx(-0.2)
    assert schedule["network"]["buses"]["B"][0]["balance_residual_mw"] == pytest.approx(0)


def test_reversed_orientation_and_angle_limit():
    raw = problem()
    raw["network"]["lines"][0].update(from_bus="B", to_bus="A", max_angle_difference_rad=0.15)
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    assert result["objective"] == pytest.approx(180)
    verdict = verify(spec, result)
    assert verdict["primal"]["passed"]
    line = verdict["commitment"]["physical"]["schedule"]["network"]["lines"]["AB"][0]
    assert line["flow_mw"] == pytest.approx(-3)
    assert line["angle_difference_rad"] == pytest.approx(-0.15)


@pytest.mark.parametrize("case", ["response", "headroom", "transmission"])
def test_infeasible_network_or_reserve(case):
    raw = problem()
    if case == "response":
        raw["network"]["reserve_requirement_mw"] = [3]
    elif case == "headroom":
        raw["units"][1].update(maximum_mw=2, startup_limit_mw=2, shutdown_limit_mw=2)
        raw["network"]["unit_reserve_capability_mw"]["local"] = 2
    else:
        raw["units"][1].update(maximum_mw=1, startup_limit_mw=1, shutdown_limit_mw=1)
        raw["network"]["unit_reserve_capability_mw"]["local"] = 1
        raw["network"]["reserve_requirement_mw"] = [0]
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    assert result["status"] == "infeasible_reported"
    assert not verify(spec, result)["primal"]["passed"]


def test_storage_dispatch_at_receiving_bus():
    raw = problem()
    raw["demand_mw"] = [1, 4]
    raw["units"][0].update(maximum_mw=2, startup_limit_mw=2, shutdown_limit_mw=2)
    raw["storage"] = [{"id": "battery", "power_mw": 1, "energy_mwh": 1,
                       "initial_mwh": 0, "terminal_mwh": 0,
                       "charge_efficiency": 1, "discharge_efficiency": 1}]
    net = raw["network"]
    net["buses"][0]["demand_mw"] = [0, 0]
    net["buses"][1]["demand_mw"] = [1, 4]
    net["reserve_requirement_mw"] = [0, 0]
    net["storage_buses"] = {"battery": "B"}
    net["lines"][0]["limit_mw"] = 2
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    assert result["objective"] == pytest.approx(90)
    physical = verify(spec, result)["commitment"]["physical"]
    assert physical["passed"]
    assert [row["soc_mwh"] for row in physical["schedule"]["storage"]["battery"]] == pytest.approx([1, 0])
    assert [row["flow_mw"] for row in physical["schedule"]["network"]["lines"]["AB"]] == pytest.approx([2, 2])


def test_meshed_dc_flow_not_unconstrained_transport():
    raw = problem()
    raw["demand_mw"] = [6]
    raw["network"]["buses"].append({"id": "C", "demand_mw": [0]})
    raw["network"]["lines"][0].update(limit_mw=2)
    raw["network"]["lines"].extend([
        {"id": "AC", "from_bus": "A", "to_bus": "C", "susceptance_mw_per_rad": 20,
         "limit_mw": 10, "max_angle_difference_rad": 0.3},
        {"id": "CB", "from_bus": "C", "to_bus": "B", "susceptance_mw_per_rad": 20,
         "limit_mw": 10, "max_angle_difference_rad": 0.3},
    ])
    spec = UnitCommitment.model_validate(raw)
    result = solve(spec)
    verdict = verify(spec, result)
    assert verdict["primal"]["passed"]
    assert result["objective"] == pytest.approx(180)
    lines = verdict["commitment"]["physical"]["schedule"]["network"]["lines"]
    assert [lines[key][0]["flow_mw"] for key in ("AB", "AC", "CB")] == pytest.approx([2, 1, 1])


@pytest.mark.parametrize("fault", ["unknown_bus", "disconnected", "duplicate_line", "demand", "profile",
                                   "missing_mapping", "reserve_capability", "missing_capability", "reference"])
def test_invalid_network_contract(fault):
    raw = problem()
    net = raw["network"]
    if fault == "unknown_bus":
        net["lines"][0]["to_bus"] = "C"
    elif fault == "disconnected":
        net["buses"].append({"id": "C", "demand_mw": [0]})
    elif fault == "duplicate_line":
        net["lines"].append(net["lines"][0])
    elif fault == "demand":
        net["buses"][1]["demand_mw"] = [5]
    elif fault == "profile":
        net["reserve_requirement_mw"] = [1, 2]
    elif fault == "missing_mapping":
        del net["unit_buses"]["local"]
    elif fault == "reserve_capability":
        net["unit_reserve_capability_mw"]["local"] = 11
    elif fault == "missing_capability":
        del net["unit_reserve_capability_mw"]["cheap"]
    else:
        net["reference_bus"] = "Z"
    with pytest.raises(ValidationError):
        UnitCommitment.model_validate(raw)


def test_independent_physical_network_verifier_rejects_changed_flow_and_reserve():
    spec = UnitCommitment.model_validate(problem())
    result = solve(spec)
    bad = copy.deepcopy(result["values"])
    bad[variable("l", 0, 0, "flow")] = 3
    bad[variable("g", 1, 0, "reserve")] = 3
    physical = physical_checks(spec, bad)
    assert not physical["passed"]
    failures = {row["id"] for row in physical["checks"] if not row["passed"]}
    assert {"line:AB:0:dc", "node:A:0:balance", "node:B:0:balance",
            "reserve:local:0:response"} <= failures


def test_deterministic_network_hash_and_resume(tmp_path):
    raw = problem()
    spec = UnitCommitment.model_validate(raw)
    raw["network"]["buses"].reverse()
    raw["units"].reverse()
    reordered = UnitCommitment.model_validate(raw)
    assert spec.sha256() == reordered.sha256()
    assert compile_commitment(spec).sha256() == compile_commitment(reordered).sha256()
    assert reservation_for(spec)["compiler"] == NETWORK_COMPILER
    identifier = start_program(tmp_path, spec)
    first = resume_program(tmp_path, identifier)
    assert first["completed"]
    assert resume_program(tmp_path, identifier, solver=lambda _: pytest.fail("Duplicate solve")) == first
    raw.pop("network")
    legacy = UnitCommitment.model_validate(raw)
    assert "network" not in legacy.canonical()
    assert reservation_for(legacy)["compiler"] == "single-area-commitment-milp-v1"
