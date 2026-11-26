"""Read-only user-facing access to locally stored research artifacts."""
import csv
import json
import re
from pathlib import Path

import numpy as np

_ID = re.compile(r"[a-f0-9]{32}")


def artifact_folder(root: Path, kind: str, identifier: str):
    if kind not in {"runs", "studies"} or not _ID.fullmatch(identifier):
        raise ValueError("Expected a full run or study ID")
    base = (root / kind).resolve()
    path = (base / identifier).resolve()
    if path.parent != base or not path.is_dir():
        raise ValueError("Unknown artifact ID")
    return path


def load_object(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise TypeError("Invalid artifact object")
    return data


def list_runs(root: Path):
    rows = []
    for folder in sorted((root / "runs").glob("*"), key=lambda p: p.name):
        if not _ID.fullmatch(folder.name):
            continue
        try:
            resolved = artifact_folder(root, "runs", folder.name)
            data = load_object(resolved / "result.json")
            rows.append({"id": folder.name, "status": data.get("status", "unknown"),
                         "case": data.get("case", "unknown"),
                         "operation": data.get("operation", "fault" if "fault" in data else "unknown")})
        except (OSError, ValueError, TypeError):
            rows.append({"id": folder.name, "status": "incomplete", "case": "-", "operation": "-"})
    return rows


def study_summary(root: Path, identifier: str):
    folder = artifact_folder(root, "studies", identifier)
    manifest = load_object(folder / "manifest.json")
    report = load_object(folder / "report.json") if (folder / "report.json").exists() else None
    lines = [f"Study {identifier}", f"Protocol: {manifest.get('protocol', 'unknown')}"]
    if report is None:
        lines.append("Unfinished · partial artifacts preserved")
    elif report.get("phase") == "mathematical_program_finished":
        verification = report["verification"]
        lines.append(f"Mathematical program · {verification['classification']}")
        lines.append(f"Solver: {report['solver_result']['route']} · {report['solver_result']['status']}")
        if verification["primal"]["passed"]:
            lines.append(f"Verified objective: {verification['primal']['objective']:.6g} {report['objective_unit']}")
        if not verification["optimality_independently_checked"]:
            lines.append("Independent optimality not established")
    elif report.get("phase") == "optimization_finished":
        lines.append(f"AC optimization · {report['termination']}")
        lines.append(f"Reserved runs: {report['reserved_solver_runs']}/{report['budget']}")
        best = report["verification"]
        if report["completed"] and best is not None:
            lines.append(f"Verified objective: {best['objective']:.6g} {report['objective_unit']}")
        else:
            lines.append("No independently verified recommendation")
        lines.append("Global optimality not established")
    elif report.get("phase") == "modeling_benchmark_finished":
        lines.append(f"Modeling benchmark: {report['task']} · {report['termination']}")
        lines.append(f"Best run: {report['best_run_id']} · {report['attempts']} attempts")
        for row in report.get("best_checks", []):
            lines.append(f"{row['id']} · {'pass' if row['passed'] else 'fail'}")
    elif report.get("phase") == "native_repair_finished":
        lines.append(f"Benchmark: {report['termination']} · {report['solver_calls']} solver calls")
        lines.append(f"Best run: {report['best_run_id']} · iteration {report['best_iteration']}")
        for row in (report.get("best_quality") or {}).get("tests", []):
            lines.append(f"{row['id']} · {'pass' if row['passed'] else 'fail'} · {row.get('observed')}")
    elif "tests_passed" in report:
        lines.append(f"Model quality: {report['tests_passed']}/{report['tests_total']} tests passed")
        if "objective_evaluations" in report:
            lines.append(f"Objective evaluations: {report['objective_evaluations']}/{report['objective_budget']}")
        else:
            lines.append(f"Attempts: {report['attempts']} · applied edits: {report['accepted_edits']}")
        for key, value in report["final_gains"].items():
            lines.append(f"{key}: {report['initial_gains'][key]:g} → {value:g}")
    elif report.get("phase") == "mitigation_attempted":
        mitigation = report["mitigation"]
        lines.append(f"Fresh mitigation attempts: {mitigation['attempted']}/{mitigation['budget']}")
        best = mitigation["recommended"]
        lines.append(f"Best measured plan: {best['plan'] if best else 'none'}")
        for row in mitigation["results"]:
            lines.append(f"{row.get('plan', '-')} · {row['status']} · {row.get('measurement')}")
    elif report.get("phase") == "screening_attempted":
        lines.append(f"Original PowerFactory screening attempts: {report['attempted']} · mitigation not run")
        for row in report["observations"]:
            lines.append(f"{row['id']} · {row['status']} · severity error {row.get('severity_error')}")
    elif report.get("phase") == "predictions_frozen":
        lines.append("Original paper predictions frozen; no fresh simulations")
        lines.append("Selected: " + ", ".join(report["selected"]))
    elif report.get("phase") == "model_edit_verified":
        lines.append("Original Solar model edited; locked fields verified; not simulated")
        lines.append(str(report["new"]))
    elif "observed" in report:
        lines.append(f"Screening attempts: {report['attempted']}")
        for row in report["observed"]:
            score = row.get("score")
            label = f"{score:.4f}" if score is not None else "unavailable"
            lines.append(f"{row['id']}  {row['status']}  voltage score {label}  run {row.get('run_id') or '-'}")
    elif "points" in report:
        for point in report["points"]:
            lines.append(f"{point['duration_s']:g} s · {point['status']} · score {point.get('score')} · "
                         f"run {point.get('run_id') or '-'}")
    lines.append("Artifacts: " + str(folder))
    return "\n".join(lines)


def waveform(root: Path, identifier: str, channel=None, relative=None):
    kind = "studies" if relative else "runs"
    folder = artifact_folder(root, kind, identifier)
    path = (folder / (relative or "voltage.csv")).resolve()
    if not path.is_relative_to(folder) or path.suffix != ".csv":
        raise ValueError("Waveform must be a CSV inside the selected artifact")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, [])
        if len(header) < 2:
            raise ValueError("Waveform has no channels")
        if channel is None:
            channel = header[1]
        if channel not in header[1:]:
            raise ValueError("Unknown channel; choices: " + ", ".join(header[1:]))
        index = header.index(channel)
        samples = [(float(row[0]), float(row[index])) for row in reader]
    data = np.asarray(samples, dtype=float)
    if data.ndim != 2 or not len(data) or not np.isfinite(data).all() or np.any(np.diff(data[:, 0]) < 0):
        raise ValueError("Invalid waveform")
    return {"channel": channel, "channels": header[1:], "time": data[:, 0], "value": data[:, 1]}


