import json
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
