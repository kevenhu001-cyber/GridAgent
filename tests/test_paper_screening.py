import json

from gridagent import paper


def test_screening_freezes_and_limits_attempts(tmp_path, monkeypatch):
    evidence = {f"P{i:02}": {"location": loc, "duration_ms": ms, "matches": []}
                for i, (loc, ms) in enumerate(paper.CANDIDATES, 1)}
    monkeypatch.setattr(paper, "training_evidence", lambda: (evidence, 100, 90))
    calls = []

    def estimate(rows):
        return {"predictions": [
            {"id": key, "severity": i / 10, "stable": True, "v_min_pu": 0.8,
             "v_max_pu": 1.1, "bus_min": "Bus 05", "bus_max": "Bus 06", "rationale": "test"}
            for i, key in enumerate(rows)]}

    def simulate(case, folder):
        assert (folder.parent / "predictions.json").is_file()
        calls.append(case)
        return {"status": "ok", "kpi": {"severity_score": 0.5, "stable": 1,
                                       "vmin_aft": 0.7, "vmax_aft": 1.2}}

    list(paper.paper_rank(tmp_path, estimate, simulate))
    assert len(calls) == 3
    study = next((tmp_path / "studies").iterdir())
    report = json.loads((study / "report.json").read_text())
    assert report["attempted"] == 3
    assert report["selected"] == ["P10", "P09", "P08"]
    assert report["mitigation"] == "not_run"
    assert not report["completed"]
    assert report["observations"][0]["stability_match"]
