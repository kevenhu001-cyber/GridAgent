"""Local, evidence-linked AC repair experience, separate from legacy native repairs.

Index pointers and coarse features only. Every retrieved record is replayed;
historical directions are suggestions, never model parameters or authorizations.
"""

import json
from contextlib import closing
from pathlib import Path

from filelock import Timeout

from .ac_check import PROTOCOL as AC_PROTOCOL
from .ac_check_ir import ACCheckSpec
from .ac_diagnostic_ir import ACDiagnosticExperiment
from .ac_evidence_repair import PROTOCOL as REPAIR_PROTOCOL
from .ac_evidence_repair import no_solver, resume_repair
from .ac_physical_features import physical_features, physical_similarity
from .diagnosis import diagnose_study
from .diagnosis_rules import rule_for
from .dsr import Study
from .engineering_ir import fingerprint
from .experience import connect

PROTOCOL = "ac-repair-experience-v1"
MAX_REPLAY_STUDIES = 20
MAX_INDEX_ROWS = 1000
SCOPE = "historical local evidence; fresh authorization and verification required"


def features(spec):
    """Coarse structure only, no device IDs, settings, demand or free text."""
    spec = ACCheckSpec.model_validate(spec)
    counts = {kind: sum(device.kind == kind for device in spec.model.devices)
              for kind in ("line", "generator", "slack", "storage")}
    return {"buses": len(spec.model.buses), "lines": counts["line"],
            "regulating_units": counts["generator"]+counts["slack"],
            "storage": counts["storage"], "snapshots": len(spec.snapshots),
            "outage_snapshots": sum(s.outage_line is not None for s in spec.snapshots)}


def similarity(a, b):
    return sum(min(a[key]+1, b[key]+1)/max(a[key]+1, b[key]+1) for key in a)/len(a)


def outcome(observations, version, verified, required):
    """Distinguish comparable observed violations from unknown or mismatched evidence."""
    if len(observations) != required:
        raise ValueError("Repair snapshot count differs from candidate scope")
    failed, unavailable = set(), 0
    passed = 0
    for item in observations:
        row = item["observation"]
        evidence = row["native_evidence"]
        if evidence["solver_version"] != version or evidence["status"] == "unavailable":
            unavailable += 1
            continue
        if row["passed"]:
            passed += 1
            continue
        native = row["native_verdict"]["checks"]
        trusted = {c["id"]: c["passed"] for c in native}
        if not all(trusted.get(key) is True for key in (
                "model_input_fidelity", "solver_success", "active_bus_coverage", "power_balance_mva")):
            unavailable += 1
            continue
        reasons = {rule_for("ac_native", c["id"]) for c in native if c["passed"] is False}
        if evidence["status"] == "verified":
            physical = (row.get("physical") or {}).get("checks", [])
            reasons.update(rule_for("ac_physical", c["id"]) for c in physical if c["passed"] is False)
        if reasons:
            failed.update(reasons)
        else:
            unavailable += 1
    if verified != (passed == required):
        raise ValueError("Inconsistent candidate verification")
    status = ("verified_original_scope" if verified else
              "rejected_observed_violation" if failed else "inconclusive")
    return {"outcome": status, "verified_snapshots": passed, "required_snapshots": required,
            "unavailable_or_noncomparable_snapshots": unavailable, "failed_rule_ids": sorted(failed)}


