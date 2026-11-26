"""Numerically integrated, synthetic two-channel Q/V PI-control benchmark.

Independent second-order plants represent a generic reactive/voltage control
loop. This is not a network, WECC model, LVRT compliance test or DMView result.
All plant constants, inputs, thresholds and solver settings are fixed.
"""
from pathlib import Path

import numpy as np

TEST_NAMES = ("flat_start", "q_step_up", "q_step_down", "v_step_up",
              "v_step_down", "combined_step", "voltage_dip", "weak_grid_step")


def run_suite(gains: dict, output: Path | None):
    kp = np.array([gains["kqp"], gains["kvp"]])
    ki = np.array([gains["kqi"], gains["kvi"]])
    omega = 2.0
    zeta = np.array([0.4] * 7 + [0.3])[:, None]
    plant = np.array([1.0] * 7 + [0.75])[:, None]
    dt = 0.02
    times = np.arange(1001) * dt
    targets = np.array([[0, 0], [0.1, 0], [-0.1, 0], [0, 0.1],
                        [0, -0.1], [0.08, -0.08], [0, 0], [0.1, 0.1]])
    state = np.zeros((8, 2, 3))
    state[0, :, 0] = 0.02

    def reference(t):
        return targets if t >= 1 else np.zeros_like(targets)

    def derivative(s, t):
        y, speed, integral = (s[:, :, i] for i in range(3))
        error = reference(t) - y
        control = kp * error + ki * integral
        disturbance = np.zeros_like(y)
        if 1 <= t < 1.2:
            disturbance[6, 1] = -0.25
        acceleration = omega**2 * (plant * control + disturbance - y) - 2 * zeta * omega * speed
        return np.stack((speed, acceleration, error), axis=-1)

    values = np.empty((len(times), 8, 2))
    values[0] = state[:, :, 0]
    # Classical RK4; frozen step, parameters and scenarios for reproducibility.
    for i, t in enumerate(times[:-1]):
        a = derivative(state, t)
        b = derivative(state + dt * a / 2, t + dt / 2)
        c = derivative(state + dt * b / 2, t + dt / 2)
        d = derivative(state + dt * c, t + dt)
        state += dt * (a + 2 * b + 2 * c + d) / 6
        values[i + 1] = state[:, :, 0]

    if output is not None:
        output.mkdir(parents=True, exist_ok=False)
    results = []
    for i, name in enumerate(TEST_NAMES):
        y = values[:, i, :]
        if not np.isfinite(y).all():
            results.append({"name": name, "passed": False, "reason": "Nonfinite integration"})
            continue
        error = y - targets[i]
        tail_error = float(np.max(np.abs(error[-100:])))
        peak = float(np.max(np.abs(y)))
        # Thresholds are synthetic benchmark criteria, not a grid code.
        passed = tail_error <= 0.025 and peak <= 0.3
        record = {"name": name, "passed": bool(passed), "tail_error_pu": tail_error,
                  "peak_deviation_pu": peak}
        if output is not None:
            np.savetxt(output / f"{name}.csv", np.column_stack((times, y)), delimiter=",",
                       header="time_s,q_deviation_pu,v_deviation_pu", comments="")
            record["waveform"] = f"{output.name}/{name}.csv"
        results.append(record)
    return results
