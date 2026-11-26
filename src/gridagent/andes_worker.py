"""Isolated ANDES process for packaged and user-approved snapshots."""
import json
import sys
from pathlib import Path

from .device_edits import apply_edits, catalog
from .domain import (
    CASES,
    FaultRequest,
    GovernorEigenRequest,
    GovernorFaultRequest,
    ScenarioRequest,
    voltage_metrics,
)
from .modal import summarize_modes
from .models import MODEL_ID, file_digest, validate_workbook
from .topology import topology_summary


def execute(operation: str, request: dict, folder: Path) -> dict:
    import andes
    import numpy as np

    case = request.get("case", "kundur")
    if case not in CASES and not MODEL_ID.fullmatch(case):
        raise ValueError("Unknown case")
    if operation not in {"inspect", "power_flow", "fault", "eigen", "scenario_flow", "governor_eigen", "governor_fault"}:
        raise ValueError("Unknown operation")
    spec = None
    governor = None
    if operation == "governor_fault":
        spec = GovernorFaultRequest.model_validate(request)
        governor = spec.governor
    elif operation == "governor_eigen":
        governor = GovernorEigenRequest.model_validate(request).governor
    elif operation == "fault":
        spec = FaultRequest.model_validate(request)
    source = Path(andes.get_case(CASES[case])) if case in CASES else folder / "case.xlsx"
    fingerprint = file_digest(source)
    if case not in CASES:
        validate_workbook(source)
        if fingerprint != case[6:]:
            raise ValueError("Model snapshot hash mismatch")
    ss = andes.load(str(source), setup=False, no_output=True)
    governor_change = None
    if governor is not None:
        matches = [idx for idx, active in zip(ss.TGOV1.idx.v, ss.TGOV1.u.v) if str(idx) == governor.device and active]
        if len(matches) != 1:
            raise ValueError("TGOV1 device must uniquely exist and be in service")
        idx = matches[0]
        original = float(ss.TGOV1.get(governor.parameter, idx, "v"))
        ss.TGOV1.set(governor.parameter, idx, governor.value)
        governor_change = {**governor.model_dump(), "before": original}
    if spec is not None:
        if spec.bus not in ss.Bus.idx.v:
            raise ValueError("Fault bus is not in model")
        # Remove preconfigured disturbances to isolate the requested fault.
        for model in (ss.Toggle, ss.Fault, ss.Alter):
            for idx in model.idx.v:
                model.set("u", idx, 0)
        ss.add("Fault", bus=spec.bus, tf=1.0, tc=1.0 + spec.duration_s)
    scenario = None
    changes = []
    if operation == "scenario_flow":
        scenario = ScenarioRequest.model_validate(request)
        # Fresh in-memory model only. Use the declared static PQ loads.
        for idx, p0, q0, active in zip(ss.PQ.idx.v, ss.PQ.p0.v, ss.PQ.q0.v, ss.PQ.u.v):
            if active:
                ss.PQ.set("p0", idx, float(p0) * scenario.load_scale)
                ss.PQ.set("q0", idx, float(q0) * scenario.load_scale)
        changes = apply_edits(ss, scenario.edits)
        if scenario.outage_branch is not None:
            matches = [idx for idx, active in zip(ss.Line.idx.v, ss.Line.u.v)
                       if str(idx) == scenario.outage_branch and active]
            if len(matches) != 1:
                raise ValueError("Outage branch must uniquely exist and be in service")
            ss.Line.set("u", matches[0], 0)
    ss.setup()
    result = {"backend": "andes", "case": case, "operation": operation, "version": andes.__version__,
              "bus_ids": [str(i) for i in ss.Bus.idx.v], "model_sha256": fingerprint}
    if governor_change:
        result["governor_change"] = governor_change
    if scenario is not None:
        result["scenario"] = scenario.model_dump()
        result["device_changes"] = changes
    if operation == "inspect":
        devices = catalog(ss)
        (folder / "devices.json").write_text(json.dumps(devices, allow_nan=False), encoding="utf-8")
        topology = topology_summary(ss)
        (folder / "topology.json").write_text(json.dumps(topology, allow_nan=False), encoding="utf-8")
        return {**result, "status": "ok", "topology": {k: v for k, v in topology.items() if k not in {"buses", "branches"}}}
    if not ss.PFlow.run():
        return {**result, "status": "failed", "reason": "Power flow did not converge"}
    if operation in {"power_flow", "scenario_flow"}:
        return {**result, "status": "ok", "voltages_pu": {
            str(i): float(v) for i, v in zip(ss.Bus.idx.v, ss.Bus.v.v)},
            "angles_rad": {str(i): float(a) for i, a in zip(ss.Bus.idx.v, ss.Bus.a.v)}}
    if operation in {"eigen", "governor_eigen"}:
        if not ss.EIG.run():
            return {**result, "status": "failed", "reason": "Eigenanalysis failed"}
        summary = summarize_modes(ss.EIG.mu)
        modes = summary.pop("modes")
        import csv

        path = folder / "eigenvalues.csv"
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(modes[0]))
            writer.writeheader()
            writer.writerows(modes)
        return {**result, "status": "ok", "metrics": summary, "spectrum": str(path)}
    ss.TDS.config.tf = spec.end_s
    if not ss.TDS.run():
        return {**result, "status": "failed", "reason": "Time-domain solver failed; physical stability unknown"}
    data = ss.TDS.get_timeseries(ss.Bus.v)
    t, v = data.index.to_numpy(), data.to_numpy()
    if len(t) < 2 or t[-1] < spec.end_s - 0.05:
        return {**result, "status": "failed", "reason": "Incomplete simulation"}
    metrics = voltage_metrics(t, v, data.columns, 1.0 + spec.duration_s)
    path = folder / "voltage.csv"
    data.index.name = "time_s"
    data.to_csv(path)
    return {**result, "status": "ok", "fault": spec.model_dump(),
            "metrics": metrics, "waveform": str(path), "samples": int(np.size(t))}


def main():
    folder = Path.cwd()
    try:
        result = execute(sys.argv[1], json.loads(sys.argv[2]), folder)
        (folder / "result.json").write_text(json.dumps(result, allow_nan=False), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 - solver process boundary
        (folder / "result.json").write_text(json.dumps({
            "status": "failed", "backend": "andes", "reason": type(exc).__name__ + ": " + str(exc)[:400]
        }), encoding="utf-8")


if __name__ == "__main__":
    main()
