import pytest
from pydantic import ValidationError

from gridagent.extra_programs import Commitment, EconomicDispatch, Wind


def test_reject_invalid_curve_and_cost_models():
    with pytest.raises(ValidationError):
        Wind(wind_speed_m_s=[5], curve_speed_m_s=[10, 0], curve_power_w=[1, 0])
    with pytest.raises(ValidationError):
        EconomicDispatch(demand_mw=3, units=[{"maximum_mw": 5, "linear_cost_per_mwh": 1, "startup_cost": 2}])
    with pytest.raises(ValidationError):
        Commitment(demand_mw=[3], units=[{"maximum_mw": 5, "linear_cost_per_mwh": 1, "quadratic_cost": 2}])
