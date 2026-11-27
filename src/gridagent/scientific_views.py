"""Data-only scientific fields, wireframes, networks and tables."""
import json
import math
import re

from . import scientific_workspace as ws
from .scientific_visualization import MAX_BYTES, _label, _number, _unique_object

SCHEMA = "gridagent.view.v1"
KINDS = {"heatmap", "surface", "topology", "table"}


def _exact(data, fields):
    if not isinstance(data, dict) or set(data) != set(fields):
        raise ValueError("Unexpected scientific view fields")


def _axis(values, maximum):
    if not isinstance(values, list) or not 2 <= len(values) <= maximum:
        raise ValueError("Invalid grid axis length")
    axis = [_number(item) for item in values]
    step = (axis[-1] - axis[0]) / (len(axis) - 1)
    if step <= 0 or any(b <= a or not math.isclose(b-a, step, rel_tol=1e-6)
                        for a, b in zip(axis, axis[1:])):
        raise ValueError("Grid axes must be strictly increasing and evenly spaced")
    return axis


def _field(data, kind):
    _exact(data, ("schema", "kind", "title", "x_label", "y_label", "value_label", "x", "y", "z"))
    maximum = 64 if kind == "heatmap" else 32
    x, y = _axis(data["x"], maximum), _axis(data["y"], maximum)
    matrix = data["z"]
    if not isinstance(matrix, list) or len(matrix) != len(y):
        raise ValueError("Grid rows must match the y axis")
    if any(not isinstance(row, list) or len(row) != len(x) for row in matrix):
        raise ValueError("Grid columns must match the x axis")
    values = [[_number(value) for value in row] for row in matrix]
    return {"x_label": _label(data["x_label"]), "y_label": _label(data["y_label"]),
            "value_label": _label(data["value_label"]), "x": x, "y": y, "z": values}, \
        f"{len(x)} × {len(y)} grid samples"


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", value):
        raise ValueError("Invalid topology node identifier")
    return value


def _topology(data):
    _exact(data, ("schema", "kind", "title", "nodes", "edges"))
    nodes, edges = data["nodes"], data["edges"]
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 100:
        raise ValueError("Topology requires 1–100 nodes")
    if not isinstance(edges, list) or len(edges) > 200:
        raise ValueError("Topology supports at most 200 edges")
    result, ids, links = [], set(), []
    positions = set()
    for node in nodes:
        _exact(node, ("id", "label", "x", "y"))
        identifier = _identifier(node["id"])
        x, y = _number(node["x"]), _number(node["y"])
        if identifier in ids or (x, y) in positions or not 0 <= x <= 1 or not 0 <= y <= 1:
            raise ValueError("Topology requires unique IDs and positions in [0,1]")
        ids.add(identifier)
        positions.add((x, y))
        result.append({"id": identifier, "label": _label(node["label"]), "x": x, "y": y})
    seen = set()
    for edge in edges:
        _exact(edge, ("source", "target"))
        source, target = _identifier(edge["source"]), _identifier(edge["target"])
        key = tuple(sorted((source, target)))
        if source not in ids or target not in ids or source == target or key in seen:
            raise ValueError("Topology edges must be unique undirected links between known distinct nodes")
        seen.add(key)
        links.append({"source": source, "target": target})
    return {"nodes": result, "edges": links}, f"{len(result)} nodes · {len(links)} undirected links"


def _table(data):
    _exact(data, ("schema", "kind", "title", "columns", "rows"))
    columns, rows = data["columns"], data["rows"]
    if not isinstance(columns, list) or not 1 <= len(columns) <= 12:
        raise ValueError("Table requires 1–12 columns")
    columns = [_label(value) for value in columns]
    if len(set(columns)) != len(columns):
        raise ValueError("Table column names must be unique")
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("Table requires 1–100 rows")
    if any(not isinstance(row, list) or len(row) != len(columns) for row in rows):
        raise ValueError("Table rows must match columns")

    def cell(value):
        if value is None or type(value) is bool:
            return value
        if isinstance(value, str):
            if len(value) > 160 or any(ord(char) < 32 for char in value):
                raise ValueError("Invalid table text cell")
            return value
        _number(value)
        # Preserve JSON integer precision in the table rather than rounding via float.
        return value

    return {"columns": columns, "rows": [[cell(value) for value in row] for row in rows]}, \
        f"{len(rows)} rows · {len(columns)} columns"


def validate_view(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("View exceeds 1 MiB")
    try:
        data = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid scientific view JSON") from exc
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise ValueError("Expected gridagent.view.v1 data-only view")
    kind = data.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError("Unknown scientific view kind")
    title = _label(data.get("title"))
    if kind in {"heatmap", "surface"}:
        body, summary = _field(data, kind)
    elif kind == "topology":
        body, summary = _topology(data)
    else:
        body, summary = _table(data)
    return {"kind": kind, "title": title, **body}, summary


def view_artifact(root, run_id, path, expected_sha256=None):
    if not isinstance(path, str) or not path.endswith(".view.json"):
        raise ValueError("Use a committed .view.json artifact")
    ws.safe_parts(path)
    report = ws.report(root, run_id)
    if report.get("status") != "ok":
        raise ValueError("Select a successful scientific run")
    row = next((item for item in report.get("artifacts", []) if item.get("path") == path), None)
    if row is None or type(row.get("size_bytes")) is not int or not 1 <= row["size_bytes"] <= MAX_BYTES:
        raise ValueError("View artifact is not committed or exceeds 1 MiB")
    raw = ws.artifact_bytes(root, run_id, path)
    digest = ws.sha(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("View changed since presentation")
    view, summary = validate_view(raw)
    return {"status": "ok", "kind": "scientific_view", "view_kind": view["kind"],
            "run_id": run_id, "path": path, "sha256": digest, "title": view["title"],
            "summary": summary, "verification": "unverified_script_output"}, view


def view_from_tool(root, message):
    if message.name != "present_scientific_view":
        return None
    try:
        data = json.loads(message.content)
        if not isinstance(data, dict) or data.get("status") != "ok" or data.get("kind") != "scientific_view":
            return None
        if not isinstance(data.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", data["sha256"]):
            return None
        descriptor, _ = view_artifact(root, data["run_id"], data["path"], data["sha256"])
        return descriptor
    except (KeyError, OSError, ValueError, TypeError, OverflowError):
        return None
