"""Versioned evidence envelopes with bounded, allowlisted artifact fingerprints."""

import hashlib
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import fingerprint
from .execution_plan import ExecutionPlan, Hash, NodeId
from .task_contracts import Contract
from .workspace import artifact_folder, load_object

AC_FILES = ("request.json", "result.json", "bus.csv", "line.csv", "trafo.csv",
            "res_bus.csv", "res_line.csv", "res_trafo.csv")
DISPATCH_FILES = ("request.json", "result.json", "generation_mw.csv", "load_mw.csv",
                  "storage_soc_mwh.csv", "storage_charge_mw.csv", "storage_discharge_mw.csv",
                  "link_mw.csv", "link_destination_mw.csv")
ALLOWED = frozenset((*AC_FILES, *DISPATCH_FILES, "line_mw.csv", "line_destination_mw.csv"))
MAX_FILE_BYTES = 64 * 1024 * 1024


class ArtifactDigest(Contract):
    name: str
    sha256: Hash
    size_bytes: int = Field(ge=0, le=MAX_FILE_BYTES)

    @model_validator(mode="after")
    def check_name(self):
        if self.name not in ALLOWED:
            raise ValueError("Unsupported evidence artifact")
        return self


class CheckRecord(Contract):
    id: str = Field(min_length=1, max_length=128)
    passed: bool


class EvidenceRecord(Contract):
    schema_version: Literal[1] = 1
    plan_sha256: Hash
    solve_node_id: NodeId
    scenario: NodeId
    run_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    request_sha256: Hash
    evaluator: Literal["ac-research-v1", "native-dispatch-v1"]
    solver_version: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["verified", "rejected", "unavailable"]
    checks: tuple[CheckRecord, ...] = Field(default=(), max_length=100)
    artifacts: tuple[ArtifactDigest, ...] = Field(default=(), max_length=16)
    required_artifacts: tuple[str, ...] = Field(default=(), max_length=16)
    verdict_sha256: Hash

    @model_validator(mode="after")
    def check_record(self):
        names = {row.name for row in self.artifacts}
        if len(names) != len(self.artifacts) or len({row.id for row in self.checks}) != len(self.checks):
            raise ValueError("Duplicate evidence artifact or check")
        required = set(self.required_artifacts)
        if not required <= ALLOWED or len(required) != len(self.required_artifacts):
            raise ValueError("Invalid required artifacts")
        if self.status == "verified" and (
                not self.solver_version or not self.checks or not all(row.passed for row in self.checks)
                or not {"request.json", "result.json"} <= required or not required <= names):
            raise ValueError("Verified evidence must contain all required artifacts and passed checks")
        return self

    def sha256(self):
        return fingerprint(self.model_dump(mode="json"))


def artifact_digest(folder, name):
    if name not in ALLOWED:
        raise ValueError("Unsupported evidence artifact")
    path = folder / name
    if path.is_symlink() or not path.is_file() or path.resolve().parent != folder.resolve():
        raise ValueError("Missing or unsafe evidence artifact")
    size = 0
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_FILE_BYTES:
                raise ValueError("Evidence artifact exceeds size limit")
            digest.update(chunk)
    return ArtifactDigest(name=name, sha256=digest.hexdigest(), size_bytes=size)


def required_files(plan, request):
    if plan.family == "ac_steady_state":
        return AC_FILES
    return (*DISPATCH_FILES, "line_mw.csv", "line_destination_mw.csv") if request.get("lines") else DISPATCH_FILES


def capture_evidence(root, plan: ExecutionPlan, scenario, run_id, request, *, version, verdict):
    """Capture an evaluator verdict and the exact artifacts used to obtain it."""
    node = plan.solve_for(scenario, request)
    required = required_files(plan, request)
    artifacts = []
    checks = tuple(CheckRecord(id=row["id"], passed=row["passed"])
                   for row in verdict.get("checks", verdict.get("tests", [])))
    identity = False
    try:
        folder = artifact_folder(Path(root), "runs", run_id)
        for name in required:
            try:
                artifacts.append(artifact_digest(folder, name))
            except (OSError, ValueError):
                continue
        if not {"request.json", "result.json"} <= {row.name for row in artifacts}:
            raise ValueError("Missing identity artifacts")
        saved = load_object(folder / "request.json")
        result = load_object(folder / "result.json")
        identity = (fingerprint(saved) == node.request_sha256 and result.get("run_id") == run_id
                    and result.get("backend") == request["backend"] and result.get("status") == "ok"
                    and result.get("version") == version)
    except (OSError, ValueError, TypeError):
        identity = False
    complete = identity and len(artifacts) == len(required)
    passed = complete and bool(version) and verdict.get("passed") is True and bool(checks) and all(
        row.passed for row in checks)
    return EvidenceRecord(
        plan_sha256=plan.sha256(), solve_node_id=node.id, scenario=scenario, run_id=run_id,
        request_sha256=node.request_sha256, evaluator=plan.evaluator, solver_version=version,
        status="verified" if passed else "rejected" if complete else "unavailable",
        checks=checks, artifacts=tuple(artifacts), required_artifacts=required,
        verdict_sha256=fingerprint(verdict),
    )


def verify_artifacts(root, record: EvidenceRecord):
    """Re-hash recorded files; this detects changes, not authenticity or optimality."""
    try:
        folder = artifact_folder(Path(root), "runs", record.run_id)
        return bool(record.artifacts) and all(artifact_digest(folder, row.name) == row for row in record.artifacts)
    except (OSError, ValueError):
        return False


def verify_record(root, record, plan, scenario, run_id, request, verdict):
    record = EvidenceRecord.model_validate(record)
    node = plan.solve_for(scenario, request)
    if (record.plan_sha256 != plan.sha256() or record.solve_node_id != node.id
            or record.scenario != scenario or record.run_id != run_id
            or record.request_sha256 != node.request_sha256 or record.evaluator != plan.evaluator
            or record.verdict_sha256 != fingerprint(verdict)
            or record.required_artifacts != required_files(plan, request)):
        raise ValueError("Evidence record differs from frozen plan or verdict")
    expected_checks = tuple(CheckRecord(id=row["id"], passed=row["passed"])
                            for row in verdict.get("checks", verdict.get("tests", [])))
    if record.checks != expected_checks:
        raise ValueError("Evidence checks differ from evaluator verdict")
    if record.artifacts and not verify_artifacts(root, record):
        raise ValueError("Recorded evidence artifacts changed")
    return record
