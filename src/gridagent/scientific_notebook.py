"""Standard, inert notebook export from a committed scientific script run."""
from . import scientific_workspace as ws

MAX_STDOUT = 12000


def export_run(root, run_id, destination, expected_sha256=None):
    ws.require_grant(root)
    ws.safe_parts(destination)
    if not destination.lower().endswith(".ipynb"):
        raise ValueError("Notebook destination must end in .ipynb")
    try:
        import nbformat
    except ImportError as exc:
        raise ValueError("Install the optional notebook dependency in the trusted runtime") from exc

    folder = ws.job_directory(root, run_id)
    report = ws.report(root, run_id)
    if (folder / "recovery.json").exists() or report.get("status") != "ok":
        raise ValueError("Select a completed successful scientific run")
    if report.get("protocol") != "scientific-python-v1" or any(
            report.get(key) is not None for key in ("shell", "api_probe", "kernel")):
        raise ValueError("Only ordinary Python script runs are supported by this exporter")
    entry = report["entry"]
    ws.safe_parts(entry)
    if not entry.endswith(".py"):
        raise ValueError("Expected Python source")
    row = next((r for r in report["inputs"] if r["path"] == entry), None)
    if row is None:
        raise ValueError("Source snapshot is missing")
    source = ws.bounded_bytes(ws.scoped(folder / "input" / "project", entry), ws.MAX_FILE)
    if ws.sha(source) != row["sha256"] or len(source) != row["size_bytes"]:
        raise ValueError("Source snapshot changed after execution")
    provenance = {
        "run_id": run_id, "entry": entry, "source_sha256": row["sha256"],
        "arguments": report.get("arguments", []), "inputs": report["inputs"],
        "plugin_ids": report.get("plugin_ids", []),
        "environment": report.get("environment", {}),
        "verification": "unverified_script_output",
    }
    cells = [
        nbformat.v4.new_markdown_cell(
            "# GridAgent scientific run\n\n"
            "Archived script and recorded evidence. The code cell is unexecuted in this notebook. "
            "Review the source before running it. Restore the original project inputs, arguments, "
            "dependencies and isolated execution environment separately. "
            "This export is not proof of numerical correctness or independent reproducibility."
        ),
        nbformat.v4.new_code_cell(source.decode("utf-8")),
    ]
    if any(r.get("path") == "stdout.log" for r in report.get("artifacts", [])):
        raw = ws.artifact_bytes(root, run_id, "stdout.log")
        provenance["stdout_sha256"] = ws.sha(raw)
        provenance["stdout_truncated"] = len(raw) > MAX_STDOUT
        cells.append(nbformat.v4.new_markdown_cell("## Recorded stdout/stderr (plain text, unverified)"))
        # Raw cell, not executable code or active HTML output.
        cells.append(nbformat.v4.new_raw_cell(raw[-MAX_STDOUT:].decode("utf-8", errors="replace"),
                                              metadata={"raw_mimetype": "text/plain"}))
    notebook = nbformat.v4.new_notebook(cells=cells, metadata={
        "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
        "gridagent": provenance,
    })
    nbformat.validate(notebook)
    encoded = nbformat.writes(notebook, version=4).encode("utf-8")
    if len(encoded) > ws.MAX_FILE:
        raise ValueError("Notebook exceeds the project file budget")
    result = ws.write_bytes(root, destination, encoded, expected_sha256)
    return {**result, "origin_run_id": run_id, "verification": "unverified_script_output"}
