import json

import pytest
from langchain_core.messages import ToolMessage

from gridagent import scientific_workspace as ws
from gridagent.desktop_bridge import dispatch
from gridagent.scientific_visualization import chart_artifact, chart_from_tool, validate_chart


def payload():
    return {"schema": "gridagent.chart.v1", "title": "Computed response", "x_label": "t (s)",
            "y_label": "Voltage (V)", "scatter": False,
            "series": [{"name": "Output", "x": [0, 1, 2], "y": [0, 0.5, 1]}]}


def fixture(root):
    ws.set_enabled(root, True)
    run = "a"*32
    folder = ws.directory(root, "scientific-runs") / run
    (folder / "output").mkdir(parents=True)
    path = folder / "output/response.chart.json"
    data = json.dumps(payload()).encode()
    path.write_bytes(data)
    (folder / "report.json").write_text(json.dumps({"status": "ok", "artifacts": [
        {"path": path.name, "size_bytes": len(data), "sha256": ws.sha(data)}]}), encoding="utf-8")
    return run, path


def test_native_chart_is_bound_to_committed_data(tmp_path):
    run, path = fixture(tmp_path)
    desc, chart = chart_artifact(tmp_path, run, path.name)
    assert desc["points"] == 3 and desc["verification"] == "unverified_script_output"
    assert chart["series"][0]["y"] == [0, 0.5, 1]
    message = ToolMessage(name="present_scientific_chart", tool_call_id="1",
                          content=json.dumps({**desc, "title": "Invented"}))
    assert chart_from_tool(tmp_path, message)["title"] == "Computed response"
    events = []
    dispatch(tmp_path, {"action": "scientific-chart-open", "run": run, "path": path.name,
                        "sha256": desc["sha256"]}, lambda kind, data: events.append((kind, data)))
    assert events[0][0] == "analysis_charts"
    assert "unverified script output" in events[0][1][0]["title"]
    path.write_text("{}", encoding="utf-8")
    assert chart_from_tool(tmp_path, message) is None
    with pytest.raises(ValueError, match="changed"):
        chart_artifact(tmp_path, run, path.name)


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), True, "1", 1e101])
def test_reject_invalid_numbers(bad):
    data = payload()
    data["series"][0]["x"][0] = bad
    with pytest.raises(ValueError, match="finite real"):
        validate_chart(json.dumps(data).encode())


def test_reject_unbounded_or_executable_chart():
    data = payload()
    data["series"][0]["x"] = [0]*12001
    data["series"][0]["y"] = [0]*12001
    with pytest.raises(ValueError, match="12000"):
        validate_chart(json.dumps(data).encode())
    data = payload()
    data["script"] = "alert(1)"
    with pytest.raises(ValueError, match="data-only"):
        validate_chart(json.dumps(data).encode())


def test_chart_requires_grant_and_exact_path(tmp_path):
    run, path = fixture(tmp_path)
    with pytest.raises(ValueError):
        chart_artifact(tmp_path, run, "../response.chart.json")
    ws.set_enabled(tmp_path, False)
    with pytest.raises(ValueError, match="disabled"):
        chart_artifact(tmp_path, run, path.name)
