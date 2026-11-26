from pathlib import Path

import pytest

from gridagent.paper import CANDIDATES, edit_original_model, original_kpis, paper_rank, training_evidence

pytestmark = pytest.mark.skipif(not Path("benchmark-assets/provenance.json").is_file(),
                                reason="Run scripts/sync_benchmark.py first")


def test_original_training_and_frozen_predictions(tmp_path):
    evidence, total, eligible = training_evidence()
    assert total >= eligible > 0
    assert len(evidence) == len(CANDIDATES) == 10
    targets = {(loc, ms // 10) for loc, ms in CANDIDATES}
    assert all((e["location"], e["duration_cycles"]) not in targets
               for row in evidence.values() for e in row["matches"])

    def estimate(rows):
        return {"predictions": [
            {"id": key, "severity": i / 10, "stable": True, "v_min_pu": 0.8,
             "v_max_pu": 1.1, "bus_min": "Bus 05", "bus_max": "Bus 06", "rationale": "test"}
            for i, key in enumerate(rows)]}

    list(paper_rank(tmp_path, estimate))
    study = next((tmp_path / "studies").iterdir())
    assert (study / "predictions.json").is_file()
    assert not (study / "attempt-1.json").exists()


def test_original_dyr_editor(tmp_path):
    sid, report = edit_original_model(tmp_path, {"Kqp": 1, "Kqi": 5, "Kvp": 1, "Kvi": 5})
    assert report["locked_fields_verified"]
    assert report["old"] == {"Kqp": 10, "Kqi": 50, "Kvp": 10, "Kvi": 50}
    assert (tmp_path / "studies" / sid / "model" / "Solar.sav").is_file()


def test_original_kpi_instability_override(tmp_path):
    path = tmp_path / "wave.csv"
    path.write_text("t,Bus 05,G 01\nTime,u1,Speed\n1.2,1.0,1.0\n1.3,1.0,1.06\n1.4,1.0,1.0\n")
    report = original_kpis(path, 1.05)
    assert report["stable"] == 0
    assert report["severity_score"] == 1
    path.write_text("t,Bus 05\nTime,u1\n1.2,1.0\n1.3,1.0\n")
    with pytest.raises(ValueError):
        original_kpis(path, 1.05)
