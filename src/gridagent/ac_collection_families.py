"""Prospectively specified synthetic network families for native AC data collection."""

import math
from typing import Literal

from pydantic import Field, model_validator

from .ac_check_ir import ACCheckSpec, validate_mapping
from .commitment_ir import UnitCommitment
from .engineering_ir import fingerprint
from .task_contracts import Contract

PROTOCOL = "ac-collection-families-v1"
FAMILIES = tuple(f"grid-{n:02d}" for n in range(3, 16))
# Predeclare interleaved groups, including smallest/largest and a meshed training family.
SPLITS = {family: "train" if family in {"grid-03", "grid-06", "grid-15"}
          else "test" if family in {"grid-08", "grid-13"} else "validation"
          for family in FAMILIES}
PROBES = (0.90, 0.94, 0.98, 1.04, 1.12)
RUNS_PER_CASE = 2+len(PROBES)  # original AC + fresh baseline + probes


class CollectionSpec(Contract):
    schema_version: Literal[1] = 1
    families: tuple[str, ...] = Field(min_length=1, max_length=13)
    levels: tuple[Literal["light", "nominal", "heavy"], ...] = Field(min_length=1, max_length=3)
    max_dc_calls: int = Field(ge=1, le=39)
    max_ac_runs: int = Field(ge=1, le=273)
    timeout_s: int = Field(default=60, ge=1, le=120)

    @model_validator(mode="after")
    def budget(self):
        if any(family not in FAMILIES for family in self.families):
            raise ValueError("Unknown collection family")
        if len(set(self.families)) != len(self.families) or len(set(self.levels)) != len(self.levels):
            raise ValueError("Duplicate collection family or level")
        count = len(self.families)*len(self.levels)
        if count > self.max_dc_calls or count*RUNS_PER_CASE > self.max_ac_runs:
            raise ValueError("Collection budget must cover every predeclared case")
        return self

    def canonical(self):
        data = self.model_dump(mode="json")
        data["families"].sort()
        data["levels"].sort()
        return data


def build_case(family, level, timeout_s=60):
    if family not in FAMILIES or level not in {"light", "nominal", "heavy"}:
        raise ValueError("Unknown prospective collection case")
    n = int(family[-2:])
    scale = {"light": 0.6, "nominal": 1.0, "heavy": 1.4}[level]
    kv = 20.0
    buses = [f"B{i:02d}" for i in range(n)]
    # Distinct base topologies; even families are meshed. Levels never change split.
    edges = [(i, i+1) for i in range(n-1)]
    if n % 2 == 0:
        edges.append((0, n-1))
    if n % 3 == 0 and n >= 6:
        edges.append((0, n//2))
    demand = [0.0]+[0.18*scale*(1+0.1*(i%3)) for i in range(1, n)]
    q = [0.35*p for p in demand]
    total = math.fsum(demand)
    capacity = 2*total+2
    x = 0.4+0.025*n
    r = x*(0.08+0.0025*(n-3))
    dc_lines, ac_lines = [], []
    for i, (a, b) in enumerate(edges):
        identifier = f"L{i:02d}"
        dc_lines.append({"id": identifier, "from_bus": buses[a], "to_bus": buses[b],
                         "susceptance_mw_per_rad": kv**2/x, "limit_mw": capacity,
                         "max_angle_difference_rad": 0.5})
        ac_lines.append({"kind": "line", "id": identifier, "from_bus": buses[a], "to_bus": buses[b],
                         "length_km": 1, "resistance_ohm_per_km": r, "reactance_ohm_per_km": x,
                         "current_limit_ka": capacity/(math.sqrt(3)*kv)*2})
    dc = UnitCommitment.model_validate({
        "description": f"Prospective synthetic {family} {level}", "currency": "USD",
        "demand_mw": [total], "units": [{"id": "G", "minimum_mw": 0.01, "maximum_mw": capacity,
            "marginal_cost_per_mwh": 20, "ramp_up_mw": capacity, "ramp_down_mw": capacity,
            "startup_limit_mw": capacity, "shutdown_limit_mw": capacity,
            "min_up_hours": 2, "min_down_hours": 1, "initially_on": True,
            "initial_mw": total, "initial_state_hours": 1}],
        "network": {"buses": [{"id": bus, "demand_mw": [p]} for bus, p in zip(buses, demand, strict=True)],
                    "lines": dc_lines, "reference_bus": buses[0], "angle_bound_rad": 1,
                    "unit_buses": {"G": buses[0]}, "reserve_requirement_mw": [0],
                    "reserve_response_minutes": 15, "unit_reserve_capability_mw": {"G": 0}}})
    ac = ACCheckSpec.model_validate({
        "commitment_study_id": "0"*32,
        "model": {"model_id": family, "buses": [{"id": bus, "nominal_kv": kv} for bus in buses],
                  "devices": [{"kind": "slack", "id": "slack", "bus": buses[0],
                               "voltage_pu": 0.86+0.02*(n-3)/12},
                              *[{"kind": "load", "id": f"D{i:02d}", "bus": bus, "active_mw": p}
                                for i, (bus, p) in enumerate(zip(buses, demand, strict=True))],
                              *ac_lines]},
        "unit_devices": {"G": "slack"}, "slack_unit": "G",
        "unit_reactive_limits": {"G": {"minimum_mvar": -capacity, "maximum_mvar": capacity}},
        "reactive_demand_mvar": {bus: [value] for bus, value in zip(buses, q, strict=True)},
        "snapshots": [{"hour": 0}], "slack_max_deviation_mw": 0.2*total+0.1,
        "timeout_s": timeout_s})
    validate_mapping(ac, dc)
    return {"family": family, "split": SPLITS[family], "level": level,
            "dc": dc.canonical(), "ac_template": ac.canonical(),
            "probe_values_pu": list(PROBES), "reserved_dc_calls": 1, "reserved_ac_runs": RUNS_PER_CASE}


def plan(auth):
    auth = CollectionSpec.model_validate(auth)
    return [build_case(family, level, auth.timeout_s)
            for family in sorted(auth.families) for level in sorted(auth.levels)]


def plan_fingerprint(auth):
    return fingerprint({"protocol": PROTOCOL, "spec": auth.canonical(), "cases": plan(auth)})
