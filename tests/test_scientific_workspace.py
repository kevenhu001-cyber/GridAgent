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



def test_exact_edit_and_artifact_promotion(tmp_path):
    ws.set_enabled(tmp_path, True)
    original = ws.write_project(tmp_path, "study.py", "x = 1\nprint(x)")
    edited = ws.edit_project(tmp_path, "study.py", "x = 1", "x = 2", original["sha256"])
    assert ws.read_project(tmp_path, "study.py")["text"] == "x = 2\nprint(x)"
    with pytest.raises(ValueError, match="changed"):
        ws.edit_project(tmp_path, "study.py", "x = 2", "x = 3", original["sha256"])
    with pytest.raises(ValueError, match="exactly once"):
        ws.edit_project(tmp_path, "study.py", "x", "y", edited["sha256"])
    folder = ws.directory(tmp_path, "scientific-runs") / ("b" * 32)
    (folder / "output").mkdir(parents=True)
    data = b"\x00\x01\xff"
    (folder / "output/model.bin").write_bytes(data)
    (folder / "report.json").write_text(json.dumps({"status": "ok", "run_id": folder.name, "artifacts": [
        {"path": "model.bin", "sha256": ws.sha(data)}]}))
    result = ws.promote_artifact(tmp_path, folder.name, "model.bin", "models/model.bin")
    assert result["sha256"] == ws.sha(data)
    assert (tmp_path / "scientific-project/models/model.bin").read_bytes() == data
    assert ws.list_scientific_runs(tmp_path)["runs"][0]["status"] == "ok"


def test_unresolved_session_blocks_execution_and_recovery(tmp_path, monkeypatch):
    import subprocess

    ws.set_enabled(tmp_path, True)
    ws.write_project(tmp_path, "main.py", "print(1)")
    identifier = "c" * 32
    folder = ws.directory(tmp_path, "scientific-runs") / identifier
    folder.mkdir()
    active = {"run_id": identifier, "session_id": "12345678-1234-1234-1234-1234567890ab"}
    (tmp_path / runtime.ACTIVE).write_text(json.dumps(active))
    monkeypatch.setattr(runtime, "require_runtime", lambda: ("fake-wsb", Path("runtime")))
    with pytest.raises(ValueError, match="Unresolved"):
        runtime.execute(tmp_path, "main.py")
    def fail(*args):
        raise subprocess.CalledProcessError(1, "stop")

    monkeypatch.setattr(runtime, "_stop", fail)
    assert runtime.recover(tmp_path)["status"] == "cleanup_unconfirmed"
    assert runtime.active_session(tmp_path) == active
    stopped = []
    monkeypatch.setattr(runtime, "_stop", lambda executable, session: stopped.append(session))
    assert runtime.recover(tmp_path)["status"] == "recovered_incomplete"
    assert stopped == [active["session_id"]]
    assert runtime.active_session(tmp_path) is None
    assert ws.run_status(tmp_path, identifier)["status"] == "recovered_incomplete"
    assert runtime.recover(tmp_path)["status"] == "ok"



def test_native_library_probe_only_runs_in_sandbox(tmp_path, monkeypatch):
    from gridagent.scientific_library import probe_source

    ws.set_enabled(tmp_path, True)
    ws.write_project(tmp_path, "main.py", "print(1)")
    with pytest.raises(ValueError, match="dotted"):
        probe_source("numpy; print(1)")
    with pytest.raises(ValueError, match="dotted"):
        probe_source("numpy", "array()")
    compile(probe_source("scipy.integrate", "solve_ivp"), "probe.py", "exec")
    monkeypatch.setattr(runtime, "require_runtime", lambda: ("fake-wsb", Path("runtime")))

    def launch(root, folder, executable, config):
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest["api_probe"] == {"module": "scipy.integrate", "symbol": "solve_ivp"}
        source = (folder / "input/project" / manifest["entry"]).read_text()
        assert "importlib.import_module('scipy.integrate')" in source
        (folder / "output/exit-code.txt").write_text("0")
        (folder / "output/api.json").write_text('{"test_double":true}')
        return "finished", None

    monkeypatch.setattr(runtime, "_launch", launch)
    result = runtime.execute(tmp_path, "api.py", probe={"module": "scipy.integrate", "symbol": "solve_ivp"})
    assert result["status"] == "ok"
    assert ws.list_project(tmp_path)["files"] == [{"path": "main.py", "size_bytes": 8}]
    assert ws.read_artifact(tmp_path, result["run_id"], "api.json")["text"] == '{"test_double":true}'


def test_inventory_reads_runtime_not_host(tmp_path):
    from gridagent.scientific_library import inventory

    packages = tmp_path / "Lib/site-packages"
    metadata = packages / "test_lib-2.0.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text("Name: test-lib\nVersion: 2.0\n")
    assert inventory(tmp_path) == [{"distribution": "test-lib", "version": "2.0", "scope": "core"}]



def test_launch_journals_before_start_and_preserves_failed_stop(tmp_path, monkeypatch):
    import subprocess

    ws.set_enabled(tmp_path, True)
    folder = ws.directory(tmp_path, "scientific-runs") / ("d" * 32)
    (folder / "output").mkdir(parents=True)
    calls = []

    def fake_run(args, **kwargs):
        calls.append(args)
        if args[1] == "start":
            assert runtime.active_session(tmp_path)["run_id"] == folder.name
            (folder / "output/exit-code.txt").write_text("0")
        elif args[1] == "stop":
            raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(runtime.subprocess, "run", fake_run)
    status, _ = runtime._launch(tmp_path, folder, "fake-wsb", "test configuration")
    assert status == "cleanup_unconfirmed"
    assert runtime.active_session(tmp_path)["run_id"] == folder.name
    assert [args[1] for args in calls] == ["start", "stop"]
