"""Deterministic post-solver checks, independent of the proposing LLM.

These are local engineering quality gates, NOT the original PowerAgentBench.
A successful solver is necessary but never sufficient for benchmark acceptance.
"""
import math

import numpy as np
import pandas as pd

PROTOCOL = "gridagent-native-quality-v1"


def check(name, passed, observed=None, criterion=None):
    return {"id": name, "passed": bool(passed), "observed": observed, "criterion": criterion}


def finite(frame):
    return bool(np.isfinite(frame.to_numpy(dtype=float)).all())


def table(folder, name):
    return pd.read_csv(folder / (name + ".csv"), index_col=0)


def pp_checks(folder, request):
    bus = table(folder, "bus")
    active = bus.index[bus.in_service.eq(True)]
    if request["analysis"] == "inspect":
        return [check("nonempty_network", len(active)>0, len(active), "At least one in-service bus")]
    if request["analysis"] == "short_circuit":
        data = table(folder, "res_bus_sc")
        current = float(data.at[request["fault_bus"], "ikss_ka"])
        return [check("finite_positive_fault_current", math.isfinite(current) and current>0,
                      current if math.isfinite(current) else None, "ikss > 0 kA")]
    solved = table(folder, "res_bus").reindex(active)
    valid = len(active)>0 and finite(solved[["vm_pu", "va_degree", "p_mw", "q_mvar"]])
    result = [check("active_bus_coverage", valid, int(solved.vm_pu.notna().sum()), f"{len(active)} active buses"),
              check("positive_voltage", valid and bool((solved.vm_pu > 0).all()),
                    None, "Every active bus has positive finite voltage")]
    # These are operating limits, not a test of whether the mathematical model is faithful.
    result.append(check("voltage_operating_range", valid and bool(solved.vm_pu.between(0.9, 1.1).all()),
                        [float(solved.vm_pu.min()), float(solved.vm_pu.max())] if valid else None,
                        "Default screening range 0.90..1.10 p.u."))
    for name in ("res_line", "res_trafo"):
        data = table(folder, name)
        if not len(data):
            continue
        # Out-of-service equipment can legitimately have missing results.
        devices = table(folder, name.removeprefix("res_"))
        loading = data.reindex(devices.index[devices.in_service.eq(True)]).loading_percent
        good = bool(np.isfinite(loading.to_numpy(dtype=float)).all())
        maximum = float(loading.max()) if len(loading) and good else None
        result.append(check(name + "_loading", good and (maximum is None or maximum<=100+1e-6),
                            maximum, "In-service equipment loading <= 100%"))
    return result


