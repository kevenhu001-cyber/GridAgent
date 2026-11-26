"""Transactional node journal for fixed engineering DAGs.

The caller owns the task execution lock and SQLite write transaction. Native
calls happen outside the transaction, only after a reservation is committed.
"""

import re

from .evidence import EvidenceRecord
from .execution_plan import ExecutionPlan
from .store import now


class ExecutionJournal:
    def __init__(self, store):
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS execution_graphs (
                    task_id TEXT PRIMARY KEY REFERENCES engineering_tasks(task_id),
                    plan_sha256 TEXT NOT NULL,
                    plan TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS execution_nodes (
                    task_id TEXT NOT NULL REFERENCES execution_graphs(task_id),
                    node_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','reserved','done','cancelled')),
                    run_id TEXT,
                    outcome TEXT,
                    evidence_sha256 TEXT,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(task_id,node_id)
                );
                CREATE UNIQUE INDEX IF NOT EXISTS execution_unique_run
                ON execution_nodes(run_id) WHERE run_id IS NOT NULL;
            """)

    @staticmethod
    def register(db, task_id, plan):
        plan = ExecutionPlan.model_validate(plan)
        db.execute("INSERT INTO execution_graphs VALUES (?,?,?)",
                   (task_id, plan.sha256(), plan.model_dump_json()))
        db.executemany("INSERT INTO execution_nodes VALUES (?,?,'pending',NULL,NULL,NULL,?)",
                       [(task_id, node.id, now()) for node in plan.nodes])

    @staticmethod
    def plan(db, task_id):
        row = db.execute("SELECT * FROM execution_graphs WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            return None
        plan = ExecutionPlan.model_validate_json(row["plan"])
        if plan.sha256() != row["plan_sha256"]:
            raise ValueError("Stored execution graph fingerprint changed")
        return plan

    @staticmethod
    def rows(db, task_id):
        return {row["node_id"]: dict(row) for row in db.execute(
            "SELECT * FROM execution_nodes WHERE task_id=? ORDER BY node_id", (task_id,))}

    def load(self, db, task_id, expected=None):
        plan = self.plan(db, task_id)
        if plan is None:
            return None, {}
        if expected is not None and expected != plan:
            raise ValueError("Journal differs from frozen execution plan")
        rows = self.rows(db, task_id)
        if set(rows) != {n.id for n in plan.nodes}:
            raise ValueError("Execution journal node set is incomplete")
        done = {key for key, row in rows.items() if row["status"] == "done"}
        plan.ready(done)
        for node in plan.nodes:
            row = rows[node.id]
            if node.kind == "solve":
                if row["status"] in {"reserved", "done"} and not re.fullmatch(
                        r"[a-f0-9]{32}", row["run_id"] or ""):
                    raise ValueError("Invalid solver reservation")
            elif row["run_id"] is not None or row["status"] == "reserved":
                raise ValueError("Only solve nodes can hold native reservations")
        return plan, rows

    def reserve(self, db, task_id, node_id, run_id):
        plan, rows = self.load(db, task_id)
        if plan is None:
            return
        node = next((n for n in plan.nodes if n.id == node_id), None)
        if node is None or node.kind != "solve" or not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid solve reservation")
        row = rows[node_id]
        if row["status"] in {"reserved", "done"} and row["run_id"] == run_id:
            return
        done = [key for key, item in rows.items() if item["status"] == "done"]
        if row["status"] != "pending" or node not in plan.ready(done):
            raise ValueError("Solve node is not ready or already reserved")
        used = sum(item["run_id"] is not None for item in rows.values())
        if used >= plan.max_solver_runs:
            raise ValueError("Execution plan solver budget exhausted")
        db.execute("UPDATE execution_nodes SET status='reserved',run_id=?,updated_at=? "
                   "WHERE task_id=? AND node_id=?", (run_id, now(), task_id, node_id))

    def finish(self, db, task_id, record):
        plan, rows = self.load(db, task_id)
        if plan is None:
            return
        record = EvidenceRecord.model_validate(record)
        node = next((n for n in plan.nodes if n.id == record.solve_node_id), None)
        if (node is None or node.kind != "solve" or record.plan_sha256 != plan.sha256()
                or record.request_sha256 != node.request_sha256 or record.scenario != node.scenario
                or record.evaluator != plan.evaluator):
            raise ValueError("Evidence does not match journal plan")
        solve = rows[node.id]
        verify = next(n for n in plan.nodes if n.kind == "verify" and n.depends_on == (node.id,))
        verification = rows[verify.id]
        digest = record.sha256()
        if solve["run_id"] != record.run_id:
            raise ValueError("Evidence run does not match reservation")
        if solve["status"] == "done" and verification["status"] == "done":
            if verification["evidence_sha256"] != digest or verification["outcome"] != record.status:
                raise ValueError("Committed verification cannot change")
            return
        if solve["status"] != "reserved" or verification["status"] != "pending":
            raise ValueError("Verification has no active solve reservation")
        db.execute("UPDATE execution_nodes SET status='done',outcome=?,updated_at=? "
                   "WHERE task_id=? AND node_id=?", ("observed" if record.status != "unavailable" else "unknown",
                                                    now(), task_id, node.id))
        db.execute("UPDATE execution_nodes SET status='done',outcome=?,evidence_sha256=?,updated_at=? "
                   "WHERE task_id=? AND node_id=?", (record.status, digest, now(), task_id, verify.id))

    def aggregate(self, db, task_id):
        plan, rows = self.load(db, task_id)
        if plan is None:
            return None
        node = next(n for n in plan.nodes if n.kind == "aggregate")
        if rows[node.id]["status"] == "done":
            return rows[node.id]["outcome"]
        done = {key for key, row in rows.items() if row["status"] == "done"}
        if rows[node.id]["status"] != "pending" or node not in plan.ready(done):
            raise ValueError("Cannot aggregate incomplete verification nodes")
        outcome = "verified" if all(rows[key]["outcome"] == "verified" for key in node.depends_on) else "rejected"
        db.execute("UPDATE execution_nodes SET status='done',outcome=?,updated_at=? "
                   "WHERE task_id=? AND node_id=?", (outcome, now(), task_id, node.id))
        return outcome

    def cancel(self, db, task_id):
        """Called only when the task execution lock is held and cancellation acknowledged."""
        db.execute("UPDATE execution_nodes SET status='cancelled',outcome=CASE "
                   "WHEN status='reserved' THEN 'unknown' ELSE 'not_started' END,updated_at=? "
                   "WHERE task_id=? AND status IN ('pending','reserved')", (now(), task_id))

    def sync_ac(self, db, task_id, state, stage):
        """Mirror AC reservation/evaluation checkpoints in the same write transaction."""
        plan, rows = self.load(db, task_id)
        if plan is None:
            if state.get("execution_journal_version") == 1:
                raise ValueError("Execution journal registration is missing")
            return
        if state.get("execution_journal_version") != 1 or state.get("execution_plan_sha256") != plan.sha256():
            raise ValueError("Journal differs from AC task plan")
        attempts = state["attempts"]
        if len(attempts) > 1:
            raise ValueError("Fixed execution journal cannot contain repairs")
        runs = attempts[0]["runs"] if attempts else []
        seen = {run["solve_node_id"]: run for run in runs}
        if len(seen) != len(runs):
            raise ValueError("Duplicate solver node reservation")
        for key, row in rows.items():
            if row["run_id"] is not None and (key not in seen or seen[key]["run_id"] != row["run_id"]):
                raise ValueError("Existing solver reservation removed or replaced")
            if row["run_id"] is not None and row["status"] == "done" and seen[key]["status"] == "reserved":
                raise ValueError("Committed verification cannot return to reserved")
        for key, run in seen.items():
            self.reserve(db, task_id, key, run["run_id"])
            if run["status"] != "reserved":
                self.finish(db, task_id, run["evidence_record"])
        if stage == "cancelled":
            self.cancel(db, task_id)
        elif stage == "failed" and state.get("termination") == "model_input_fidelity_failed":
            self.cancel(db, task_id)
        elif stage in {"passed", "failed"}:
            outcome = self.aggregate(db, task_id)
            if (stage == "passed") != (outcome == "verified"):
                raise ValueError("Task completion differs from aggregated evidence")
