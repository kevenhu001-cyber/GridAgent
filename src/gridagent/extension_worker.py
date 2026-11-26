"""Native extension APIs in a separate process; never executes supplied source."""
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .extension_program import Battery, ControlResponse, Feeder, Solar


def feeder(params, folder):
    import opendssdirect as dss

    p = Feeder.model_validate(params)
    dss.Basic.ClearAll()
    commands = [
        f"new circuit.gridagent basekv={p.kv} pu=1 phases=3 bus1=source mvasc3={p.source_mvasc}",
        (f"new line.feeder bus1=source bus2=loadbus phases=3 length={p.length_km} units=km "
         f"r1={p.r_ohm_km} x1={p.x_ohm_km} r0={p.r_ohm_km} x0={p.x_ohm_km} c1=0 c0=0"),
        f"new load.demand bus1=loadbus phases=3 conn=wye kv={p.kv} kw={p.load_kw} kvar={p.load_kvar} model=1",
        f"set voltagebases=[{p.kv}]", "calcvoltagebases", "solve",
    ]
    for command in commands:
        dss.Text.Command(command)
    if not dss.Solution.Converged():
        raise ValueError("OpenDSS did not converge")
    names = dss.Circuit.AllNodeNames()
    volts = np.asarray(dss.Circuit.AllBusMagPu(), dtype=float)
    if len(volts) != len(names) or not len(volts) or not np.isfinite(volts).all():
        raise ValueError("Incomplete voltage evidence")
    pd.DataFrame({"node": names, "voltage_pu": volts}).to_csv(folder / "node_voltage.csv", index=False)
    return {"version": str(dss.Basic.Version()), "metrics": {
        "voltage_min_pu": float(volts.min()), "voltage_max_pu": float(volts.max()), "nodes": len(names)},
        "scope": "Balanced three-phase feeder snapshot; not independent engineering certification"}


def battery(params, folder):
    import pybamm

    p = Battery.model_validate(params)
    model = pybamm.lithium_ion.SPM() if p.model == "SPM" else pybamm.lithium_ion.DFN()
    parameters = pybamm.ParameterValues("Chen2020")
    parameters.update({"Current function [A]": p.current_a})
    solution = pybamm.Simulation(model, parameter_values=parameters).solve(
        [0, p.duration_s], initial_soc=p.initial_soc)
    t = np.asarray(solution.t, dtype=float).reshape(-1)
    v = np.asarray(solution["Voltage [V]"].entries, dtype=float).reshape(-1)
    if len(t) < 2 or len(t) != len(v) or not np.isfinite(t).all() or not np.isfinite(v).all():
        raise ValueError("Incomplete battery evidence")
    pd.DataFrame({"time_s": t, "voltage_v": v}).to_csv(folder / "battery_voltage.csv", index=False)
    return {"version": pybamm.__version__, "metrics": {"duration_s": float(t[-1]),
        "initial_voltage_v": float(v[0]), "final_voltage_v": float(v[-1]),
        "capacity_ah": float(p.current_a * (t[-1]-t[0])/3600), "termination": str(solution.termination)},
        "scope": "Chen2020 reference-cell simulation; not a calibrated battery or lifetime prediction"}


def solar(params, folder):
    import pvlib

    p = Solar.model_validate(params)
    watts = float(pvlib.pvsystem.pvwatts_dc(p.effective_irradiance_w_m2, p.cell_temperature_c,
                                           p.rated_dc_w, p.gamma_pdc_per_c))
    if not np.isfinite(watts) or watts < 0:
        raise ValueError("Invalid PVWatts DC result")
    pd.DataFrame([{**p.model_dump(), "dc_power_w": watts}]).to_csv(folder / "solar_power.csv", index=False)
    return {"version": pvlib.__version__, "metrics": {"dc_power_w": watts},
            "scope": "PVWatts DC snapshot with user-supplied effective irradiance and cell temperature"}


def control_response(params, folder):
    import control

    p = ControlResponse.model_validate(params)
    system = control.tf(p.numerator, p.denominator)
    poles = control.poles(system)
    t, y = control.step_response(system, np.linspace(0, p.duration_s, p.samples))
    t, y = np.asarray(t), np.asarray(y).reshape(-1)
    if len(t) != len(y) or not np.isfinite(y).all() or not np.isfinite(poles).all():
        raise ValueError("Non-finite response or poles")
    pd.DataFrame({"time_s": t, "response": y}).to_csv(folder / "control_step.csv", index=False)
    return {"version": control.__version__, "metrics": {
        "poles": [{"real": float(z.real), "imag": float(z.imag)} for z in poles],
        "all_poles_left_half_plane": bool(np.all(poles.real < 0)),
        "final_sample": float(y[-1]), "peak_absolute_response": float(np.max(np.abs(y)))},
        "scope": "Continuous SISO transfer function unit step; not a complete internal stability certificate"}


def main():
    folder = Path.cwd()
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    backend = request["backend"]
    try:
        handler = {"opendss": feeder, "pybamm": battery, "pvlib": solar, "control": control_response}[backend]
        result = {"backend": backend, "status": "ok", **handler(request["parameters"], folder)}
        encoded = json.dumps(result, allow_nan=False)
    except Exception as exc:  # noqa: BLE001 - native solver boundary
        encoded = json.dumps({"backend": backend, "status": "failed", "reason": type(exc).__name__})
    (folder / "result.json").write_text(encoded, encoding="utf-8")


if __name__ == "__main__":
    main()
