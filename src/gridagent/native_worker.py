"""Dispatch to installed pandapower and PyPSA APIs; never execute supplied code."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .native_backends import ADAPTER
from .native_program import PPProgram


def scalar(value):
    if pd.isna(value):
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value


def rows(table, columns, limit=30):
    selected = [c for c in columns if c in table.columns]
    return [{"index": int(i), **{k: scalar(row[k]) for k in selected}}
            for i, row in table[selected].head(limit).iterrows()]


def pandapower_run(program, folder):
    import pandapower as pp
    from pandapower import networks, shortcircuit

    factories = {"empty": pp.create_empty_network, "case14": networks.case14,
                 "case39": networks.case39, "case118": networks.case118}
    net = factories[program.base]()
    calls = {name: getattr(pp, name) for name in (
        "create_bus", "create_ext_grid", "create_line_from_parameters", "create_load",
        "create_gen", "create_sgen", "create_storage", "create_transformer_from_parameters", "create_switch")}
    audit = []
    for step in program.steps:
        args = step.model_dump(exclude_none=True)
        name = args.pop("op")
        if name == "edit":
            table = net[args["element"]]
            idx, field, value = args["index"], args["field"], args["value"]
            if idx not in table.index or field not in table.columns:
                raise ValueError("Unknown element index or field")
            if field == "tap_pos":
                lower, upper = table.loc[idx, ["tap_min", "tap_max"]]
                if (pd.notna(lower) and value < lower) or (pd.notna(upper) and value > upper):
                    raise ValueError("Tap position outside the transformer's declared range")
            before = scalar(table.at[idx, field])
            table.at[idx, field] = value
            audit.append({**args, "before": before})
        else:
            for key in ("bus", "from_bus", "to_bus", "hv_bus", "lv_bus"):
                if key in args and args[key] not in net.bus.index:
                    raise ValueError("Referenced bus does not exist")
            if name == "create_line_from_parameters" and args["from_bus"] == args["to_bus"]:
                raise ValueError("Line endpoints must differ")
            if name == "create_transformer_from_parameters" and args.get("tap_side"):
                args["tap_changer_type"] = "Ratio"
            index = calls[name](net, **args)
            audit.append({"api": name, "index": int(index), "arguments": args})
    if len(net.bus) > 500:
        raise ValueError("Network exceeds 500 bus limit")
    if program.load_scale != 1:
        net.load["scaling"] *= program.load_scale
    if program.contingency is not None:
        outage = program.contingency
        devices = net[outage.element]
        if outage.index not in devices.index or not devices.at[outage.index, "in_service"]:
            raise ValueError("Contingency requires an in-service line or transformer")
        open_switches = net.switch[net.switch.et.eq(outage.element[0]) & net.switch.element.eq(outage.index)
                                   & ~net.switch.closed]
        if not open_switches.empty:
            raise ValueError("Contingency requires a connected line or transformer")
        devices.at[outage.index, "in_service"] = False
        audit.append({"contingency": outage.model_dump(), "before": True, "after": False})
    pp.to_json(net, str(folder / "network.json"))
    tables = {"bus": ["vn_kv", "in_service"], "line": ["from_bus", "to_bus", "in_service", "max_i_ka"],
              "trafo": ["hv_bus", "lv_bus", "in_service"], "load": ["bus", "p_mw", "q_mvar", "scaling"],
              "gen": ["bus", "p_mw", "vm_pu"], "sgen": ["bus", "p_mw", "q_mvar"],
              "storage": ["bus", "p_mw", "max_e_mwh"], "ext_grid": ["bus", "vm_pu"],
              "switch": ["bus", "element", "et", "closed"]}
    for key in tables:
        net[key].to_csv(folder / (key + ".csv"))
    result = {"backend": "pandapower", "version": pp.__version__, "operation": program.analysis,
              "case": program.base, "status": "ok", "audit": audit,
              "counts": {key: len(net[key]) for key in tables}}
    if program.analysis == "inspect":
        result["elements"] = {key: rows(net[key], cols) for key, cols in tables.items()}
    elif program.analysis == "power_flow":
        pp.runpp(net, numba=False, max_iteration=30, check_connectivity=True)
        if not net.converged:
            raise ValueError("Power flow did not converge")
        net.res_bus.to_csv(folder / "res_bus.csv")
        net.res_line.to_csv(folder / "res_line.csv")
        net.res_trafo.to_csv(folder / "res_trafo.csv")
        for name in ("res_ext_grid", "res_gen", "res_load", "res_storage"):
            net[name].to_csv(folder / (name + ".csv"))
        voltage = net.res_bus.vm_pu.dropna()
        if voltage.empty or not np.isfinite(voltage).all():
            raise ValueError("No finite solved voltages")
        result["metrics"] = {"voltage_min_pu": float(voltage.min()),
                             "voltage_max_pu": float(voltage.max()),
                             "solved_buses": len(voltage), "unsolved_buses": len(net.bus)-len(voltage)}
        result["bus_results"] = rows(net.res_bus, ["vm_pu", "va_degree", "p_mw", "q_mvar"])
        loading = net.res_line.loading_percent.dropna()
        result["metrics"]["max_line_loading_percent"] = float(loading.max()) if len(loading) else None
        result["scope"] = "AC steady state; not transient stability"
    else:
        if program.fault_bus not in net.bus.index:
            raise ValueError("Unknown fault bus")
        shortcircuit.calc_sc(net, bus=program.fault_bus, fault="3ph", case="max")
        net.res_bus_sc.to_csv(folder / "res_bus_sc.csv")
        current = float(net.res_bus_sc.at[program.fault_bus, "ikss_ka"])
        if not np.isfinite(current):
            raise ValueError("No finite short-circuit result")
        result["metrics"] = {"fault_bus": program.fault_bus, "ikss_ka": current}
        result["scope"] = "IEC 60909 three-phase maximum initial symmetrical fault current"
    return result


def pypsa_run(program, folder):
    import pypsa

    n = pypsa.Network()
    n.set_snapshots(pd.date_range("2000-01-01", periods=program.hours, freq="h"))
    n.add("Carrier", "AC")
    for bus in program.buses:
        n.add("Bus", bus.name, carrier="AC", v_nom=bus.vn_kv)
    for load in program.loads:
        n.add("Load", load.name, bus=load.bus, p_set=load.p_set_mw)
    for gen in program.generators:
        n.add("Generator", gen.name, bus=gen.bus, p_nom=gen.p_nom_mw,
              p_max_pu=gen.p_max_pu if gen.p_max_pu is not None else 1,
              marginal_cost=gen.marginal_cost)
    for storage in program.storage:
        soc_options = {"cyclic_state_of_charge": storage.cyclic_soc}
        if storage.initial_soc_mwh is not None:
            soc_options["state_of_charge_initial"] = storage.initial_soc_mwh
        if storage.terminal_soc_mwh is not None:
            target = pd.Series(np.nan, index=n.snapshots)
            target.iloc[-1] = storage.terminal_soc_mwh
            soc_options["state_of_charge_set"] = target
        n.add("StorageUnit", storage.name, bus=storage.bus, p_nom=storage.p_nom_mw,
              max_hours=storage.max_hours, efficiency_store=storage.efficiency_store,
              efficiency_dispatch=storage.efficiency_dispatch, marginal_cost=storage.marginal_cost,
              **soc_options)
    for link in program.links:
        n.add("Link", link.name, bus0=link.bus0, bus1=link.bus1,
              p_nom=link.p_nom_mw, efficiency=link.efficiency, p_min_pu=0)
    for line in program.lines:
        n.add("Line", line.name, bus0=line.bus0, bus1=line.bus1, s_nom=line.s_nom_mva,
              x=line.x_ohm, r=line.r_ohm)
    status, condition = n.optimize(solver_name="highs", solver_options={"threads": 1, "time_limit": 120})
    result = {"backend": "pypsa", "version": pypsa.__version__, "operation": "dispatch",
              "case": "custom", "solver": "highs", "solver_status": str(status),
              "termination_condition": str(condition), "status": "failed"}
    if status != "ok" or condition != "optimal":
        return result
    for name, frame in (("generation_mw", n.generators_t.p), ("storage_mw", n.storage_units_t.p),
                        ("storage_soc_mwh", n.storage_units_t.state_of_charge),
                        ("link_mw", n.links_t.p0), ("marginal_price", n.buses_t.marginal_price)):
        frame.reindex(n.snapshots).to_csv(folder / (name + ".csv"))
    # Export independent per-component numerical evidence, including inputs as
    # materialized by the native backend, not values invented by the policy.
    n.loads_t.p.reindex(n.snapshots).to_csv(folder / "load_mw.csv")
    n.storage_units_t.p_store.reindex(n.snapshots).to_csv(folder / "storage_charge_mw.csv")
    n.storage_units_t.p_dispatch.reindex(n.snapshots).to_csv(folder / "storage_discharge_mw.csv")
    n.links_t.p1.reindex(n.snapshots).to_csv(folder / "link_destination_mw.csv")
    if program.lines:
        n.lines_t.p0.reindex(n.snapshots).to_csv(folder / "line_mw.csv")
        n.lines_t.p1.reindex(n.snapshots).to_csv(folder / "line_destination_mw.csv")
    n.export_to_csv_folder(folder / "network")
    result.update({"status": "ok", "metrics": {"objective": float(n.objective),
                   "hours": program.hours, "generation_mwh": float(n.generators_t.p.sum().sum()),
                   "storage_discharge_mwh": float(n.storage_units_t.p_dispatch.sum().sum()),
                   "storage_charge_mwh": float(n.storage_units_t.p_store.sum().sum())},
                   "scope": "Fixed-capacity hourly linear dispatch with explicit SOC boundaries; not AC or transient analysis"})
    return result


def main():
    folder = Path.cwd()
    program = ADAPTER.validate_json((folder / "request.json").read_bytes())
    try:
        result = pandapower_run(program, folder) if isinstance(program, PPProgram) else pypsa_run(program, folder)
        encoded = json.dumps(result, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 - solver boundary, failure is not a physical verdict
        result = {"backend": program.backend, "operation": getattr(program, "analysis", "dispatch"),
                  "status": "failed", "reason": type(exc).__name__,
                  "detail": str(exc)[:400]}
        encoded = json.dumps(result, allow_nan=False)
    (folder / "result.json").write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
