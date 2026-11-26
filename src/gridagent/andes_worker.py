"""Isolated ANDES process. Only packaged cases and validated operations are accepted."""
import json
import sys
from pathlib import Path

from .domain import CASES, FaultRequest, voltage_metrics
from .modal import summarize_modes


def execute(operation: str, request: dict, folder: Path) -> dict:
    import andes
    import numpy as np

    case = request.get("case", "kundur")
    if case not in CASES:
        raise ValueError("Unknown packaged case")
    if operation not in {"inspect", "power_flow", "fault", "eigen"}:
        raise ValueError("Unknown operation")
    spec = FaultRequest.model_validate(request) if operation == "fault" else None
    ss = andes.load(andes.get_case(CASES[case]), setup=False, no_output=True)
    if operation == "fault":
        # Remove preconfigured disturbances to isolate the requested fault.
        for model in (ss.Toggle, ss.Fault, ss.Alter):
            for idx in model.idx.v:
                model.set("u", idx, 0)
        ss.add("Fault", bus=spec.bus, tf=1.0, tc=1.0 + spec.duration_s)
    ss.setup()
    result = {"backend": "andes", "case": case, "operation": operation,
              "bus_ids": [str(i) for i in ss.Bus.idx.v]}
    if operation == "inspect":
        return {**result, "status": "ok"}
    if not ss.PFlow.run():
        return {**result, "status": "failed", "reason": "Power flow did not converge"}
    if operation == "power_flow":
        return {**result, "status": "ok", "voltages_pu": {
            str(i): float(v) for i, v in zip(ss.Bus.idx.v, ss.Bus.v.v)}}
    if operation == "eigen":
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
