"""Deterministically lower supported engineering IR to existing typed solver programs."""

from collections import defaultdict
from dataclasses import dataclass

from .engineering_ir import EngineeringStudy, fingerprint
from .native_program import PPProgram
from .research_spec import ResearchManifest


@dataclass(frozen=True)
class CompiledStudy:
    manifest: ResearchManifest
    provenance: dict


def compile_study(source: EngineeringStudy) -> CompiledStudy:
    """Compile AC IR without an LLM, running a solver, or changing physical parameters."""
    source = EngineeringStudy.model_validate(source)
    data = source.model.canonical()
    indices = {}
    steps = []
    counts = defaultdict(int)

    def add(row, table, op, fields, *, implicit_index=False):
        index = counts[table]
        counts[table] += 1
        indices[row["id"]] = {"table": table, "index": index, "step": len(steps)}
        step = {"op": op, **fields}
        if not implicit_index:
            step["index"] = index
        steps.append(step)

    for bus in data["buses"]:
        add(bus, "bus", "create_bus", {"vn_kv": bus["nominal_kv"]})

    def bus_id(name):
        return indices[name]["index"]

    for row in data["devices"]:
        kind = row["kind"]
        if kind == "slack":
            add(row, "ext_grid", "create_ext_grid", {
                "bus": bus_id(row["bus"]), "vm_pu": row["voltage_pu"],
            }, implicit_index=True)
        elif kind == "load":
            add(row, "load", "create_load", {
                "bus": bus_id(row["bus"]), "p_mw": row["active_mw"], "q_mvar": row["reactive_mvar"],
            })
        elif kind == "generator":
            add(row, "gen", "create_gen", {
                "bus": bus_id(row["bus"]), "p_mw": row["active_mw"], "vm_pu": row["voltage_pu"],
            })
        elif kind == "storage":
            add(row, "storage", "create_storage", {
                "bus": bus_id(row["bus"]), "p_mw": row["charging_mw"], "q_mvar": row["reactive_mvar"],
                "max_e_mwh": row["energy_capacity_mwh"], "soc_percent": row["initial_soc_percent"],
            })
        elif kind == "line":
            add(row, "line", "create_line_from_parameters", {
                "from_bus": bus_id(row["from_bus"]), "to_bus": bus_id(row["to_bus"]),
                "length_km": row["length_km"], "r_ohm_per_km": row["resistance_ohm_per_km"],
                "x_ohm_per_km": row["reactance_ohm_per_km"], "c_nf_per_km": row["capacitance_nf_per_km"],
                "max_i_ka": row["current_limit_ka"],
            })
        elif kind == "transformer":
            add(row, "trafo", "create_transformer_from_parameters", {
                "hv_bus": bus_id(row["hv_bus"]), "lv_bus": bus_id(row["lv_bus"]),
                "sn_mva": row["rated_mva"], "vn_hv_kv": row["rated_hv_kv"], "vn_lv_kv": row["rated_lv_kv"],
                "vkr_percent": row["resistance_percent"], "vk_percent": row["impedance_percent"],
                "pfe_kw": row["iron_loss_kw"], "i0_percent": row["no_load_current_percent"],
                "shift_degree": row["phase_shift_degree"],
            })
        else:
            raise ValueError(f"Unsupported AC device family: {kind}")

    program = PPProgram.model_validate({"steps": steps})
    scenarios = []
    for scenario in source.study.scenarios:
        outage = None
        if scenario.outage_device is not None:
            target = indices.get(scenario.outage_device)
            if target is None or target["table"] not in {"line", "trafo"}:
                raise ValueError("Contingency must identify an existing line or transformer")
            outage = {"element": target["table"], "index": target["index"]}
        scenarios.append({"name": scenario.name, "load_scale": scenario.load_scale, "outage": outage})
    manifest = ResearchManifest.model_validate({
        "objective": source.study.objective,
        "program": program.model_dump(mode="json"),
        "scenarios": scenarios,
        "limits": source.study.acceptance.model_dump(mode="json"),
        "editable": [],
        "max_repairs": 0,
        "max_runs": source.study.max_runs,
    })
    study_data = source.study.model_dump(mode="json")
    provenance = {
        "compiler": "ac-pandapower-v1",
        "model": data,
        "model_sha256": source.model.sha256(),
        "study": study_data,
        "study_sha256": fingerprint(study_data),
        "device_indices": indices,
        "program_sha256": fingerprint(program.model_dump(mode="json")),
    }
    return CompiledStudy(manifest, provenance)
