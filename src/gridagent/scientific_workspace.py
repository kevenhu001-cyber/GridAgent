"""Scoped project files for the LLM; never expose the host filesystem as a tool."""
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

MAX_FILE = 1024 * 1024
MAX_PROJECT = 16 * MAX_FILE
MAX_FILES = 128
MAX_OUTPUT = 64 * MAX_FILE
GRANT = "scientific-execution.json"
_COMPONENT = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,79}")
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}


def safe_parts(name):
    if not isinstance(name, str) or not 1 <= len(name) <= 240:
        raise ValueError("Invalid relative file path")
    parts = name.split("/")
    if len(parts) > 8 or any(not _COMPONENT.fullmatch(p) or p.endswith(".")
                             or p.split(".")[0].upper() in _RESERVED for p in parts):
        raise ValueError("Use project-relative names with letters, digits, dot, dash and underscore")
    return parts


def plain(path, *, directory=False):
    info = path.lstat()
    if (stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400
            or (not directory and info.st_nlink != 1)):
        raise ValueError("Links and reparse points are not permitted")
    if not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
        raise ValueError("Unexpected project file type")
    return info


def scoped(base, name, *, create_parents=False):
    plain(base, directory=True)
    parts = safe_parts(name)
    current = base
    for part in parts[:-1]:
        current = current / part
        if create_parents:
            current.mkdir(exist_ok=True)
        plain(current, directory=True)
    target = current / parts[-1]
    if target.exists() or target.is_symlink():
        plain(target)
    return target


def bounded_bytes(path, maximum):
    if plain(path).st_size > maximum:
        raise ValueError("File exceeds size limit")
    with path.open("rb") as handle:
        data = handle.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError("File exceeds size limit")
    return data


def scan(base, *, limit=MAX_PROJECT, max_files=MAX_FILES, per_file=MAX_FILE):
    plain(base, directory=True)
    rows, total, directories = [], 0, 0
    for folder, dirs, names in os.walk(base, followlinks=False):
        path = Path(folder)
        for name in dirs:
            child = path / name
            safe_parts(child.relative_to(base).as_posix())
            plain(child, directory=True)
            directories += 1
            if directories > max_files:
                raise ValueError("Too many directories")
        for name in names:
            child = path / name
            relative = child.relative_to(base).as_posix()
            safe_parts(relative)
            size = plain(child).st_size
            total += size
            if size > per_file or total > limit or len(rows) >= max_files:
                raise ValueError("File count or storage budget exceeded")
            rows.append({"path": relative, "size_bytes": size})
    return sorted(rows, key=lambda row: row["path"])


def atomic_bytes(path, content):
    temp = path.parent / ("stage-" + uuid4().hex)
    try:
        with temp.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)


def enabled(root):
    try:
        return bounded_bytes(Path(root) / GRANT, 128) == b'{"enabled":true}'
    except (OSError, ValueError):
        return False


def set_enabled(root, value):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    atomic_bytes(root / GRANT, b'{"enabled":true}' if value else b'{"enabled":false}')


def require_grant(root):
    if not enabled(root):
        raise ValueError("General scientific execution is disabled; ask the user to enable it in settings")


def directory(root, name):
    root = Path(root).resolve()
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    plain(path, directory=True)
    return path


def sha(data):
    return hashlib.sha256(data).hexdigest()


def project(root):
    require_grant(root)
    return directory(root, "scientific-project")


def list_project(root):
    return {"status": "ok", "files": scan(project(root))}


def read_project(root, path):
    data = bounded_bytes(scoped(project(root), path), MAX_FILE)
    return {"status": "ok", "path": path, "sha256": sha(data), "text": data.decode("utf-8")}


def write_project(root, path, text, expected_sha256=None):
    base = project(root)
    data = text.encode("utf-8")
    if len(data) > MAX_FILE:
        raise ValueError("Project file exceeds 1 MiB")
    with FileLock(str(Path(root).resolve() / "scientific-project.lock"), timeout=5):
        rows = scan(base)
        target = scoped(base, path, create_parents=True)
        prior = bounded_bytes(target, MAX_FILE) if target.exists() else None
        if prior is None and expected_sha256 is not None:
            raise ValueError("Expected file does not exist")
        if prior is not None and expected_sha256 != sha(prior):
            raise ValueError("Read the current file and provide its SHA-256 before overwriting")
        if prior is None and len(rows) >= MAX_FILES:
            raise ValueError("Project file count exceeded")
        if sum(row["size_bytes"] for row in rows) - len(prior or b"") + len(data) > MAX_PROJECT:
            raise ValueError("Project storage budget exceeded")
        atomic_bytes(target, data)
    return {"status": "ok", "path": path, "sha256": sha(data), "size_bytes": len(data)}


def snapshot(root, target):
    base = project(root)
    target.mkdir(parents=True, exist_ok=False)
    records = []
    with FileLock(str(Path(root).resolve() / "scientific-project.lock"), timeout=5):
        for row in scan(base):
            path = row["path"]
            data = bounded_bytes(scoped(base, path), MAX_FILE)
            output = scoped(target, path, create_parents=True)
            output.write_bytes(data)
            records.append({"path": path, "size_bytes": len(data), "sha256": sha(data)})
    return records


def job_directory(root, identifier):
    if not re.fullmatch(r"[a-f0-9]{32}", identifier):
        raise ValueError("Use a full scientific run ID")
    base = directory(root, "scientific-runs")
    folder = base / identifier
    plain(folder, directory=True)
    return folder


def report(root, identifier):
    require_grant(root)
    folder = job_directory(root, identifier)
    return json.loads(bounded_bytes(folder / "report.json", MAX_FILE))


def read_artifact(root, identifier, path, offset=0, limit=12000):
    if not 0 <= offset <= MAX_OUTPUT or not 1 <= limit <= 24000:
        raise ValueError("Invalid artifact pagination")
    info = report(root, identifier)
    row = next((row for row in info.get("artifacts", []) if row["path"] == path), None)
    if row is None:
        raise ValueError("Artifact is not committed")
    folder = job_directory(root, identifier)
    data = bounded_bytes(scoped(folder / "output", path), MAX_OUTPUT)
    if sha(data) != row["sha256"]:
        raise ValueError("Artifact changed after execution")
    text = data.decode("utf-8")
    return {"status": "ok", "run_id": identifier, "path": path, "text": text[offset:offset+limit],
            "next_offset": offset+limit if offset+limit < len(text) else None, "sha256": row["sha256"]}


def cancel(root, identifier):
    folder = job_directory(root, identifier)
    if (folder / "report.json").exists():
        return "Scientific run has already ended"
    atomic_bytes(folder / "cancel-requested", b"1")
    return "Cancellation requested; sandbox shutdown has not yet been confirmed"
