"""Build a bounded, source-verified AC candidate ranking dataset."""

import math
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .ac_check_ir import ACCheckSpec
from .ac_physical_features import SCALES, physical_features
from .ac_policy_benchmark import replay_fixed
from .diagnosis_rules import rule_for
from .dsr import Study
from .engineering_ir import fingerprint
from .task_contracts import Contract

PROTOCOL = "ac-decision-dataset-v1"
FEATURES = tuple(key for name in SCALES for key in (name, name+"_missing")) + (
    "outage", "voltage_target", "loading_target", "reactive_target",
    "voltage_probe", "reactive_probe", "signed_normalized_step",
    "baseline_violation_scaled", "metric_is_mw", "device_is_slack")
TARGETS = {"voltage": 0.05, "loading": 20.0, "reactive": 1.0}


class DatasetCase(Contract):
    study_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    family: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.-]+$")
    split: Literal["train", "validation", "test"]


class DatasetSpec(Contract):
    schema_version: Literal[1] = 1
    cases: tuple[DatasetCase, ...] = Field(min_length=3, max_length=120)

    @model_validator(mode="after")
    def partition(self):
        if len({row.study_id for row in self.cases}) != len(self.cases):
            raise ValueError("Duplicate fixed study")
        groups = {}
        for case in self.cases:
            if case.family in groups and groups[case.family] != case.split:
                raise ValueError("Model family crosses dataset splits")
            groups[case.family] = case.split
        if set(groups.values()) != {"train", "validation", "test"}:
            raise ValueError("All three family-disjoint splits required")
        return self


def family_identity(spec):
    # Ignore model ID, revision, operating point and equipment ordering.
    model = spec.model
    return fingerprint({"buses": sorted((b.id, b.nominal_kv) for b in model.buses),
                        "branches": sorted((d.kind, min(d.from_bus, d.to_bus), max(d.from_bus, d.to_bus))
                                           for d in model.devices if d.kind == "line"),
                        "devices": sorted((d.kind, d.bus) for d in model.devices if hasattr(d, "bus"))})


def vector(spec, job, metric, descriptors, ac_spec):
    target = rule_for(spec.target_scope, spec.target_check)
    if target not in TARGETS:
        raise ValueError("Unsupported decision target")
    values = []
    for key, scale in SCALES.items():
        value = descriptors[key]
        values.extend((0.0 if value is None else math.asinh(value/scale), float(value is None)))
    probe, change = job["probe"], job["change"]
    span = 0.4 if probe["kind"] == "voltage_setpoint" else probe["maximum_mvar"]-probe["minimum_mvar"]
    device = next(d for d in ac_spec.model.devices if d.id == change["device"])
    values.extend((float(spec.snapshot.outage_line is not None), float(target == "voltage"),
                   float(target == "loading"), float(target == "reactive"),
                   float(probe["kind"] == "voltage_setpoint"), float(probe["kind"] == "storage_reactive"),
                   (change["after"]-change["before"])/max(span, 1e-12),
                   math.asinh(metric["violation"]/(10.0 if metric["unit"] == "MW" else TARGETS[target])),
                   float(metric["unit"] == "MW"), float(device.kind == "slack")))
    if len(values) != len(FEATURES) or not all(map(math.isfinite, values)):
        raise ValueError("Non-finite or inconsistent decision features")
    return values


def label(row, version):
    """Unknown outcomes are not treated as failures."""
    metric = row["measurement"]
    if metric is None or metric["solver_version"] != version:
        return None
    observation = row["observation"]
    evidence = observation["native_evidence"]
    if evidence["status"] not in {"verified", "rejected"}:
        return None
    if observation["passed"] is True and metric["passed"] is True:
        return 1
    if not metric["passed"]:
        return 0
    checks = observation["native_verdict"]["checks"]
    if any(c["passed"] is False and rule_for("ac_native", c["id"]) in {
            "voltage", "loading", "balance"} for c in checks):
        return 0
    if evidence["status"] == "verified":
        physical = (observation.get("physical") or {}).get("checks", [])
        if any(c["passed"] is False for c in physical):
            return 0
    return None


def source_context(root, spec, report):
    source = Study.reopen(Path(root) / "studies", spec.source_study_id)
    original = source.read("report")
    if fingerprint(original) != report["source_report_sha256"]:
        raise ValueError("Dataset source evidence changed")
    ac_spec = ACCheckSpec.model_validate(source.read("manifest")["spec"])
    snapshot = spec.snapshot.model_dump(mode="json")
    rows = [row for row in original["snapshots"] if row["snapshot"] == snapshot]
    if len(rows) != 1:
        raise ValueError("Dataset source snapshot missing or duplicated")
    kind = "outage" if spec.snapshot.outage_line else "base"
    physical = physical_features(ac_spec, {"snapshots": rows}, kind)
    return ac_spec, physical["descriptors"]


def build_dataset(root, authorization):
    root = Path(root).resolve()
    auth = DatasetSpec.model_validate(authorization)
    rows, sources, partitions, provenance = [], set(), {}, []
    unknown = dict.fromkeys(("train", "validation", "test"), 0)
    for case in sorted(auth.cases, key=lambda row: row.study_id):
        spec, jobs, report = replay_fixed(root, case.study_id)
        source_hash = report["source_report_sha256"]
        if source_hash in sources:
            raise ValueError("Duplicate source report across dataset cases")
        sources.add(source_hash)
        ac_spec, descriptors = source_context(root, spec, report)
        for identity in ("id:"+ac_spec.model.model_id, "topology:"+family_identity(ac_spec)):
            if identity in partitions and partitions[identity] != case.split:
                raise ValueError("Source model identity or named topology crosses dataset splits")
            partitions[identity] = case.split
        version = report["source_measurement"]["solver_version"]
        provenance.append({"study_id": case.study_id, "family": case.family, "split": case.split,
                           "source_report_sha256": source_hash, "fixed_report_sha256": fingerprint(report),
                           "solver_version": version})
        for job, observation in zip(jobs[1:], report["observations"][1:], strict=True):
            outcome = label(observation, version)
            if outcome is None:
                unknown[case.split] += 1
                continue
            rows.append({"study_id": case.study_id, "family": case.family, "split": case.split,
                         "candidate_index": job["index"], "solver_version": version,
                         "x": vector(spec, job, report["source_measurement"], descriptors, ac_spec),
                         "y": outcome})
    return {"protocol": PROTOCOL, "feature_names": list(FEATURES), "rows": rows,
            "provenance": provenance, "excluded_unknown": unknown, "solver_calls": 0,
            "scope": "caller-defined model families; no automatic proof of independent topologies"}
