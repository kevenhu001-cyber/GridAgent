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


def list_project_directory(root, path=""):
    """One directory of the existing authorized scientific project, including empty folders."""
    base = project(root)
    scan(base)  # Enforce the same project-wide size, file and link constraints.
    current = base
    if path:
        for part in safe_parts(path):
            current = current / part
            plain(current, directory=True)
    entries = []
    for child in current.iterdir():
        relative = child.relative_to(base).as_posix()
        safe_parts(relative)
        info = child.lstat()
        if stat.S_ISDIR(info.st_mode):
            plain(child, directory=True)
            entries.append({"path": relative, "name": child.name, "kind": "directory",
                            "hasChildren": next(child.iterdir(), None) is not None})
        else:
            size = plain(child).st_size
            entries.append({"path": relative, "name": child.name, "kind": "file", "sizeBytes": size})
        if len(entries) > 2 * MAX_FILES:
            raise ValueError("Directory exceeds entry limit")
    entries.sort(key=lambda row: (row["kind"] != "directory", row["name"].casefold(), row["name"]))
    return {"directoryPath": path, "entries": entries}


def search_project_files(root, query, limit=25):
    """Bounded literal path search; never searches file contents or the host root."""
    if not isinstance(query, str) or not query.strip() or len(query) > 240 or not 1 <= limit <= 128:
        raise ValueError("Invalid project search")
    needle = query.strip().casefold()
    rows = scan(project(root))
    matches = [{"path": row["path"], "name": row["path"].rsplit("/", 1)[-1]}
               for row in rows if needle in row["path"].casefold()]
    return {"results": matches[:limit]}


def _entry_target(base, path):
    """Resolve an existing parent; never create parents for UI mutations."""
    current = base
    parts = safe_parts(path)
    plain(base, directory=True)
    for part in parts[:-1]:
        current = current / part
        plain(current, directory=True)
    return current / parts[-1]


def _require_absent(target):
    # Treat case-insensitive collisions consistently across platforms.
    if any(child.name.casefold() == target.name.casefold() for child in target.parent.iterdir()):
        raise ValueError("Project entry already exists")


def _checked_entry(target, kind, expected_sha256):
    if kind == "directory":
        plain(target, directory=True)
        if expected_sha256 is not None or next(target.iterdir(), None) is not None:
            raise ValueError("Only empty directories can be renamed or deleted")
    elif kind == "file":
        data = bounded_bytes(target, MAX_FILE)
        if expected_sha256 != sha(data):
            raise ValueError("Project file changed; read the latest revision")
    else:
        raise ValueError("Unsupported project entry kind")


def create_project_entry(root, path, kind, text=""):
    base = project(root)
    if "\x00" in text:
        raise ValueError("Project text cannot contain NUL")
    data = text.encode("utf-8")
    with FileLock(str(Path(root).resolve() / "scientific-project.lock"), timeout=5):
        require_grant(root)
        rows = scan(base)
        target = _entry_target(base, path)
        _require_absent(target)
        if kind == "directory":
            if text:
                raise ValueError("Directories cannot have file content")
            if sum(len(dirs) for _, dirs, _ in os.walk(base, followlinks=False)) >= MAX_FILES:
                raise ValueError("Too many directories")
            target.mkdir()
            return {"entry": {"path": path, "name": target.name, "kind": kind, "hasChildren": False}}
        if kind != "file" or len(data) > MAX_FILE or len(rows) >= MAX_FILES:
            raise ValueError("Invalid project file or file count exceeded")
        if sum(row["size_bytes"] for row in rows) + len(data) > MAX_PROJECT:
            raise ValueError("Project storage budget exceeded")
        # Exclusive creation, never replace an existing file.
        with target.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return {"entry": {"path": path, "name": target.name, "kind": kind,
                          "sizeBytes": len(data), "isText": "\x00" not in text},
                "file": {"path": path, "kind": kind, "content": text, "versionToken": sha(data),
                         "encoding": "utf-8", "sizeBytes": len(data), "isText": True, "tooLarge": False}}


def rename_project_entry(root, path, new_path, kind, expected_sha256=None):
    base = project(root)
    with FileLock(str(Path(root).resolve() / "scientific-project.lock"), timeout=5):
        require_grant(root)
        scan(base)
        target, destination = _entry_target(base, path), _entry_target(base, new_path)
        _checked_entry(target, kind, expected_sha256)
        _require_absent(destination)
        # The project lock serializes cooperating writers, including the Agent.
        # External programs modifying this directory concurrently are unsupported.
        target.rename(destination)
        entry = {"path": new_path, "name": destination.name, "kind": kind}
        if kind == "file":
            entry["sizeBytes"] = plain(destination).st_size
        else:
            entry["hasChildren"] = False
        return {"oldPath": path, "entry": entry}


def delete_project_entry(root, path, kind, expected_sha256=None):
    base = project(root)
    with FileLock(str(Path(root).resolve() / "scientific-project.lock"), timeout=5):
        require_grant(root)
        scan(base)
        target = _entry_target(base, path)
        _checked_entry(target, kind, expected_sha256)
        if kind == "directory":
            target.rmdir()  # Never recursively remove a directory.
        else:
            target.unlink()
        return {"path": path, "kind": kind}


