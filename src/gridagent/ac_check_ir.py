"""Explicit mapping from a verified DC commitment schedule to AC snapshots."""

import math
from typing import Annotated

from pydantic import Field, model_validator

from .commitment_compiler import ordered
from .commitment_ir import UnitCommitment
from .commitment_security import references
from .engineering_ir import AcceptanceIR, EngineeringStudy, ModelIR, StudySpec, fingerprint
from .math_program_ir import Identifier
from .task_contracts import Contract


class ReactiveRange(Contract):
    minimum_mvar: float = Field(ge=-1e6, le=1e6)
    maximum_mvar: float = Field(ge=-1e6, le=1e6)

    @model_validator(mode="after")
    def limits(self):
        if self.minimum_mvar > self.maximum_mvar:
            raise ValueError("Invalid reactive range")
        return self


class Snapshot(Contract):
    hour: int = Field(ge=0, le=23)
    outage_line: Identifier | None = None


class ACCheckSpec(Contract):
    commitment_study_id: Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]
    model: ModelIR
    unit_devices: dict[Identifier, Identifier]
    storage_devices: dict[Identifier, Identifier] = Field(default_factory=dict)
    slack_unit: Identifier
    unit_reactive_limits: dict[Identifier, ReactiveRange]
    reactive_demand_mvar: dict[Identifier, tuple[Annotated[float, Field(ge=-1e6, le=1e6)], ...]]
    snapshots: tuple[Snapshot, ...] = Field(min_length=1, max_length=24)
    acceptance: AcceptanceIR = Field(default_factory=AcceptanceIR)
    slack_max_deviation_mw: float = Field(gt=0, le=1e6)
    dispatch_tolerance_mw: float = Field(default=1e-5, gt=0, le=0.01)
    timeout_s: int = Field(default=120, ge=1, le=300)

    def canonical(self):
        data = self.model_dump(mode="json")
        data["model"] = self.model.canonical()
        return data

    def sha256(self):
        return fingerprint(self.canonical())


def validate_mapping(spec, commitment):
    commitment = ordered(UnitCommitment.model_validate(commitment))
    network = commitment.network
    if network is None:
        raise ValueError("AC verification requires a DC network commitment")
    buses = {bus.id: bus for bus in spec.model.buses}
    devices = {d.id: d for d in spec.model.devices}
    if set(buses) != {bus.id for bus in network.buses}:
        raise ValueError("AC and DC bus IDs must match exactly")
    units = {unit.id for unit in commitment.units}
    storage = {item.id for item in commitment.storage}
    if (set(spec.unit_devices) != units or set(spec.storage_devices) != storage
            or set(spec.unit_reactive_limits) != units or spec.slack_unit not in units):
        raise ValueError("Explicit mappings and reactive limits required for all equipment")
    if network.unit_buses[spec.slack_unit] != network.reference_bus:
        raise ValueError("Slack unit must be connected to the DC reference bus")
    if set(spec.reactive_demand_mvar) != set(buses) or any(
            len(profile) != len(commitment.demand_mw) for profile in spec.reactive_demand_mvar.values()):
        raise ValueError("Explicit hourly reactive demand required at every bus")
    used = []
    for key, device_id in spec.unit_devices.items():
        device = devices.get(device_id)
        kind = "slack" if key == spec.slack_unit else "generator"
        if device is None or device.kind != kind or device.bus != network.unit_buses[key]:
            raise ValueError("Incorrect AC unit mapping")
        used.append(device_id)
    for key, device_id in spec.storage_devices.items():
        device = devices.get(device_id)
        battery = next(b for b in commitment.storage if b.id == key)
        if (device is None or device.kind != "storage" or device.bus != network.storage_buses[key]
                or not math.isclose(device.energy_capacity_mwh, battery.energy_mwh, rel_tol=1e-9)):
            raise ValueError("Incorrect AC storage mapping")
        used.append(device_id)
    for bus in buses:
        loads = [d for d in devices.values() if d.kind == "load" and d.bus == bus]
        if len(loads) != 1:
            raise ValueError("Exactly one explicitly authorized AC load per bus is required")
        used.append(loads[0].id)
    for line in network.lines:
        ac = devices.get(line.id)
        if ac is None or ac.kind != "line" or (ac.from_bus, ac.to_bus) != (line.from_bus, line.to_bus):
            raise ValueError("AC and DC branch IDs and orientation must match")
        coefficient = buses[ac.from_bus].nominal_kv**2 / (ac.length_km*ac.reactance_ohm_per_km)
        if not math.isclose(coefficient, line.susceptance_mw_per_rad, rel_tol=1e-6):
            raise ValueError("AC reactance inconsistent with DC flow coefficient")
        used.append(line.id)
    if len(used) != len(set(used)) or set(used) != set(devices):
        raise ValueError("Unmapped or duplicated AC equipment")
    allowed = set(network.security.outage_lines) if network.security is not None else set()
    keys = set()
    for snapshot in spec.snapshots:
        key = (snapshot.hour, snapshot.outage_line)
        if key in keys or snapshot.hour >= len(commitment.demand_mw):
            raise ValueError("Duplicate or out-of-range snapshot")
        keys.add(key)
        if snapshot.outage_line is not None:
            if snapshot.outage_line not in allowed:
                raise ValueError("Outage not verified in DC commitment")
            if len(references(network, snapshot.outage_line)) != 1:
                raise ValueError("Islanded AC snapshots require an explicit per-island slack model")
    return commitment


