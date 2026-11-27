"""Run independent public-network references and controller verification."""

import argparse
import json
from pathlib import Path

from gridagent.ac_reference import compare_public_run
from gridagent.dynamic_control_benchmark import run_benchmark
from gridagent.native_backends import run_program
from gridagent.standard_ac_benchmark import NETWORKS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    dynamic = run_benchmark()
    (args.output / "frequency-control.json").write_text(json.dumps(dynamic, indent=2, allow_nan=False),
                                                       encoding="utf-8")
    rows = []
    for network in NETWORKS:
        for scale in (1, 1.1):
            run = run_program(args.workspace, {"backend": "pandapower", "base": network, "load_scale": scale})
            row = {"network": network, "load_scale": scale, "run_id": run.get("run_id")}
            try:
                row.update(compare_public_run(args.workspace, network, scale, run["run_id"]))
            except (ValueError, KeyError) as exc:
                row.update(passed=False, reason=str(exc))
            rows.append(row)
            (args.output / "ac-reference.json").write_text(json.dumps(rows, indent=2, allow_nan=False),
                                                          encoding="utf-8")
    if not all(row["passed"] for row in rows):
        raise SystemExit("One or more public AC numerical references did not pass")


if __name__ == "__main__":
    main()
