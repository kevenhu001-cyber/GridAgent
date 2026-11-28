"""Trusted integration fixtures; not a claim of OS isolation or PDF support."""
import importlib.util
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[1] / "examples" / "scientific"


def load_example(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.integration
def test_joblib_threaded_sweep_matches_serial():
    pytest.importorskip("joblib")
    example = load_example("joblib_sweep")
    resistances = [1.0, 2.0, 5.0, 10.0]
    assert example.sweep(resistances, workers=2) == [example.response(r) for r in resistances]
    with pytest.raises(ValueError):
        example.sweep(resistances, workers=5)
    with pytest.raises(ValueError):
        example.sweep([float("nan")])


@pytest.mark.integration
def test_docling_local_docx_fixture(tmp_path, monkeypatch):
    pytest.importorskip("docling")
    from docx import Document

    monkeypatch.setenv("HF_HUB_OFFLINE", "1")
    monkeypatch.setenv("TRANSFORMERS_OFFLINE", "1")
    project = tmp_path / "project"
    project.mkdir()
    output = tmp_path / "output"
    output.mkdir()
    document = Document()
    document.add_heading("GridAgent fixture", level=1)
    document.add_paragraph("Voltage magnitude is 1.0 p.u.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Bus"
    table.cell(0, 1).text = "Voltage"
    table.cell(1, 0).text = "B1"
    table.cell(1, 1).text = "1.0"
    document.save(project / "fixture.docx")
    example = load_example("docling_convert")
    text = example.convert("fixture.docx", project, output)
    assert "GridAgent fixture" in text
    assert "Voltage magnitude" in text and "B1" in text
    assert (output / "document.md").read_text(encoding="utf-8") == text
    with pytest.raises(ValueError, match="project-relative"):
        example.convert("../outside.docx", project, output)
    (project / "fixture.pdf").write_bytes(b"%PDF")
    with pytest.raises(ValueError, match="Only DOCX and PPTX"):
        example.convert("fixture.pdf", project, output)
