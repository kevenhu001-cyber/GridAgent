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
        ):
            assert not available(key), key
            print(key, install(key), flush=True)
            assert available(key)
            result = run()
            assert result["status"] == "ok", result
            if key == "pypsa":
                assert result["quality"]["passed"], result
            size = sum(p.stat().st_size for p in (plugin_root() / key).rglob("*") if p.is_file())
            print(key, "installed bytes:", size, flush=True)
            uninstall(key)
            assert not available(key)
        assert not guidance()
        assert importlib.util.find_spec("pypsa") is None


if __name__ == "__main__":
    main()
