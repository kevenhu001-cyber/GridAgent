"""Plot-ready numerical series derived from verified local artifacts."""
from pathlib import Path

import numpy as np
import pandas as pd

from .extension_program import ControlResponse
from .workspace import artifact_folder, load_object


def series(name, x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if not valid.any():
        raise ValueError("No finite plot samples")
    return {"name": name, "x": x[valid].tolist(), "y": y[valid].tolist()}


def plot(title, x_label, y_label, traces, *, scatter=False):
    return {"title": title, "x_label": x_label, "y_label": y_label, "scatter": scatter, "series": traces}


def chart_data(root, run_id):
    folder = artifact_folder(Path(root), "runs", run_id)
    result = load_object(folder / "result.json")
    if result.get("status") != "ok":
        raise ValueError("Select a successful numerical run")
    if result["operation"] in {"eigen", "governor_eigen"}:
        modes = pd.read_csv(folder / "eigenvalues.csv")
        return [plot("Eigenvalue distribution", "Real part (1/s)", "Imaginary part (rad/s)",
                     [series("Eigenvalues", modes.real_per_s, modes.imag_rad_s)], scatter=True)]
    if result["backend"] == "ngspice":
        raw = pd.read_csv(folder / "rc_response.csv")
        if result["operation"] == "transient":
            return [plot("RC transient", "Time (s)", "Voltage (V)", [series("RC output", raw.time_s, raw.voltage_v)])]
        x = np.log10(raw.frequency_hz)
        return bode(x, 20*np.log10(np.maximum(raw.gain, 1e-12)), raw.phase_deg, "log₁₀(f / Hz)")
    if result["backend"] == "control":
        request = load_object(folder / "request.json")
        model = ControlResponse.model_validate(request["parameters"])
        poles = np.abs(np.roots(model.denominator))
        poles = poles[poles > 1e-12]
        lower = max(1e-8, float(poles.min())/100) if len(poles) else 0.01
        upper = max(lower*1e4, float(poles.max())*100) if len(poles) else 100
        x = np.linspace(np.log10(lower), np.log10(upper), 240)
        omega = 10**x
        z = 1j*omega
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            response = np.polyval(model.numerator, z) / np.polyval(model.denominator, z)
        charts = bode(x, 20*np.log10(np.maximum(np.abs(response), 1e-12)), np.rad2deg(np.angle(response)),
                      "log₁₀(ω / rad·s⁻¹)")
        roots = np.concatenate([np.roots(np.polyadd(model.denominator, gain*np.array(model.numerator)))
                                for gain in np.r_[0, np.logspace(-3, 3, 120)]])
        charts.append(plot("Root locus · K=0 and 0.001–1000", "Real part (1/s)", "Imaginary part (rad/s)",
                           [series("Closed-loop poles", roots.real, roots.imag)], scatter=True))
        return charts
    raise ValueError("Select an eigenvalue, control or ngspice run")


def bode(x, gain_db, phase_deg, unit):
    return [plot("Bode magnitude", unit, "Gain (dB)", [series("Magnitude", x, gain_db)]),
            plot("Bode phase", unit, "Phase (°)", [series("Phase", x, phase_deg)])]
