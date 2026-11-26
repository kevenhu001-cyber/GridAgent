"""Explicit allowlisted pre-setup changes; all values in native ANDES p.u."""
FIELDS = {"PQ": ("p0", "q0"), "PV": ("p0", "v0"), "Slack": ("v0",)}


def catalog(ss):
    rows = []
    for name, fields in FIELDS.items():
        model = getattr(ss, name)
        for i, (idx, bus, active) in enumerate(zip(model.idx.v, model.bus.v, model.u.v)):
            rows.append({"model": name, "device": str(idx), "bus": str(bus), "in_service": bool(active),
                         "parameters": {field: float(getattr(model, field).v[i]) for field in fields}})
    return rows


def apply_edits(ss, edits):
    changes = []
    for edit in edits:
        model = getattr(ss, edit.model)
        matches = [(i, idx) for i, idx in enumerate(model.idx.v) if str(idx) == edit.device and model.u.v[i]]
        if len(matches) != 1:
            raise ValueError("Edit target must uniquely exist and be in service")
        i, idx = matches[0]
        before = float(getattr(model, edit.field).v[i])
        model.set(edit.field, idx, edit.value)
        changes.append({**edit.model_dump(), "before": before, "after": edit.value})
    return changes
