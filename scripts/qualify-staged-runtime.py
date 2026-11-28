"""Trusted packaging fixture. Never run user or Agent code on the host."""
import json
import sys
import time
from importlib.metadata import version
from pathlib import Path
from tempfile import TemporaryDirectory


def component_size(directory):
    return sum(path.stat().st_size for path in directory.rglob("*") if path.is_file())


def main():
    staged = Path(sys.argv[1]).resolve(strict=True)
    if Path(sys.executable).resolve().parent != (staged / "python").resolve():
        raise RuntimeError("Qualification must use the relocated private interpreter")

    start = time.perf_counter()
    import nbformat
    from gridagent import kernel_batch, scientific_workspace as ws
    from gridagent.native_service import dispatch

    versions = {name: version(name) for name in (
        "jupyter-client", "ipykernel", "nbformat", "numpy", "scipy", "andes", "pandapower"
    )}
    imports_ms = round((time.perf_counter() - start) * 1000)
    with TemporaryDirectory(prefix="gridagent-staged-research-") as tmp:
        root = Path(tmp)
        output = root / "kernel-output"
        output.mkdir()
        start = time.perf_counter()
        # Fixed known fixture only; guest launcher is not invoked on the host.
        if kernel_batch.run_cells(["import numpy as np; x = np.array([2, 3])", "print(int(x.sum()))"], output):
            raise RuntimeError("Relocated kernel fixture failed")
        result = json.loads((output / "kernel-results.json").read_text(encoding="utf-8"))
        if result["status"] != "ok" or result["cells"][1]["text"].strip() != "5":
            raise RuntimeError("Relocated kernel did not preserve state")
        kernel_ms = round((time.perf_counter() - start) * 1000)

        workspace = root / "workspace"
        ws.set_enabled(workspace, True)
        run_id = "a" * 32
        folder = workspace / "scientific-runs" / run_id
        snapshot = folder / "input" / "project"
        snapshot.mkdir(parents=True)
        source = b"print(42)\n"
        (snapshot / "study.py").write_bytes(source)
        output = folder / "output"
        output.mkdir()
        stdout = b"42\n"
        (output / "stdout.log").write_bytes(stdout)
        report = {
            "protocol": "scientific-python-v1", "run_id": run_id, "status": "ok", "entry": "study.py",
            "inputs": [{"path": "study.py", "size_bytes": len(source), "sha256": ws.sha(source)}],
            "artifacts": [{"path": "stdout.log", "size_bytes": len(stdout), "sha256": ws.sha(stdout)}],
        }
        (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
        start = time.perf_counter()
        dispatch(workspace, "scientific.export_notebook",
                 {"run_id": run_id, "destination": "study.ipynb"}, allow_tasks=True)
        notebook = nbformat.read(workspace / "scientific-project" / "study.ipynb", as_version=4)
        nbformat.validate(notebook)
        if notebook.cells[1].source != source.decode() or notebook.cells[1].execution_count is not None:
            raise RuntimeError("Notebook source/provenance fixture failed")
        notebook_ms = round((time.perf_counter() - start) * 1000)
    print(json.dumps({
        "qualification": "relocated_runtime_trusted_fixtures",
        "versions": versions,
        "component_bytes": {name: component_size(staged / name) for name in ("python", "node", "pi")},
        "import_fixture_ms": imports_ms, "kernel_fixture_ms": kernel_ms,
        "notebook_export_fixture_ms": notebook_ms,
        "actual_vm_qualified": False,
        "clean_machine_install_qualified": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
