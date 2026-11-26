"""Offline evaluator. Never imported by the DSR policy or retrieval index."""
import argparse
import json
from pathlib import Path

from .dsr import digest, read_manifest
from .simulator import AndesSimulator


def build_truth(manifest, simulator, output: Path):
    # Keep evaluator runs outside the policy's workspace/runs tree.
    data = manifest.model_dump(mode="json")
    truth = {"protocol": "andes-voltage-proxy-v1", "manifest_sha256": digest(data), "results": {}}
    for candidate in manifest.candidates:
        result = simulator.run("fault", candidate.fault.model_dump(mode="json"))
        if result.get("status") != "ok":
            raise RuntimeError(f"Ground truth unavailable for {candidate.id}")
        truth["results"][candidate.id] = result["metrics"]["voltage_severity_proxy"]
    with output.open("x", encoding="utf-8") as handle:
        json.dump(truth, handle, indent=2, allow_nan=False)
    return truth


def score_study(manifest_record, predictions, truth):
    if (manifest_record["manifest_sha256"] != truth["manifest_sha256"]
            or manifest_record["protocol"] != truth["protocol"]):
        raise ValueError("Evaluator and study manifest differ")
    ranked = predictions["ranking"]
    labels = truth["results"]
    expected = {c["id"] for c in manifest_record["manifest"]["candidates"]}
    if len(ranked) != len(expected) or {p["id"] for p in ranked} != expected or set(labels) != expected:
        raise ValueError("Candidate IDs differ")
    budget = manifest_record["manifest"]["budget"]
    selected = predictions["selected"]
    ranked_ids = [p["id"] for p in sorted(ranked, key=lambda p: (-p["score"], p["id"]))]
    if selected != ranked_ids[:budget]:
        raise ValueError("Selected candidates violate frozen ranking/budget")
    best = sorted(labels, key=lambda cid: (-labels[cid], cid))[:budget]
    return {"top_k_recall": len(set(selected) & set(best)) / budget,
            "severity_proxy_mae": sum(abs(p["score"] - labels[p["id"]]) for p in ranked) / len(ranked),
            "k": budget, "ground_truth_top_k": best,
            "scope": "voltage proxy only; no physical-stability or mitigation score"}


def main():
    parser = argparse.ArgumentParser(description="Offline DSR voltage-proxy evaluator")
    sub = parser.add_subparsers(dest="command", required=True)
    truth = sub.add_parser("truth")
    truth.add_argument("manifest", type=Path)
    truth.add_argument("output", type=Path)
    score = sub.add_parser("score")
    score.add_argument("study", type=Path)
    score.add_argument("truth", type=Path)
    args = parser.parse_args()
    if args.command == "truth":
        args.output.parent.mkdir(parents=True, exist_ok=True)
        build_truth(read_manifest(args.manifest), AndesSimulator(args.output.parent / "evaluator-runs"), args.output)
        print("Ground truth written:", args.output)
    else:
        def load(path):
            return json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps(score_study(load(args.study / "manifest.json"),
                                     load(args.study / "predictions.json"), load(args.truth)), indent=2))


if __name__ == "__main__":
    main()
