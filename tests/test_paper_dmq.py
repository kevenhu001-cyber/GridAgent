from gridagent.paper_dmq import original_dmq


def test_original_dmq_feedback_and_guard(tmp_path):
    calls = []
    proposals = iter([{"gains": {"Kqp": 1, "Kqi": 1, "Kvp": 1, "Kvi": 1, "extra": 1}, "rationale": "bad"},
                      {"gains": {"Kqp": 1, "Kqi": 2, "Kvp": 1, "Kvi": 2}, "rationale": "diagnosis"}])

    def run(gains, folder, iteration):
        calls.append(gains)
        return {"status": "ok", "evaluation": {"overall_pass": iteration > 0,
                                               "n_pass": 8 if iteration else 0, "tests": {}}}

    list(original_dmq(tmp_path, lambda observation: next(proposals), run))
    assert len(calls) == 2
    study = next((tmp_path / "studies").iterdir())
    assert (study / "proposal-1.json").is_file()
    assert (study / "iteration-2.json").is_file()
    assert not (study / "iteration-1.json").exists()


def test_original_dmq_stops_on_infrastructure_failure(tmp_path):
    def run(gains, folder, iteration):
        return {"status": "failed", "reason": "license"}

    def propose(observation):
        raise AssertionError("No model call after infrastructure failure")

    list(original_dmq(tmp_path, propose, run))
