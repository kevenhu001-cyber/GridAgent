"""Local research session and append-only task event storage."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from langchain_core.messages import HumanMessage, messages_from_dict, messages_to_dict


def now():
    return datetime.now(UTC).isoformat()


class ResearchStore:
    def __init__(self, path: Path):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                    prompt TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                    finished_at TEXT, error TEXT
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id),
                    node TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tasks_session ON tasks(session_id, created_at);
                CREATE INDEX IF NOT EXISTS events_task ON events(task_id, id);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            with db:
                yield db
        finally:
            db.close()

    def create_session(self, title="New research session"):
        sid = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (sid, title, now()))
        return sid

    def sessions(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                """SELECT s.*, (SELECT COUNT(*) FROM tasks t WHERE t.session_id=s.id) AS tasks
                   FROM sessions s ORDER BY s.created_at DESC, s.id"""
            )]

    def require_session(self, sid):
        with self.connect() as db:
            if db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone() is None:
                raise ValueError("Unknown session ID")
        return sid

    def start_task(self, sid, prompt):
        tid = uuid4().hex
        with self.connect() as db:
            db.execute("INSERT INTO tasks(id,session_id,prompt,status,created_at) VALUES (?,?,?,?,?)",
                       (tid, sid, prompt, "running", now()))
        return tid

    def append(self, tid, node, update):
        # Record public messages and budget counters, never hidden model reasoning fields.
        safe = []
        for msg in update.get("messages", []):
            item = messages_to_dict([msg])[0]
            data = item["data"]
            data.pop("response_metadata", None)
            data.pop("additional_kwargs", None)
            if isinstance(data.get("content"), list):
                data["content"] = [block for block in data["content"]
                                   if isinstance(block, str) or
                                   (isinstance(block, dict) and block.get("type") == "text")]
            safe.append(item)
        payload = {"messages": safe}
        for key in ("used", "calls", "rounds"):
            if key in update:
                payload[key] = update[key]
        with self.connect() as db:
            db.execute("INSERT INTO events(task_id,node,payload,created_at) VALUES (?,?,?,?)",
                       (tid, node, json.dumps(payload, ensure_ascii=False, allow_nan=False), now()))

    def finish(self, tid, status, error=None):
        if status not in {"completed", "failed", "interrupted"}:
            raise ValueError("Invalid terminal task state")
        with self.connect() as db:
            db.execute("UPDATE tasks SET status=?, finished_at=?, error=? WHERE id=? AND status='running'",
                       (status, now(), error, tid))

    def tasks(self, sid):
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT * FROM tasks WHERE session_id=? ORDER BY created_at,id", (sid,))]

    def events(self, tid):
        with self.connect() as db:
            rows = list(db.execute("SELECT * FROM events WHERE task_id=? ORDER BY id", (tid,)))
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def history(self, sid):
        # Incomplete tool-call exchanges cannot be injected into the next model request.
        messages = []
        for task in self.tasks(sid):
            if task["status"] != "completed":
                continue
            messages.append(HumanMessage(content=task["prompt"]))
            for event in self.events(task["id"]):
                messages.extend(messages_from_dict(event["payload"]["messages"]))
        return messages


def recorded_task(graph, store, sid, prompt):
    from .agent import stream_task

    history = store.history(sid)
    tid = store.start_task(sid, prompt)
    try:
        for event in stream_task(graph, prompt, history):
            for node, update in event.items():
                store.append(tid, node, update)
            yield event
    except GeneratorExit:
        store.finish(tid, "interrupted")
        raise
    except KeyboardInterrupt:
        store.finish(tid, "interrupted")
        raise
    except Exception as exc:  # noqa: BLE001 - persist error before propagating to client
        store.finish(tid, "failed", type(exc).__name__)
        raise
    else:
        store.finish(tid, "completed")
