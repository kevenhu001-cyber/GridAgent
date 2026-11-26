"""Evidence-gated authorization for full original-scope AC repair candidates."""

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .ac_check_ir import ACCheckSpec
from .ac_diagnostic_ir import ACDiagnosticExperiment, compile_probes
from .engineering_ir import fingerprint
from .math_program_ir import Identifier
from .task_contracts import Contract


class ACRepairAuthorization(Contract):
    schema_version: Literal[1] = 1
    diagnostic_study_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    diagnostic_report_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    candidate_indices: tuple[Annotated[int, Field(ge=1, le=8)], ...] = Field(min_length=1, max_length=4)
    storage_apparent_limits_mva: dict[Identifier, Annotated[float, Field(gt=0, le=1e6)]] = Field(
        default_factory=dict, max_length=4)
    max_solver_runs: int = Field(ge=1, le=60)

    @model_validator(mode="after")
    def unique_candidates(self):
        if len(set(self.candidate_indices)) != len(self.candidate_indices):
            raise ValueError("Duplicate repair candidate")
        return self

    def canonical(self):
        # Input order is explicit recommendation priority, not a numeric ranking.
        return self.model_dump(mode="json")

    def sha256(self):
        return fingerprint(self.canonical())


def compile_candidates(auth, diagnostic, original, report):
    auth = ACRepairAuthorization.model_validate(auth)
    diagnostic = ACDiagnosticExperiment.model_validate(diagnostic)
    original = ACCheckSpec.model_validate(original)
    if not report["baseline_reproduced"]:
        raise ValueError("Diagnostic baseline was not reproduced")
    variants = compile_probes(diagnostic, original)
    observed = report["observations"]
    updates = report["hypothesis_updates"]
    if report.get("protocol") == "adaptive-ac-experiment-v1":
        observed_by_index = {row["index"]: row for row in observed}
        updates_by_index = {row["index"]: row for row in updates}
        if (len(observed_by_index) != len(observed) or len(updates_by_index) != len(updates)
                or set(observed_by_index) != {0, *updates_by_index}):
            raise ValueError("Adaptive diagnostic evidence inconsistent")
    else:
        if len(observed) != len(variants) or len(updates) != len(variants)-1:
            raise ValueError("Diagnostic candidate evidence incomplete")
        observed_by_index = dict(enumerate(observed))
        updates_by_index = dict(enumerate(updates, 1))
    if len(auth.candidate_indices)*len(original.snapshots) > auth.max_solver_runs:
        raise ValueError("Budget must cover every original snapshot for every selected candidate")
    candidates, storage_devices = [], set()
    for index in auth.candidate_indices:
        if index >= len(variants):
            raise ValueError("Unknown diagnostic candidate index")
        job, variant = variants[index]
        if index not in observed_by_index or index not in updates_by_index:
            raise ValueError("Repair candidate was not experimentally tested")
        row, update = observed_by_index[index], updates_by_index[index]
        if (row["index"] != index or row["probe"] != job["probe"] or row["change"] != job["change"]
                or row["ac_spec_sha256"] != variant.sha256() or update["probe"] != job["probe"]):
            raise ValueError("Diagnostic evidence does not match compiled candidate")
        if (update["status"] != "target_resolved_in_counterfactual"
                or update["all_snapshot_checks_passed"] is not True or row["observation"]["passed"] is not True):
            raise ValueError("Candidate must resolve target and pass all diagnostic snapshot checks")
        if job["probe"]["kind"] == "storage_reactive":
            storage_devices.add(job["probe"]["device"])
        data = variant.canonical()
        data["snapshots"] = [snapshot.model_dump(mode="json") for snapshot in original.snapshots]
        full = ACCheckSpec.model_validate(data)
        candidates.append(({**job, "full_ac_spec_sha256": full.sha256()}, full))
    if storage_devices != set(auth.storage_apparent_limits_mva):
        raise ValueError("Declare exactly the apparent power limits of storage devices selected for repair")
    return candidates


def storage_capacity_check(auth, job, variant, case):
    """Conservative scheduled P/Q envelope, including original dispatch check tolerance."""
    if job["probe"]["kind"] != "storage_reactive":
        return None
    device = job["probe"]["device"]
    row = next(d for d in case[1].model.devices if d.id == device)
    limit = auth.storage_apparent_limits_mva[device]
    tolerance = variant.dispatch_tolerance_mw
    required = math.hypot(abs(row.charging_mw)+tolerance, abs(row.reactive_mvar)+tolerance)
    return {"device": device, "limit_mva": limit, "conservative_required_mva": required,
            "passed": required <= limit}