def replay_records(root, identifier):
    """Require finalized evidence before replay so no call can start new simulation."""
    root = Path(root).resolve()
    repair = Study.reopen(root / "studies", identifier)
    if not repair.exists("report"):
        raise ValueError("Experience requires a committed repair report")
    manifest = repair.read("manifest")
    if manifest.get("protocol") != REPAIR_PROTOCOL:
        raise ValueError("Unsupported repair experience protocol")
    jobs = manifest["jobs"]
    if not 1 <= len(jobs) <= 60 or not all(
            repair.exists(f"reservation-{i}") and repair.exists(f"evaluation-{i}") for i in range(len(jobs))):
        raise ValueError("Repair evidence incomplete")
    report = resume_repair(root, identifier, solver=no_solver)
    diagnostic = Study.reopen(root / "studies", report["diagnostic_study_id"])
    diagnostic_manifest = diagnostic.read("manifest")
    raw = diagnostic_manifest["spec"]
    if diagnostic_manifest["protocol"] == "adaptive-ac-experiment-v1":
        raw = raw["experiment"]
    spec = ACDiagnosticExperiment.model_validate(raw)
    source = Study.reopen(root / "studies", spec.source_study_id)
    context = features(source.read("manifest")["spec"])
    target = rule_for(spec.target_scope, spec.target_check)
    records = []
    for candidate in report["candidates"]:
        index = candidate["candidate_index"]
        job = next(row for row in manifest["candidates"] if row["index"] == index)
        change = candidate["change"]
        observations = [row for row in report["observations"] if row["candidate_index"] == index]
        result = outcome(observations, manifest["solver_version"], candidate["verified"],
                         candidate["required_snapshots"])
        records.append({"protocol": PROTOCOL, "repair_study_id": identifier,
                        "repair_report_sha256": fingerprint(report), "candidate_index": index,
                        "source_report_sha256": spec.source_report_sha256,
                        "target_rule_id": target, "snapshot_kind": "outage" if spec.snapshot.outage_line else "base",
                        "features": context, "solver_version": manifest["solver_version"],
                        "intervention": job["probe"]["kind"],
                        "direction": "increase" if change["after"] > change["before"] else "decrease",
                        "full_dc_schedule_coverage": report["full_dc_schedule_coverage"],
                        **result, "scope": SCOPE})
    return records


def ensure_table(db):
    db.execute("CREATE TABLE IF NOT EXISTS ac_repair_experience ("
               "study_id TEXT NOT NULL, candidate_index INTEGER NOT NULL, "
               "target_rule TEXT NOT NULL, payload TEXT NOT NULL, "
               "PRIMARY KEY(study_id,candidate_index))")


def remember_ac_repair(root, identifier):
    records = replay_records(root, identifier)
    with closing(connect(root)) as db, db:
        ensure_table(db)
        for row in records:
            payload = json.dumps(row, sort_keys=True, allow_nan=False)
            key = (identifier, row["candidate_index"])
            previous = db.execute("SELECT payload FROM ac_repair_experience WHERE study_id=? AND candidate_index=?",
                                  key).fetchone()
            if previous is not None and previous[0] != payload:
                raise ValueError("Indexed AC experience differs from replayed evidence")
            db.execute("INSERT OR IGNORE INTO ac_repair_experience VALUES (?,?,?,?)",
                       (*key, row["target_rule_id"], payload))
        db.execute("DELETE FROM ac_repair_experience WHERE rowid IN ("
                   "SELECT rowid FROM ac_repair_experience ORDER BY rowid DESC LIMIT -1 OFFSET ?)",
                   (MAX_INDEX_ROWS,))
    return {"study_id": identifier, "indexed_candidates": len(records),
            "outcomes": [row["outcome"] for row in records], "scope": SCOPE}


def source_features(root, source_id, expected_digest, kind):
    source = Study.reopen(root / "studies", source_id)
    report = source.read("report")
    if fingerprint(report) != expected_digest:
        raise ValueError("Physical feature source report changed")
    return physical_features(source.read("manifest")["spec"], report, kind)


def historical_source_id(root, identifier):
    repair = Study.reopen(root / "studies", identifier)
    diagnostic = Study.reopen(root / "studies", repair.read("report")["diagnostic_study_id"])
    manifest = diagnostic.read("manifest")
    raw = manifest["spec"]
    if manifest["protocol"] == "adaptive-ac-experiment-v1":
        raw = raw["experiment"]
    return ACDiagnosticExperiment.model_validate(raw).source_study_id


