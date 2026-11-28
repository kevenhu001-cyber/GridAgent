import json

import pytest

from gridagent import kernel_batch, scientific_runtime
from gridagent import scientific_workspace as ws


def test_validate_and_generate_guest_only_source():
    cells = ["x = 2", "print(x)"]
    source = kernel_batch.launcher_source(cells)
    compile(source, "guest-kernel.py", "exec")
    assert b"KernelManager" in source
    assert b"print(x)" in source
    for bad in ([], [""] * 9, ["x" * 24001], ["\x00"], [42]):
        with pytest.raises(ValueError):
            kernel_batch.validate_cells(bad)


def test_kernel_never_runs_without_sandbox(tmp_path, monkeypatch):
    ws.set_enabled(tmp_path, True)

    def unavailable():
        raise ValueError("No isolated runtime")

    monkeypatch.setattr(scientific_runtime, "require_runtime", unavailable)
    with pytest.raises(ValueError, match="No isolated runtime"):
        scientific_runtime.execute(tmp_path, "internal-kernel.py", kernel_cells=["x = 1"])


@pytest.mark.integration
def test_actual_kernel_fixture_preserves_state_and_stops_on_error(tmp_path):
    pytest.importorskip("jupyter_client")
    pytest.importorskip("ipykernel")
    cells = ["import numpy as np; x = np.array([2, 3])",
             "print(int(x.sum()))", "raise ValueError('fixture')", "print('not executed')"]
    assert kernel_batch.run_cells(cells, tmp_path) == 1
    result = json.loads((tmp_path / "kernel-results.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["cells"][0]["status"] == "ok"
    assert result["cells"][1]["text"].strip() == "5"
    assert result["cells"][2]["status"] == "error"
    assert len(result["cells"]) == 3
