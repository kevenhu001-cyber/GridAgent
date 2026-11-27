from types import SimpleNamespace

from gridagent import ac_llm_policy_benchmark as benchmark


def fixture(monkeypatch):
    spec = SimpleNamespace(target_check="voltage", target_scope="ac_native")
    jobs = [{"index": i, "change": {"after": i}} for i in range(3)]
    report = {"source_measurement": {"violation": 1},
              "observations": [{"index": i, "measurement": {"secret_outcome": i},
                                "observation": {"passed": i == 2}} for i in range(3)]}

    def progress(spec, metric, rows, budget, pool_size):
        stop = ("verified_single_snapshot_candidate" if rows[-1]["index"] == 2 else
                "budget_exhausted" if len(rows) >= budget else None)
        return stop, True, []

    monkeypatch.setattr(benchmark, "progress", progress)
    return spec, jobs, report


def test_no_future_outcomes_and_matched_budget(monkeypatch):
    spec, jobs, report = fixture(monkeypatch)

    def select(payload):
        assert [row["index"] for row in payload["observed"]] == [0]
        assert "measurement" not in payload["candidates"][0]
        assert payload["remaining_budget"] == 1
        return {"index": 2}

    result = benchmark.evaluate_llm(spec, jobs, report, 2, select)
    assert result["success"] and result["projected_solver_calls"] == 2
    assert result["model_decisions"] == 1


def test_unauthorized_selection_fails_without_retry(monkeypatch):
    spec, jobs, report = fixture(monkeypatch)
    result = benchmark.evaluate_llm(spec, jobs, report, 3, lambda payload: {"index": 99})
    assert not result["success"]
    assert result["termination"] == "invalid_model_decision"
    assert result["model_decisions"] == result["projected_solver_calls"] == 1
