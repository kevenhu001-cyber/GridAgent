import json

import pytest

from gridagent.knowledge_store import import_pack
from gridagent.scientific_reference import inspect_source, search_references


def installed(root, name="demo", version="2.0"):
    root.mkdir(parents=True, exist_ok=True)
    meta = root / f"{name}-{version}.dist-info"
    meta.mkdir()
    (meta / "METADATA").write_text(f"Name: {name}\nVersion: {version}\n", encoding="utf-8")
    (meta / "RECORD").write_text(f"{name}/api.py,,\n", encoding="utf-8")
    pkg = root / name
    pkg.mkdir()
    (pkg / "api.py").write_text(
        'raise RuntimeError("Never import on host")\n'
        'class Solver:\n'
        '    def run(self, x: float = 1.0) -> float:\n'
        '        """Example solver docstring."""\n'
        '        return x\n', encoding="utf-8")
    return pkg


def test_source_is_static_and_versioned(tmp_path):
    runtime = tmp_path / "runtime"
    installed(runtime / "Lib/site-packages")
    result = inspect_source(runtime, {}, "demo", "demo.api", "Solver.run")
    assert result["installed_version"] == "2.0"
    assert result["source_path"] == "demo/api.py"
    assert len(result["source_sha256"]) == 64
    assert result["definitions"][0]["signature"] == "(self, x: float=1.0) -> float"
    assert result["definitions"][0]["docstring"] == "Example solver docstring."
    assert result["definitions"][0]["line"] == 3
    assert inspect_source(runtime, {}, "demo", "demo.api")["definitions"][0]["name"] == "Solver"
    assert inspect_source(runtime, {}, "demo", "demo.missing")["availability"] == "source_unavailable"
    with pytest.raises(ValueError, match="dotted"):
        inspect_source(runtime, {}, "demo", "../secret")


def test_reference_exact_version_and_plugin_precedence(tmp_path):
    runtime = tmp_path / "runtime"
    installed(runtime / "Lib/site-packages", version="1.0")
    plugin = tmp_path / "plugin"
    installed(plugin, version="2.0")
    workspace = tmp_path / "workspace"
    path = tmp_path / "pack.json"
    path.write_text(json.dumps({"title": "Demo docs", "entries": [
        {"kind": "function", "backend": "demo", "function": "Solver.run", "version": v,
         "source": f"Manual {v}", "description": f"Solver run example {v}"} for v in ("1.0", "2.0")
    ]}), encoding="utf-8")
    import_pack(workspace, path)
    result = search_references(workspace, runtime, {"plugin": plugin}, "demo", "Solver.run")
    assert result["installed_version"] == "2.0"
    assert result["distribution_scope"] == "plugin"
    assert [row["version"] for row in result["references"]] == ["2.0"]
    assert result["other_reference_versions"] == ["1.0"]
    assert result["dependency_conflicts"][0]["distribution"] == "demo"
    assert inspect_source(runtime, {"plugin": plugin}, "demo", "demo.api")["installed_version"] == "2.0"


def test_record_and_grant_boundaries(tmp_path):
    from gridagent.scientific_tools import scientific_tools

    runtime = tmp_path / "runtime"
    pkg = installed(runtime / "Lib/site-packages")
    (pkg / "unrecorded.py").write_text("def secret(): pass", encoding="utf-8")
    assert inspect_source(runtime, {}, "demo", "demo.unrecorded")["availability"] == "source_unavailable"
    with pytest.raises(ValueError, match="distribution"):
        inspect_source(runtime, {}, "../demo", "demo.api")
    tools = {item.name: item for item in scientific_tools(tmp_path)}
    with pytest.raises(ValueError, match="disabled"):
        tools["inspect_installed_api_source"].invoke({"distribution": "demo", "module": "demo.api"})
