"""DC network and spinning reserve lowering plus independent engineering checks."""


def reserve_limit(unit, network):
    return min(network.unit_reserve_capability_mw[unit.id],
               unit.ramp_up_mw * network.reserve_response_minutes / 60)


def add_network(spec, add_var, row, variable):
    network = spec.network
    buses = {bus.id: i for i, bus in enumerate(network.buses)}
    for t, requirement in enumerate(network.reserve_requirement_mw):
        angles = {}
        for i, bus in enumerate(network.buses):
            bound = 0 if bus.id == network.reference_bus else network.angle_bound_rad
            angles[bus.id] = add_var(variable("n", i, t, "angle"), -bound, bound, "rad")
        balances = {bus.id: {} for bus in network.buses}
        for i, unit in enumerate(spec.units):
            balances[network.unit_buses[unit.id]][variable("g", i, t, "p")] = 1
        for i, battery in enumerate(spec.storage):
            balance = balances[network.storage_buses[battery.id]]
            balance[variable("b", i, t, "charge")] = -1
            balance[variable("b", i, t, "discharge")] = 1
        for i, line in enumerate(network.lines):
            flow = add_var(variable("l", i, t, "flow"), -line.limit_mw, line.limit_mw, "MW")
            origin, target = angles[line.from_bus], angles[line.to_bus]
            row(variable("l", i, t, "dc"), {flow: 1, origin: -line.susceptance_mw_per_rad,
                                          target: line.susceptance_mw_per_rad}, "MW", lower=0, upper=0)
            row(variable("l", i, t, "angle-limit"), {origin: 1, target: -1}, "rad",
                lower=-line.max_angle_difference_rad, upper=line.max_angle_difference_rad)
            balances[line.from_bus][flow] = -1
            balances[line.to_bus][flow] = 1
        for bus in network.buses:
            demand = bus.demand_mw[t]
            row(variable("n", buses[bus.id], t, "balance"), balances[bus.id], "MW",
                lower=demand, upper=demand)
        reserves = {}
        for i, unit in enumerate(spec.units):
            reserve = add_var(variable("g", i, t, "reserve"), 0, reserve_limit(unit, network), "MW")
            row(variable("g", i, t, "headroom"),
                {reserve: 1, variable("g", i, t, "p"): 1,
                 variable("g", i, t, "on"): -unit.maximum_mw}, "MW", upper=0)
            reserves[reserve] = 1
        row(f"reserve-h{t:02}", reserves, "MW", lower=requirement)


def network_checks(spec, values, variable, check, schedules):
    """Reconstruct each bus injection, branch relation and reserve from source data."""
    network = spec.network
    schedule = {"buses": {bus.id: [] for bus in network.buses},
                "lines": {line.id: [] for line in network.lines}, "reserve": []}
    for t, requirement in enumerate(network.reserve_requirement_mw):
        residual = {bus.id: -bus.demand_mw[t] for bus in network.buses}
        angles = {bus.id: values[variable("n", i, t, "angle")] for i, bus in enumerate(network.buses)}
        for bus in network.buses:
            check(f"network:{bus.id}:{t}:angle", abs(angles[bus.id])-network.angle_bound_rad)
        check(f"network:reference:{t}", abs(angles[network.reference_bus]))
        reserve_total = 0.0
        for i, unit in enumerate(spec.units):
            p = values[variable("g", i, t, "p")]
            on = round(values[variable("g", i, t, "on")])
            reserve = values[variable("g", i, t, "reserve")]
            residual[network.unit_buses[unit.id]] += p
            cap = min(network.unit_reserve_capability_mw[unit.id],
                      unit.ramp_up_mw * network.reserve_response_minutes / 60)
            check(f"reserve:{unit.id}:{t}:response", max(-reserve, reserve-cap))
            check(f"reserve:{unit.id}:{t}:headroom", p+reserve-on*unit.maximum_mw)
            schedules["units"][unit.id]["hours"][t]["reserve_mw"] = reserve
            reserve_total += reserve
        for i, battery in enumerate(spec.storage):
            charge = values[variable("b", i, t, "charge")]
            discharge = values[variable("b", i, t, "discharge")]
            residual[network.storage_buses[battery.id]] += discharge-charge
        for i, line in enumerate(network.lines):
            flow = values[variable("l", i, t, "flow")]
            difference = angles[line.from_bus]-angles[line.to_bus]
            check(f"line:{line.id}:{t}:capacity", abs(flow)-line.limit_mw)
            check(f"line:{line.id}:{t}:angle", abs(difference)-line.max_angle_difference_rad)
            check(f"line:{line.id}:{t}:dc", abs(flow-line.susceptance_mw_per_rad*difference))
            residual[line.from_bus] -= flow
            residual[line.to_bus] += flow
            schedule["lines"][line.id].append({"hour": t, "flow_mw": flow,
                                                "angle_difference_rad": difference,
                                                "loading_percent": 100*abs(flow)/line.limit_mw})
        for bus in network.buses:
            check(f"node:{bus.id}:{t}:balance", abs(residual[bus.id]))
            schedule["buses"][bus.id].append({"hour": t, "angle_rad": angles[bus.id],
                                             "demand_mw": bus.demand_mw[t],
                                             "balance_residual_mw": residual[bus.id]})
        check(f"reserve:system:{t}", requirement-reserve_total)
        schedule["reserve"].append({"hour": t, "requirement_mw": requirement,
                                    "scheduled_mw": reserve_total, "margin_mw": reserve_total-requirement})
    return schedule
