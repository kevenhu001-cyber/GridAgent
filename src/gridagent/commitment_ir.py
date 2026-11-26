"""Unit-explicit single-area hourly commitment and storage optimization."""

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


class UnitCommitment(Contract):
    schema_version: Literal[1] = 1
    family: Literal["unit_commitment"] = "unit_commitment"
    description: str = Field(min_length=1, max_length=4000)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    demand_mw: tuple[Power, ...] = Field(min_length=1, max_length=24)
    units: tuple[ThermalUnit, ...] = Field(min_length=1, max_length=12)
    storage: tuple[CommitmentStorage, ...] = Field(default=(), max_length=6)
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
        if hours * 4 * (len(self.units) + len(self.storage)) > 200:
            raise ValueError("Commitment exceeds the mathematical variable budget")
        rows = hours * (8*len(self.units) + 3*len(self.storage) + 1) + len(self.storage)
        if rows > 500:
            raise ValueError("Commitment exceeds the mathematical constraint budget")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        for group in ("units", "storage"):
            data[group].sort(key=lambda row: row["id"])
        return data

    def sha256(self):
        return fingerprint(self.canonical())

    def route(self):
        return "scipy-highs-milp"
