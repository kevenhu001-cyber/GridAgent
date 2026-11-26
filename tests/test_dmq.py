from gridagent.dmq import Gains, Manifest, build_dmq
from gridagent.dmq_model import run_suite
from gridagent.dsr import Study


def test_numerical_suite_has_repairable_case(tmp_path):
    initial = run_suite(Gains().model_dump(), tmp_path / "initial")
    repaired = run_suite(Gains(kqp=1, kqi=0.5, kvp=1, kvi=0.5).model_dump(), tmp_path / "fixed")
    assert len(initial) == len(repaired) == 8
    assert not all(t["passed"] for t in initial)
    assert all(t["passed"] for t in repaired), repaired
    assert (tmp_path / "fixed" / "flat_start.csv").is_file()


def test_dmq_runs_baseline_and_repair(tmp_path):
    study = Study(tmp_path)
    def propose(_observation):
        return {"gains": {"kqp": 1, "kqi": 0.5, "kvp": 1, "kvi": 0.5}, "rationale": "Lower loop gains"}
    result = build_dmq(Manifest(), propose, study).invoke({})
    assert result["report"]["passed"]
    assert result["report"]["attempts"] == 1
    assert (study.path / "proposal-1.json").is_file()
    assert (study.path / "iteration-1.json").is_file()


def test_rejects_unlisted_parameter_and_enforces_budget(tmp_path):
    study = Study(tmp_path)
    def propose(_observation):
        return {"gains": {"kqp": 1, "kqi": 1, "kvp": 1, "kvi": 1, "plant": 2},
                "rationale": "Attempt unauthorized edit"}
    result = build_dmq(Manifest(max_iterations=2), propose, study).invoke({})
    assert result["report"]["attempts"] == 2
    assert result["report"]["accepted_edits"] == 0
    assert result["report"]["final_gains"] == Gains().model_dump()
    assert not (study.path / "iteration-1.json").exists()
