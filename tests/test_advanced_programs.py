import pytest
from pydantic import ValidationError

from gridagent.advanced_programs import FluidState, PowerFlowCase, TrackingQP
from gridagent.extension_runner import OPERATIONS, SCHEMAS
from gridagent.plugins import CATALOG


def test_catalog_has_typed_execution_contracts():
    assert set(CATALOG) - {"pypsa"} <= set(SCHEMAS)
    assert set(SCHEMAS) == set(OPERATIONS)
    assert len(CATALOG) == 14
    assert len({t for row in CATALOG.values() for t in row["tools"]}) == len(CATALOG)


def test_advanced_validation():
    with pytest.raises(ValidationError):
        TrackingQP(target_mw=[0, 1], lower_mw=5, upper_mw=1, ramp_mw_per_hour=1)
    with pytest.raises(ValidationError):
        PowerFlowCase(case="user.py")
    with pytest.raises(ValidationError):
        FluidState(fluid="REFPROP::Water", temperature_k=300, pressure_pa=101325)
