"""Stable presentation projections derived from saved engineering evidence, not model prose."""
import json
import math
import re
from pathlib import Path

SCHEMA = "gridagent.artifact.v1"
RUN_ID = re.compile(r"[a-f0-9]{32}")
MAX_POINTS = 240


def _label(value, default="unknown"):
    return value[:120] if isinstance(value, str) and value else default


def run_artifact(root, identifier):
    from .workspace import artifact_folder, load_object

    folder = artifact_folder(Path(root), "runs", identifier)
    result = load_object(folder / "result.json")
    status = _label(result.get("status"))
    backend = _label(result.get("backend"))
    operation = _label(result.get("operation"))
    quality = None
    try:
        raw = load_object(folder / "quality.json")
        passed, total = raw.get("passed_count"), raw.get("test_count")
        if type(passed) is int and type(total) is int and 0 <= passed <= total <= 10000:
            quality = {"passed": passed, "total": total, "protocol": _label(raw.get("protocol"))}
    except (OSError, ValueError, TypeError):
        pass
    metrics = []
    if isinstance(result.get("metrics"), dict):
        for key, value in result["metrics"].items():
            if len(metrics) == 12:
                break
            if type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1e100:
                metrics.append({"name": _label(key), "value": value})
    views = []
    if status == "ok":
        if (folder / "voltage.csv").is_file():
            views.append("waveform")
        if operation in {"eigen", "governor_eigen"} or backend in {"control", "ngspice"}:
            views.append("analysis")
        if backend == "pandapower":
            views.append("topology")
    return {"schema": SCHEMA, "kind": "run", "id": identifier, "backend": backend,
            "operation": operation, "status": status, "case": _label(result.get("case")),
            "quality": quality, "metrics": metrics, "views": views}


def artifact_from_tool(root, message):
    """Only exact IDs found in actual tool output and existing workspace evidence qualify."""
    try:
        data = json.loads(message.content)
        identifier = data.get("run_id") if isinstance(data, dict) else None
        if not isinstance(identifier, str) or not RUN_ID.fullmatch(identifier):
            return None
        return run_artifact(root, identifier)
    except (OSError, ValueError, TypeError, OverflowError):
        return None


def preview_run(root, identifier):
    """One bounded, evidence-derived preview; full data stay in the original run."""
    import numpy as np

    from .scientific_charts import chart_data
    from .workspace import waveform

    artifact = run_artifact(root, identifier)
    if "waveform" in artifact["views"]:
        data = waveform(Path(root), identifier)
        chart = {"title": data["channel"], "x_label": "Time (s)", "y_label": "Voltage (p.u.)",
                 "scatter": False, "series": [{"name": data["channel"], "x": data["time"], "y": data["value"]}]}
    elif "analysis" in artifact["views"]:
        chart = chart_data(root, identifier)[0]
    else:
        raise ValueError("No numerical preview available for this run")
    trace = chart["series"][0]
    x, y = np.asarray(trace["x"], dtype=float), np.asarray(trace["y"], dtype=float)
    if len(x) != len(y) or len(x) == 0 or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise ValueError("Invalid preview series")
    count = len(x)
    if count > MAX_POINTS:
        if chart["scatter"]:
            indices = np.linspace(0, count - 1, MAX_POINTS, dtype=int)
        else:
            indices = {0, count - 1}
            for block in np.array_split(np.arange(count), (MAX_POINTS - 2) // 2):
                indices.add(int(block[np.argmin(y[block])]))
                indices.add(int(block[np.argmax(y[block])]))
            indices = sorted(indices)
        x, y = x[indices], y[indices]
    return {"schema": SCHEMA, "kind": "chart-preview", "id": identifier,
            "title": _label(chart["title"]), "x_label": _label(chart["x_label"]),
            "y_label": _label(chart["y_label"]), "scatter": bool(chart["scatter"]),
            "source_points": count, "x": x.tolist(), "y": y.tolist()}
