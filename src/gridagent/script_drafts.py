"""Draft source for explicit user review; no Python execution on the host."""
import hashlib
import json
from pathlib import Path
from uuid import uuid4


def draft_script(root, title, source):
    if not 1 <= len(title) <= 160 or not 1 <= len(source.encode("utf-8")) <= 65536:
        raise ValueError("Invalid script title or size")
    # Parse syntax only. Never evaluate, import or run the submitted source.
    compile(source, "research_draft.py", "exec", dont_inherit=True)
    identifier = uuid4().hex
    folder = Path(root).resolve() / "drafts" / identifier
    folder.mkdir(parents=True)
    (folder / "script.py").write_bytes(source.encode("utf-8"))
    info = {"id": identifier, "title": title, "sha256": hashlib.sha256(source.encode()).hexdigest(),
            "status": "awaiting_user_review", "executed": False}
    (folder / "metadata.json").write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return info


def list_drafts(root):
    rows = []
    for path in (Path(root) / "drafts").glob("*/metadata.json"):
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
            rows.append(row)
        except (OSError, ValueError):
            continue
    return rows