def search_ac_experience(root, source_study_id, limit=5, *, physical=False):
    if not 1 <= limit <= 10:
        raise ValueError("Experience limit must be 1..10")
    root = Path(root).resolve()
    diagnosis = diagnose_study(root, source_study_id)
    if diagnosis["source_protocol"] != AC_PROTOCOL:
        raise ValueError("AC experience query requires a committed AC cross-check")
    source = Study.reopen(root / "studies", source_study_id)
    query = features(source.read("manifest")["spec"])
    rules = {row["rule_id"] for row in diagnosis["findings"]}
    query_kinds = {}
    for finding in diagnosis["findings"]:
        kinds = query_kinds.setdefault(finding["rule_id"], set())
        for item in finding["evidence"]:
            context = item["context"]
            if isinstance(context, dict) and "snapshot" in context:
                kinds.add("outage" if context["snapshot"].get("outage_line") else "base")
    empty = {"protocol": PROTOCOL, "matches": [], "replayed_studies": 0, "skipped_studies": 0,
             "scope": SCOPE, "solver_calls": 0}
    if not rules or not (root / "experience.sqlite3").is_file():
        return empty
    with closing(connect(root)) as db:
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ac_repair_experience'").fetchone():
            return empty
        # Fixed scan bound; exact rule filter is applied to replayed content too.
        indexed = db.execute("SELECT study_id,candidate_index,payload FROM ac_repair_experience "
                             "ORDER BY rowid DESC LIMIT ?", (MAX_INDEX_ROWS,)).fetchall()
    grouped = {}
    for identifier, index, raw in indexed:
        try:
            row = json.loads(raw)
            if row["target_rule_id"] not in rules:
                continue
            grouped.setdefault(identifier, {})[index] = row
        except (ValueError, TypeError, KeyError):
            continue
    matches, skipped = [], 0
    query_physics = {kind: source_features(root, source_study_id, diagnosis["source_report_sha256"], kind)
                     for kind in ("base", "outage")} if physical else {}
    selected = list(grouped)[:MAX_REPLAY_STUDIES]
    for identifier in selected:
        try:
            records = replay_records(root, identifier)
        except (OSError, ValueError, KeyError, TypeError, IndexError, Timeout):
            skipped += 1
            continue
        by_index = {row["candidate_index"]: row for row in records}
        for index, stored in grouped[identifier].items():
            row = by_index.get(index)
            if row != stored or row["target_rule_id"] not in rules:
                continue
            score = similarity(query, row["features"])
            kinds = query_kinds.get(row["target_rule_id"], set())
            match = {**row, "structure_similarity": round(score, 6),
                     "snapshot_kind_matches": row["snapshot_kind"] in kinds,
                     "same_source_report": row["source_report_sha256"] == diagnosis["source_report_sha256"]}
            if physical:
                try:
                    kind = row["snapshot_kind"]
                    historical = source_features(root, historical_source_id(root, identifier),
                                                 row["source_report_sha256"], kind)
                    comparison = physical_similarity(query_physics[kind], historical)
                except (OSError, ValueError, KeyError, TypeError, IndexError):
                    continue
                match["physical_similarity"] = comparison
                # Missing measurement coverage does not count as agreement.
                physical_score = comparison["score"]
                match["retrieval_score"] = round((score+physical_score)/2 if physical_score is not None else score/2, 6)
            matches.append(match)
    matches.sort(key=lambda row: (-int(row["snapshot_kind_matches"]),
                                  -row.get("retrieval_score", row["structure_similarity"]),
                                  row["repair_study_id"], row["candidate_index"]))
    return {**empty, "matches": matches[:limit], "replayed_studies": len(selected)-skipped,
            "skipped_studies": skipped, "scan_truncated": len(grouped) > len(selected),
            "method": ("exact diagnosis rule, snapshot kind, coarse and derived electrical similarity; not a probability"
                       if physical else "exact diagnosis rule, snapshot kind, coarse count similarity; not a probability")}
