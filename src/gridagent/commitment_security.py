"""Corrective single-component security constraints and independent source-based checks."""


def references(network, outage):
    """One deterministic angle reference per surviving connected component."""
    neighbors = {bus.id: set() for bus in network.buses}
    for line in network.lines:
        if line.id != outage:
            neighbors[line.from_bus].add(line.to_bus)
            neighbors[line.to_bus].add(line.from_bus)
    remaining = set(neighbors)
    refs = set()
    while remaining:
        stack = [min(remaining)]
        component = set()
        while stack:
            node = stack.pop()
            if node not in component:
                component.add(node)
                stack.extend(neighbors[node] - component)
        remaining -= component
        refs.add(network.reference_bus if network.reference_bus in component else min(component))
    return refs


def security_variable(case, prefix, index, hour, field):
    return f"c{case:02}-{prefix}{index:02}h{hour:02}-{field}"


def contingency_cases(network):
    return [("line", key) for key in network.security.outage_lines] + [
        ("unit", key) for key in network.security.outage_units]


def add_security(spec, add_var, row, variable):
    network = spec.network
    buses = {bus.id: i for i, bus in enumerate(network.buses)}
    for case, (kind, outage) in enumerate(contingency_cases(network)):
        line_outage = outage if kind == "line" else None
        refs = references(network, line_outage)

        def v(prefix, index, hour, field, case=case):
            return security_variable(case, prefix, index, hour, field)

        for t in range(len(spec.demand_mw)):
            angles, balances = {}, {bus.id: {} for bus in network.buses}
            for i, bus in enumerate(network.buses):
                bound = 0 if bus.id in refs else network.angle_bound_rad
                angles[bus.id] = add_var(v("n", i, t, "angle"), -bound, bound, "rad")
            for i, unit in enumerate(spec.units):
                failed = kind == "unit" and unit.id == outage
                p = add_var(v("g", i, t, "p"), 0, 0 if failed else unit.maximum_mw, "MW")
                balances[network.unit_buses[unit.id]][p] = 1
                if failed:
                    continue
                base, on, reserve = (variable("g", i, t, field) for field in ("p", "on", "reserve"))
                row(v("g", i, t, "max"), {p: 1, on: -unit.maximum_mw}, "MW", upper=0)
                row(v("g", i, t, "min"), {p: 1, on: -unit.minimum_mw}, "MW", lower=0)
                row(v("g", i, t, "up"), {p: 1, base: -1, reserve: -1}, "MW", upper=0)
                row(v("g", i, t, "down"), {base: 1, p: -1}, "MW",
                    upper=unit.ramp_down_mw * network.reserve_response_minutes / 60)
            for i, battery in enumerate(spec.storage):
                balance = balances[network.storage_buses[battery.id]]
                balance[variable("b", i, t, "charge")] = -1
                balance[variable("b", i, t, "discharge")] = 1
            for i, line in enumerate(network.lines):
                limit = 0 if line.id == line_outage else line.limit_mw
                flow = add_var(v("l", i, t, "flow"), -limit, limit, "MW")
                if line.id != line_outage:
                    origin, target = angles[line.from_bus], angles[line.to_bus]
                    row(v("l", i, t, "dc"), {flow: 1, origin: -line.susceptance_mw_per_rad,
                                              target: line.susceptance_mw_per_rad}, "MW", lower=0, upper=0)
                    row(v("l", i, t, "angle-limit"), {origin: 1, target: -1}, "rad",
                        lower=-line.max_angle_difference_rad, upper=line.max_angle_difference_rad)
                balances[line.from_bus][flow] = -1
                balances[line.to_bus][flow] = 1
            for bus in network.buses:
                demand = bus.demand_mw[t]
                row(v("n", buses[bus.id], t, "balance"), balances[bus.id], "MW", lower=demand, upper=demand)


