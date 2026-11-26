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


class Transformer(Strict):
    op: Literal["create_transformer_from_parameters"]
    index: Index
    hv_bus: Index
    lv_bus: Index
    sn_mva: Positive
    vn_hv_kv: Positive
    vn_lv_kv: Positive
    vkr_percent: float = Field(ge=0, le=100)
    vk_percent: float = Field(gt=0, le=100)
    pfe_kw: float = Field(ge=0, le=1e6)
    i0_percent: float = Field(ge=0, le=100)
    shift_degree: float = Field(default=0, ge=-180, le=180)
    tap_side: Literal["hv", "lv"] | None = None
    tap_neutral: int = Field(default=0, ge=-50, le=50)
    tap_min: int | None = Field(default=None, ge=-50, le=50)
    tap_max: int | None = Field(default=None, ge=-50, le=50)
    tap_step_percent: float | None = Field(default=None, gt=0, le=20)
    tap_pos: int | None = Field(default=None, ge=-50, le=50)

    @model_validator(mode="after")
    def check(self):
        if self.hv_bus == self.lv_bus or self.vn_hv_kv <= self.vn_lv_kv or self.vkr_percent > self.vk_percent:
            raise ValueError("Invalid transformer buses, rated voltages or impedances")
        tap = (self.tap_min, self.tap_max, self.tap_step_percent, self.tap_pos)
        if self.tap_side is None:
            if any(value is not None for value in tap):
                raise ValueError("A tap changer requires tap_side")
        elif any(value is None for value in tap):
            raise ValueError("Specify the tap range, step and position")
        elif not (self.tap_min <= self.tap_neutral <= self.tap_max and self.tap_min <= self.tap_pos <= self.tap_max):
            raise ValueError("Tap neutral and position must lie inside the tap range")
        return self


class Switch(Strict):
    op: Literal["create_switch"]
    index: Index
    bus: Index
    element: Index
    et: Literal["b", "l", "t"]
    closed: bool


class Edit(Strict):
    op: Literal["edit"]
    element: Literal["load", "gen", "sgen", "storage", "line", "trafo", "ext_grid", "switch"]
    index: Index
    field: Literal["p_mw", "q_mvar", "vm_pu", "scaling", "in_service", "max_i_ka", "tap_pos", "closed"]
    value: Finite | bool

    @model_validator(mode="after")
    def check(self):
        allowed = {"load": {"p_mw", "q_mvar", "scaling", "in_service"},
                   "gen": {"p_mw", "vm_pu", "scaling", "in_service"},
                   "sgen": {"p_mw", "q_mvar", "scaling", "in_service"},
                   "storage": {"p_mw", "q_mvar", "scaling", "in_service"},
                   "line": {"in_service", "max_i_ka"}, "trafo": {"in_service", "tap_pos"},
                   "ext_grid": {"vm_pu", "in_service"}, "switch": {"closed"}}
        if self.field not in allowed[self.element]:
            raise ValueError("Field is not supported for this element")
        if self.field in {"in_service", "closed"}:
            if not isinstance(self.value, bool):
                raise ValueError(f"{self.field} must be boolean")
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


Step = Annotated[Bus | Grid | Line | Load | Generator | StaticGenerator | Storage | Transformer | Switch | Edit,
                 Field(discriminator="op")]


class Outage(Strict):
    element: Literal["line", "trafo"]
    index: Index


class PPProgram(Strict):
    backend: Literal["pandapower"] = "pandapower"
    base: Literal["empty", "case14", "case39", "case118"] = "empty"
    parent_run: str | None = Field(default=None, pattern=r"^[a-f0-9]{32}$")
    steps: list[Step] = Field(default_factory=list, max_length=200)
    analysis: Literal["inspect", "power_flow", "short_circuit"] = "power_flow"
    fault_bus: Index | None = None
    load_scale: float = Field(default=1, ge=0, le=2)
    contingency: Outage | None = None

    @model_validator(mode="after")
    def check(self):
        if (self.analysis == "short_circuit") != (self.fault_bus is not None):
            raise ValueError("Specify fault_bus only for a three-phase short circuit")
        if (self.load_scale != 1 or self.contingency is not None) and self.analysis != "power_flow":
            raise ValueError("Load scaling and outage studies require power flow")
        return self


Series = Annotated[list[Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)]],
                   Field(min_length=1, max_length=168)]
Availability = Annotated[list[Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]],
                         Field(min_length=1, max_length=168)]
CostSeries = Annotated[list[Annotated[float, Field(ge=0, le=1e6, allow_inf_nan=False)]],
                       Field(min_length=1, max_length=168)]


class EnergyBus(Strict):
    name: Name
    vn_kv: Positive = 110


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
    cyclic_soc: bool = True
    initial_soc_mwh: float | None = Field(default=None, ge=0, le=1e14)
    terminal_soc_mwh: float | None = Field(default=None, ge=0, le=1e14)

    @model_validator(mode="after")
    def check_soc(self):
        if self.cyclic_soc and (self.initial_soc_mwh is not None or self.terminal_soc_mwh is not None):
            raise ValueError("Cyclic storage cannot also specify fixed initial or terminal SOC")
        if not self.cyclic_soc and self.initial_soc_mwh is None:
            raise ValueError("Non-cyclic storage requires an explicit initial SOC")
        for value in (self.initial_soc_mwh, self.terminal_soc_mwh):
            if value is not None and value > self.p_nom_mw * self.max_hours + 1e-9:
                raise ValueError("SOC exceeds storage energy capacity")
        return self


class EnergyLink(Strict):
    name: Name
    bus0: Name
    bus1: Name
    p_nom_mw: Positive
    efficiency: float = Field(default=1, gt=0, le=1)


class EnergyLine(Strict):
    name: Name
    bus0: Name
    bus1: Name
    s_nom_mva: Positive
    x_ohm: Positive
    r_ohm: float = Field(default=0, ge=0, le=1e6)


class DispatchProgram(Strict):
    backend: Literal["pypsa"] = "pypsa"
    hours: int = Field(ge=1, le=168)
    buses: list[EnergyBus] = Field(min_length=1, max_length=30)
    loads: list[EnergyLoad] = Field(min_length=1, max_length=50)
    generators: list[EnergyGenerator] = Field(min_length=1, max_length=50)
    storage: list[EnergyStorage] = Field(default_factory=list, max_length=30)
    links: list[EnergyLink] = Field(default_factory=list, max_length=50)
    lines: list[EnergyLine] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def check(self):
        buses = {b.name: b.vn_kv for b in self.buses}
        for group in (self.buses, self.loads, self.generators, self.storage, self.links, self.lines):
            if len({x.name for x in group}) != len(group):
                raise ValueError("Duplicate component name")
        for component in [*self.loads, *self.generators, *self.storage]:
            if component.bus not in buses:
                raise ValueError("Component references unknown bus")
        for link in [*self.links, *self.lines]:
            if link.bus0 not in buses or link.bus1 not in buses or link.bus0 == link.bus1:
                raise ValueError("Invalid transmission endpoints")
        for line in self.lines:
            if buses[line.bus0] != buses[line.bus1]:
                raise ValueError("Passive lines require equal bus voltage bases")
        for load in self.loads:
            if len(load.p_set_mw) != self.hours:
                raise ValueError("Load profile must have exactly hours samples")
        for gen in self.generators:
            for profile in (gen.p_max_pu, gen.marginal_cost):
                if isinstance(profile, list) and len(profile) != self.hours:
                    raise ValueError("Generator profile must have exactly hours samples")
        return self


Program = Annotated[PPProgram | DispatchProgram, Field(discriminator="backend")]
