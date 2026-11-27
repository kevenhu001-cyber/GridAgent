"""Explicit offline training and read-only inference from local AC evidence.

python -m gridagent.ac_decision_train WORKSPACE SPLITS.json
python -m gridagent.ac_decision_train WORKSPACE --rank TRAINING_ID PROBE_POOL.json
"""

import argparse
import json
from pathlib import Path

from .ac_decision_dataset import DatasetSpec, build_dataset, source_context, vector
from .ac_decision_model import rank, train
from .ac_diagnostic_experiment import prepare
from .ac_diagnostic_ir import ACDiagnosticExperiment
from .dsr import Study
from .engineering_ir import fingerprint

PROTOCOL = "ac-decision-training-v1"


def read_json(path):
    with Path(path).open("rb") as handle:
        raw = handle.read(1024*1024+1)
    if len(raw) > 1024*1024:
        raise ValueError("Input exceeds 1 MiB")
    return json.loads(raw)


def train_study(root, authorization):
    root = Path(root).resolve()
    auth = DatasetSpec.model_validate(authorization)
    dataset = build_dataset(root, auth)
    artifact = train(dataset)
    study = Study(root / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "authorization": auth.model_dump(mode="json"),
                             "dataset_sha256": fingerprint(dataset)})
    study.write("dataset", dataset)
    report = {"study_id": study.id, "phase": "ac_decision_training_finished", "protocol": PROTOCOL,
              "completed": True, "artifact": artifact, "solver_calls": 0,
              "scope": "offline ranking only; never a verified engineering solution"}
    study.write("report", report)
    return report


def rank_study(root, identifier, authorization):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    manifest = study.read("manifest")
    if manifest.get("protocol") != PROTOCOL or not study.exists("report"):
        raise ValueError("Ranking requires completed AC decision training")
    dataset = build_dataset(root, manifest["authorization"])
    if fingerprint(dataset) != manifest["dataset_sha256"] or study.read("dataset") != dataset:
        raise ValueError("Training dataset evidence changed")
    saved = study.read("report")["artifact"]
    # Verify training inputs and regenerate fitted model/activation rather than trusting mutable JSON.
    reproduced = train(dataset)
    if saved != reproduced:
        raise ValueError("Training artifact differs from deterministic replay")
    spec = ACDiagnosticExperiment.model_validate(authorization)
    cases, metric = prepare(root, spec)
    ac_spec, descriptors = source_context(root, spec, {"source_report_sha256": spec.source_report_sha256})
    candidates = [(job["index"], vector(spec, job, metric, descriptors, ac_spec))
                  for job, *_ in cases[1:]]
    result = rank(reproduced, candidates, metric["solver_version"])
    return {**result, "training_study_id": identifier, "artifact_sha256": reproduced["artifact_sha256"],
            "source_report_sha256": spec.source_report_sha256, "solver_calls": 0,
            "scope": "offline candidate ranking only; use ordinary authorized simulation after abstention or ranking"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("splits", nargs="?")
    parser.add_argument("--rank", nargs=2, metavar=("TRAINING_ID", "PROBE_POOL_JSON"))
    args = parser.parse_args()
    if bool(args.splits) == bool(args.rank):
        parser.error("Specify either SPLITS.json or --rank TRAINING_ID PROBE_POOL.json")
    if args.rank:
        report = rank_study(args.workspace, args.rank[0], read_json(args.rank[1]))
    else:
        report = train_study(args.workspace, read_json(args.splits))
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))


if __name__ == "__main__":
    main()
