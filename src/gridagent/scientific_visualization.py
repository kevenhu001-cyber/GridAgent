"""Bounded data-only charts from committed scientific sandbox artifacts."""
import json
import math

from . import scientific_workspace as ws

SCHEMA = "gridagent.chart.v1"
MAX_BYTES = 1024 * 1024
MAX_POINTS = 12000
MAX_SERIES = 6


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate chart JSON key")
        result[key] = value
    return result


def _label(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 160:
        raise ValueError("Chart labels must be nonempty text of at most 160 characters")
    if any(ord(char) < 32 for char in value):
        raise ValueError("Chart labels cannot contain control characters")
    return value


def _number(value):
    if type(value) not in (int, float) or abs(value) > 1e100 or not math.isfinite(value):
        raise ValueError("Chart coordinates must be finite real numbers within magnitude 1e100")
    return float(value)


def validate_chart(raw):
    if len(raw) > MAX_BYTES:
        raise ValueError("Chart artifact exceeds 1 MiB")
    try:
        chart = json.loads(raw, object_pairs_hook=_unique_object)
    except (UnicodeError, RecursionError) as exc:
        raise ValueError("Invalid chart JSON") from exc
    if not isinstance(chart, dict) or set(chart) != {
            "schema", "title", "x_label", "y_label", "scatter", "series"} or chart["schema"] != SCHEMA:
        raise ValueError("Expected gridagent.chart.v1 data-only chart")
    if type(chart["scatter"]) is not bool:
        raise ValueError("scatter must be a boolean")
    rows = chart["series"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SERIES:
        raise ValueError("Select one to six chart series")
    traces, points = [], 0
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "x", "y"}:
            raise ValueError("Each series needs name, x and y")
        x, y = row["x"], row["y"]
        if not isinstance(x, list) or not isinstance(y, list) or len(x) != len(y) or not x:
            raise ValueError("Series x and y must be nonempty arrays of equal length")
        points += len(x)
        if points > MAX_POINTS:
            raise ValueError("Chart exceeds 12000 total samples; export a deliberate bounded view")
        traces.append({"name": _label(row["name"]), "x": [_number(value) for value in x],
                       "y": [_number(value) for value in y]})
    return {"title": _label(chart["title"]), "x_label": _label(chart["x_label"]),
            "y_label": _label(chart["y_label"]), "scatter": chart["scatter"], "series": traces}


def chart_artifact(root, run_id, path, expected_sha256=None):
    """Recheck the committed run and content hash on every presentation/open."""
    if not isinstance(path, str) or not path.endswith(".chart.json"):
        raise ValueError("Use a committed .chart.json artifact")
    ws.safe_parts(path)
    report = ws.report(root, run_id)
    if report.get("status") != "ok":
        raise ValueError("Select a successful scientific run for chart presentation")
    row = next((item for item in report.get("artifacts", []) if item.get("path") == path), None)
    if row is None:
        raise ValueError("Chart artifact is not committed")
    if type(row.get("size_bytes")) is not int or not 1 <= row["size_bytes"] <= MAX_BYTES:
        raise ValueError("Chart artifact size is missing or exceeds 1 MiB")
    raw = ws.artifact_bytes(root, run_id, path)
    digest = ws.sha(raw)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ValueError("Chart changed since presentation; reload the original artifact")
    chart = validate_chart(raw)
    descriptor = {"status": "ok", "kind": "scientific_chart", "run_id": run_id, "path": path,
                  "sha256": digest, "title": chart["title"], "x_label": chart["x_label"],
                  "y_label": chart["y_label"], "scatter": chart["scatter"],
                  "series_count": len(chart["series"]),
                  "points": sum(len(trace["x"]) for trace in chart["series"]),
                  "verification": "unverified_script_output"}
    return descriptor, chart


def chart_from_tool(root, message):
    """Never trust a model-authored or replayed chart descriptor without revalidation."""
    if message.name != "present_scientific_chart":
        return None
    try:
        data = json.loads(message.content)
        if not isinstance(data, dict) or data.get("status") != "ok" or data.get("kind") != "scientific_chart":
            return None
        if not isinstance(data.get("sha256"), str) or len(data["sha256"]) != 64:
            return None
        descriptor, _ = chart_artifact(root, data["run_id"], data["path"], data["sha256"])
        return descriptor
    except (KeyError, OSError, ValueError, TypeError, OverflowError):
        return None
