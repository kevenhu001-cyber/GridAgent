import pytest

from gridagent.simulator import AndesSimulator


@pytest.mark.integration
def test_real_andes_fault(tmp_path):
    pytest.importorskip("andes")
    sim = AndesSimulator(tmp_path, timeout_s=300)
    result = sim.run("fault", {"case": "kundur", "bus": 5, "duration_s": 0.1, "end_s": 3.0})
    assert result["status"] == "ok", result
    assert result["backend"] == "andes"
    assert result["metrics"]["stability"] == "not_assessed"
    assert (tmp_path / result["run_id"] / "voltage.csv").is_file()
