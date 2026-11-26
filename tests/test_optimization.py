from gridagent.optimization import optimize_updates, quality


def test_quality_prefers_passed_suite():
    good = [{"passed": True, "peak_deviation_pu": 0.2, "tail_error_pu": 0.02}]
    bad = [{"passed": False, "peak_deviation_pu": 0.4, "tail_error_pu": 0.02}]
    assert quality(good) < quality(bad)


def test_optimization_budget_and_verified_result(tmp_path):
    events = list(optimize_updates(tmp_path, budget=3))
    report = events[-1][1]
    assert 1 <= report["objective_evaluations"] <= 3
    assert report["total_suites"] == report["objective_evaluations"] + 2
    assert report["tests_passed"] == 8
    assert (tmp_path / events[0][1]["id"] / "verification" / "flat_start.csv").is_file()
