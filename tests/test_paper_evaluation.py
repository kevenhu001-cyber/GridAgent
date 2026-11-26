from pathlib import Path

import pytest

from gridagent.paper import CANDIDATES
from gridagent.paper_evaluation import read_truth, score


def test_score_frozen_predictions():
    labels = [{"location": loc, "duration_ms": ms,
               "kpi": {"severity_score": i / 10, "stable": 1, "vmin_aft": 0.8, "vmax_aft": 1.1}}
              for i, (loc, ms) in enumerate(CANDIDATES)]
    predictions = {"ranking": [
        {"id": f"P{i+1:02}", "severity": i / 10, "stable": True,
         "v_min_pu": 0.8, "v_max_pu": 1.1, "bus_min": "Bus 05", "bus_max": "Bus 06", "rationale": "test"}
        for i in range(10)], "selected": ["P10", "P09", "P08"]}
    result = score(predictions, labels)
    assert result["top3_recall"] == 1
    assert result["severity_mae"] == 0
    assert result["stability_accuracy"] == 1
    assert result["full_workflow_success"] == "not_scored"


@pytest.mark.skipif(not Path("offline-evaluation/test_memory.json").is_file(), reason="Offline labels not staged")
def test_original_holdout_has_all_ten_cases():
    labels = read_truth("offline-evaluation/test_memory.json")
    assert all(sum(e["location"] == loc and e["duration_ms"] == ms for e in labels) == 1
               for loc, ms in CANDIDATES)