def dispatch_checks(folder, request, result_record=None):
    hours = request["hours"]
    frames = {name: table(folder, name) for name in
              ("generation_mw", "load_mw", "storage_soc_mwh", "storage_charge_mw",
               "storage_discharge_mw", "link_mw", "link_destination_mw")}
    if request.get("lines"):
        frames.update({name: table(folder, name) for name in ("line_mw", "line_destination_mw")})
    aligned = all(len(f)==hours and finite(f) and f.index.equals(frames["generation_mw"].index)
                  for f in frames.values())
    result = [check("complete_hourly_results", aligned, hours, "Finite aligned hourly results")]
    if not aligned:
        return result
    residual = {b["name"]: np.zeros(hours) for b in request["buses"]}
    violation = 0.0
    demand_error = 0.0
    operating_cost = 0.0
    for item in request["loads"]:
        values = frames["load_mw"][item["name"]].to_numpy()
        demand_error = max(demand_error, float(np.max(np.abs(values-item["p_set_mw"]))))
        residual[item["bus"]] -= values
    for item in request["generators"]:
        values = frames["generation_mw"][item["name"]].to_numpy()
        ceiling = item["p_nom_mw"] * np.asarray(item["p_max_pu"] if item["p_max_pu"] is not None else 1)
        violation = max(violation, float(np.max(values-ceiling)), float(np.max(-values)))
        residual[item["bus"]] += values
        operating_cost += float(np.sum(values * np.asarray(item["marginal_cost"])))
    soc_error = 0.0
    terminal_error = 0.0
    for item in request["storage"]:
        name = item["name"]
        charge = frames["storage_charge_mw"][name].to_numpy()
        discharge = frames["storage_discharge_mw"][name].to_numpy()
        soc = frames["storage_soc_mwh"][name].to_numpy(dtype=float)
        violation = max(violation, float(np.max(charge-item["p_nom_mw"])),
                        float(np.max(discharge-item["p_nom_mw"])), float(np.max(-charge)),
                        float(np.max(-discharge)), float(np.max(-soc)),
                        float(np.max(soc-item["p_nom_mw"]*item["max_hours"])))
        predecessor = np.roll(soc, 1)
        if not item.get("cyclic_soc", True):
            predecessor[0] = item["initial_soc_mwh"]
        mismatch = soc-predecessor-charge*item["efficiency_store"]+discharge/item["efficiency_dispatch"]
        soc_error = max(soc_error, float(np.max(np.abs(mismatch))))
        if item.get("terminal_soc_mwh") is not None:
            terminal_error = max(terminal_error, abs(float(soc[-1])-item["terminal_soc_mwh"]))
        residual[item["bus"]] += discharge-charge
        operating_cost += float(np.sum(discharge)) * item["marginal_cost"]
    for item in request["links"]:
        p0 = frames["link_mw"][item["name"]].to_numpy()
        p1 = frames["link_destination_mw"][item["name"]].to_numpy()
        residual[item["bus0"]] -= p0
        residual[item["bus1"]] -= p1
        violation = max(violation, float(np.max(-p0)), float(np.max(p0-item["p_nom_mw"])),
                        float(np.max(np.abs(p1+p0*item["efficiency"]))))
    for item in request.get("lines", []):
        p0 = frames["line_mw"][item["name"]].to_numpy()
        p1 = frames["line_destination_mw"][item["name"]].to_numpy()
        residual[item["bus0"]] -= p0
        residual[item["bus1"]] -= p1
        violation = max(violation, float(np.max(np.abs(p0)-item["s_nom_mva"])), float(np.max(np.abs(p0+p1))))
    balance = max(float(np.max(np.abs(v))) for v in residual.values())
    scale = max(1.0, sum(max(x["p_set_mw"]) for x in request["loads"]),
                sum(x["p_nom_mw"] for x in request["generators"]))
    tol = 1e-6 + 1e-8*scale
    cyclic = all(item.get("cyclic_soc", True) for item in request["storage"])
    balance_check = "cyclic_storage_balance" if cyclic else "storage_energy_balance"
    checks = [*result, check("demand_preserved", demand_error<=tol, demand_error, f"<= {tol} MW"),
              check("nodal_power_balance", balance<=tol, balance, f"<= {tol} MW"),
              check("component_limits", violation<=tol, violation, f"<= {tol}"),
              check(balance_check, soc_error<=tol, soc_error, f"<= {tol} MWh")]
    if not cyclic:
        checks.append(check("terminal_soc", terminal_error<=tol, terminal_error, f"<= {tol} MWh"))
    if result_record is not None:
        reported = result_record.get("metrics", {}).get("objective")
        valid = isinstance(reported, (int, float)) and not isinstance(reported, bool) and math.isfinite(reported)
        cost_error = abs(operating_cost-reported) if valid else None
        cost_tol = 1e-5 + 1e-7*max(1.0, abs(operating_cost))
        checks.append(check("operating_cost_reconciliation", valid and cost_error<=cost_tol,
                            cost_error, f"<= {cost_tol} currency units"))
    return checks


def evaluate_run(folder, request, result):
    tests = [check("solver_success", result.get("status")=="ok", result.get("status"), "Successful native solver")]
    if tests[0]["passed"]:
        try:
            tests.extend(pp_checks(folder, request) if request["backend"]=="pandapower"
                         else dispatch_checks(folder, request, result))
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            tests.append(check("evidence_integrity", False, type(exc).__name__, "Complete readable solver evidence"))
    return {"protocol": PROTOCOL, "passed": all(t["passed"] for t in tests),
            "passed_count": sum(t["passed"] for t in tests), "test_count": len(tests), "tests": tests,
            "scope": "local model/operating checks; not original paper benchmark or engineering certification"}
