"""Fixed-capacity, hourly linear-dispatch contracts, distinct from AC power flow."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .engineering_ir import fingerprint
from .native_program import DispatchProgram
from .task_contracts import Contract

Id = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")]
Positive = Annotated[float, Field(gt=0, le=1e7)]
Cost = Annotated[float, Field(ge=0, le=1e6)]
Power = Annotated[float, Field(ge=0, le=1e6)]
Fraction = Annotated[float, Field(ge=0, le=1)]
PowerProfile = Annotated[tuple[Power, ...], Field(min_length=1, max_length=168)]
CostProfile = Annotated[tuple[Cost, ...], Field(min_length=1, max_length=168)]
Availability = Annotated[tuple[Fraction, ...], Field(min_length=1, max_length=168)]


class DispatchBus(Contract):
    id: Id
    nominal_kv: Positive


class DispatchLoad(Contract):
    id: Id
    bus: Id
    demand_mw: PowerProfile


class DispatchGenerator(Contract):
    id: Id
    bus: Id
    capacity_mw: Positive
    marginal_cost_per_mwh: Cost | CostProfile
    availability_pu: Availability | None = None


class DispatchStorage(Contract):
    """Symmetric fixed MW limit and fixed MWh capacity, with explicit SOC boundaries."""

    id: Id
    bus: Id
    power_capacity_mw: Positive
    energy_capacity_mwh: Positive
    charge_efficiency: float = Field(gt=0, le=1)
    discharge_efficiency: float = Field(gt=0, le=1)
    discharge_cost_per_mwh: Cost = 0
    soc_boundary: Literal["cyclic", "fixed_initial"]
    initial_soc_mwh: float | None = Field(default=None, ge=0, le=1e7)
    terminal_soc_mwh: float | None = Field(default=None, ge=0, le=1e7)

    @model_validator(mode="after")
    def check(self):
        if self.energy_capacity_mwh / self.power_capacity_mw > 168:
            raise ValueError("Storage energy-to-power ratio exceeds supported 168 hours")
        if self.soc_boundary == "cyclic":
            if self.initial_soc_mwh is not None or self.terminal_soc_mwh is not None:
                raise ValueError("Cyclic storage cannot specify fixed SOC boundaries")
        elif self.initial_soc_mwh is None:
            raise ValueError("Fixed-initial storage requires initial_soc_mwh")
        for value in (self.initial_soc_mwh, self.terminal_soc_mwh):
            if value is not None and value > self.energy_capacity_mwh:
                raise ValueError("SOC exceeds energy capacity")
        return self


class DispatchLink(Contract):
    """One-way controllable active-power transfer with conversion losses."""

    id: Id
    from_bus: Id
    to_bus: Id
    capacity_mw: Positive
    efficiency: float = Field(gt=0, le=1)


class DispatchLine(Contract):
    """Lossless linear active-power flow approximation, not an AC rating check."""

    id: Id
    from_bus: Id
    to_bus: Id
    transfer_limit_mw: Positive
    reactance_ohm: Positive


class DispatchModelIR(Contract):
    schema_version: Literal[1] = 1
    family: Literal["hourly_linear_dispatch"] = "hourly_linear_dispatch"
    model_id: Id
    revision: int = Field(default=1, ge=1)
    hours: int = Field(ge=1, le=168)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    buses: tuple[DispatchBus, ...] = Field(min_length=1, max_length=30)
    loads: tuple[DispatchLoad, ...] = Field(min_length=1, max_length=50)
    generators: tuple[DispatchGenerator, ...] = Field(min_length=1, max_length=50)
    storage: tuple[DispatchStorage, ...] = Field(default=(), max_length=30)
    links: tuple[DispatchLink, ...] = Field(default=(), max_length=50)
    lines: tuple[DispatchLine, ...] = Field(default=(), max_length=50)

    @model_validator(mode="after")
    def check(self):
        groups = (self.buses, self.loads, self.generators, self.storage, self.links, self.lines)
        ids = [item.id for group in groups for item in group]
        if len(ids) != len(set(ids)):
            raise ValueError("Dispatch component IDs must be globally unique")
        buses = {bus.id: bus.nominal_kv for bus in self.buses}
        for item in (*self.loads, *self.generators, *self.storage):
            if item.bus not in buses:
                raise ValueError(f"Unknown bus: {item.id}")
        for item in (*self.links, *self.lines):
            if item.from_bus not in buses or item.to_bus not in buses or item.from_bus == item.to_bus:
                raise ValueError(f"Invalid transfer endpoints: {item.id}")
            if isinstance(item, DispatchLine) and buses[item.from_bus] != buses[item.to_bus]:
                raise ValueError("Passive lines require equal nominal bus voltages")
        for load in self.loads:
            if len(load.demand_mw) != self.hours:
                raise ValueError("Demand profile must contain one value per hour")
        for generator in self.generators:
            for profile in (generator.marginal_cost_per_mwh, generator.availability_pu):
                if isinstance(profile, tuple) and len(profile) != self.hours:
                    raise ValueError("Generator profiles must contain one value per hour")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        for name in ("buses", "loads", "generators", "storage", "links", "lines"):
            data[name].sort(key=lambda item: item["id"])
        return data

    def sha256(self):
        return fingerprint(self.canonical())


class DispatchStudySpec(Contract):
    schema_version: Literal[1] = 1
    analysis: Literal["hourly_linear_dispatch"] = "hourly_linear_dispatch"
    objective: Literal["minimize_operating_cost"] = "minimize_operating_cost"
    description: str = Field(min_length=1, max_length=4000)
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DispatchStudy(Contract):
    schema_version: Literal[1] = 1
    model: DispatchModelIR
    study: DispatchStudySpec

    @model_validator(mode="after")
    def verify_binding(self):
        if self.model.sha256() != self.study.model_sha256:
            raise ValueError("Study model fingerprint does not match supplied model")
        return self


def compile_dispatch(source: DispatchStudy) -> tuple[DispatchProgram, dict]:
    """Lower a fixed physical model without changing demand, capacities, or prices."""
    source = DispatchStudy.model_validate(source)
    model = source.model.canonical()
    program = DispatchProgram.model_validate({
        "hours": model["hours"],
        "buses": [{"name": x["id"], "vn_kv": x["nominal_kv"]} for x in model["buses"]],
        "loads": [{"name": x["id"], "bus": x["bus"], "p_set_mw": x["demand_mw"]} for x in model["loads"]],
        "generators": [{"name": x["id"], "bus": x["bus"], "p_nom_mw": x["capacity_mw"],
                        "marginal_cost": x["marginal_cost_per_mwh"], "p_max_pu": x["availability_pu"]}
                       for x in model["generators"]],
        "storage": [{"name": x["id"], "bus": x["bus"], "p_nom_mw": x["power_capacity_mw"],
                     "max_hours": x["energy_capacity_mwh"] / x["power_capacity_mw"],
                     "efficiency_store": x["charge_efficiency"], "efficiency_dispatch": x["discharge_efficiency"],
                     "marginal_cost": x["discharge_cost_per_mwh"], "cyclic_soc": x["soc_boundary"] == "cyclic",
                     "initial_soc_mwh": x["initial_soc_mwh"], "terminal_soc_mwh": x["terminal_soc_mwh"]}
                    for x in model["storage"]],
        "links": [{"name": x["id"], "bus0": x["from_bus"], "bus1": x["to_bus"],
                   "p_nom_mw": x["capacity_mw"], "efficiency": x["efficiency"]} for x in model["links"]],
        # PyPSA's s_nom is an active-power bound in this linear optimization, not an AC MVA result.
        "lines": [{"name": x["id"], "bus0": x["from_bus"], "bus1": x["to_bus"],
                   "s_nom_mva": x["transfer_limit_mw"], "x_ohm": x["reactance_ohm"]}
                  for x in model["lines"]],
    })
    study = source.study.model_dump(mode="json")
    return program, {
        "compiler": "hourly-dispatch-pypsa-v1",
        "model": model,
        "model_sha256": source.model.sha256(),
        "study": study,
        "study_sha256": fingerprint(study),
        "program_sha256": fingerprint(program.model_dump(mode="json")),
        "currency": model["currency"],
        "snapshot_duration_hours": 1,
    }
