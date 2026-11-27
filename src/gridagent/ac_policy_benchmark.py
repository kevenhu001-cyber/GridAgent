"""Compare selection policies on replay-verified complete fixed AC probe studies.

This is an offline policy evaluation, not another numerical solver run.
"""

import argparse
import json
import time
from pathlib import Path

from .ac_diagnostic_experiment import PROTOCOL as FIXED_PROTOCOL
from .ac_diagnostic_experiment import resume_experiment
from .ac_diagnostic_ir import ACDiagnosticExperiment
from .adaptive_ac_experiment import progress
from .adaptive_ac_policy import POLICY, choose
from .dsr import Study
from .engineering_ir import fingerprint

PROTOCOL = "ac-policy-replay-benchmark-v1"


def no_solver(*args, **kwargs):
    raise AssertionError("Policy evaluation must not launch a solver")


def replay_fixed(root, identifier):
    study = Study.reopen(root / "studies", identifier)
    manifest = study.read("manifest")
    if manifest.get("protocol") != FIXED_PROTOCOL or not study.exists("report"):
        raise ValueError("Benchmark requires a committed fixed AC diagnostic study")
    spec = ACDiagnosticExperiment.model_validate(manifest["spec"])
    count = len(spec.probes)+1
    if not all(study.exists(f"reservation-{i}") and study.exists(f"evaluation-{i}")
               for i in range(count)):
        raise ValueError("Benchmark requires the complete fixed candidate pool")
    report = resume_experiment(root, identifier, solver=no_solver)
    if not report["baseline_reproduced"]:
        raise ValueError("Benchmark baseline must reproduce the original failure")
    rows = report["observations"]
    if len(rows) != count or any(row["index"] != i for i, row in enumerate(rows)):
        raise ValueError("Benchmark candidate observations do not match the pool")
    return spec, manifest["cases"], report


def evaluate_policy(spec, jobs, report, budget, *, adaptive):
    """Only reveal the outcome of a probe after its selection."""
    if not 2 <= budget <= len(jobs):
        raise ValueError("Benchmark budget must fit baseline plus pool")
    oracle = {row["index"]: row for row in report["observations"]}
    if set(oracle) != {job["index"] for job in jobs}:
        raise ValueError("Incomplete fixed observation pool")
    revealed = []
    start = time.perf_counter()
    stop, _, updates = progress(spec, report["source_measurement"], revealed, budget, len(jobs))
    while stop is None:
        if adaptive:
            decision = choose(jobs, revealed, [])
            if decision is None:
                raise ValueError("Adaptive policy returned no choice")
            index = decision["index"]
        else:
            index = jobs[len(revealed)]["index"]
        if index in {row["index"] for row in revealed} or index not in oracle:
            raise ValueError("Policy chose a repeated or unauthorized probe")
        revealed.append(oracle[index])
        stop, _, updates = progress(spec, report["source_measurement"], revealed, budget, len(jobs))
    elapsed = time.perf_counter()-start
    success = stop == "verified_single_snapshot_candidate"
    winner = next((row["index"] for row in updates if row["status"] == "target_resolved_in_counterfactual"
                   and row["all_snapshot_checks_passed"]), None)
    return {"success": success, "termination": stop, "projected_solver_calls": len(revealed),
            "selected_indices": [row["index"] for row in revealed], "winner": winner,
            "policy_replay_seconds": elapsed}


def benchmark_studies(root, identifiers, budget):
    root = Path(root).resolve()
    if not 1 <= len(identifiers) <= 12 or len(set(identifiers)) != len(identifiers):
        raise ValueError("Provide one to twelve distinct fixed study IDs")
    cases, source_hashes = [], set()
    for identifier in identifiers:
        spec, jobs, report = replay_fixed(root, identifier)
        if report["source_report_sha256"] in source_hashes:
            raise ValueError("Repeated source report would inflate benchmark case count")
        source_hashes.add(report["source_report_sha256"])
        fixed = evaluate_policy(spec, jobs, report, budget, adaptive=False)
        adaptive = evaluate_policy(spec, jobs, report, budget, adaptive=True)
        cases.append({"study_id": identifier, "source_report_sha256": report["source_report_sha256"],
                      "fixed_report_sha256": fingerprint(report), "candidate_pool": len(jobs)-1,
                      "recorded_native_observations": len(jobs),
                      "inconclusive_observations": sum(row["measurement"] is None or
                          row["measurement"]["solver_version"] != report["source_measurement"]["solver_version"]
                          for row in report["observations"]),
                      "fixed_first_fit": fixed, "adaptive": adaptive})
    totals = {}
    for name in ("fixed_first_fit", "adaptive"):
        totals[name] = {"successful_cases": sum(case[name]["success"] for case in cases),
                        "projected_solver_calls": sum(case[name]["projected_solver_calls"] for case in cases)}
    return {"protocol": PROTOCOL, "policy": POLICY, "budget_per_case": budget,
            "cases": cases, "totals": totals, "solver_calls": 0, "historical_priors_used": False,
            "scope": "offline replay of recorded native observations; no measured solver speedup or holdout guarantee"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("studies", nargs="+")
    parser.add_argument("--budget", type=int, required=True, choices=range(2, 10))
    args = parser.parse_args()
    report = benchmark_studies(args.workspace, args.studies, args.budget)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