def waveform_text(data, width=60, height=9):
    """Terminal plot with a time axis and extrema-preserving per-column envelopes."""
    t, y = data["time"], data["value"]
    if width < 2 or height < 2:
        raise ValueError("Plot dimensions too small")
    ymin, ymax = float(y.min()), float(y.max())
    span = ymax - ymin or 1.0
    duration = float(t[-1] - t[0]) or 1.0
    columns = np.clip(((t - t[0]) / duration * (width - 1)).astype(int), 0, width - 1)
    levels = np.clip(np.rint((y - ymin) / span * (height - 1)).astype(int), 0, height - 1)
    canvas = [[" "] * width for _ in range(height)]
    for col in np.unique(columns):
        segment = levels[columns == col]
        for row in range(int(segment.min()), int(segment.max()) + 1):
            canvas[height - 1 - row][int(col)] = "•"
    lines = [f"{data['channel']} · {len(t)} samples · min {ymin:.5g} · max {ymax:.5g}"]
    for i, row in enumerate(canvas):
        label = f"{ymax - i * (ymax - ymin) / (height - 1):9.3g}"
        lines.append(label + " │" + "".join(row))
    lines.append(" " * 10 + "└" + "─" * width)
    lines.append(f"           {t[0]:.3g} s" + " " * max(1, width - 15) + f"{t[-1]:.3g} s")
    return "\n".join(lines)