def read_project(root, path, offset=0, limit=24000):
    if not 0 <= offset <= MAX_FILE or not 1 <= limit <= 24000:
        raise ValueError("Invalid project file pagination")
    data = bounded_bytes(scoped(project(root), path), MAX_FILE)
    text = data.decode("utf-8")
    return {"status": "ok", "path": path, "sha256": sha(data), "text": text[offset:offset+limit],
            "next_offset": offset+limit if offset+limit < len(text) else None}


def inspect_project(root, path):
    """Return the content fingerprint even for a binary project file."""
    data = bounded_bytes(scoped(project(root), path), MAX_FILE)
    try:
        data.decode("utf-8")
        text_readable = b"\x00" not in data
    except UnicodeDecodeError:
        text_readable = False
    return {"status": "ok", "path": path, "sha256": sha(data), "size_bytes": len(data),
            "text_readable": text_readable}


def write_project(root, path, text, expected_sha256=None):
    return write_bytes(root, path, text.encode("utf-8"), expected_sha256)


def write_bytes(root, path, data, expected_sha256=None):
    base = project(root)
    if len(data) > MAX_FILE:
        raise ValueError("Project file exceeds 1 MiB")
    with FileLock(str(Path(root).resolve() / "scientific-project.lock"), timeout=5):
        require_grant(root)
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


def edit_project(root, path, old, new, expected_sha256):
    """Apply exactly one unambiguous text replacement; the write is hash guarded."""
    if not old or len(old) > MAX_FILE or len(new) > MAX_FILE:
        raise ValueError("Invalid replacement size")
    data = bounded_bytes(scoped(project(root), path), MAX_FILE)
    if sha(data) != expected_sha256:
        raise ValueError("Project file changed; read the latest revision")
    text = data.decode("utf-8")
    if text.count(old) != 1:
        raise ValueError("Replacement must match exactly once")
    return write_project(root, path, text.replace(old, new, 1), expected_sha256)


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


def artifact_bytes(root, identifier, path):
    info = report(root, identifier)
    if (job_directory(root, identifier) / "recovery.json").exists():
        raise ValueError("Recovered incomplete outputs cannot be consumed")
    if info.get("status") == "cleanup_unconfirmed":
        raise ValueError("Sandbox shutdown is unconfirmed; outputs cannot be consumed")
    row = next((row for row in info.get("artifacts", []) if row["path"] == path), None)
    if row is None:
        raise ValueError("Artifact is not committed")
    folder = job_directory(root, identifier)
    data = bounded_bytes(scoped(folder / "output", path), MAX_OUTPUT)
    if sha(data) != row["sha256"]:
        raise ValueError("Artifact changed after execution")
    return data


def read_artifact(root, identifier, path, offset=0, limit=12000):
    if not 0 <= offset <= MAX_OUTPUT or not 1 <= limit <= 24000:
        raise ValueError("Invalid artifact pagination")
    data = artifact_bytes(root, identifier, path)
    text = data.decode("utf-8")
    return {"status": "ok", "run_id": identifier, "path": path, "text": text[offset:offset+limit],
            "next_offset": offset+limit if offset+limit < len(text) else None, "sha256": sha(data)}


def cancel(root, identifier):
    folder = job_directory(root, identifier)
    if (folder / "recovery.json").exists():
        return "Scientific run has been recovered; partial outputs were discarded"
    if (folder / "report.json").exists():
        if run_status(root, identifier)["status"] == "cleanup_unconfirmed":
            return "Sandbox stop is unconfirmed; request explicit scientific recovery"
        return "Scientific run has already ended"
    atomic_bytes(folder / "cancel-requested", b"1")
    return "Cancellation requested; sandbox shutdown has not yet been confirmed"


def promote_artifact(root, identifier, path, destination, expected_sha256=None):
    """Explicitly copy committed, hash-checked output into the persistent project."""
    data = artifact_bytes(root, identifier, path)
    result = write_bytes(root, destination, data, expected_sha256)
    return {**result, "origin_run_id": identifier, "origin_path": path}


def run_status(root, identifier):
    folder = job_directory(root, identifier)
    result = {"run_id": identifier, "status": "preparing", "artifacts": []}
    if (folder / "manifest.json").exists():
        result.update(json.loads(bounded_bytes(folder / "manifest.json", MAX_FILE)))
        result["status"] = "interrupted_or_running"
    if (folder / "report.json").exists():
        result = json.loads(bounded_bytes(folder / "report.json", MAX_FILE))
    if (folder / "recovery.json").exists():
        result["recovery"] = json.loads(bounded_bytes(folder / "recovery.json", MAX_FILE))
        result["status"] = "recovered_incomplete"
        result["artifacts"] = []
    result["cancellation_requested"] = (folder / "cancel-requested").exists()
    return result


def list_scientific_runs(root, limit=20):
    if not 1 <= limit <= 50:
        raise ValueError("Run limit must be 1..50")
    base = directory(root, "scientific-runs")
    rows = []
    for child in base.iterdir():
        if not re.fullmatch(r"[a-f0-9]{32}", child.name):
            continue
        try:
            info = plain(child, directory=True)
            rows.append((info.st_mtime_ns, child.name))
        except (OSError, ValueError):
            continue
    result = []
    for _, identifier in sorted(rows, reverse=True)[:limit]:
        try:
            item = run_status(root, identifier)
            result.append({key: item.get(key) for key in ("run_id", "status", "entry", "plugin", "plugin_ids",
                                                          "reason", "cancellation_requested")})
        except (OSError, ValueError):
            result.append({"run_id": identifier, "status": "invalid_record"})
    return {"status": "ok", "runs": result}
