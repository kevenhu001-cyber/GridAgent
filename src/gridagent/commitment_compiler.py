"""Deterministic commitment lowering into the existing typed MILP."""

from .commitment_ir import UnitCommitment
from .math_program_ir import MathematicalProgram

COMPILER = "single-area-commitment-milp-v1"


def variable(prefix, index, hour, field):
    return f"{prefix}{index:02}h{hour:02}-{field}"


def ordered(spec):
    return UnitCommitment.model_validate(spec.canonical())


def compile_commitment(spec):
    spec = ordered(UnitCommitment.model_validate(spec))
    variables, constraints, costs = [], [], []

    def add_var(name, lower, upper, unit, *, binary=False, cost=0):
        variables.append({"id": name, "lower": lower, "upper": upper, "unit": unit,
                          "kind": "binary" if binary else "continuous"})
        costs.append({"variable": name, "coefficient": cost})
        return name

    def row(name, terms, unit, lower=None, upper=None):
        constraints.append({"id": name, "terms": [
            {"variable": key, "coefficient": coefficient} for key, coefficient in terms.items()],
            "lower": lower, "upper": upper, "unit": unit})

    hours = len(spec.demand_mw)
    for i, unit in enumerate(spec.units):
        def v(t, field, index=i):
            return variable("g", index, t, field)

        initial_on = int(unit.initially_on)
        remaining = max(0, (unit.min_up_hours if initial_on else unit.min_down_hours)
                        - unit.initial_state_hours)
        for t in range(hours):
            p = add_var(v(t, "p"), 0, unit.maximum_mw, "MW", cost=unit.marginal_cost_per_mwh)
            on = add_var(v(t, "on"), initial_on if t < remaining else 0,
                         initial_on if t < remaining else 1, "1", binary=True,
                         cost=unit.online_cost_per_hour)
            start = add_var(v(t, "start"), 0, 1, "1", binary=True, cost=unit.startup_cost)
            stop = add_var(v(t, "stop"), 0, 1, "1", binary=True, cost=unit.shutdown_cost)
            row(v(t, "maximum"), {p: 1, on: -unit.maximum_mw}, "MW", upper=0)
            row(v(t, "minimum"), {p: 1, on: -unit.minimum_mw}, "MW", lower=0)
            transition = {on: 1, start: -1, stop: 1}
            up = {p: 1, start: -unit.startup_limit_mw}
            down = {p: -1, on: -unit.ramp_down_mw, stop: -unit.shutdown_limit_mw}
            if t:
                transition[v(t-1, "on")] = -1
                up[v(t-1, "p")] = -1
                up[v(t-1, "on")] = -unit.ramp_up_mw
                down[v(t-1, "p")] = 1
                prev_on, prev_p = 0, 0
            else:
                prev_on, prev_p = initial_on, unit.initial_mw
            row(v(t, "transition"), transition, "1", lower=prev_on, upper=prev_on)
            row(v(t, "exclusive"), {start: 1, stop: 1}, "1", upper=1)
            row(v(t, "rampup"), up, "MW", upper=prev_p+unit.ramp_up_mw*prev_on)
            row(v(t, "rampdown"), down, "MW", upper=-prev_p)
            starts = {v(k, "start"): 1 for k in range(max(0, t-unit.min_up_hours+1), t+1)}
            stops = {v(k, "stop"): 1 for k in range(max(0, t-unit.min_down_hours+1), t+1)}
            row(v(t, "minup"), {**starts, on: -1}, "1", upper=0)
            row(v(t, "mindown"), {**stops, on: 1}, "1", upper=1)

    for i, battery in enumerate(spec.storage):
        def v(t, field, index=i):
            return variable("b", index, t, field)

        for t in range(hours):
            charge = add_var(v(t, "charge"), 0, battery.power_mw, "MW")
            discharge = add_var(v(t, "discharge"), 0, battery.power_mw, "MW",
                                cost=battery.discharge_cost_per_mwh)
            soc = add_var(v(t, "soc"), 0, battery.energy_mwh, "MWh")
            mode = add_var(v(t, "mode"), 0, 1, "1", binary=True)
            row(v(t, "chargecap"), {charge: 1, mode: -battery.power_mw}, "MW", upper=0)
            row(v(t, "dischargecap"), {discharge: 1, mode: battery.power_mw}, "MW", upper=battery.power_mw)
            equation = {soc: 1, charge: -battery.charge_efficiency,
                        discharge: 1/battery.discharge_efficiency}
            initial = battery.initial_mwh
            if t:
                equation[v(t-1, "soc")] = -1
                initial = 0
            row(v(t, "energy"), equation, "MWh", lower=initial, upper=initial)
        row(v(hours-1, "terminal"), {v(hours-1, "soc"): 1}, "MWh",
            lower=battery.terminal_mwh, upper=battery.terminal_mwh)

    for t, demand in enumerate(spec.demand_mw):
        balance = {variable("g", i, t, "p"): 1 for i in range(len(spec.units))}
        for i in range(len(spec.storage)):
            balance[variable("b", i, t, "charge")] = -1
            balance[variable("b", i, t, "discharge")] = 1
        row(f"balance-h{t:02}", balance, "MW", lower=demand, upper=demand)

    return MathematicalProgram.model_validate({
        "description": spec.description, "variables": variables, "constraints": constraints,
        "objective": {"sense": "minimize", "terms": costs, "unit": spec.currency},
        "time_limit_s": spec.time_limit_s, "node_limit": spec.node_limit,
    })
