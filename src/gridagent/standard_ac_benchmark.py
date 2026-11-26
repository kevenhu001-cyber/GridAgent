"""Native public test-network screening, separate from synthetic decision training."""

import argparse
import json
import time
from pathlib import Path

from .research import ResearchTasks
from .research_spec import ResearchManifest

NETWORKS = ("case14", "case39", "case118")
PROTOCOL = "public-ac-screening-v1"


def manifest_for(name):
    if name not in NETWORKS:
        raise ValueError("Unsupported built-in network")
    return ResearchManifest(objective=f"Public pandapower {name} base and 110% load screening",
                            program={"base": name}, scenarios=[{"name": "base"},
                            {"name": "load110", "load_scale": 1.1}],
                            max_runs=2, max_repairs=0)


def run_benchmark(root, networks=NETWORKS):
    if not networks or len(networks) != len(set(networks)) or not set(networks) <= set(NETWORKS):
        raise ValueError("Select distinct built-in network names")
    tasks = ResearchTasks(root)
    rows = []
    for name in networks:
        manifest = manifest_for(name)
        start = time.perf_counter()
        identifier = tasks.start(manifest.objective, "single", manifest=manifest, use_repair=False,
                                 use_experience=False, benchmark=True)
        for _ in tasks.resume(identifier):
            pass
        summary = tasks.summary(identifier)
        rows.append({"network": name, "task_id": identifier, "manifest_sha256": summary["manifest_sha256"],
                     "stage": summary["stage"], "reserved_runs": summary["runs_used"],
                     "cache_hits": summary.get("cache_hits", 0),
                     "native_launches_observed": summary.get("native_launches_observed"),
                     "elapsed_workflow_seconds": time.perf_counter()-start,
                     "scenarios": summary["best_runs"]})
    return {"protocol": PROTOCOL, "observations": rows,
            "scope": "built-in network screening; not reference-solution accuracy or DC-AC training data"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("--networks", nargs="+", choices=NETWORKS, default=NETWORKS)
    args = parser.parse_args()
    print(json.dumps(run_benchmark(args.workspace, args.networks), ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
