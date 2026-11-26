"""Backend-independent, unit-explicit AC steady-state engineering contracts."""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .task_contracts import Contract

DeviceId = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
Positive = Annotated[float, Field(gt=0, le=1e7)]
Finite = Annotated[float, Field(ge=-1e7, le=1e7)]


class BusIR(Contract):
    id: DeviceId
    nominal_kv: Positive


class SlackIR(Contract):
    kind: Literal["slack"]
    id: DeviceId
    bus: DeviceId
    voltage_pu: float = Field(default=1, ge=0.8, le=1.2)


class LoadIR(Contract):
    kind: Literal["load"]
    id: DeviceId
    bus: DeviceId
    active_mw: float = Field(ge=0, le=1e6)
    reactive_mvar: Finite = 0


class GeneratorIR(Contract):
    kind: Literal["generator"]
    id: DeviceId
    bus: DeviceId
    active_mw: float = Field(ge=0, le=1e6)
    voltage_pu: float = Field(default=1, ge=0.8, le=1.2)


class StorageIR(Contract):
    """Fixed PQ operating point, not a state-of-charge evolution model.

    Positive charging_mw denotes consumption; negative denotes discharge.
    Reactive power uses the same consumption-positive convention.
    """
    kind: Literal["storage"]
    id: DeviceId
    bus: DeviceId
    charging_mw: Finite
    reactive_mvar: Finite = 0
    energy_capacity_mwh: Positive
    initial_soc_percent: float = Field(ge=0, le=100)


class LineIR(Contract):
    kind: Literal["line"]
    id: DeviceId
    from_bus: DeviceId
    to_bus: DeviceId
    length_km: Positive
    resistance_ohm_per_km: float = Field(ge=0, le=100)
    reactance_ohm_per_km: Positive
    capacitance_nf_per_km: float = Field(default=0, ge=0, le=1e5)
    current_limit_ka: Positive


class TransformerIR(Contract):
    kind: Literal["transformer"]
    id: DeviceId
    hv_bus: DeviceId
    lv_bus: DeviceId
    rated_mva: Positive
    rated_hv_kv: Positive
    rated_lv_kv: Positive
    resistance_percent: float = Field(ge=0, le=100)
    impedance_percent: float = Field(gt=0, le=100)
    iron_loss_kw: float = Field(ge=0, le=1e6)
    no_load_current_percent: float = Field(ge=0, le=100)
    phase_shift_degree: float = Field(default=0, ge=-180, le=180)

    @model_validator(mode="after")
    def validate_ratings(self):
        if self.rated_hv_kv <= self.rated_lv_kv or self.resistance_percent > self.impedance_percent:
            raise ValueError("Invalid transformer voltage or impedance ratings")
        return self


DeviceIR = Annotated[
    SlackIR | LoadIR | GeneratorIR | StorageIR | LineIR | TransformerIR,
    Field(discriminator="kind"),
]


def fingerprint(data):
    serialized = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ModelIR(Contract):
    """Versioned physical-unit network; voltage p.u. is relative to the connected bus nominal kV."""

    schema_version: Literal[1] = 1
    family: Literal["ac_steady_state"] = "ac_steady_state"
    model_id: DeviceId
    revision: int = Field(default=1, ge=1)
    buses: tuple[BusIR, ...] = Field(min_length=1, max_length=199)
    devices: tuple[DeviceIR, ...] = Field(min_length=1, max_length=199)

    @model_validator(mode="after")
    def validate_network(self):
        if len(self.buses) + len(self.devices) > 200:
            raise ValueError("Network exceeds the native 200-step limit")
        ids = [item.id for item in (*self.buses, *self.devices)]
        if len(ids) != len(set(ids)):
            raise ValueError("Bus and device IDs must be globally unique")
        buses = {bus.id: bus.nominal_kv for bus in self.buses}
        neighbors = {key: set() for key in buses}
        slacks = set()
        for device in self.devices:
            if isinstance(device, (LineIR, TransformerIR)):
                if isinstance(device, LineIR):
                    a, b = device.from_bus, device.to_bus
                else:
                    a, b = device.hv_bus, device.lv_bus
                if a not in buses or b not in buses or a == b:
                    raise ValueError(f"Invalid branch endpoints: {device.id}")
                if isinstance(device, LineIR) and buses[a] != buses[b]:
                    raise ValueError(f"Line voltage bases differ: {device.id}; use a transformer")
                if isinstance(device, TransformerIR) and buses[a] <= buses[b]:
                    raise ValueError(f"Transformer must connect higher to lower voltage buses: {device.id}")
                neighbors[a].add(b)
                neighbors[b].add(a)
            else:
                if device.bus not in buses:
                    raise ValueError(f"Unknown bus for device: {device.id}")
                if isinstance(device, SlackIR):
                    slacks.add(device.bus)
        pending = set(buses)
        while pending:
            component = set()
            stack = [next(iter(pending))]
            while stack:
                bus = stack.pop()
                if bus in component:
                    continue
                component.add(bus)
                stack.extend(neighbors[bus] - component)
            pending -= component
            if not component.intersection(slacks):
                raise ValueError("Every baseline connected component must have a slack source")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        for name in ("buses", "devices"):
            data[name].sort(key=lambda row: row["id"])
        return data

    def sha256(self):
        return fingerprint(self.canonical())


class ScenarioIR(Contract):
    name: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")]
    load_scale: float = Field(default=1, ge=0, le=2)
    outage_device: DeviceId | None = None


class AcceptanceIR(Contract):
    voltage_min_pu: float = Field(default=0.90, gt=0, le=2)
    voltage_max_pu: float = Field(default=1.10, gt=0, le=2)
    loading_max_percent: float = Field(default=100, gt=0, le=200)
    balance_tolerance_mva: float = Field(default=0.001, gt=0, le=1)

    @model_validator(mode="after")
    def check_voltage(self):
        if self.voltage_min_pu > self.voltage_max_pu:
            raise ValueError("Minimum voltage exceeds maximum voltage")
        return self


class StudySpec(Contract):
    schema_version: Literal[1] = 1
    analysis: Literal["ac_power_flow"] = "ac_power_flow"
    objective: str = Field(min_length=1, max_length=4000)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    scenarios: tuple[ScenarioIR, ...] = Field(min_length=1, max_length=20)
    acceptance: AcceptanceIR = Field(default_factory=AcceptanceIR)
    max_runs: int = Field(default=20, ge=1, le=60)

    @model_validator(mode="after")
    def check_scenarios(self):
        if len({scenario.name for scenario in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario names must be unique")
        if self.max_runs < len(self.scenarios):
            raise ValueError("Insufficient simulation budget for specified scenarios")
        return self


class EngineeringStudy(Contract):
    """Portable input document binding a study to one exact model revision."""

    schema_version: Literal[1] = 1
    model: ModelIR
    study: StudySpec

    @model_validator(mode="after")
    def verify_binding(self):
        if self.model.sha256() != self.study.model_sha256:
            raise ValueError("Study model fingerprint does not match supplied model")
        return self
