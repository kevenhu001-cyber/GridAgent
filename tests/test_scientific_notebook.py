import json

import pytest

from gridagent import scientific_workspace as ws
from gridagent.native_service import dispatch
from gridagent.scientific_notebook import export_run


def fixture_run(root):
    ws.set_enabled(root, True)
    run_id = "a" * 32
    folder = root / "scientific-runs" / run_id
    source = b"print(42)\n"
    snapshot = folder / "input" / "project"
    snapshot.mkdir(parents=True)
    (snapshot / "study.py").write_bytes(source)
    output = folder / "output"
    output.mkdir()
    stdout = b"42\n"
    (output / "stdout.log").write_bytes(stdout)
    report = {"protocol": "scientific-python-v1", "status": "ok", "entry": "study.py",
              "run_id": run_id, "arguments": [], "inputs": [
                  {"path": "study.py", "size_bytes": len(source), "sha256": ws.sha(source)}],
              "artifacts": [{"path": "stdout.log", "size_bytes": len(stdout), "sha256": ws.sha(stdout)}]}
    (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    return run_id, folder


def test_export_standard_notebook_with_source_and_provenance(tmp_path):
    nbformat = pytest.importorskip("nbformat")
    run_id, _ = fixture_run(tmp_path)
    result = dispatch(tmp_path, "scientific.export_notebook",
                      {"run_id": run_id, "destination": "study.ipynb"}, allow_tasks=True)
    notebook = nbformat.read(tmp_path / "scientific-project" / "study.ipynb", as_version=4)
    nbformat.validate(notebook)
    assert notebook.cells[1].source == "print(42)\n"
    assert notebook.cells[1].execution_count is None and notebook.cells[1].outputs == []
    assert notebook.cells[-1].cell_type == "raw"
    assert notebook.cells[-1].source == "42\n"
    assert notebook.metadata.gridagent.run_id == run_id
    assert result["origin_run_id"] == run_id
    with pytest.raises(ValueError, match="SHA-256"):
        export_run(tmp_path, run_id, "study.ipynb")


def test_export_denies_tampered_source_and_output(tmp_path):
    pytest.importorskip("nbformat")
    run_id, folder = fixture_run(tmp_path)
    (folder / "output" / "stdout.log").write_text("tampered", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        export_run(tmp_path, run_id, "study.ipynb")
    (folder / "input" / "project" / "study.py").write_text("print(3)", encoding="utf-8")
    with pytest.raises(ValueError, match="changed"):
        export_run(tmp_path, run_id, "study.ipynb")
    assert not (tmp_path / "scientific-project" / "study.ipynb").exists()


def test_export_requires_task_permission_and_workspace_grant(tmp_path):
    run_id, _ = fixture_run(tmp_path)
    args = {"run_id": run_id, "destination": "study.ipynb"}
    with pytest.raises(ValueError, match="Unknown"):
        dispatch(tmp_path, "scientific.export_notebook", args)
    ws.set_enabled(tmp_path, False)
    with pytest.raises(ValueError, match="disabled"):
        dispatch(tmp_path, "scientific.export_notebook", args, allow_tasks=True)