def security_checks(spec, values, variable, check):
    """Rebuild each outage's physical equations independently of compiled rows."""
    network = spec.network
    cases, unit_cases = {}, {}
    for case, (kind, outage) in enumerate(contingency_cases(network)):
        line_outage = outage if kind == "line" else None
        refs = references(network, line_outage)
        schedule = {"reference_buses": sorted(refs), "hours": []}
        for t in range(len(spec.demand_mw)):
            prefix = f"security:{outage}:{t}" if kind == "line" else f"unit-security:{outage}:{t}"
            residual = {bus.id: -bus.demand_mw[t] for bus in network.buses}
            angles = {bus.id: values[security_variable(case, "n", i, t, "angle")]
                      for i, bus in enumerate(network.buses)}
            for bus in network.buses:
                check(f"{prefix}:angle:{bus.id}", abs(angles[bus.id])-network.angle_bound_rad)
                if bus.id in refs:
                    check(f"{prefix}:reference:{bus.id}", abs(angles[bus.id]))
            units, lines = {}, {}
            for i, unit in enumerate(spec.units):
                p = values[security_variable(case, "g", i, t, "p")]
                base, on, reserve = (values[variable("g", i, t, field)] for field in ("p", "on", "reserve"))
                online = round(on)
                change = p-base
                failed = kind == "unit" and unit.id == outage
                if failed:
                    check(f"{prefix}:unit:{unit.id}:outage", abs(p))
                else:
                    check(f"{prefix}:unit:{unit.id}:capacity",
                          max(unit.minimum_mw*online-p, p-unit.maximum_mw*online, -p))
                    check(f"{prefix}:unit:{unit.id}:up", change-reserve)
                    check(f"{prefix}:unit:{unit.id}:down",
                          -change-unit.ramp_down_mw*network.reserve_response_minutes/60)
                residual[network.unit_buses[unit.id]] += p
                units[unit.id] = {"generation_mw": p, "redispatch_mw": change,
                                  "allocated_upward_reserve_mw": reserve}
                if kind == "unit":
                    units[unit.id].update(outaged=failed, usable_upward_reserve_mw=0 if failed else reserve)
            for i, battery in enumerate(spec.storage):
                charge = values[variable("b", i, t, "charge")]
                discharge = values[variable("b", i, t, "discharge")]
                residual[network.storage_buses[battery.id]] += discharge-charge
            for i, line in enumerate(network.lines):
                flow = values[security_variable(case, "l", i, t, "flow")]
                failed = line.id == line_outage
                if failed:
                    check(f"{prefix}:line:{line.id}:outage", abs(flow))
                else:
                    difference = angles[line.from_bus]-angles[line.to_bus]
                    check(f"{prefix}:line:{line.id}:capacity", abs(flow)-line.limit_mw)
                    check(f"{prefix}:line:{line.id}:angle", abs(difference)-line.max_angle_difference_rad)
                    check(f"{prefix}:line:{line.id}:dc", abs(flow-line.susceptance_mw_per_rad*difference))
                residual[line.from_bus] -= flow
                residual[line.to_bus] += flow
                lines[line.id] = {"flow_mw": flow, "outaged": failed}
            for bus, error in residual.items():
                check(f"{prefix}:node:{bus}:balance", abs(error))
            schedule["hours"].append({"hour": t, "units": units, "lines": lines,
                                      "angles_rad": angles, "nodal_residual_mw": residual})
        if kind == "unit":
            unit_cases[outage] = schedule
        else:
            cases[outage] = schedule
    report = {"cases": cases, "all_network_lines_covered": set(cases) == {line.id for line in network.lines},
              "scope": "independent_single_line_outages_fixed_commitment_and_storage"}
    if network.security.outage_units:
        report.update(unit_cases=unit_cases,
                      all_thermal_units_covered=set(unit_cases) == {unit.id for unit in spec.units},
                      scope="independent_single_component_outages_fixed_commitment_and_storage")
    return report
