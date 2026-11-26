"""Independent offline evaluator; never imported by policy, TUI or desktop bridge."""
import argparse
import hashlib
import json
import statistics
from pathlib import Path

from .paper import CANDIDATES, PIN, Ranking

TEST_BLOB = "223c2e4f1cd6e2d431b2515391fb887a7c773017"


def read_truth(path):
    data = Path(path).read_bytes()
    actual = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    if actual != TEST_BLOB:
        raise ValueError("Use the exact pinned upstream test-memory file")
    return json.loads(data)


def score(predictions, labels):
    values = Ranking.model_validate({"predictions": predictions["ranking"]}).predictions
    expected = {f"P{i:02}": case for i, case in enumerate(CANDIDATES, 1)}
    if len({p.id for p in values}) != 10 or {p.id for p in values} != set(expected):
        raise ValueError("Expected ten distinct original cases")
    truth = {}
    for cid, (location, ms) in expected.items():
        matches = [e["kpi"] for e in labels if e["location"] == location and e["duration_ms"] == ms]
        if len(matches) != 1:
            raise ValueError("Test-memory coverage differs")
        truth[cid] = matches[0]
    ranked = sorted(values, key=lambda x: (-x.severity, x.id))
    selected = [p.id for p in ranked[:3]]
    if predictions["selected"] != selected:
        raise ValueError("Selection violates frozen ranking")
    best = sorted(truth, key=lambda cid: (-truth[cid]["severity_score"], cid))[:3]
    errors = {"vmin_aft": [], "vmax_aft": []}
    for item in ranked:
        actual = truth[item.id]
        for key, estimate in (("vmin_aft", item.v_min_pu), ("vmax_aft", item.v_max_pu)):
            if estimate is not None and actual.get(key) is not None:
                errors[key].append(abs(estimate - actual[key]))
    return {"upstream_commit": PIN, "scope": "frozen predictions vs upstream held-out memory",
            "top3_recall": len(set(selected) & set(best)) / 3,
            "severity_mae": sum(abs(p.severity - truth[p.id]["severity_score"]) for p in ranked) / 10,
            "stability_accuracy": sum(p.stable == bool(truth[p.id]["stable"]) for p in ranked) / 10,
            "voltage_mae": {k: sum(v) / len(v) if v else None for k, v in errors.items()},
            "voltage_compared_counts": {k: len(v) for k, v in errors.items()},
            "full_workflow_success": "not_scored", "mitigation": "not_scored"}


def score_study(study, labels):
    manifest = json.loads((study / "manifest.json").read_text(encoding="utf-8"))
    if (manifest["protocol"] != "poweragentbench-dsr-prediction-v1"
            or manifest["manifest"]["upstream_commit"] != PIN
            or manifest["manifest"]["candidates"] != [list(c) for c in CANDIDATES]):
        raise ValueError("Study does not use the pinned paper protocol")
    return score(json.loads((study / "predictions.json").read_text(encoding="utf-8")), labels)


def score_batch(batch, labels):
    report = json.loads((batch / "report.json").read_text(encoding="utf-8"))
    if report["task"] not in {"rank", "dsr", "mitigate"} or report["upstream_commit"] != PIN:
        raise ValueError("Expected a DSR prediction batch")
    rows = []
    for trial in report["trials"]:
        row = {"trial": trial["trial"], "outcome": trial["outcome"]}
        try:
            study = (batch / (trial["study"] or "")).resolve()
            if not study.is_relative_to(batch.resolve()) or not trial["study"]:
                raise ValueError("Missing study")
            row["score"] = score_study(study, labels)
        except (OSError, ValueError, KeyError, TypeError):
            row["score"] = None
        rows.append(row)
    scored = [r["score"] for r in rows if r["score"] is not None]
    return {"trials": rows, "attempted": len(rows), "scored": len(scored),
            "prediction_metrics_conditional_on_valid_score": {
                key: statistics.mean(s[key] for s in scored) if scored else None
                for key in ("top3_recall", "severity_mae", "stability_accuracy")},
            "full_workflow_success": "not_scored"}


def main():
    parser = argparse.ArgumentParser(description="Offline original DSR prediction evaluator")
    parser.add_argument("study", type=Path)
    parser.add_argument("test_memory", type=Path)
    parser.add_argument("--batch", action="store_true")
    args = parser.parse_args()
    labels = read_truth(args.test_memory)
    if args.batch:
        result = score_batch(args.study, labels)
    else:
        result = score_study(args.study, labels)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
