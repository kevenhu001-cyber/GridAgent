"""Independent physical checks of a decoded commitment schedule."""

import math

from .commitment_compiler import compile_commitment, compiler_for, ordered, variable
from .commitment_ir import UnitCommitment
from .commitment_network import network_checks
from .commitment_security import security_checks
from .math_program_solver import solve_program, verify_result

TOL = 1e-6


def solve_commitment(spec):
    spec = UnitCommitment.model_validate(spec)
    program = compile_commitment(spec)
    return {**solve_program(program), "compiler": compiler_for(spec), "compiled_program_sha256": program.sha256()}


def physical_checks(spec, values):
    """Recompute physics and chronology from the source contract, not matrix rows."""
    spec = ordered(UnitCommitment.model_validate(spec))
    hours = len(spec.demand_mw)
    residual = list(spec.demand_mw)
    checks, costs, schedules = [], [], {"units": {}, "storage": {}}

    def check(name, violation):
        violation = max(0.0, float(violation))
        checks.append({"id": name, "violation": violation, "passed": violation <= TOL})

    for i, unit in enumerate(spec.units):
        prior_on = int(unit.initially_on)
        prior_p = unit.initial_mw
        duration = unit.initial_state_hours
        rows = []
        for t in range(hours):
            prefix = f"unit:{unit.id}:{t}"
            p, on, start, stop = (values[variable("g", i, t, field)]
                                  for field in ("p", "on", "start", "stop"))
            state = round(on)
            check(prefix+":capacity", max(unit.minimum_mw*state-p, p-unit.maximum_mw*state, -p))
            check(prefix+":transition", abs(state-prior_on-start+stop))
            check(prefix+":exclusive", start+stop-1)
            if state != prior_on:
                minimum_duration = unit.min_up_hours if prior_on else unit.min_down_hours
                check(prefix+":prior_duration", minimum_duration-duration)
                duration = 1
            else:
                duration += 1
            check(prefix+":ramp_up", p-prior_p-unit.ramp_up_mw*prior_on-unit.startup_limit_mw*start)
            check(prefix+":ramp_down", prior_p-p-unit.ramp_down_mw*state-unit.shutdown_limit_mw*stop)
            residual[t] -= p
            cost = (p*unit.marginal_cost_per_mwh + state*unit.online_cost_per_hour
                    + start*unit.startup_cost + stop*unit.shutdown_cost)
            costs.append(cost)
            rows.append({"hour": t, "generation_mw": p, "on": state,
                         "startup": round(start), "shutdown": round(stop), "cost": cost})
            prior_on, prior_p = state, p
        obligation = max(0, (unit.min_up_hours if prior_on else unit.min_down_hours)-duration)
        schedules["units"][unit.id] = {"hours": rows, "terminal_on": bool(prior_on),
                                       "terminal_state_hours": duration,
                                       "remaining_minimum_state_hours": obligation}

    for i, battery in enumerate(spec.storage):
        previous = battery.initial_mwh
        rows = []
        for t in range(hours):
            prefix = f"storage:{battery.id}:{t}"
            charge, discharge, soc = (values[variable("b", i, t, field)]
                                      for field in ("charge", "discharge", "soc"))
            check(prefix+":charge", max(-charge, charge-battery.power_mw))
            check(prefix+":discharge", max(-discharge, discharge-battery.power_mw))
            check(prefix+":exclusive", min(charge, discharge))
            check(prefix+":capacity", max(-soc, soc-battery.energy_mwh))
            expected = previous + battery.charge_efficiency*charge - discharge/battery.discharge_efficiency
            check(prefix+":energy", abs(soc-expected))
            residual[t] += charge-discharge
            costs.append(discharge*battery.discharge_cost_per_mwh)
            rows.append({"hour": t, "charge_mw": charge, "discharge_mw": discharge, "soc_mwh": soc})
            previous = soc
        check("storage:"+battery.id+":terminal", abs(previous-battery.terminal_mwh))
        schedules["storage"][battery.id] = rows

    for t, error in enumerate(residual):
        check(f"balance:{t}", abs(error))
    if spec.network is not None:
        schedules["network"] = network_checks(spec, values, variable, check, schedules)
        if spec.network.security is not None:
            schedules["security"] = security_checks(spec, values, variable, check)
    return {"passed": all(row["passed"] for row in checks), "checks": checks,
            "total_cost": math.fsum(costs), "schedule": schedules,
            "power_balance_residual_mw": residual, "currency": spec.currency}


def verify_commitment(spec, result):
    spec = UnitCommitment.model_validate(spec)
    program = compile_commitment(spec)
    if result.get("status") == "solver_exception":
        if result.get("values") is not None or result.get("objective") is not None:
            raise ValueError("Invalid failed commitment result")
        return verify_result(program, result)
    if (result.get("compiler") != compiler_for(spec)
            or result.get("compiled_program_sha256") != program.sha256()):
        raise ValueError("Commitment result differs from compiled program")
    verdict = verify_result(program, result)
    physical = None
    if verdict["primal"]["passed"]:
        physical = physical_checks(spec, result["values"])
        cost_difference = abs(physical["total_cost"]-verdict["primal"]["objective"])
        cost_ok = cost_difference <= TOL + 1e-7*abs(physical["total_cost"])
        physical["checks"].append({"id": "operating_cost", "passed": cost_ok, "violation": cost_difference})
        physical["passed"] = physical["passed"] and cost_ok
        verdict["primal"]["passed"] = physical["passed"]
        if not physical["passed"]:
            verdict["classification"] = "no_verified_candidate"
    model = "single_area_no_network_constraints"
    if spec.network is not None:
        model = "lossless_dc_selected_line_outages" if spec.network.security is not None else "lossless_dc_base_topology"
    verdict["commitment"] = {"compiler": compiler_for(spec), "source_sha256": spec.sha256(),
                             "compiled_program_sha256": program.sha256(), "physical": physical,
                             "network_model": model,
                             "horizon_boundary": "carry_remaining_minimum_state_obligations"}
    return verdict
