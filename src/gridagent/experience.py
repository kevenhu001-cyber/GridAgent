"""Local experience from completed, independently rechecked native repairs only.

No paper labels, fixed modeling benchmark solutions, user model values or free
text rationales are indexed. Local artifacts are trusted, not tamper-proof.
"""
import copy
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from .dsr import Study, digest
from .model_quality import PROTOCOL, evaluate_run
from .workspace import artifact_folder, load_object


def connect(root):
    path = Path(root) / "experience.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS verified_repairs "
               "(study_id TEXT PRIMARY KEY, backend TEXT NOT NULL, payload TEXT NOT NULL)")
    return db


def recheck(root, study, iteration, candidate):
    entry = study.read(f"iteration-{iteration}")
    if entry.get("candidate_sha256") != digest(candidate):
        raise ValueError("Candidate digest mismatch")
    result = entry["result"]
    run_id = result["run_id"]
    folder = artifact_folder(Path(root), "runs", run_id)
    saved = load_object(folder / "result.json")
    if saved != result or load_object(folder / "request.json") != candidate:
        raise ValueError("Stored run does not match candidate and iteration")
    if saved.get("status") != "ok" or saved.get("backend") != candidate["backend"]:
        raise ValueError("Only comparable converged simulations are learned")
    quality = evaluate_run(folder, candidate, saved)
    if quality != saved.get("quality") or quality != load_object(folder / "quality.json"):
        raise ValueError("Independent quality replay differs")
    return run_id, saved, quality


def remember_repair(root, study_id):
    # Import lazily to avoid a module cycle; the same authorization logic is reused.
    from .model_repair import Manifest, leaf

    study = Study.reopen(Path(root) / "studies", study_id)
    envelope = study.read("manifest")
    if envelope.get("protocol") != "gridagent-native-repair-v1":
        return False
    frozen = envelope["manifest"]
    if envelope["manifest_sha256"] != digest(frozen):
        raise ValueError("Manifest digest mismatch")
    manifest = Manifest.model_validate(frozen)
    report = study.read("report")
    index = report.get("best_iteration")
    if report.get("passed") is not True or not isinstance(index, int) or not 1 <= index <= manifest.max_repairs:
        return False
    before = study.read("candidate-0")
    after = study.read(f"candidate-{index}")
    if before != manifest.initial.model_dump(mode="json") or after != study.read("best-program"):
        raise ValueError("Model provenance mismatch")
    reconstructed = copy.deepcopy(before)
    changes = []
    for path in manifest.editable_paths:
        src, field = leaf(before, path)
        dst, _ = leaf(after, path)
        target, _ = leaf(reconstructed, path)
        if src[field] == dst[field]:
            continue
        target[field] = dst[field]
        group = path.split("/")[1]
        changes.append({"component": src.get("element", src.get("op", group)),
                        "parameter": src.get("field", field) if field == "value" else field,
                        "direction": "increase" if dst[field] > src[field] else "decrease"})
    if not changes or reconstructed != after:
        raise ValueError("Unapproved model difference")
    baseline_id, baseline, old_quality = recheck(root, study, 0, before)
    best_id, best, new_quality = recheck(root, study, index, after)
    if old_quality["passed"] or not new_quality["passed"] or best_id != report["best_run_id"]:
        return False
    if baseline.get("version") != best.get("version") or not best.get("version"):
        return False
    failed = [t["id"] for t in old_quality["tests"] if not t["passed"]]
    payload = {"study_id": study_id, "backend": after["backend"], "backend_version": best["version"],
               "operation": best["operation"], "quality_protocol": PROTOCOL,
               "baseline_run_id": baseline_id, "verified_run_id": best_id,
               "failed_checks": failed, "changes": changes,
               "scope": "historical local repair; candidate must be revalidated in the new model"}
    with closing(connect(root)) as db, db:
        db.execute("INSERT OR IGNORE INTO verified_repairs VALUES (?, ?, ?)",
                   (study_id, payload["backend"], json.dumps(payload, allow_nan=False)))
    return True


def search_experience(root, backend, failed_checks, limit=5):
    if backend not in {"pandapower", "pypsa"} or not 1 <= limit <= 10:
        raise ValueError("Invalid backend or limit")
    if not failed_checks or not (Path(root) / "experience.sqlite3").is_file():
        return []
    keys = set(failed_checks)
    with closing(connect(root)) as db:
        rows = [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM verified_repairs WHERE backend=? ORDER BY rowid DESC LIMIT 500", (backend,))]
    matches = [row for row in rows if row["quality_protocol"] == PROTOCOL and keys.intersection(row["failed_checks"])]
    matches.sort(key=lambda row: -len(keys.intersection(row["failed_checks"])))
    return matches[:limit]


def failure_experience(root, backend, quality):
    """Failure of optional local memory must not prevent an engineering run."""
    if backend not in {"pandapower", "pypsa"}:
        return []
    failed = [t["id"] for t in quality.get("tests", []) if not t["passed"]]
    try:
        return search_experience(root, backend, failed)
    except (OSError, sqlite3.Error, ValueError, KeyError, TypeError):
        return []


def list_experience(root, limit=30):
    if not 1 <= limit <= 100:
        raise ValueError("Invalid limit")
    if not (Path(root) / "experience.sqlite3").is_file():
        return []
    with closing(connect(root)) as db:
        return [json.loads(row[0]) for row in db.execute(
            "SELECT payload FROM verified_repairs ORDER BY rowid DESC LIMIT ?", (limit,))]