def snapshot_study(spec, commitment, schedule, snapshot):
    """Freeze one AC operating point, preserving authorized impedances and voltage setpoints."""
    t = snapshot.hour
    network = commitment.network
    data = spec.model.canonical()
    rows = {row["id"]: row for row in data["devices"]}
    outage = snapshot.outage_line
    post = schedule["security"]["cases"][outage]["hours"][t]["units"] if outage else None
    expected = {}
    removed = set()
    for unit in commitment.units:
        base = schedule["units"][unit.id]["hours"][t]
        actual = post[unit.id]["generation_mw"] if post else base["generation_mw"]
        device_id = spec.unit_devices[unit.id]
        if not base["on"]:
            if unit.id == spec.slack_unit:
                raise ValueError("Authorized slack is offline in selected snapshot")
            removed.add(device_id)
            continue
        expected[unit.id] = {"device": device_id, "p_mw": actual, "base_mw": base["generation_mw"],
                             "reserve_mw": base["reserve_mw"]}
        if unit.id != spec.slack_unit:
            rows[device_id]["active_mw"] = max(0.0, actual)
    for battery in commitment.storage:
        state = schedule["storage"][battery.id][t]
        row = rows[spec.storage_devices[battery.id]]
        row["charging_mw"] = state["charge_mw"]-state["discharge_mw"]
        previous = battery.initial_mwh if t == 0 else schedule["storage"][battery.id][t-1]["soc_mwh"]
        row["initial_soc_percent"] = min(100.0, max(0.0, previous/battery.energy_mwh*100))
    for bus in network.buses:
        load = next(row for row in rows.values() if row["kind"] == "load" and row["bus"] == bus.id)
        load["active_mw"] = bus.demand_mw[t]
        load["reactive_mvar"] = spec.reactive_demand_mvar[bus.id][t]
    data["revision"] += 1
    data["devices"] = [row for row in rows.values() if row["id"] not in removed]
    model = ModelIR.model_validate(data)
    study = StudySpec(objective="AC validation of frozen DC commitment snapshot",
                      model_sha256=model.sha256(), scenarios=[{"name": "snapshot", "outage_device": outage}],
                      acceptance=spec.acceptance, max_runs=1)
    return EngineeringStudy(model=model, study=study), expected
