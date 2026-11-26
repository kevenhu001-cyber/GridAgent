import json

from langchain_core.messages import ToolMessage

from gridagent.artifact_presentation import artifact_from_tool, preview_run, run_artifact


def fixture(root):
    identifier = "a" * 32
    folder = root / "runs" / identifier
    folder.mkdir(parents=True)
    (folder / "result.json").write_text(json.dumps({"backend": "andes", "operation": "fault", "case": "kundur",
                                                     "status": "ok", "metrics": {"v_min_pu": 0.2, "reason": "secret"}}))
    (folder / "voltage.csv").write_text("time_s,B5\n" + "\n".join(
        f"{i / 1000},{0.2 if i == 501 else 1.0}" for i in range(3000)))
    return identifier, folder


def test_artifact_is_derived_from_saved_run_not_tool_claim(tmp_path):
    identifier, folder = fixture(tmp_path)
    (folder / "quality.json").write_text(json.dumps({"protocol": "test", "passed_count": 2, "test_count": 3}))
    message = ToolMessage(content=json.dumps({"run_id": identifier, "status": "failed", "metrics": {"v_min_pu": 9}}),
                          tool_call_id="fixture")
    artifact = artifact_from_tool(tmp_path, message)
    assert artifact == run_artifact(tmp_path, identifier)
    assert artifact["status"] == "ok"
    assert artifact["metrics"] == [{"name": "v_min_pu", "value": 0.2}]
    assert artifact["quality"]["passed"] == 2
    assert artifact["views"] == ["waveform"]


def test_preview_is_bounded_and_keeps_extrema(tmp_path):
    identifier, _ = fixture(tmp_path)
    preview = preview_run(tmp_path, identifier)
    assert preview["source_points"] == 3000
    assert len(preview["x"]) == len(preview["y"]) <= 240
    assert min(preview["y"]) == 0.2
    assert preview["x"][0] == 0 and preview["x"][-1] == 2.999


def test_missing_or_forged_run_is_not_a_card(tmp_path):
    for identifier in ("../secret", "b" * 32):
        msg = ToolMessage(content=json.dumps({"run_id": identifier}), tool_call_id="fixture")
        assert artifact_from_tool(tmp_path, msg) is None
