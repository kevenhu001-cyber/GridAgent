"""Bounded deterministic fault-duration sweep, not a stability threshold estimator."""
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .domain import FaultRequest
from .dsr import Study, digest


class SweepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    bus: int = Field(ge=1, le=10)
    durations_s: list[float] = Field(min_length=1, max_length=10)
    end_s: float = Field(default=5, ge=2, le=20)

    @model_validator(mode="after")
    def validate_points(self):
        if len(set(self.durations_s)) != len(self.durations_s):
            raise ValueError("Duplicate duration")
        for duration in self.durations_s:
            FaultRequest(bus=self.bus, duration_s=duration, end_s=self.end_s)
        return self


def sweep_updates(spec: SweepRequest, simulator, root: Path):
    study = Study(root)
    manifest = spec.model_dump(mode="json")
    study.write("manifest", {"protocol": "andes-fault-duration-sweep-v1", "manifest": manifest,
                             "manifest_sha256": digest(manifest)})
    yield "study", study.id
    points = []
    for i, duration in enumerate(sorted(spec.durations_s), 1):
        request = FaultRequest(bus=spec.bus, duration_s=duration, end_s=spec.end_s).model_dump()
        study.write(f"attempt-{i}", request)
        try:
            result = simulator.run("fault", request)
        except Exception as exc:  # noqa: BLE001 - preserve attempted run and continue
            result = {"status": "failed", "reason": type(exc).__name__}
        point = {"duration_s": duration, "status": result.get("status", "failed"),
                 "run_id": result.get("run_id"),
                 "score": result.get("metrics", {}).get("voltage_severity_proxy")}
        study.write(f"result-{i}", {"point": point, "result": result})
        points.append(point)
        yield "point", point
    report = {"study_id": study.id, "protocol": "andes-fault-duration-sweep-v1",
              "points": points, "completed": all(p["status"] == "ok" for p in points),
              "stability": "not_assessed"}
    study.write("report", report)
    yield "report", report


def format_update(node, data):
    if node == "study":
        return f"Duration sweep · {data}"
    if node == "point":
        score = data["score"]
        label = f"{score:.5g}" if score is not None else "unavailable"
        return f"{data['duration_s']:g} s · {data['status']} · voltage score {label}"
    return "Sweep complete. Voltage score does not establish critical clearing time."
