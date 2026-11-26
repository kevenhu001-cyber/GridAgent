"""Read-only, bounded evidence tools for the general research agent."""
from pathlib import Path

import numpy as np

from .topology import shortest_path
from .workspace import artifact_folder, list_runs, load_object, waveform


def run_record(root, identifier):
    folder = artifact_folder(root, "runs", identifier)
    record = load_object(folder / "result.json")
    # Return numerical evidence without arbitrary filesystem paths or raw solver logs.
    keys = ("status", "reason", "detail", "case", "operation", "backend", "version", "scope", "counts", "solver_status", "termination_condition", "audit", "parent_run", "model_sha256",
            "bus_ids", "fault", "scenario", "device_changes", "metrics", "voltages_pu", "angles_rad", "topology", "samples")
    return {"run_id": identifier, **{k: record[k] for k in keys if k in record}}


def topology_path(root, run_id, origin, destination):
    folder = artifact_folder(root, "runs", run_id)
    record = run_record(root, run_id)
    if record.get("status") != "ok" or record.get("operation") != "inspect":
        raise ValueError("Use a successful inspect_case run")
    return {"run_id": run_id, **shortest_path(load_object(folder / "topology.json"), origin, destination)}


def recent_runs(root, limit=12):
    if not 1 <= limit <= 30:
        raise ValueError("Limit must be 1..30")
    rows = list_runs(root)
    rows.sort(key=lambda row: (Path(root) / "runs" / row["id"]).stat().st_mtime, reverse=True)
    return rows[:limit]


def analyze_voltage(root, run_id, channel, start_s=None):
    record = run_record(root, run_id)
    if record.get("status") != "ok" or record.get("operation") != "fault":
        raise ValueError("Use a completed fault simulation")
    data = waveform(root, run_id, channel)
    t, y = data["time"], data["value"]
    clearing = 1 + record["fault"]["duration_s"]
    start = clearing if start_s is None else float(start_s)
    if not np.isfinite(start) or start < 0:
        raise ValueError("Invalid analysis window")
    t, y = t[t >= start], y[t >= start]
    if len(t) < 2 or t[-1] <= t[0]:
        raise ValueError("Insufficient waveform samples in requested window")
    dt = np.diff(t)
    duration = float(t[-1] - t[0])
    def integrate(a):
        return float(np.sum(dt * (a[:-1] + a[1:]) / 2))
    i, j = int(y.argmin()), int(y.argmax())
    return {"run_id": run_id, "channel": data["channel"], "window_s": [float(t[0]), float(t[-1])],
            "samples": len(t), "min_pu": float(y[i]), "min_time_s": float(t[i]),
            "max_pu": float(y[j]), "max_time_s": float(t[j]),
            "rms_deviation_from_1pu": float(np.sqrt(integrate((y-1)**2)/duration)),
            "low_sample_fraction_time_proxy": integrate((y < 0.95).astype(float))/duration,
            "high_sample_fraction_time_proxy": integrate((y > 1.05).astype(float))/duration,
            "last_pu": float(y[-1]), "stability": "not_assessed",
            "method": "trapezoidal sample indicators; approximate threshold duration"}


def compare_faults(root, baseline_id, candidate_id):
    a, b = run_record(root, baseline_id), run_record(root, candidate_id)
    if baseline_id == candidate_id:
        raise ValueError("Select two distinct runs")
    for row in (a, b):
        if row.get("status") != "ok" or row.get("operation") != "fault" or not row.get("model_sha256"):
            raise ValueError("Comparison needs completed, fingerprinted fault runs")
    if a["model_sha256"] != b["model_sha256"] or a["fault"]["end_s"] != b["fault"]["end_s"]:
        raise ValueError("Model snapshot and simulation end time must match")
    keys = ("v_min_pu", "v_max_pu", "voltage_severity_proxy")
    return {"baseline_run": baseline_id, "candidate_run": candidate_id, "model_sha256": a["model_sha256"],
            "baseline_fault": a["fault"], "candidate_fault": b["fault"],
            "baseline_window_s": a["metrics"]["window_s"], "candidate_window_s": b["metrics"]["window_s"],
            "metrics": {k: {"baseline": a["metrics"][k], "candidate": b["metrics"][k],
                            "delta": b["metrics"][k]-a["metrics"][k]} for k in keys},
            "caution": "Each run uses its own post-clearing window; descriptive comparison, not causal proof.",
            "stability": "not_assessed"}


def compare_power_flows(root, baseline_id, candidate_id):
    a, b = run_record(root, baseline_id), run_record(root, candidate_id)
    if baseline_id == candidate_id:
        raise ValueError("Select distinct runs")
    for row in (a, b):
        if (row.get("status") != "ok" or row.get("operation") not in {"power_flow", "scenario_flow"}
                or not row.get("model_sha256")):
            raise ValueError("Comparison needs two converged power-flow runs")
    if a["model_sha256"] != b["model_sha256"] or set(a["voltages_pu"]) != set(b["voltages_pu"]):
        raise ValueError("Model snapshots and buses must match")
    delta = [{"bus": bus, "baseline_pu": v, "candidate_pu": b["voltages_pu"][bus],
              "delta_pu": b["voltages_pu"][bus]-v} for bus, v in a["voltages_pu"].items()]
    delta.sort(key=lambda row: (-abs(row["delta_pu"]), row["bus"]))
    return {"baseline_run": baseline_id, "candidate_run": candidate_id,
            "model_sha256": a["model_sha256"], "baseline_scenario": a.get("scenario"),
            "candidate_scenario": b.get("scenario"), "buses": len(delta),
            "largest_voltage_changes": delta[:20],
            "candidate_voltage_min_pu": min(b["voltages_pu"].values()),
            "candidate_voltage_max_pu": max(b["voltages_pu"].values()),
            "scope": "steady-state voltage comparison; no thermal or transient stability verdict"}


def network_branches(root, run_id, bus=None, offset=0, limit=30):
    if not 1 <= limit <= 50 or offset < 0:
        raise ValueError("Invalid pagination")
    folder = artifact_folder(root, "runs", run_id)
    record = run_record(root, run_id)
    if record.get("status") != "ok" or record.get("operation") != "inspect":
        raise ValueError("Use a successful inspect_case run")
    topology = load_object(folder / "topology.json")
    if bus is not None and bus not in topology["buses"]:
        raise ValueError("Unknown bus")
    branches = [b for b in topology["branches"] if bus is None or bus in (b["from"], b["to"])]
    branches.sort(key=lambda row: row["id"])
    end = offset + limit
    return {"run_id": run_id, "model_sha256": record.get("model_sha256"),
            "bus": bus, "total": len(branches), "branches": branches[offset:end],
            "next_offset": end if end < len(branches) else None}


def list_devices(root, run_id, model=None, bus=None, offset=0, limit=20):
    import json

    if offset < 0 or not 1 <= limit <= 50:
        raise ValueError("Invalid pagination")
    folder = artifact_folder(root, "runs", run_id)
    record = run_record(root, run_id)
    if record.get("operation") != "inspect" or record.get("status") != "ok":
        raise ValueError("Use a successful inspect_case run")
    rows = json.loads((folder / "devices.json").read_text(encoding="utf-8"))
    rows = [r for r in rows if (model is None or r["model"] == model) and (bus is None or r["bus"] == bus)]
    return {"run_id": run_id, "total": len(rows), "devices": rows[offset:offset+limit],
            "next_offset": offset+limit if offset+limit < len(rows) else None}
