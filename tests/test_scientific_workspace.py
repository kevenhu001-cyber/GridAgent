import json
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from gridagent import scientific_runtime as runtime
from gridagent import scientific_workspace as ws


def test_grant_and_revision(tmp_path):
    with pytest.raises(ValueError, match="disabled"):
        ws.write_project(tmp_path, "model.py", "print(1)")
    ws.set_enabled(tmp_path, True)
    first = ws.write_project(tmp_path, "models/model.py", "print(1)")
    with pytest.raises(ValueError, match="SHA-256"):
        ws.write_project(tmp_path, "models/model.py", "print(2)")
    ws.write_project(tmp_path, "models/model.py", "print(2)", first["sha256"])
    assert ws.read_project(tmp_path, "models/model.py")["text"] == "print(2)"
    records = ws.snapshot(tmp_path, tmp_path / "snapshot")
    assert records[0]["sha256"] == ws.sha(b"print(2)")
    assert (tmp_path / "snapshot/models/model.py").read_text() == "print(2)"


@pytest.mark.parametrize("path", ["../x", "/x", "C:/x", "a\\b", "a/../b", "CON.txt", "a:stream", "a."])
def test_reject_escape(path):
    with pytest.raises(ValueError):
        ws.safe_parts(path)


def test_no_host_fallback(tmp_path, monkeypatch):
    ws.set_enabled(tmp_path, True)
    ws.write_project(tmp_path, "main.py", "print(1)")

    def unavailable():
        raise ValueError("Sandbox unavailable")

    monkeypatch.setattr(runtime, "require_runtime", unavailable)
    with pytest.raises(ValueError, match="unavailable"):
        runtime.execute(tmp_path, "main.py")
    assert not (tmp_path / "scientific-runs").exists()


def test_configuration_read_only_inputs_and_disabled_network(tmp_path):
    config = ET.fromstring(runtime.configuration(tmp_path / "runtime", tmp_path / "input",
                                                tmp_path / "output", tmp_path / "plugin"))
    assert config.findtext("Networking") == "Disable"
    assert [row.findtext("ReadOnly") for row in config.findall("MappedFolders/MappedFolder")] == [
        "true", "true", "false", "true"]


def test_artifact_hash_and_pagination(tmp_path):
    ws.set_enabled(tmp_path, True)
    folder = ws.directory(tmp_path, "scientific-runs") / ("a" * 32)
    (folder / "output").mkdir(parents=True)
    path = folder / "output/result.csv"
    path.write_bytes(b"a,b\n1,2")
    (folder / "report.json").write_text(json.dumps({"artifacts": [
        {"path": "result.csv", "sha256": ws.sha(path.read_bytes())}]}))
    assert ws.read_artifact(tmp_path, folder.name, "result.csv", 0, 3)["text"] == "a,b"
    path.write_bytes(b"changed")
    with pytest.raises(ValueError, match="changed"):
        ws.read_artifact(tmp_path, folder.name, "result.csv")


def test_execution_adapter_contract_without_claiming_real_sandbox(tmp_path, monkeypatch):
    ws.set_enabled(tmp_path, True)
    ws.write_project(tmp_path, "main.py", "print('example')")
    monkeypatch.setattr(runtime, "require_runtime", lambda: ("fake-wsb", Path("runtime")))

    def fake_launch(root, folder, executable, config):
        assert (folder / "input/project/main.py").is_file()
        (folder / "output/stdout.log").write_text("example")
        (folder / "output/exit-code.txt").write_text("0")
        return "finished", None

    monkeypatch.setattr(runtime, "_launch", fake_launch)
    result = runtime.execute(tmp_path, "main.py")
    assert result["status"] == "ok" and result["verification"] == "unverified_script_output"
    assert result["stdout_stderr_tail"] == "example"
    assert ws.read_artifact(tmp_path, result["run_id"], "stdout.log")["text"] == "example"
