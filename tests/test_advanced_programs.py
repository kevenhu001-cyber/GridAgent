import pytest
from pydantic import ValidationError

from gridagent.advanced_programs import FluidState, PowerFlowCase, TrackingQP
from gridagent.extension_runner import OPERATIONS, SCHEMAS
from gridagent.plugins import CATALOG


def test_catalog_has_typed_execution_contracts():
    typed = {name for name, row in CATALOG.items() if row["tools"]}
    native_api = set(CATALOG) - typed
    # The fixed solver registry and the sandbox-only native API catalog have
    # different contracts. Never allow an API-only plugin into the host runner.
    assert native_api == {"docling", "joblib"}
    assert typed == (set(SCHEMAS) - {"control"}) | {"pypsa"}
    assert set(SCHEMAS) == set(OPERATIONS)
    assert native_api.isdisjoint(SCHEMAS)
    assert len(typed) == 14
    tools = [tool for name in typed for tool in CATALOG[name]["tools"]]
    assert len(set(tools)) == len(tools) == len(typed)


@pytest.mark.parametrize("plugin", ["docling", "joblib"])
def test_native_api_plugins_cannot_use_fixed_host_extension_runner(tmp_path, plugin):
    from gridagent.extension_runner import run_extension

    with pytest.raises(ValueError, match="Unknown extension backend"):
        run_extension(tmp_path, plugin, {})
    assert not (tmp_path / "runs").exists()


def test_advanced_validation():
    with pytest.raises(ValidationError):
        TrackingQP(target_mw=[0, 1], lower_mw=5, upper_mw=1, ramp_mw_per_hour=1)
    with pytest.raises(ValidationError):
        PowerFlowCase(case="user.py")
    with pytest.raises(ValidationError):
        FluidState(fluid="REFPROP::Water", temperature_k=300, pressure_pa=101325)
