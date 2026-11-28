import json
import subprocess
import sys

import pytest

from gridagent import plugins


def test_catalog_and_managed_state(tmp_path, monkeypatch):
    monkeypatch.setenv("GRIDAGENT_PLUGIN_ROOT", str(tmp_path))
    monkeypatch.setattr(plugins.importlib.util, "find_spec", lambda name: None)
    assert not plugins.available("pypsa")
    with pytest.raises(ValueError):
        plugins.install("../unexpected")
    folder = tmp_path / "pypsa"
    (folder / "packages").mkdir(parents=True)
    (folder / "installed.json").write_text(json.dumps({
        "plugin": "pypsa", "python": list(sys.version_info[:2]),
        "requirements": plugins.CATALOG["pypsa"]["packages"]}))
    assert plugins.available("pypsa")
    assert "cyclic SOC" in plugins.guidance()
    assert not plugins.available("pybamm")
    assert plugins.uninstall("pypsa") == "Removed managed plugin"
    assert not plugins.available("pypsa")


def test_no_provider_secrets(monkeypatch):
    monkeypatch.setenv("GRIDAGENT_API_KEY", "secret")
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    assert "GRIDAGENT_API_KEY" not in plugins.clean_env()
    assert "OPENAI_API_KEY" not in plugins.clean_env()


def test_plugin_probe_precedes_switch_and_rollback(tmp_path, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setenv("GRIDAGENT_PLUGIN_ROOT", str(tmp_path))
    resolved = ["3.2"]
    probe_fails = [False]

    def run(args, **kwargs):
        if "--target" in args:
            (kwargs["cwd"] / "packages").mkdir()
            return SimpleNamespace(stdout="")
        if probe_fails[0]:
            raise subprocess.CalledProcessError(1, args)
        return SimpleNamespace(stdout=json.dumps({"rainflow": resolved[0]}))

    monkeypatch.setattr(plugins.subprocess, "run", run)
    monkeypatch.setattr(plugins, "distributions", lambda **_: [
        SimpleNamespace(metadata={"Name": "rainflow"}, version=resolved[0])])
    plugins.install("rainflow")
    first = plugins.installed_target("rainflow")
    resolved[0] = "3.3"
    probe_fails[0] = True
    with pytest.raises(ValueError, match="install or import check failed"):
        plugins.install("rainflow", update=True)
    assert plugins.installed_target("rainflow") == first
    probe_fails[0] = False
    plugins.install("rainflow", update=True)
    assert plugins.installed_metadata("rainflow")["versions"] == {"rainflow": "3.3"}
    assert plugins.installed_target("rainflow") != first
    plugins.rollback("rainflow")
    assert plugins.installed_target("rainflow") == first
    assert plugins.installed_metadata("rainflow")["versions"] == {"rainflow": "3.2"}


def test_optional_document_and_parallel_plugins_use_native_api_catalog():
    for name in ("docling", "joblib"):
        spec = plugins.spec(name)
        assert spec["modules"] == [name]
        assert spec["tools"] == []
        assert len(spec["packages"]) == 1
        assert spec["packages"][0].startswith(name + ">=")
    assert "offline" in plugins.spec("docling")["prompt"]
    assert "untrusted pickle" in plugins.spec("joblib")["prompt"]
