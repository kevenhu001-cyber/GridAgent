"""Opt-in, local AC cache for already verified native evidence.

Cache entries are hints. Every reuse checks the source and publishes an
independent copy under the newly reserved run ID before fresh verification.
"""

import hashlib
import json
import os
import platform
import re
import shutil
import sys
from importlib.metadata import PackageNotFoundError, distributions, version
from pathlib import Path
from uuid import uuid4

from .engineering_ir import fingerprint
from .evidence import AC_FILES, EvidenceRecord, artifact_digest, verify_artifacts
from .workspace import artifact_folder, load_object

CACHE_VERSION = 1
MAX_ENTRIES = 512
MODULES = ("native_worker.py", "native_program.py", "native_backends.py",
           "model_quality.py", "research_spec.py", "engineering_compiler.py",
           "research.py", "evidence.py", "verified_cache.py")


def runtime_identity():
    """Conservative identity: installed distribution versions plus local implementation hashes."""
    try:
        backend_version = version("pandapower")
        packages = sorted((dist.metadata["Name"].lower(), dist.version) for dist in distributions()
                          if dist.metadata.get("Name"))
        folder = Path(__file__).parent
        modules = {name: hashlib.sha256((folder / name).read_bytes()).hexdigest() for name in MODULES}
    except (OSError, PackageNotFoundError):
        return None
    return {
        "schema": CACHE_VERSION, "backend": "pandapower", "backend_version": backend_version,
        "python": sys.version, "platform": platform.platform(), "machine": platform.machine(),
        "packages_sha256": fingerprint(packages), "modules": modules,
        "settings": {"numba": False, "max_iteration": 30, "check_connectivity": True,
                     "native_threads": 1, "timeout_s": 300},
    }


def cache_enabled():
    return os.getenv("GRIDAGENT_VERIFIED_CACHE", "0") == "1"


class VerifiedCache:
    def __init__(self, store, root, identity):
        self.store, self.root, self.identity = store, Path(root), identity
        with store.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS verified_ac_cache (
                    cache_key TEXT PRIMARY KEY, record TEXT NOT NULL, verdict TEXT NOT NULL,
                    created_at INTEGER NOT NULL DEFAULT (unixepoch())
                )
            """)

    def key(self, plan, request, limits):
        return fingerprint({"runtime": self.identity, "model": plan.model_sha256,
                            "evaluator": plan.evaluator, "request": request, "limits": limits})

    def publish(self, key, record, verdict):
        record = EvidenceRecord.model_validate(record)
        if (record.status != "verified" or record.evaluator != "ac-research-v1"
                or record.solver_version != self.identity["backend_version"]
                or record.verdict_sha256 != fingerprint(verdict)
                or set(record.required_artifacts) != set(AC_FILES)
                or not verify_artifacts(self.root, record)):
            return
        with self.store.connect() as db:
            db.execute("""INSERT INTO verified_ac_cache(cache_key,record,verdict) VALUES (?,?,?)
                          ON CONFLICT(cache_key) DO UPDATE SET record=excluded.record,
                          verdict=excluded.verdict,created_at=unixepoch()""",
                       (key, record.model_dump_json(), json.dumps(verdict, allow_nan=False)))
            db.execute("""DELETE FROM verified_ac_cache WHERE cache_key IN (
                          SELECT cache_key FROM verified_ac_cache ORDER BY created_at DESC,cache_key
                          LIMIT -1 OFFSET ?)""", (MAX_ENTRIES,))

    def restore(self, key, request, run_id, *, recheck, cancelled):
        """Return the source run ID on hit, or None before publishing anything on a miss."""
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid cache destination run ID")
        with self.store.connect() as db:
            row = db.execute("SELECT record,verdict FROM verified_ac_cache WHERE cache_key=?", (key,)).fetchone()
        if row is None or cancelled():
            return None
        staging = None
        try:
            record = EvidenceRecord.model_validate_json(row["record"])
            verdict = json.loads(row["verdict"])
            if (record.status != "verified" or record.evaluator != "ac-research-v1"
                    or record.request_sha256 != fingerprint(request)
                    or record.solver_version != self.identity["backend_version"]
                    or record.verdict_sha256 != fingerprint(verdict)
                    or set(record.required_artifacts) != set(AC_FILES)
                    or not verify_artifacts(self.root, record)):
                return None
            source = artifact_folder(self.root, "runs", record.run_id)
            saved = load_object(source / "request.json")
            result = load_object(source / "result.json")
            if (saved != request or result.get("status") != "ok" or result.get("backend") != "pandapower"
                    or result.get("run_id") != record.run_id or result.get("version") != record.solver_version
                    or result.get("cache_origin_run_id") is not None or not recheck(result)["passed"]):
                return None
            runs = (self.root / "runs").resolve()
            destination = runs / run_id
            if destination.exists():
                raise ValueError("Cache destination already exists")
            staging = runs / (".cache-" + uuid4().hex)
            staging.mkdir()
            for item in record.artifacts:
                shutil.copyfile(source / item.name, staging / item.name)
                if artifact_digest(staging, item.name) != item:
                    return None
            if cancelled():
                return None
            # Read the verified copied identity rather than retaining a stale in-memory source.
            result = load_object(staging / "result.json")
            result["run_id"] = run_id
            result["cache_origin_run_id"] = record.run_id
            result["cache_key"] = key
            (staging / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
            staging.rename(destination)
            return record.run_id
        except (OSError, ValueError, TypeError, KeyError):
            return None
        finally:
            if staging is not None and staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
