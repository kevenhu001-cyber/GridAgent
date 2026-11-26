from typing import Annotated, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

CaseName = Annotated[str, Field(pattern=r"^(kundur|ieee14|ieee39|model-[a-f0-9]{64})$")]
CASES = {"kundur": "kundur/kundur_full.xlsx", "ieee14": "ieee14/ieee14_full.xlsx",
         "ieee39": "ieee39/ieee39_full.xlsx"}


class CaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case: CaseName = "kundur"


class DeviceEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    model: Literal["PQ", "PV", "Slack"]
    device: str = Field(min_length=1, max_length=80)
    field: Literal["p0", "q0", "v0"]
    value: float = Field(ge=-20, le=20)

    @model_validator(mode="after")
    def permitted(self):
        allowed = {"PQ": {"p0", "q0"}, "PV": {"p0", "v0"}, "Slack": {"v0"}}
        if self.field not in allowed[self.model]:
            raise ValueError("Unsupported device field")
        if self.field == "v0" and not 0.8 <= self.value <= 1.2:
            raise ValueError("Voltage setpoint must be 0.8..1.2 p.u.")
        return self


class ScenarioRequest(CaseRequest):
    """Local hypothetical steady-state changes, never edits the source model."""
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    load_scale: float = Field(default=1.0, ge=0.5, le=1.5)
    outage_branch: str | None = Field(default=None, min_length=1, max_length=80)
    edits: list[DeviceEdit] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def distinct_edits(self):
        if len({(e.model, e.device, e.field) for e in self.edits}) != len(self.edits):
            raise ValueError("Duplicate device field edit")
        return self


class FaultRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    case: CaseName = "kundur"
    bus: int = Field(ge=1, le=1000000)
    duration_s: float = Field(ge=0.02, le=0.5)
    end_s: float = Field(default=5.0, ge=2.0, le=20.0)

    @model_validator(mode="after")
    def validate_window(self):
        maximum = {"kundur": 10, "ieee14": 14, "ieee39": 39}.get(self.case)
        if maximum is not None and self.bus > maximum:
            raise ValueError("Bus outside packaged case range")
        if self.end_s <= 1.0 + self.duration_s:
            raise ValueError("Simulation must extend past clearing")
        return self


def voltage_metrics(t, v, bus_ids, clearing_s: float) -> dict:
    """Time-averaged normalized post-fault voltage violations, not a stability proof."""
    t = np.asarray(t, dtype=float)
    v = np.asarray(v, dtype=float)
    if t.ndim != 1 or v.ndim != 2 or v.shape != (t.size, len(bus_ids)):
        raise ValueError("Invalid waveform shape")
    if not np.isfinite(t).all() or not np.isfinite(v).all() or np.any(np.diff(t) < 0):
        raise ValueError("Invalid waveform samples")
    mask = t >= clearing_s
    t, v = t[mask], v[mask]
    if len(t) < 2 or t[-1] <= t[0] or not len(bus_ids):
        raise ValueError("Missing post-fault recovery window")
    low = np.clip((0.95 - v) / 0.05, 0, 1)
    high = np.clip((v - 1.05) / 0.05, 0, 1)
    # Trapezoidal integration works with adaptive solver time steps.
    dt = np.diff(t)
    def average(a):
        integral = ((a[:-1] + a[1:]) * 0.5 * dt[:, None]).sum(axis=0)
        return float(np.mean(integral / (t[-1] - t[0])))
    i, j = np.unravel_index(v.argmin(), v.shape)
    k, l = np.unravel_index(v.argmax(), v.shape)
    lo, hi = average(low), average(high)
    return {"v_min_pu": float(v[i, j]), "v_min_bus": str(bus_ids[j]),
            "v_max_pu": float(v[k, l]), "v_max_bus": str(bus_ids[l]),
            "low_voltage_integral": lo, "high_voltage_integral": hi,
            "voltage_severity_proxy": (lo + hi) / 2,
            "window_s": [float(t[0]), float(t[-1])],
            "stability": "not_assessed"}
