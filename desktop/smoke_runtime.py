"""Run with the relocated private interpreter, with system Python off PATH."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import andes
import numpy
import scipy

from gridagent.simulator import AndesSimulator


def main():
    root = Path(sys.executable).resolve().parent
    assert Path(sys.prefix).resolve() == root, sys.prefix
    for module in (andes, numpy, scipy):
        assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
    with tempfile.TemporaryDirectory(prefix="GridAgent smoke ") as temp:
        workspace = Path(temp)
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "gridagent.desktop_bridge", "--workspace", str(workspace)],
            input=json.dumps({"action": "new"}) + "\n", text=True, encoding="utf-8",
            capture_output=True, timeout=120, check=True,
        )
        events = [json.loads(line) for line in result.stdout.splitlines()]
        assert any(e["kind"] == "session" for e in events), events
        assert events[-1] == {"kind": "done", "data": True}, events
        simulator = AndesSimulator(workspace / "runs", timeout_s=300)
        fault = simulator.run("fault", {"case": "kundur", "bus": 5, "duration_s": 0.1, "end_s": 3.0})
        assert fault["status"] == "ok", fault
        assert (workspace / "runs" / fault["run_id"] / "voltage.csv").is_file()
        eigen = simulator.run("eigen", {"case": "kundur"})
        assert eigen["status"] == "ok", eigen
    print("Private interpreter, native dependencies, desktop bridge, fault and eigenanalysis: OK")


if __name__ == "__main__":
    main()
