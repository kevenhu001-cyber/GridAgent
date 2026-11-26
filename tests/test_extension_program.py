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
