"""Fixed native solver adapters for wind, dispatch, commitment and RC dynamics."""
import numpy as np
import pandas as pd

from .extra_programs import Commitment, EconomicDispatch, EquivalentCell, Wind


def wind(params, folder):
    import windpowerlib
    from windpowerlib.power_output import power_curve

    p = Wind.model_validate(params)
    watts = np.asarray(power_curve(np.asarray(p.wind_speed_m_s), np.asarray(p.curve_speed_m_s),
                                   np.asarray(p.curve_power_w)), dtype=float)
    if not np.isfinite(watts).all() or np.any(watts < 0):
        raise ValueError("Invalid wind power")
    pd.DataFrame({"wind_speed_m_s": p.wind_speed_m_s, "power_w": watts}).to_csv(
        folder / "wind_power.csv", index=False)
    return {"version": windpowerlib.__version__, "metrics": {"power_w": watts.tolist()},
            "scope": "User-supplied turbine power curve; outside curve returns zero, no wake/weather model"}


def dispatch(params, folder):
    import cvxpy as cp

    p = EconomicDispatch.model_validate(params)
    lower = np.array([u.minimum_mw for u in p.units])
    upper = np.array([u.maximum_mw for u in p.units])
    linear = np.array([u.linear_cost_per_mwh for u in p.units])
    quadratic = np.array([u.quadratic_cost for u in p.units])
    x = cp.Variable(len(p.units))
    objective = cp.sum(cp.multiply(quadratic, cp.square(x))) + linear @ x
    problem = cp.Problem(cp.Minimize(objective), [x >= lower, x <= upper, cp.sum(x) == p.demand_mw])
    problem.solve(solver=cp.CLARABEL)
    if problem.status != cp.OPTIMAL or x.value is None:
        raise ValueError("Dispatch did not reach optimal status")
    values = np.asarray(x.value)
    tol = 1e-5 + 1e-7 * max(1, p.demand_mw)
    residual = abs(float(values.sum()) - p.demand_mw)
    if (not np.isfinite(values).all() or residual > tol
            or np.any(values < lower-tol) or np.any(values > upper+tol)):
        raise ValueError("Dispatch constraints violated")
    pd.DataFrame({"unit": range(len(values)), "generation_mw": values}).to_csv(
        folder / "economic_dispatch.csv", index=False)
    return {"version": cp.__version__, "metrics": {"objective_per_hour": float(problem.value),
            "generation_mw": values.tolist(), "balance_error_mw": residual},
            "scope": "Single-period convex quadratic economic dispatch, no AC network or commitment"}


def commitment(params, folder):
    import pyomo
    import pyomo.environ as pe
    from pyomo.contrib.appsi.base import TerminationCondition
    from pyomo.contrib.appsi.solvers import Highs

    p = Commitment.model_validate(params)
    m = pe.ConcreteModel()
    m.g = pe.RangeSet(0, len(p.units)-1)
    m.t = pe.RangeSet(0, len(p.demand_mw)-1)
    m.power = pe.Var(m.g, m.t, domain=pe.NonNegativeReals)
    m.on = pe.Var(m.g, m.t, domain=pe.Binary)
    m.start = pe.Var(m.g, m.t, domain=pe.Binary)
    m.low = pe.Constraint(m.g, m.t, rule=lambda m,g,t: m.power[g,t] >= p.units[g].minimum_mw*m.on[g,t])
    m.high = pe.Constraint(m.g, m.t, rule=lambda m,g,t: m.power[g,t] <= p.units[g].maximum_mw*m.on[g,t])
    m.balance = pe.Constraint(m.t, rule=lambda m,t: sum(m.power[g,t] for g in m.g) == p.demand_mw[t])
    m.starts = pe.Constraint(m.g, m.t, rule=lambda m,g,t: m.start[g,t] >= m.on[g,t]-(m.on[g,t-1] if t else 0))
    m.start_upper = pe.Constraint(m.g, m.t, rule=lambda m,g,t: m.start[g,t] <= m.on[g,t])
    m.start_prev = pe.Constraint(m.g, m.t, rule=lambda m,g,t: m.start[g,t] <= 1-(m.on[g,t-1] if t else 0))
    m.obj = pe.Objective(expr=sum(p.units[g].linear_cost_per_mwh*m.power[g,t]
        + p.units[g].online_cost_per_hour*m.on[g,t] + p.units[g].startup_cost*m.start[g,t]
        for g in m.g for t in m.t))
    opt = Highs()
    opt.config.time_limit = 90
    opt.config.load_solution = False
    opt.highs_options["threads"] = 1
    result = opt.solve(m)
    if result.termination_condition != TerminationCondition.optimal:
        raise ValueError("Commitment did not reach optimal status")
    opt.load_vars()
    rows = [{"hour": t, "unit": g, "generation_mw": pe.value(m.power[g,t]),
             "online": round(pe.value(m.on[g,t])), "start": round(pe.value(m.start[g,t]))}
            for t in m.t for g in m.g]
    frame = pd.DataFrame(rows)
    residual = float(np.max(np.abs(frame.groupby("hour").generation_mw.sum().to_numpy()-p.demand_mw)))
    if residual > 1e-5 + 1e-7*max(p.demand_mw) or not np.isfinite(frame.to_numpy()).all():
        raise ValueError("Commitment balance violated")
    frame.to_csv(folder / "commitment.csv", index=False)
    return {"version": pyomo.__version__, "metrics": {"objective": float(pe.value(m.obj)),
            "balance_error_mw": residual, "starts": int(frame.start.sum())},
            "scope": "Hourly single-bus MILP, all units initially off; no ramp, minimum up/down time or reserve"}


def equivalent_cell(params, folder):
    import casadi as ca

    p = EquivalentCell.model_validate(params)
    x = ca.SX.sym("polarization")
    ode = (p.current_a - x/p.polarization_resistance_ohm)/p.polarization_capacitance_f
    times = np.linspace(0, p.duration_s, p.samples)
    integrate = ca.integrator("cell_rc", "cvodes", {"x": x, "ode": ode}, 0, times[1:].tolist(),
                              {"abstol": 1e-10, "reltol": 1e-8})
    polarization = np.r_[0, np.asarray(integrate(x0=0)["xf"]).reshape(-1)]
    terminal = p.ocv_v - p.current_a*p.ohmic_resistance_ohm - polarization
    if len(terminal) != len(times) or not np.isfinite(terminal).all():
        raise ValueError("Invalid RC trajectory")
    pd.DataFrame({"time_s": times, "terminal_v": terminal, "polarization_v": polarization}).to_csv(
        folder / "equivalent_cell.csv", index=False)
    return {"version": ca.__version__, "metrics": {"initial_voltage_v": float(terminal[0]),
            "final_voltage_v": float(terminal[-1])},
            "scope": "Constant OCV and current, first-order Thevenin RC, zero initial polarization; no SOC/thermal/cutoff model"}
