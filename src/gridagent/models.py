"""User-approved, content-addressed ANDES workbook registration."""
import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from uuid import uuid4

from filelock import FileLock

from .domain import CASES

MODEL_ID = re.compile(r"model-[a-f0-9]{64}")


def file_digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def validate_workbook(path):
    if path.suffix.lower() != ".xlsx" or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError("Select an ANDES .xlsx workbook no larger than 32 MiB")
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 5000 or sum(e.file_size for e in entries) > 128 * 1024 * 1024:
            raise ValueError("Workbook exceeds expansion limits")
        names = {e.filename for e in entries}
        if not {"[Content_Types].xml", "xl/workbook.xml"} <= names:
            raise ValueError("Not an Excel workbook")
        if any("vbaproject" in n.lower() or n.lower().startswith("xl/externallinks/") for n in names):
            raise ValueError("Macros and external links are not accepted")


def register_model(root, source):
    source = Path(source)
    validate_workbook(source)
    data = source.read_bytes()
    identifier = "model-" + hashlib.sha256(data).hexdigest()
    registry = (Path(root) / "models").resolve()
    folder = registry / identifier
    folder.mkdir(parents=True, exist_ok=True)
    if folder.resolve().parent != registry:
        raise ValueError("Invalid model directory")
    with FileLock(str(folder / ".import.lock")):
        target = folder / "case.xlsx"
        if not target.exists():
            tmp = folder / (".import-" + uuid4().hex + ".xlsx")
            try:
                tmp.write_bytes(data)
                validate_workbook(tmp)
                os.link(tmp, target)
            finally:
                tmp.unlink(missing_ok=True)
        resolve_model(root, identifier)
        metadata = folder / "metadata.json"
        if not metadata.exists():
            metadata.write_text(json.dumps({"id": identifier, "name": source.name,
                                          "format": "andes-xlsx"}), encoding="utf-8")
    return identifier


def resolve_model(root, identifier):
    if not MODEL_ID.fullmatch(identifier):
        raise ValueError("Invalid model ID")
    registry = (Path(root) / "models").resolve()
    target = (registry / identifier / "case.xlsx").resolve()
    if target.parent != registry / identifier or not target.is_file():
        raise ValueError("Model has not been registered")
    if file_digest(target) != identifier[6:]:
        raise ValueError("Registered model hash mismatch")
    validate_workbook(target)
    return target


def list_models(root):
    rows = [{"id": key, "name": key, "format": "packaged-andes"} for key in CASES]
    for folder in sorted((Path(root) / "models").glob("model-*")):
        try:
            resolve_model(root, folder.name)
            record = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
            rows.append({"id": folder.name, "name": record["name"], "format": "andes-xlsx"})
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            continue
    return rows
