import json

import pytest

from gridagent.modeling_benchmark import benchmark_updates, expected_program


def test_fidelity_blocks_wrong_model_before_solver(tmp_path):
    correct = expected_program("storage-dispatch").model_dump(mode="json")
    wrong = expected_program("storage-dispatch").model_dump(mode="json")
    wrong["loads"][0]["p_set_mw"] = [1]*4
    choices = iter([wrong, correct])
    calls = []

    def solve(root, candidate):
        calls.append(candidate)
        return {"status": "ok", "quality": {"passed": True},
                "metrics": {"objective": 200, "storage_discharge_mwh": 10, "storage_charge_mwh": 10}}

    list(benchmark_updates(tmp_path, "storage-dispatch", lambda obs: next(choices), solve))
    assert len(calls) == 1
    report = next((tmp_path / "studies").glob("*/report.json"))
    data = json.loads(report.read_text())
    assert data["passed"] and data["attempts"] == 2


@pytest.mark.integration
@pytest.mark.parametrize("task,package", [("two-bus", "pandapower"), ("storage-dispatch", "pypsa"),
    ("source-short-circuit", "pandapower"), ("lossy-storage", "pypsa"), ("lossy-link", "pypsa")])
def test_independent_analytic_reference(tmp_path, task, package):
    pytest.importorskip(package)
    list(benchmark_updates(tmp_path, task, lambda obs: expected_program(task), max_attempts=1))
    report = next((tmp_path / "studies").glob("*/report.json"))
    data = json.loads(report.read_text())
    assert data["passed"], data
