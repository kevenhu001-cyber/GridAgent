"""Bounded independent ANDES disturbance and governor-parameter studies."""
import json
from pathlib import Path

from pydantic import Field, model_validator

from .domain import FaultRequest, GovernorEigenRequest, GovernorFaultRequest
from .dsr import Study, digest
from .model_quality import check
from .native_program import Strict
from .simulator import AndesSimulator
from .workspace import waveform


class AndesBatch(Strict):
    faults: list[FaultRequest] = Field(default_factory=list, max_length=20)
    governor_eigen: list[GovernorEigenRequest] = Field(default_factory=list, max_length=20)
    governor_faults: list[GovernorFaultRequest] = Field(default_factory=list, max_length=20)
    require_voltage_recovery: bool = True

    @model_validator(mode="after")
    def check_budget(self):
        if not 1 <= len(self.faults) + len(self.governor_eigen) + len(self.governor_faults) <= 20:
            raise ValueError("Provide 1–20 ANDES runs")
        return self


def verdict(root, operation, result, require_voltage_recovery=True):
    if result.get("status") != "ok":
        return [check("solver_success", False, result.get("reason"))]
    if operation == "governor_eigen":
        modes = result["metrics"]
        return [check("no_growing_small_signal_modes", modes["growing_count"] == 0,
                      modes["growing_count"], "No growing eigenmodes")]
    if not require_voltage_recovery:
        return [check("solver_success", True)]
    try:
        series = waveform(root, result["run_id"])
        extrema = []
        for channel in series["channels"]:
            row = waveform(root, result["run_id"], channel)
            values = row["value"][row["time"] >= row["time"][-1]-0.5]
            extrema.append((float(values.min()), float(values.max())))
        minimum, maximum = min(x[0] for x in extrema), max(x[1] for x in extrema)
        return [check("post_fault_voltage_recovery", 0.90 <= minimum <= maximum <= 1.10,
                      [minimum, maximum], "0.90–1.10 p.u. in the final 0.5 seconds")]
    except (OSError, ValueError, KeyError, TypeError):
        return [check("waveform_evidence", False)]


def run_batch(root, request):
    batch = AndesBatch.model_validate(request)
    root = Path(root)
    study = Study(root / "studies")
    frozen = batch.model_dump(mode="json")
    simulator = AndesSimulator(root / "runs")
    rows = []
    with study.lock():
        study.write("manifest", {"protocol": "gridagent-andes-batch-v1", "batch": frozen,
                                 "manifest_sha256": digest(frozen)})
        for operation, scenarios in (("fault", batch.faults), ("governor_eigen", batch.governor_eigen),
                                     ("governor_fault", batch.governor_faults)):
            for scenario in scenarios:
                index = len(rows)
                inputs = scenario.model_dump(mode="json")
                study.write(f"reservation-{index}", {"operation": operation, "request": inputs})
                result = simulator.run(operation, inputs)
                checks = verdict(root, operation, result, batch.require_voltage_recovery)
                row = {"operation": operation, "run_id": result.get("run_id"), "version": result.get("version"),
                       "checks": checks, "passed": all(x["passed"] for x in checks),
                       "model_sha256": result.get("model_sha256")}
                study.write(f"result-{index}", row)
                rows.append(row)
                yield f"{study.id} · {operation} · {row['run_id']} · {'pass' if row['passed'] else 'fail'}"
        report = {"study_id": study.id, "phase": "andes_batch_finished", "runs": rows,
                  "passed": all(row["passed"] for row in rows)}
        study.write("report", report)
        yield json.dumps(report, ensure_ascii=False)
