import json

import pytest
from langchain_core.messages import ToolMessage

from gridagent import scientific_workspace as ws
from gridagent.desktop_bridge import dispatch
from gridagent.scientific_views import validate_view, view_artifact, view_from_tool


def field(kind="heatmap"):
    return {"schema": "gridagent.view.v1", "kind": kind, "title": "Computed field",
            "x_label": "x (m)", "y_label": "y (m)", "value_label": "Temperature (K)",
            "x": [0, 1, 2], "y": [0, 1], "z": [[290, 300, 310], [295, 305, 315]]}


def network():
    return {"schema": "gridagent.view.v1", "kind": "topology", "title": "Example graph",
            "nodes": [{"id": "a", "label": "A", "x": 0, "y": 0},
                      {"id": "b", "label": "B", "x": 1, "y": 1}],
            "edges": [{"source": "a", "target": "b"}]}


def table():
    return {"schema": "gridagent.view.v1", "kind": "table", "title": "Results",
            "columns": ["bus", "voltage (pu)", "valid"], "rows": [[1, 0.98, True], [2, None, False]]}


def encode(value):
    return json.dumps(value).encode()


@pytest.mark.parametrize("data", [field(), field("surface"), network(), table()])
def test_general_views_are_validated_and_reloaded(tmp_path, data):
    ws.set_enabled(tmp_path, True)
    run = "b"*32
    folder = ws.directory(tmp_path, "scientific-runs") / run
    (folder / "output").mkdir(parents=True)
    path = folder / "output/result.view.json"
    raw = encode(data)
    path.write_bytes(raw)
    (folder / "report.json").write_text(json.dumps({"status": "ok", "artifacts": [
        {"path": path.name, "size_bytes": len(raw), "sha256": ws.sha(raw)}]}), encoding="utf-8")
    desc, view = view_artifact(tmp_path, run, path.name)
    assert view["kind"] == data["kind"]
    assert desc["verification"] == "unverified_script_output"
    message = ToolMessage(name="present_scientific_view", tool_call_id="1",
                          content=json.dumps({**desc, "title": "forged"}))
    assert view_from_tool(tmp_path, message)["title"] == data["title"]
    events = []
    dispatch(tmp_path, {"action": "scientific-view-open", "run": run, "path": path.name,
                        "sha256": desc["sha256"]}, lambda kind, value: events.append((kind, value)))
    assert events == [("scientific_view_data", {**view, "run_id": run,
                                               "verification": "unverified_script_output"})]
    path.write_bytes(b"{}")
    assert view_from_tool(tmp_path, message) is None
    with pytest.raises(ValueError, match="changed"):
        view_artifact(tmp_path, run, path.name)


def test_invalid_grids():
    for patch in ({"x": [0, 1, 3]}, {"y": [1, 0]}, {"z": [[1], [2]]},
                  {"z": [[0, 1, float("nan")], [0, 1, 2]]}, {"script": "print(1)"}):
        with pytest.raises(ValueError):
            validate_view(encode({**field(), **patch}))


def test_invalid_topology_and_table():
    data = network()
    data["edges"].append({"source": "b", "target": "a"})
    with pytest.raises(ValueError, match="unique undirected"):
        validate_view(encode(data))
    data = network()
    data["edges"][0]["target"] = "missing"
    with pytest.raises(ValueError):
        validate_view(encode(data))
    data = table()
    data["rows"].append([1, 2])
    with pytest.raises(ValueError, match="match columns"):
        validate_view(encode(data))
    data = table()
    data["rows"] = [[0, 1, True]]*101
    with pytest.raises(ValueError, match="100 rows"):
        validate_view(encode(data))
