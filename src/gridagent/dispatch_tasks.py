"""One-run dispatch workflow on the canonical engineering task repository."""

import json
import re
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from .dispatch_ir import DispatchStudy, compile_dispatch
from .engineering_ir import fingerprint
from .evidence import capture_evidence
from .execution_journal import ExecutionJournal
from .execution_plan import ExecutionPlan, dispatch_plan
from .model_quality import evaluate_run
from .native_backends import run_program
from .store import ResearchStore
from .task_contracts import (
    TERMINAL_STATUSES,
    RequirementSpec,
    TaskEvent,
    TaskStatus,
    request_cancellation,
    transition_task,
)
from .workspace import artifact_folder, load_object


class DispatchTasks(ResearchStore):
    """Persist the source, single native reservation and independently checked verdict.

    Shares the canonical task IDs, transitions and transaction machinery with AC research.
    A reserved run is never automatically executed twice, including on process restart.
    """

    def __init__(self, root):
        self.root = Path(root).resolve()
        super().__init__(self.root / "research.sqlite3")
        self.repository = self.engineering_tasks()
        self.journal = ExecutionJournal(self)
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS dispatch_tasks (
                    id TEXT PRIMARY KEY REFERENCES engineering_tasks(task_id),
                    source TEXT NOT NULL,
                    run_id TEXT UNIQUE,
                    evidence TEXT
                )
            """)

    def _read_in(self, db, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Use a full dispatch task ID")
        row = db.execute("SELECT * FROM dispatch_tasks WHERE id = ?", (identifier,)).fetchone()
        if row is None:
            raise ValueError("Unknown dispatch task")
        return self.repository._head(db, identifier), dict(row)

    def _move(self, db, task, target, **kwargs):
        if target == TaskStatus.CANCELLED:
            self.journal.cancel(db, task.task_id)
        updated, _ = self.repository._mutate_in(
            db, task.task_id, task.revision, lambda current: transition_task(current, target, **kwargs)
        )
        return updated

    def start(self, source):
        program, provenance = compile_dispatch(source)
        request = program.model_dump(mode="json")
        plan = dispatch_plan(request, provenance)
        frozen = json.dumps({"provenance": provenance, "program": request,
                             "execution_plan": plan.model_dump(mode="json"),
                             "execution_plan_sha256": plan.sha256(),
                             "execution_journal_version": 1}, allow_nan=False, ensure_ascii=False)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task = self.repository._create_in(
                db, RequirementSpec(request=provenance["study"]["description"]),
                model_revision=provenance["model_sha256"],
            )
            db.execute("INSERT INTO dispatch_tasks(id, source) VALUES (?, ?)", (task.task_id, frozen))
            self.journal.register(db, task.task_id, plan)
            self._move(db, task, TaskStatus.PLANNED, plan_revision=1,
                       reason=f"Execution plan: {plan.sha256()}; Frozen dispatch study: {provenance['study_sha256']}")
        return task.task_id

    def summary(self, identifier):
        with self.connect() as db:
            db.execute("BEGIN")
            task, row = self._read_in(db, identifier)
            graph, nodes = self.journal.load(db, identifier)
        return {
            "id": identifier, "status": task.status.value, "revision": task.revision,
            "cancel_requested": task.cancel_requested, "reason": task.terminal_reason,
            "model_sha256": task.model_revision, "run_id": row["run_id"],
            "source": json.loads(row["source"]),
            "evidence": json.loads(row["evidence"]) if row["evidence"] else None,
            **({"execution_nodes": list(nodes.values())} if graph is not None else {}),
        }

    def _lock(self, identifier):
        if not re.fullmatch(r"[a-f0-9]{32}", identifier):
            raise ValueError("Use a full dispatch task ID")
        directory = self.root / "dispatch-locks"
        directory.mkdir(exist_ok=True)
        return FileLock(str(directory / (identifier + ".lock")), timeout=0)

    def _validate_frozen(self, db, task, row):
        data = json.loads(row["source"])
        p = data["provenance"]
        program, provenance = compile_dispatch(DispatchStudy(model=p["model"], study=p["study"]))
        plan_row = db.execute("""
            SELECT event FROM engineering_task_revisions WHERE task_id=? AND revision=1
        """, (task.task_id,)).fetchone()
        plan = TaskEvent.model_validate_json(plan_row["event"]) if plan_row else None
        request = program.model_dump(mode="json")
        reason = "Frozen dispatch study: " + p["study_sha256"]
        if (provenance != p or request != data["program"]
                or task.model_revision != p["model_sha256"] or plan is None):
            raise ValueError("Frozen dispatch compiler provenance changed")
        expected = dispatch_plan(request, p)
        if plan.reason != reason:
            if "execution_plan" not in data:
                raise ValueError("Frozen dispatch compiler provenance changed: missing execution plan")
            actual = ExecutionPlan.model_validate(data["execution_plan"])
            if (actual != expected or data.get("execution_plan_sha256") != actual.sha256()
                    or plan.reason != f"Execution plan: {actual.sha256()}; " + reason):
                raise ValueError("Frozen dispatch execution plan changed")
            return request, actual
        if "execution_plan" in data or "execution_plan_sha256" in data:
            raise ValueError("Dispatch execution plan has no matching lifecycle event")
        return request, None

    def cancel(self, identifier):
        """Request cancellation; only a worker holding the execution lock acknowledges it."""
        from filelock import Timeout

        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            task, _ = self._read_in(db, identifier)
            if task.status not in TERMINAL_STATUSES and not task.cancel_requested:
                self.repository._mutate_in(db, identifier, task.revision, request_cancellation)
        try:
            with self._lock(identifier), self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                task, _ = self._read_in(db, identifier)
                if task.cancel_requested and task.status not in TERMINAL_STATUSES:
                    self._move(db, task, TaskStatus.CANCELLED)
        except Timeout:
            pass
        return self.summary(identifier)

    def resume(self, identifier, *, solver=run_program):
        with self._lock(identifier):
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                task, row = self._read_in(db, identifier)
                if task.status in TERMINAL_STATUSES:
                    execute = False
                    run_id = None
                elif task.cancel_requested:
                    self._move(db, task, TaskStatus.CANCELLED)
                    execute = False
                    run_id = None
                else:
                    request, plan = self._validate_frozen(db, task, row)
                    graph, nodes = self.journal.load(db, identifier, plan)
                    source = json.loads(row["source"])
                    if (source.get("execution_journal_version") == 1) != (graph is not None):
                        raise ValueError("Dispatch journal registration is inconsistent")
                    if graph is not None and graph != plan:
                        raise ValueError("Journal differs from frozen execution plan")
                    node = plan.solve_for("dispatch", request) if plan is not None else None
                    run_id = row["run_id"]
                    if graph is not None and nodes[node.id]["run_id"] != run_id:
                        raise ValueError("Dispatch checkpoint differs from committed reservation")
                    execute = run_id is None
                    if execute:
                        if task.status != TaskStatus.PLANNED:
                            raise ValueError("Dispatch reservation is missing")
                        run_id = uuid4().hex
                        if graph is not None:
                            self.journal.reserve(db, identifier, node.id, run_id)
                        db.execute("UPDATE dispatch_tasks SET run_id=? WHERE id=?", (run_id, identifier))
                        self._move(db, task, TaskStatus.RUNNING)
            if run_id is None:
                return self.summary(identifier)
            launch_error = None
            if execute:
                # Only the newly committed reservation may launch a native job.
                # The PyPSA plugin currently stops cooperatively only at the call boundary.
                try:
                    solver(self.root, request, run_id=run_id)
                except Exception as exc:  # noqa: BLE001 - preserve unknown execution outcome
                    launch_error = type(exc).__name__
            evidence = self._recover(run_id, request)
            if launch_error is not None:
                evidence["launch_error_type"] = launch_error
            if plan is not None:
                verdict = evidence.get("quality") or {"passed": False, "checks": []}
                envelope = capture_evidence(self.root, plan, "dispatch", run_id, request,
                                            version=evidence.get("solver_version"), verdict=verdict)
                if evidence["passed"] and envelope.status != "verified":
                    evidence.update(passed=False, reason="artifact_provenance_failed")
                evidence["evidence_record"] = envelope.model_dump(mode="json")
            with self.connect() as db:
                db.execute("BEGIN IMMEDIATE")
                task, _ = self._read_in(db, identifier)
                if graph is not None:
                    self.journal.finish(db, identifier, envelope)
                    if not task.cancel_requested:
                        outcome = self.journal.aggregate(db, identifier)
                        if evidence["passed"] != (outcome == "verified"):
                            raise ValueError("Dispatch completion differs from aggregated evidence")
                db.execute("UPDATE dispatch_tasks SET evidence=? WHERE id=?",
                           (json.dumps(evidence, allow_nan=False), identifier))
                if task.cancel_requested:
                    self._move(db, task, TaskStatus.CANCELLED)
                else:
                    if task.status == TaskStatus.RUNNING:
                        task = self._move(db, task, TaskStatus.VERIFYING)
                    if evidence["passed"]:
                        self._move(db, task, TaskStatus.COMPLETED, actor="verifier",
                                   reason="Independent dispatch checks passed")
                    else:
                        self._move(db, task, TaskStatus.FAILED, reason=evidence["reason"])
        return self.summary(identifier)

    def _recover(self, run_id, request):
        """Re-evaluate persisted native artifacts; never trust a solver's claimed quality alone."""
        evidence = {"run_id": run_id, "request_sha256": fingerprint(request),
                    "passed": False, "reason": "unknown_or_missing_native_result"}
        try:
            folder = artifact_folder(self.root, "runs", run_id)
            saved = load_object(folder / "request.json")
            result = load_object(folder / "result.json")
            if saved != request or result.get("run_id") != run_id or result.get("backend") != "pypsa":
                evidence["reason"] = "native_evidence_identity_mismatch"
                return evidence
            quality = evaluate_run(folder, request, result)
            if result.get("status") == "ok" and (
                    result.get("solver_status") != "ok" or result.get("termination_condition") != "optimal"):
                evidence["reason"] = "native_optimization_status_unverified"
                return evidence
            if not isinstance(result.get("version"), str) or not result["version"]:
                evidence["reason"] = "native_solver_version_missing"
                return evidence
            evidence.update(solver_status=result.get("status"), solver_version=result["version"],
                            metrics=result.get("metrics"), quality=quality, passed=quality["passed"],
                            reason="verified" if quality["passed"] else "dispatch_checks_failed")
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return evidence
