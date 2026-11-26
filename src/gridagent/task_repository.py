"""Transactional storage of versioned engineering tasks in a local workspace."""

from .task_contracts import (
    TERMINAL_STATUSES,
    EngineeringTask,
    RequirementSpec,
    TaskEvent,
    TaskStatus,
    request_cancellation,
    revise_requirement,
    transition_task,
)


class TaskRevisionConflict(ValueError):
    """The caller used a stale task revision; reload before retrying."""


class EngineeringTaskRepository:
    """Persist the canonical state using the existing ResearchStore connection.

    Each committed mutation appends exactly one immutable snapshot and event.
    The head is advanced in the same transaction. Legacy session and research
    tables are deliberately unaffected.
    """

    def __init__(self, store):
        self._store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS engineering_tasks (
                    task_id TEXT PRIMARY KEY,
                    head_revision INTEGER NOT NULL CHECK(head_revision >= 0)
                );
                CREATE TABLE IF NOT EXISTS engineering_task_revisions (
                    task_id TEXT NOT NULL REFERENCES engineering_tasks(task_id),
                    revision INTEGER NOT NULL CHECK(revision >= 0),
                    snapshot TEXT NOT NULL,
                    event_id TEXT UNIQUE,
                    event TEXT,
                    PRIMARY KEY(task_id, revision),
                    CHECK((revision = 0 AND event_id IS NULL AND event IS NULL)
                        OR (revision > 0 AND event_id IS NOT NULL AND event IS NOT NULL))
                );
            """)

    @staticmethod
    def _read_snapshot(row):
        if row is None:
            raise ValueError("Unknown engineering task or revision")
        snapshot = EngineeringTask.model_validate_json(row["snapshot"])
        if snapshot.task_id != row["task_id"] or snapshot.revision != row["revision"]:
            raise ValueError("Engineering task snapshot identity mismatch")
        return snapshot

    @classmethod
    def _head(cls, db, task_id):
        row = db.execute("""
            SELECT r.* FROM engineering_tasks t
            JOIN engineering_task_revisions r
              ON r.task_id = t.task_id AND r.revision = t.head_revision
            WHERE t.task_id = ?
        """, (task_id,)).fetchone()
        return cls._read_snapshot(row)

    @staticmethod
    def _create_in(db, requirement: RequirementSpec, *, task_id=None, model_revision=None) -> EngineeringTask:
        """Create a task inside the caller's write transaction."""
        requirement = RequirementSpec.model_validate(requirement)
        if requirement.revision != 1:
            raise ValueError("A new engineering task must start with requirement revision 1")
        identity = {} if task_id is None else {"task_id": task_id}
        snapshot = EngineeringTask(requirement=requirement, model_revision=model_revision, **identity)
        db.execute("INSERT INTO engineering_tasks VALUES (?, 0)", (snapshot.task_id,))
        db.execute("""
            INSERT INTO engineering_task_revisions(task_id, revision, snapshot)
            VALUES (?, 0, ?)
        """, (snapshot.task_id, snapshot.model_dump_json()))
        return snapshot

    def create(self, requirement: RequirementSpec) -> EngineeringTask:
        with self._store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            return self._create_in(db, requirement)

    @classmethod
    def _find_in(cls, db, task_id):
        """Return None only for a task that has no V2 head, not for corrupt snapshots."""
        if db.execute("SELECT 1 FROM engineering_tasks WHERE task_id = ?", (task_id,)).fetchone() is None:
            return None
        return cls._head(db, task_id)

    def get(self, task_id: str) -> EngineeringTask:
        with self._store.connect() as db:
            return self._head(db, task_id)

    def get_revision(self, task_id: str, revision: int) -> EngineeringTask:
        with self._store.connect() as db:
            row = db.execute("""
                SELECT * FROM engineering_task_revisions WHERE task_id = ? AND revision = ?
            """, (task_id, revision)).fetchone()
            return self._read_snapshot(row)

    def events(self, task_id: str) -> tuple[TaskEvent, ...]:
        """Return committed events in sequence order, checking identity and continuity."""
        with self._store.connect() as db:
            # A read transaction keeps the head and its revisions consistent during concurrent writes.
            db.execute("BEGIN")
            head = self._head(db, task_id)
            rows = db.execute("""
                SELECT * FROM engineering_task_revisions
                WHERE task_id = ? AND revision > 0 ORDER BY revision
            """, (task_id,)).fetchall()
            if len(rows) != head.revision:
                raise ValueError("Engineering task event history is incomplete")
            previous = self._read_snapshot(db.execute("""
                SELECT * FROM engineering_task_revisions WHERE task_id = ? AND revision = 0
            """, (task_id,)).fetchone())
            events = []
            for sequence, row in enumerate(rows, start=1):
                snapshot = self._read_snapshot(row)
                event = TaskEvent.model_validate_json(row["event"])
                if (snapshot.revision != sequence or event.sequence != sequence
                        or event.task_id != task_id or event.event_id != row["event_id"]
                        or event.from_status != previous.status or event.to_status != snapshot.status
                        or event.occurred_at != snapshot.updated_at):
                    raise ValueError("Engineering task event history is inconsistent")
                events.append(event)
                previous = snapshot
            if previous != head:
                raise ValueError("Engineering task history does not match the head")
            return tuple(events)

    def unfinished(self) -> tuple[EngineeringTask, ...]:
        """Discover resumable or interrupted tasks without automatically rerunning them."""
        with self._store.connect() as db:
            rows = db.execute("""
                SELECT r.* FROM engineering_tasks t
                JOIN engineering_task_revisions r
                  ON r.task_id = t.task_id AND r.revision = t.head_revision
                ORDER BY t.task_id
            """).fetchall()
        snapshots = (self._read_snapshot(row) for row in rows)
        return tuple(task for task in snapshots if task.status not in TERMINAL_STATUSES)

    def _mutate_in(self, db, task_id, expected_revision, operation):
        """Apply one mutation using the caller's active write transaction."""
        current = self._head(db, task_id)
        if current.revision != expected_revision:
            raise TaskRevisionConflict(
                f"Expected revision {expected_revision}, found {current.revision}; reload task"
            )
        updated, event = operation(current)
        if (updated.task_id != task_id or event.task_id != task_id
                or updated.revision != current.revision + 1 or event.sequence != updated.revision
                or event.from_status != current.status or event.to_status != updated.status
                or event.occurred_at != updated.updated_at):
            raise ValueError("Invalid engineering task mutation")
        db.execute("""
            INSERT INTO engineering_task_revisions(task_id, revision, snapshot, event_id, event)
            VALUES (?, ?, ?, ?, ?)
        """, (task_id, updated.revision, updated.model_dump_json(), event.event_id, event.model_dump_json()))
        result = db.execute("""
            UPDATE engineering_tasks SET head_revision = ?
            WHERE task_id = ? AND head_revision = ?
        """, (updated.revision, task_id, expected_revision))
        if result.rowcount != 1:
            raise TaskRevisionConflict("Engineering task changed during the transaction")
        return updated, event

    def _mutate(self, task_id, expected_revision, operation):
        # Serialize competing writers even when they use separate processes/connections.
        with self._store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            research_table = db.execute("""
                SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'research_tasks'
            """).fetchone()
            if research_table and db.execute(
                    "SELECT 1 FROM research_tasks WHERE id = ?", (task_id,)).fetchone():
                raise ValueError("Research-managed tasks must be changed through ResearchTasks")
            dispatch_table = db.execute("""
                SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'dispatch_tasks'
            """).fetchone()
            if dispatch_table and db.execute(
                    "SELECT 1 FROM dispatch_tasks WHERE id = ?", (task_id,)).fetchone():
                raise ValueError("Dispatch-managed tasks must be changed through DispatchTasks")
            return self._mutate_in(db, task_id, expected_revision, operation)

    def transition(self, task_id: str, expected_revision: int, target: TaskStatus, **kwargs):
        return self._mutate(
            task_id, expected_revision, lambda task: transition_task(task, target, **kwargs)
        )

    def request_cancel(self, task_id: str, expected_revision: int, **kwargs):
        return self._mutate(
            task_id, expected_revision, lambda task: request_cancellation(task, **kwargs)
        )

    def revise(self, task_id: str, expected_revision: int, requirement: RequirementSpec, **kwargs):
        requirement = RequirementSpec.model_validate(requirement)
        return self._mutate(
            task_id, expected_revision, lambda task: revise_requirement(task, requirement, **kwargs)
        )
