"""Derived electrical descriptors; never use raw parameters as transferable settings."""

import math
from statistics import median

from .ac_check_ir import ACCheckSpec

PROTOCOL = "ac-physical-features-v1"


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def physical_features(spec, report, snapshot_kind):
    spec = ACCheckSpec.model_validate(spec)
    buses = {b.id: b.nominal_kv for b in spec.model.buses}
    lines = sorted((d for d in spec.model.devices if d.kind == "line"), key=lambda d: d.id)
    degree = dict.fromkeys(buses, 0)
    for line in lines:
        degree[line.from_bus] += 1
        degree[line.to_bus] += 1

    def components(exclude=None):
        adjacency = {key: set() for key in buses}
        for line in lines:
            if line.id != exclude:
                adjacency[line.from_bus].add(line.to_bus)
                adjacency[line.to_bus].add(line.from_bus)
        unseen = set(buses)
        count = 0
        while unseen:
            count += 1
            stack = [unseen.pop()]
            while stack:
                for key in adjacency[stack.pop()] & unseen:
                    unseen.remove(key)
                    stack.append(key)
        return count

    connected_components = components()
    bridge_fraction = (sum(components(line.id) > connected_components for line in lines)/len(lines)
                       if lines else None)
    voltage, loading, reactive = [], [], []
    selected, comparable = 0, 0
    for row in report["snapshots"]:
        kind = "outage" if row["snapshot"].get("outage_line") else "base"
        if kind != snapshot_kind:
            continue
        selected += 1
        evidence = row["native_evidence"]
        checks = {c["id"]: c for c in row["native_verdict"]["checks"]}
        if (evidence["status"] not in {"verified", "rejected"}
                or not all(checks.get(key, {}).get("passed") is True for key in (
                    "model_input_fidelity", "solver_success", "active_bus_coverage", "power_balance_mva"))):
            continue
        comparable += 1
        v = checks.get("voltage_operating_range", {}).get("observed")
        if isinstance(v, list) and len(v) == 2 and all(map(finite, v)) and v[0] <= v[1]:
            voltage.append(min(v[0]-spec.acceptance.voltage_min_pu, spec.acceptance.voltage_max_pu-v[1]))
        load = checks.get("res_line_loading", {}).get("observed")
        if finite(load):
            loading.append((spec.acceptance.loading_max_percent-load)/100)
        if evidence["status"] == "verified":
            for unit, value in (row.get("physical") or {}).get("units", {}).items():
                q = value.get("reactive_mvar")
                bounds = spec.unit_reactive_limits[unit]
                span = bounds.maximum_mvar-bounds.minimum_mvar
                if finite(q) and span > 0:
                    reactive.append(min(q-bounds.minimum_mvar, bounds.maximum_mvar-q)/span)
    descriptors = {"mean_degree": sum(degree.values())/len(buses),
                   "cycle_rank_per_bus": (len(lines)-len(buses)+connected_components)/len(buses),
                   "bridge_fraction": bridge_fraction,
                   "median_r_over_x": median(d.resistance_ohm_per_km/d.reactance_ohm_per_km for d in lines)
                   if lines else None,
                   "median_x_pu_100mva": median(100*d.length_km*d.reactance_ohm_per_km/buses[d.from_bus]**2
                                                for d in lines) if lines else None,
                   "voltage_margin_pu": min(voltage) if voltage else None,
                   "loading_margin_fraction": min(loading) if loading else None,
                   "reactive_margin_fraction": min(reactive) if reactive else None}
    return {"protocol": PROTOCOL, "snapshot_kind": snapshot_kind, "selected_snapshots": selected,
            "comparable_snapshots": comparable, "descriptors": descriptors}


SCALES = {"mean_degree": 1, "cycle_rank_per_bus": 0.2, "bridge_fraction": 0.25,
          "median_r_over_x": 0.1, "median_x_pu_100mva": 0.1,
          "voltage_margin_pu": 0.05, "loading_margin_fraction": 0.2, "reactive_margin_fraction": 0.2}


def physical_similarity(left, right):
    """Signed margin distances; missing evidence cannot increase the match score."""
    a, b = left["descriptors"], right["descriptors"]
    values, available = [], 0
    for key, scale in SCALES.items():
        x, y = a[key], b[key]
        if x is None and y is None:
            continue
        if x is None or y is None:
            values.append(0.0)
            continue
        available += 1
        values.append(1/(1+abs(x-y)/(scale+max(abs(x), abs(y)))))
    return {"score": sum(values)/len(values) if values else None,
            "compared_features": available, "possible_features": len(values)}
