import pandas as pd

from gridagent.model_quality import evaluate_run


def test_solver_success_not_enough(tmp_path):
    pd.DataFrame({"in_service": [True, True]}).to_csv(tmp_path / "bus.csv")
    pd.DataFrame({"vm_pu": [1.0, 0.8], "va_degree": [0, 1],
                  "p_mw": [-5, 5], "q_mvar": [0, 0]}).to_csv(tmp_path / "res_bus.csv")
    for name in ("line", "trafo"):
        pd.DataFrame(columns=["loading_percent"]).to_csv(tmp_path / f"res_{name}.csv")
    result = evaluate_run(tmp_path, {"backend": "pandapower", "analysis": "power_flow"}, {"status": "ok"})
    assert not result["passed"]
    assert any(t["id"]=="voltage_operating_range" and not t["passed"] for t in result["tests"])


def test_missing_evidence_cannot_pass(tmp_path):
    result = evaluate_run(tmp_path, {"backend": "pypsa"}, {"status": "ok"})
    assert not result["passed"]
