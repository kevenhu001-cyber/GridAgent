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


@pytest.mark.integration
def test_real_andes_eigen(tmp_path):
    pytest.importorskip("andes")
    sim = AndesSimulator(tmp_path, timeout_s=300)
    result = sim.run("eigen", {"case": "kundur"})
    assert result["status"] == "ok", result
    assert result["metrics"]["mode_count"] > 0
    assert (tmp_path / result["run_id"] / "eigenvalues.csv").is_file()


@pytest.mark.integration
@pytest.mark.parametrize("case", ["ieee14", "ieee39"])
def test_packaged_model_inspection(tmp_path, case):
    pytest.importorskip("andes")
    result = AndesSimulator(tmp_path / "runs", timeout_s=300).run("inspect", {"case": case})
    assert result["status"] == "ok", result
    assert result["topology"]["bus_count"] == int(case[4:])
    assert result["model_sha256"]


@pytest.mark.integration
def test_registered_model_scenario(tmp_path):
    andes = pytest.importorskip("andes")
    from gridagent.models import register_model
    from gridagent.research_tools import compare_power_flows

    identifier = register_model(tmp_path, andes.get_case("kundur/kundur_full.xlsx"))
    sim = AndesSimulator(tmp_path / "runs", timeout_s=300)
    a = sim.run("power_flow", {"case": identifier})
    b = sim.run("scenario_flow", {"case": identifier, "load_scale": 0.95})
    assert a["status"] == b["status"] == "ok", (a, b)
    assert a["model_sha256"] == b["model_sha256"] == identifier[6:]
    assert b["scenario"]["load_scale"] == 0.95
    comparison = compare_power_flows(tmp_path, a["run_id"], b["run_id"])
    assert comparison["buses"] > 0
    assert any(abs(row["delta_pu"]) > 1e-7 for row in comparison["largest_voltage_changes"])
    assert (tmp_path / "runs" / b["run_id"] / "case.xlsx").is_file()
