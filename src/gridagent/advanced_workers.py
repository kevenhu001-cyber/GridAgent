"""Native independent backends for benchmark cases and bounded physical tasks."""
from importlib.metadata import version

import numpy as np
import pandas as pd

from .advanced_programs import (
    FluidState,
    PowerFlowCase,
    PowSyBlCase,
    RainflowSeries,
    TrackingQP,
    TransmissionLine,
)


def pypower_flow(params, folder):
    from pypower.api import case14, case30, case118, ppoption, runpf
    from pypower.idx_bus import BUS_I, VA, VM

    p = PowerFlowCase.model_validate(params)
    case = {"ieee14": case14, "ieee30": case30, "ieee118": case118}[p.case]()
    result, success = runpf(case, ppoption(VERBOSE=0, OUT_ALL=0))
    if not success:
        raise ValueError("PYPOWER did not converge")
    bus = result["bus"]
    if not np.isfinite(bus[:, [VM, VA]]).all():
        raise ValueError("Incomplete bus voltages")
    pd.DataFrame({"bus": bus[:, BUS_I].astype(int), "voltage_pu": bus[:, VM],
                  "angle_deg": bus[:, VA]}).to_csv(folder / "pypower_bus.csv", index=False)
    return {"version": version("PYPOWER"), "metrics": {"bus_count": len(bus),
        "voltage_min_pu": float(bus[:, VM].min()), "voltage_max_pu": float(bus[:, VM].max())},
        "scope": "Native packaged IEEE test case AC power flow; not an imported user network"}


def powsybl_flow(params, folder):
    import pypowsybl as pp

    PowSyBlCase.model_validate(params)
    network = pp.network.create_ieee14()
    components = pp.loadflow.run_ac(network)
    if not components or any(row.status.name != "CONVERGED" for row in components):
        raise ValueError("PowSyBl did not converge")
    buses = network.get_buses()
    data = buses[["v_mag", "v_angle"]]
    if data.empty or not np.isfinite(data.to_numpy(dtype=float)).all():
        raise ValueError("Incomplete PowSyBl bus voltages")
    data.rename(columns={"v_mag": "voltage_kv", "v_angle": "angle_deg"}).to_csv(folder / "powsybl_bus.csv")
    return {"version": version("pypowsybl"), "metrics": {"bus_count": len(data),
        "voltage_min_kv": float(data.v_mag.min()), "voltage_max_kv": float(data.v_mag.max())},
        "scope": "PowSyBl packaged IEEE14 AC load flow; voltages are kV, not per unit"}


def tracking(params, folder):
    import osqp
    from scipy import sparse

    p = TrackingQP.model_validate(params)
    target = np.asarray(p.target_mw)
    n = len(target)
    identity = sparse.eye(n, format="csc")
    difference = sparse.diags([-np.ones(n-1), np.ones(n-1)], [0, 1], shape=(n-1, n), format="csc") if n > 1 else sparse.csc_matrix((0, n))
    matrix = sparse.vstack([identity, difference], format="csc")
    solver = osqp.OSQP()
    solver.setup(P=identity, q=-target, A=matrix,
                 l=np.r_[np.full(n, p.lower_mw), np.full(n-1, -p.ramp_mw_per_hour)],
                 u=np.r_[np.full(n, p.upper_mw), np.full(n-1, p.ramp_mw_per_hour)],
                 verbose=False, eps_abs=1e-8, eps_rel=1e-8, max_iter=20000)
    solution = solver.solve()
    if solution.info.status.lower() != "solved" or solution.x is None:
        raise ValueError("OSQP did not solve")
    x = np.asarray(solution.x)
    tol = 1e-5 + 1e-7*max(1, abs(p.lower_mw), abs(p.upper_mw))
    if (not np.isfinite(x).all() or np.any(x < p.lower_mw-tol)
            or np.any(x > p.upper_mw+tol) or np.any(np.abs(np.diff(x)) > p.ramp_mw_per_hour+tol)):
        raise ValueError("Tracking constraints violated")
    pd.DataFrame({"hour": range(n), "target_mw": target, "setpoint_mw": x}).to_csv(
        folder / "tracking_qp.csv", index=False)
    return {"version": version("osqp"), "metrics": {"setpoint_mw": x.tolist(),
        "squared_tracking_error": float(np.sum((x-target)**2))},
        "scope": "Bounded ramp-limited least-squares setpoint tracking; no storage SOC or power balance model"}


def transmission_line(params, folder):
    import skrf
    from skrf.media import DefinedGammaZ0

    p = TransmissionLine.model_validate(params)
    frequency = skrf.Frequency.from_f([p.frequency_hz], unit="hz")
    gamma = complex(p.attenuation_np_per_m, 2*np.pi*p.frequency_hz/p.velocity_m_s)
    medium = DefinedGammaZ0(frequency=frequency, z0=p.characteristic_ohm, gamma=gamma,
                            z0_port=p.port_ohm)
    network = medium.line(p.length_m, unit="m")
    s = network.s[0]
    if not np.isfinite(s).all():
        raise ValueError("Invalid scattering matrix")
    pd.DataFrame([{"frequency_hz": p.frequency_hz, "s11_real": s[0,0].real, "s11_imag": s[0,0].imag,
        "s21_real": s[1,0].real, "s21_imag": s[1,0].imag}]).to_csv(folder / "scattering.csv", index=False)
    return {"version": version("scikit-rf"), "metrics": {"s11_magnitude": float(abs(s[0,0])),
        "s21_magnitude": float(abs(s[1,0])), "s21_phase_rad": float(np.angle(s[1,0]))},
        "scope": "Linear uniform transmission line at one frequency, supplied propagation and impedance"}


def fluid_state(params, folder):
    from CoolProp.CoolProp import PhaseSI, PropsSI

    p = FluidState.model_validate(params)
    metrics = {key: float(PropsSI(prop, "T", p.temperature_k, "P", p.pressure_pa, p.fluid))
               for key, prop in (("density_kg_m3", "Dmass"), ("enthalpy_j_kg", "Hmass"),
                                 ("cp_j_kg_k", "Cpmass"), ("conductivity_w_m_k", "conductivity"))}
    if not all(np.isfinite(list(metrics.values()))) or metrics["density_kg_m3"] <= 0:
        raise ValueError("Invalid thermophysical state")
    metrics["phase"] = PhaseSI("T", p.temperature_k, "P", p.pressure_pa, p.fluid)
    pd.DataFrame([{**p.model_dump(), **metrics}]).to_csv(folder / "fluid_state.csv", index=False)
    return {"version": version("CoolProp"), "metrics": metrics,
            "scope": "Equilibrium pure-fluid/air properties, not heat-transfer simulation"}


def rainflow_cycles(params, folder):
    import rainflow

    p = RainflowSeries.model_validate(params)
    rows = [{"range": float(r), "mean": float(m), "count": float(c), "start_index": i, "end_index": j}
            for r, m, c, i, j in rainflow.extract_cycles(p.samples)]
    frame = pd.DataFrame(rows, columns=["range", "mean", "count", "start_index", "end_index"])
    frame.to_csv(folder / "rainflow_cycles.csv", index=False)
    return {"version": version("rainflow"), "metrics": {"equivalent_full_cycle_count": float(frame["count"].sum()),
        "maximum_range": float(frame["range"].max()) if len(frame) else 0.0},
        "scope": "Rainflow range/mean/half-cycle counting; not battery degradation or fatigue-life prediction"}
