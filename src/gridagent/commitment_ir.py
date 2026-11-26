"""Unit-explicit hourly commitment, storage and optional DC network contracts."""

import math
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import fingerprint
from .math_program_ir import Identifier
from .task_contracts import Contract

Power = Annotated[float, Field(ge=0, le=1e6)]
PositivePower = Annotated[float, Field(gt=0, le=1e6)]
Cost = Annotated[float, Field(ge=0, le=1e6)]


class ThermalUnit(Contract):
    id: Identifier
    minimum_mw: Power
    maximum_mw: PositivePower
    marginal_cost_per_mwh: Cost
    online_cost_per_hour: Cost = 0
    startup_cost: Cost = 0
    shutdown_cost: Cost = 0
    ramp_up_mw: Power
    ramp_down_mw: Power
    startup_limit_mw: Power
    shutdown_limit_mw: Power
    min_up_hours: int = Field(ge=1, le=24)
    min_down_hours: int = Field(ge=1, le=24)
    initially_on: bool
    initial_mw: Power
    initial_state_hours: int = Field(ge=1, le=8760)

    @model_validator(mode="after")
    def limits(self):
        if self.minimum_mw > self.maximum_mw:
            raise ValueError("Minimum generation exceeds capacity")
        if max(self.startup_limit_mw, self.shutdown_limit_mw) > self.maximum_mw:
            raise ValueError("Startup/shutdown limits exceed capacity")
        if self.initially_on:
            if not self.minimum_mw <= self.initial_mw <= self.maximum_mw:
                raise ValueError("Initial online generation outside bounds")
        elif self.initial_mw != 0:
            raise ValueError("Offline unit must have zero initial generation")
        return self


class CommitmentStorage(Contract):
    id: Identifier
    power_mw: PositivePower
    energy_mwh: PositivePower
    initial_mwh: Power
    terminal_mwh: Power
    charge_efficiency: float = Field(ge=0.01, le=1)
    discharge_efficiency: float = Field(ge=0.01, le=1)
    discharge_cost_per_mwh: Cost = 0

    @model_validator(mode="after")
    def limits(self):
        if max(self.initial_mwh, self.terminal_mwh) > self.energy_mwh:
            raise ValueError("Initial or terminal SOC exceeds storage capacity")
        return self


class CommitmentBus(Contract):
    id: Identifier
    demand_mw: tuple[Power, ...] = Field(min_length=1, max_length=24)


class CommitmentLine(Contract):
    """Positive flow is from_bus -> to_bus; lossless DC approximation."""

    id: Identifier
    from_bus: Identifier
    to_bus: Identifier
    susceptance_mw_per_rad: float = Field(ge=1e-3, le=1e8)
    limit_mw: PositivePower
    max_angle_difference_rad: float = Field(gt=0, le=0.5)


class CommitmentNetwork(Contract):
    schema_version: Literal[1] = 1
    buses: tuple[CommitmentBus, ...] = Field(min_length=2, max_length=20)
    lines: tuple[CommitmentLine, ...] = Field(min_length=1, max_length=40)
    reference_bus: Identifier
    angle_bound_rad: float = Field(gt=0, le=3.141592653589793)
    unit_buses: dict[Identifier, Identifier]
    storage_buses: dict[Identifier, Identifier] = Field(default_factory=dict)
    reserve_requirement_mw: tuple[Power, ...] = Field(min_length=1, max_length=24)
    reserve_response_minutes: float = Field(gt=0, le=60)
    unit_reserve_capability_mw: dict[Identifier, Power]

    @model_validator(mode="after")
    def topology(self):
        ids = [b.id for b in self.buses]
        nodes = set(ids)
        if len(nodes) != len(ids) or len({line.id for line in self.lines}) != len(self.lines):
            raise ValueError("Duplicate network component ID")
        if self.reference_bus not in nodes:
            raise ValueError("Unknown reference bus")
        neighbors = {key: set() for key in nodes}
        for line in self.lines:
            if line.from_bus not in nodes or line.to_bus not in nodes or line.from_bus == line.to_bus:
                raise ValueError("Invalid network line endpoints")
            neighbors[line.from_bus].add(line.to_bus)
            neighbors[line.to_bus].add(line.from_bus)
        visited = set()
        stack = [self.reference_bus]
        while stack:
            node = stack.pop()
            if node not in visited:
                visited.add(node)
                stack.extend(neighbors[node] - visited)
        if visited != nodes:
            raise ValueError("DC commitment currently requires a connected network")
        if not (set(self.unit_buses.values()) | set(self.storage_buses.values())) <= nodes:
            raise ValueError("Unknown equipment connection bus")
        return self


class UnitCommitment(Contract):
    schema_version: Literal[1] = 1
    family: Literal["unit_commitment"] = "unit_commitment"
    description: str = Field(min_length=1, max_length=4000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    demand_mw: tuple[Power, ...] = Field(min_length=1, max_length=24)
    units: tuple[ThermalUnit, ...] = Field(min_length=1, max_length=12)
    storage: tuple[CommitmentStorage, ...] = Field(default=(), max_length=6)
    network: CommitmentNetwork | None = None
    time_limit_s: int = Field(default=30, ge=1, le=120)
    node_limit: int = Field(default=10000, ge=1, le=100000)

    @model_validator(mode="after")
    def validate_size(self):
        ids = [item.id for item in (*self.units, *self.storage)]
        if len(ids) != len(set(ids)):
            raise ValueError("Commitment equipment IDs must be unique")
        hours = len(self.demand_mw)
        # Exactly four variables per device/hour; the generic solver's limits
        # also bound generated constraint rows.
        variables = hours * 4 * (len(self.units) + len(self.storage))
        rows = hours * (8*len(self.units) + 3*len(self.storage) + 1) + len(self.storage)
        if self.network is not None:
            network = self.network
            unit_ids = {u.id for u in self.units}
            storage_ids = {b.id for b in self.storage}
            if set(network.unit_buses) != unit_ids or set(network.storage_buses) != storage_ids:
                raise ValueError("Network must map every unit and storage device exactly once")
            if set(network.unit_reserve_capability_mw) != unit_ids:
                raise ValueError("Declare reserve capability for every unit, including zero")
            if any(network.unit_reserve_capability_mw[u.id] > u.maximum_mw for u in self.units):
                raise ValueError("Reserve capability exceeds unit capacity")
            if any(len(bus.demand_mw) != hours for bus in network.buses) or len(network.reserve_requirement_mw) != hours:
                raise ValueError("Network profiles must match the commitment horizon")
            for t, demand in enumerate(self.demand_mw):
                if abs(math.fsum(bus.demand_mw[t] for bus in network.buses) - demand) > 1e-8:
                    raise ValueError("Bus demands must sum to the specified system demand")
            variables += hours * (len(network.buses) + len(network.lines) + len(self.units))
            rows += hours * (len(network.buses) + 2*len(network.lines) + len(self.units))
        if variables > 200:
            raise ValueError("Commitment exceeds the mathematical variable budget")
        if rows > 500:
            raise ValueError("Commitment exceeds the mathematical constraint budget")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        for group in ("units", "storage"):
            data[group].sort(key=lambda row: row["id"])
        if self.network is None:
            data.pop("network")
        else:
            for group in ("buses", "lines"):
                data["network"][group].sort(key=lambda row: row["id"])
        return data

    def sha256(self):
        return fingerprint(self.canonical())

    def route(self):
        return "scipy-highs-milp"
