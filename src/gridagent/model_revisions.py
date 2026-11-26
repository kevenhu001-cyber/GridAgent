"""Immutable local revisions of pandapower programs and a bounded topology view."""
from pathlib import Path

from .dsr import Study, digest
from .model_quality import table
from .native_backends import run_program
from .native_program import Edit, PPProgram
from .workspace import artifact_folder, load_object

EDITABLE = {"load": ("p_mw", "q_mvar"), "gen": ("p_mw", "vm_pu"), "sgen": ("p_mw", "q_mvar"),
            "storage": ("p_mw", "q_mvar"), "ext_grid": ("vm_pu",), "trafo": ("tap_pos",),
            "line": ("max_i_ka",), "switch": ("closed",)}


def topology(root, identifier):
    folder = artifact_folder(Path(root), "runs", identifier)
    result = load_object(folder / "result.json")
    if result.get("status") != "ok" or result["backend"] != "pandapower":
        raise ValueError("Select a successful pandapower run")
    buses = table(folder, "bus")
    nodes = [{"id": int(idx), "kv": float(row.vn_kv), "active": bool(row.in_service)}
             for idx, row in buses.iterrows()]
    switches = table(folder, "switch") if (folder / "switch.csv").exists() else None
    opened = {(row.et, int(row.element)) for _, row in switches.iterrows() if not row.closed} if switches is not None else set()
    links = []
    for device, left, right in (("line", "from_bus", "to_bus"), ("trafo", "hv_bus", "lv_bus")):
        for idx, row in table(folder, device).iterrows():
            links.append({"id": int(idx), "from": int(row[left]), "to": int(row[right]), "type": device,
                          "closed": bool(row.in_service) and (device[0], int(idx)) not in opened})
    if switches is not None:
        links.extend({"id": int(idx), "from": int(row.bus), "to": int(row.element),
                      "type": "switch", "closed": bool(row.closed)}
                     for idx, row in switches.iterrows() if row.et == "b")
    devices = []
    for element, fields in EDITABLE.items():
        if element == "switch" and switches is None:
            continue
        rows = switches if element == "switch" else table(folder, element)
        for field in fields:
            if field not in rows:
                continue
            for idx, value in rows[field].dropna().items():
                device = {"element": element, "index": int(idx), "field": field,
                          "value": bool(value) if field == "closed" else float(value)}
                if field == "tap_pos":
                    bounds = rows.loc[idx, ["tap_min", "tap_max"]]
                    if bounds.isna().any():
                        continue
                    device.update(minimum=float(bounds.tap_min), maximum=float(bounds.tap_max))
                devices.append(device)
    return {"run_id": identifier, "nodes": nodes, "links": links, "devices": devices}


def create_revision(root, identifier, edit, *, name=None):
    edit = Edit.model_validate(edit)
    model = topology(root, identifier)
    eligible = [row for row in model["devices"]
                if row["element"] == edit.element and row["index"] == edit.index and row["field"] == edit.field]
    if not eligible:
        raise ValueError("The parameter does not exist in this simulation snapshot")
    old = eligible[0]
    if "minimum" in old and not old["minimum"] <= edit.value <= old["maximum"]:
        raise ValueError("Edit lies outside the transformer's tap changer range")
    root = Path(root)
    folder = artifact_folder(root, "runs", identifier)
    program = load_object(folder / "request.json")
    program.update(analysis="power_flow", fault_bus=None)
    program["steps"].append(edit.model_dump(mode="json"))
    data = PPProgram.model_validate(program).model_dump(mode="json")
    name = (name or f"{edit.element} {edit.index} · {edit.field}").strip()
    if not name or len(name) > 120:
        raise ValueError("Model revision name must contain 1–120 characters")
    revision = Study(root / "model-revisions")
    item = {"id": revision.id, "name": name, "parent_run": identifier, "program": data, "sha256": digest(data),
            "diff": {**edit.model_dump(), "before": old["value"]}}
    revision.write("revision", item)
    return item


def revisions(root):
    directory = Path(root) / "model-revisions"
    rows = []
    for record in directory.glob("*/revision.json"):
        try:
            revision = Study.reopen(directory, record.parent.name).read("revision")
            rows.append({key: revision[key] for key in ("id", "name", "parent_run", "diff", "sha256")})
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return rows


def run_revision(root, identifier):
    revision = Study.reopen(Path(root) / "model-revisions", identifier).read("revision")
    program = revision["program"]
    if revision["sha256"] != digest(program):
        raise ValueError("Model revision contents changed")
    return run_program(root, program)
