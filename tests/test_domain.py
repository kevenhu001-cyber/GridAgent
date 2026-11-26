import pytest
from pydantic import ValidationError

from gridagent.domain import FaultRequest, voltage_metrics


def test_normal_voltage():
    result = voltage_metrics([1, 2, 3], [[1, 1], [1, 1], [1, 1]], [1, 2], 1)
    assert result["voltage_severity_proxy"] == 0
    assert result["stability"] == "not_assessed"


def test_saturated_low_voltage():
    result = voltage_metrics([1, 2, 4], [[0.8], [0.8], [0.8]], [5], 1)
    assert result["voltage_severity_proxy"] == pytest.approx(0.5)
    assert result["v_min_bus"] == "5"


def test_invalid_action():
    with pytest.raises(ValidationError):
        FaultRequest(bus=500, duration_s=0.1)
    with pytest.raises(ValidationError):
        FaultRequest(bus=5, duration_s=0.1, file="forbidden")
