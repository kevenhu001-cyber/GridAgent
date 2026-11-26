import pytest
from pydantic import ValidationError

from gridagent.extension_program import Battery, Feeder


def test_extension_requests_are_typed():
    with pytest.raises(ValidationError):
        Battery(current_a=1, duration_s=60, initial_soc=1, source="import os")
    with pytest.raises(ValidationError):
        Feeder(kv=11, length_km=1, r_ohm_km=0.1, x_ohm_km=0.2, load_kw=-1, load_kvar=0)


@pytest.mark.integration
def test_opendss_extension(tmp_path):
    pytest.importorskip("opendssdirect")
    from gridagent.extension_runner import run_extension

    result = run_extension(tmp_path, "opendss", {"kv": 11, "length_km": 1, "r_ohm_km": 0.1,
        "x_ohm_km": 0.2, "load_kw": 100, "load_kvar": 25})
    assert result["status"] == "ok", result
    assert 0.9 < result["metrics"]["voltage_min_pu"] <= 1.05


@pytest.mark.integration
def test_pybamm_extension(tmp_path):
    pytest.importorskip("pybamm")
    from gridagent.extension_runner import run_extension

    result = run_extension(tmp_path, "pybamm", {"current_a": 1, "duration_s": 60, "initial_soc": 0.9})
    assert result["status"] == "ok", result
    assert result["metrics"]["capacity_ah"] == pytest.approx(1/60)


@pytest.mark.integration
def test_solar_reference(tmp_path):
    pytest.importorskip("pvlib")
    from gridagent.extension_runner import run_extension

    result = run_extension(tmp_path, "pvlib", {"effective_irradiance_w_m2": 1000,
        "cell_temperature_c": 25, "rated_dc_w": 500, "gamma_pdc_per_c": -0.004})
    assert result["status"] == "ok", result
    assert result["metrics"]["dc_power_w"] == pytest.approx(500)


@pytest.mark.integration
def test_control_reference(tmp_path):
    pytest.importorskip("control")
    from gridagent.extension_runner import run_extension

    result = run_extension(tmp_path, "control", {"numerator": [1], "denominator": [1, 1], "duration_s": 5})
    assert result["status"] == "ok", result
    assert result["metrics"]["all_poles_left_half_plane"]
    assert result["metrics"]["final_sample"] == pytest.approx(0.993262053, abs=1e-7)
