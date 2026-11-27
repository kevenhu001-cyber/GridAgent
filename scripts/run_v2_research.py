"""Run the predeclared full native collection and held-out replay, with no LLM calls."""

import argparse
import json
import time
from pathlib import Path

from gridagent.ac_collection_families import FAMILIES, RUNS_PER_CASE
from gridagent.ac_decision_train import rank_study, train_study
from gridagent.ac_native_collection import resume_collection, start_collection
from gridagent.ac_policy_benchmark import benchmark_studies, evaluate_policy, replay_fixed
from gridagent.standard_ac_benchmark import run_benchmark


def save(path, report):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def run(root, output, collection_id=None):
    root.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)
    count = len(FAMILIES) * 3
    authorization = {"families": list(FAMILIES), "levels": ["light", "nominal", "heavy"],
                     "max_dc_calls": count, "max_ac_runs": count * RUNS_PER_CASE}
    identifier = collection_id or start_collection(root, authorization)
    save(output / "collection-plan.json", {"study_id": identifier, "authorization": authorization})
    start = time.perf_counter()
    report = resume_collection(root, identifier)
    save(output / "collection.json", {**report, "elapsed_seconds": time.perf_counter()-start})
    screening = run_benchmark(root)
    save(output / "public-screening.json", screening)
    splits = report["dataset_authorization"]
    if splits is None:
        save(output / "training-status.json", {"status": "insufficient_split_evidence"})
        return
    try:
        training = train_study(root, splits)
    except ValueError as exc:
        save(output / "training-status.json", {"status": "training_rejected", "reason": str(exc)})
        training = None
    if training is not None:
        save(output / "training.json", training)
    heldout = [row["study_id"] for row in splits["cases"] if row["split"] == "test"]
    if not heldout:
        return
    comparison = benchmark_studies(root, heldout, 3)
    ranked = []
    if training is not None and training["artifact"]["enabled"]:
        for identifier in heldout:
            spec, jobs, observed = replay_fixed(root, identifier)
            ordering = rank_study(root, training["study_id"], spec.canonical())
            preferred = [row["candidate_index"] for row in ordering["ranked"]]
            result = (evaluate_policy(spec, jobs, observed, 3, adaptive=False, preferred=preferred)
                      if preferred else evaluate_policy(spec, jobs, observed, 3, adaptive=True))
            ranked.append({"study_id": identifier, "ranking_status": ordering["status"],
                           "used_learned_order": bool(preferred), **result})
    comparison["learned_policy"] = {"status": "evaluated" if ranked else "not_activated",
                                    "cases": ranked,
                                    "successful_cases": sum(row["success"] for row in ranked),
                                    "projected_solver_calls": sum(row["projected_solver_calls"] for row in ranked),
                                    "actual_solver_calls": 0}
    save(output / "heldout-policy-replay.json", comparison)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--resume-collection")
    args = parser.parse_args()
    run(args.workspace.resolve(), args.output.resolve(), args.resume_collection)


if __name__ == "__main__":
    main()
