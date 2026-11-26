"""Test real optional package installation from the packaged private interpreter."""
import importlib.util
import os
import tempfile
from pathlib import Path

from gridagent.extension_runner import run_extension
from gridagent.native_backends import run_program
from gridagent.plugins import available, guidance, install, plugin_root, uninstall


def main():
    with tempfile.TemporaryDirectory(prefix="GridAgent plugin smoke ") as tmp:
        root = Path(tmp)
        os.environ["GRIDAGENT_PLUGIN_ROOT"] = str(root / "plugins")
        assert importlib.util.find_spec("pypsa") is None
        assert not available("pypsa")
        for key, run in (
            ("pypsa", lambda: run_program(root, {"backend": "pypsa", "hours": 2,
                "buses": [{"name": "b"}], "loads": [{"name": "load", "bus": "b", "p_set_mw": [1, 2]}],
                "generators": [{"name": "gen", "bus": "b", "p_nom_mw": 3, "marginal_cost": 20}]})),
            ("opendss", lambda: run_extension(root, "opendss", {"kv": 11, "length_km": 1,
                "r_ohm_km": 0.1, "x_ohm_km": 0.2, "load_kw": 100, "load_kvar": 25})),
            ("pybamm", lambda: run_extension(root, "pybamm", {"current_a": 1, "duration_s": 60, "initial_soc": 0.9})),
            ("pvlib", lambda: run_extension(root, "pvlib", {"effective_irradiance_w_m2": 1000,
                "cell_temperature_c": 25, "rated_dc_w": 500, "gamma_pdc_per_c": -0.004})),
            ("windpowerlib", lambda: run_extension(root, "windpowerlib", {"wind_speed_m_s": [5],
                "curve_speed_m_s": [0, 10], "curve_power_w": [0, 1000]})),
            ("cvxpy", lambda: run_extension(root, "cvxpy", {"demand_mw": 10,
                "units": [{"maximum_mw": 20, "linear_cost_per_mwh": 1, "quadratic_cost": 1}]})),
            ("pyomo", lambda: run_extension(root, "pyomo", {"demand_mw": [5, 0],
                "units": [{"maximum_mw": 10, "linear_cost_per_mwh": 2, "startup_cost": 3}]})),
            ("casadi", lambda: run_extension(root, "casadi", {"ocv_v": 4, "ohmic_resistance_ohm": 0.1,
                "polarization_resistance_ohm": 0.2, "polarization_capacitance_f": 10,
                "current_a": 1, "duration_s": 2})),
        ):
            assert not available(key), key
            print(key, install(key), flush=True)
            assert available(key)
            result = run()
            assert result["status"] == "ok", result
            if key == "pypsa":
                assert result["quality"]["passed"], result
            if key == "windpowerlib":
                assert abs(result["metrics"]["power_w"][0] - 500) < 1e-6
            if key == "cvxpy":
                assert abs(result["metrics"]["objective_per_hour"] - 110) < 1e-4
            if key == "pyomo":
                assert abs(result["metrics"]["objective"] - 13) < 1e-6
            if key == "casadi":
                assert abs(result["metrics"]["final_voltage_v"] - (3.7+0.2*__import__("math").exp(-1))) < 1e-6
            size = sum(p.stat().st_size for p in (plugin_root() / key).rglob("*") if p.is_file())
            print(key, "installed bytes:", size, flush=True)
            uninstall(key)
            assert not available(key)
        assert not guidance()
        assert importlib.util.find_spec("pypsa") is None


if __name__ == "__main__":
    main()
