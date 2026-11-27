"""Local, explicitly imported, attributed engineering reference packs."""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Reference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["function", "option", "concept", "troubleshooting"]
    backend: str | None = Field(default=None, min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    function: str = Field(min_length=1, max_length=100)
    option: str | None = Field(default=None, max_length=100)
    description: str = Field(min_length=1, max_length=1800)
    source: str = Field(min_length=1, max_length=500)
    version: str = Field(min_length=1, max_length=100)


class ReferencePack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=160)
    entries: list[Reference] = Field(min_length=1, max_length=1000)


def connect(root):
    path = Path(root) / "knowledge.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.execute("CREATE TABLE IF NOT EXISTS packs (id TEXT PRIMARY KEY, title TEXT, payload TEXT)")
    return db


def import_pack(root, path):
    path = Path(path)
    if path.suffix.lower() != ".json" or path.stat().st_size > 4*1024*1024:
        raise ValueError("Select a reference pack JSON of at most 4 MiB")
    data = ReferencePack.model_validate_json(path.read_bytes())
    serialized = data.model_dump()
    # Preserve content IDs of existing reference packs without native backend tags.
    for entry in serialized["entries"]:
        if entry["backend"] is None:
            entry.pop("backend")
    payload = json.dumps(serialized, ensure_ascii=False, sort_keys=True)
    identifier = hashlib.sha256(payload.encode()).hexdigest()
    with closing(connect(root)) as db, db:
        db.execute("INSERT OR IGNORE INTO packs VALUES (?, ?, ?)", (identifier, data.title, payload))
    return identifier, len(data.entries)


def list_packs(root):
    with closing(connect(root)) as db:
        return [{"id": key, "title": title, "entries": len(json.loads(payload)["entries"])}
                for key, title, payload in db.execute("SELECT id,title,payload FROM packs ORDER BY title,id")]


def reference_rows(root):
    if not (Path(root) / "knowledge.sqlite3").is_file():
        return []
    with closing(connect(root)) as db:
        packs = db.execute("SELECT id,payload FROM packs ORDER BY id").fetchall()
    rows = []
    for key, payload in packs:
        pack = ReferencePack.model_validate_json(payload)
        for i, entry in enumerate(pack.entries):
            row = entry.model_dump()
            row.update({"id": f"ref:{key}:{i}", "reference_kind": row["kind"], "kind": "reference",
                        "pack_title": pack.title, "authority": "user-imported reference; not tool contract"})
            rows.append(row)
    return rows
