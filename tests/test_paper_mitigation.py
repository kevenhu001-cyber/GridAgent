import pytest

from gridagent.dsr import Study
from gridagent.paper_mitigation import MitigationProfile, run_mitigation


def test_fresh_budget_and_measured_recommendation(tmp_path):
    study = Study(tmp_path)
    choices = iter(["04", "04", "16+26"])
    calls = []

    def propose(obs):
        assert "matches" not in obs["fault"]
        assert "memory" not in obs
        return {"plan": next(choices), "rationale": "test"}

    def simulate(case, folder):
        assert (study.path / f"mitigation-reservation-{1 if not calls else 3}.json").exists()
        calls.append(case["condenser_plan"])
        stable = case["condenser_plan"] == "16+26"
        return {"status": "ok", "kpi": {"stable": int(stable), "severity_score": 0.2 if stable else 1}}

    baseline = {"status": "ok", "kpi": {"stable": 0, "severity_score": 1}}
    rows = list(run_mitigation(study, {"location": "Bus 05", "duration_ms": 100, "matches": ["excluded"]},
                               baseline, propose, simulate, budget=3))
    assert calls == ["04", "16+26"]
    assert rows[1]["status"] == "denied"
    report = study.read("mitigation-report")
    assert report["recommended"]["plan"] == "16+26"
    assert not report["all_plans_verified"]


def test_invalid_profile_rejected():
    with pytest.raises(ValueError):
        MitigationProfile.model_validate({"device_names": {"04": "SC04"}, "variants": {}})
