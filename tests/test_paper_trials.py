from gridagent.dsr import Study
from gridagent.paper_trials import run_trials


def test_failed_trials_count_and_isolation(tmp_path):
    roots = []

    def factory(root):
        roots.append(root)
        if len(roots) == 2:
            raise ValueError("provider failure")
        study = Study(root / "studies")
        study.write("manifest", {})
        study.write("report", {"phase": "predictions_frozen"})
        yield "done"

    list(run_trials(tmp_path, "rank", factory, 3, "test"))
    batch = next((tmp_path / "batches").iterdir())
    import json

    report = json.loads((batch / "report.json").read_text())
    assert len(set(roots)) == 3
    assert report["count"] == 3
    assert report["outcome_count"] == 2
    assert report["trials"][1]["error"] == "ValueError"
