"""A typed simulation program: native solver APIs, not arbitrary Python evaluation."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Finite = Annotated[float, Field(allow_inf_nan=False, ge=-1e7, le=1e7)]
Positive = Annotated[float, Field(allow_inf_nan=False, gt=0, le=1e7)]
Index = Annotated[int, Field(ge=0, le=100000)]
Name = Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,47}$")]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bus(Strict):
    op: Literal["create_bus"]
    index: Index
    vn_kv: Positive


class Grid(Strict):
    op: Literal["create_ext_grid"]
    bus: Index
    vm_pu: float = Field(default=1, ge=0.8, le=1.2)
    s_sc_max_mva: Positive | None = None
    rx_max: float = Field(default=0.1, gt=0, le=10)


class Line(Strict):
    op: Literal["create_line_from_parameters"]
    index: Index
    from_bus: Index
    to_bus: Index
    length_km: Positive
    r_ohm_per_km: float = Field(ge=0, le=100)
    x_ohm_per_km: Positive
    c_nf_per_km: float = Field(default=0, ge=0, le=1e5)
    max_i_ka: Positive


class Load(Strict):
    op: Literal["create_load"]
    index: Index
    bus: Index
    p_mw: float = Field(ge=0, le=1e6)
    q_mvar: Finite = 0


class Generator(Strict):
    op: Literal["create_gen"]
    index: Index
    bus: Index
    p_mw: float = Field(ge=0, le=1e6)
    vm_pu: float = Field(default=1, ge=0.8, le=1.2)


class StaticGenerator(Strict):
    op: Literal["create_sgen"]
    index: Index
    bus: Index
    p_mw: float = Field(ge=0, le=1e6)
    q_mvar: Finite = 0


class Storage(Strict):
    op: Literal["create_storage"]
    index: Index
    bus: Index
    p_mw: Finite
    max_e_mwh: Positive
    q_mvar: Finite = 0
    soc_percent: float = Field(default=50, ge=0, le=100)


class Edit(Strict):
    op: Literal["edit"]
    element: Literal["load", "gen", "sgen", "storage", "line", "trafo", "ext_grid"]
    index: Index
    field: Literal["p_mw", "q_mvar", "vm_pu", "scaling", "in_service", "max_i_ka", "tap_pos"]
    value: Finite | bool

    @model_validator(mode="after")
    def check(self):
        allowed = {"load": {"p_mw", "q_mvar", "scaling", "in_service"},
                   "gen": {"p_mw", "vm_pu", "scaling", "in_service"},
                   "sgen": {"p_mw", "q_mvar", "scaling", "in_service"},
                   "storage": {"p_mw", "q_mvar", "scaling", "in_service"},
                   "line": {"in_service", "max_i_ka"}, "trafo": {"in_service", "tap_pos"},
                   "ext_grid": {"vm_pu", "in_service"}}
        if self.field not in allowed[self.element]:
            raise ValueError("Field is not supported for this element")
        if self.field == "in_service":
            if not isinstance(self.value, bool):
                raise ValueError("in_service must be boolean")
        elif isinstance(self.value, bool):
            raise ValueError("Expected numerical parameter")
        elif self.field == "vm_pu" and not 0.8 <= self.value <= 1.2:
            raise ValueError("Voltage setpoint outside 0.8..1.2 p.u.")
        elif self.field == "scaling" and not 0 <= self.value <= 2:
            raise ValueError("Scaling outside 0..2")
        elif self.field == "max_i_ka" and self.value <= 0:
            raise ValueError("Current rating must be positive")
        elif self.field == "tap_pos" and not float(self.value).is_integer():
            raise ValueError("Tap position must be integer")
        return self


Step = Annotated[Bus | Grid | Line | Load | Generator | StaticGenerator | Storage | Edit,
                 Field(discriminator="op")]


class PPProgram(Strict):
    backend: Literal["pandapower"] = "pandapower"
    base: Literal["empty", "case14", "case39", "case118"] = "empty"
    steps: list[Step] = Field(default_factory=list, max_length=200)
    analysis: Literal["inspect", "power_flow", "short_circuit"] = "power_flow"
    fault_bus: Index | None = None

    @model_validator(mode="after")
    def check(self):
        if (self.analysis == "short_circuit") != (self.fault_bus is not None):
            raise ValueError("Specify fault_bus only for a three-phase short circuit")
        return self


Series = Annotated[list[Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)]],
                   Field(min_length=1, max_length=168)]
Availability = Annotated[list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]],
                         Field(min_length=1, max_length=168)]
CostSeries = Annotated[list[Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)]],
                       Field(min_length=1, max_length=168)]


class EnergyBus(Strict):
    name: Name


class EnergyLoad(Strict):
    name: Name
    bus: Name
    p_set_mw: Series


class EnergyGenerator(Strict):
    name: Name
    bus: Name
    p_nom_mw: Positive
    marginal_cost: float | CostSeries
    p_max_pu: Availability | None = None

    @model_validator(mode="after")
    def check(self):
        if isinstance(self.marginal_cost, float) and not 0 <= self.marginal_cost <= 1e6:
            raise ValueError("Marginal cost must be 0..1e6")
        return self


class EnergyStorage(Strict):
    name: Name
    bus: Name
    p_nom_mw: Positive
    max_hours: float = Field(gt=0, le=168)
    efficiency_store: float = Field(default=0.95, gt=0, le=1)
    efficiency_dispatch: float = Field(default=0.95, gt=0, le=1)
    marginal_cost: float = Field(default=0, ge=0, le=1e6)


class EnergyLink(Strict):
    name: Name
    bus0: Name
    bus1: Name
    p_nom_mw: Positive
    efficiency: float = Field(default=1, gt=0, le=1)


class DispatchProgram(Strict):
    backend: Literal["pypsa"] = "pypsa"
    hours: int = Field(ge=1, le=168)
    buses: list[EnergyBus] = Field(min_length=1, max_length=30)
    loads: list[EnergyLoad] = Field(min_length=1, max_length=50)
    generators: list[EnergyGenerator] = Field(min_length=1, max_length=50)
    storage: list[EnergyStorage] = Field(default_factory=list, max_length=30)
    links: list[EnergyLink] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def check(self):
        buses = {b.name for b in self.buses}
        for group in (self.buses, self.loads, self.generators, self.storage, self.links):
            if len({x.name for x in group}) != len(group):
                raise ValueError("Duplicate component name")
        for component in [*self.loads, *self.generators, *self.storage]:
            if component.bus not in buses:
                raise ValueError("Component references unknown bus")
        for link in self.links:
            if link.bus0 not in buses or link.bus1 not in buses or link.bus0 == link.bus1:
                raise ValueError("Invalid link endpoints")
        for load in self.loads:
            if len(load.p_set_mw) != self.hours:
                raise ValueError("Load profile must have exactly hours samples")
        for gen in self.generators:
            for profile in (gen.p_max_pu, gen.marginal_cost):
                if isinstance(profile, list) and len(profile) != self.hours:
                    raise ValueError("Generator profile must have exactly hours samples")
        return self


Program = Annotated[PPProgram | DispatchProgram, Field(discriminator="backend")]
