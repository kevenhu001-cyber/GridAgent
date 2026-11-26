import numpy as np
import pytest

from gridagent.modal import summarize_modes


def test_modes_and_neutral():
    r = summarize_modes([-2 + 4j, -2 - 4j, 0, 0.1])
    assert r["growing_count"] == 1
    assert r["neutral_count"] == 1
    assert r["decaying_count"] == 2
    mode = r["least_damped_oscillatory_modes"][0]
    assert mode["frequency_hz"] == pytest.approx(4 / (2 * np.pi))
    assert mode["damping_ratio"] == pytest.approx(2 / np.sqrt(20))
    assert r["classification"] == "growing_modes"


def test_neutral_not_asymptotic():
    assert summarize_modes([-1, 0])["classification"] == "neutral_modes"
    with pytest.raises(ValueError):
        summarize_modes([float("nan")])
