"""Run with the relocated private interpreter, with system Python off PATH."""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import andes
import numpy
import pandapower
import control
import sympy
import networkx
import highspy
import scipy

from gridagent.extension_runner import run_extension
from gridagent.native_backends import run_program
from gridagent.paper import asset, training_evidence
from gridagent.research import ResearchTasks
from gridagent.research_spec import ResearchManifest
from gridagent.simulator import AndesSimulator


def main():
    root = Path(sys.executable).resolve().parent
    assert Path(sys.prefix).resolve() == root, sys.prefix
    os.environ["GRIDAGENT_BENCHMARK_ROOT"] = str(root.parent / "benchmark-assets")
    evidence, total, eligible = training_evidence()
    assert len(evidence) == 10 and total >= eligible > 0
    assert asset("cases/solar_wecc/psse/Solar.sav").is_file()
    assert not (root.parent / "benchmark-assets/benchmarks/dynamic/level2/test_memory.json").exists()
    for module in (andes, numpy, scipy, pandapower, control, sympy, networkx, highspy):
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
        frames = [
            {"version": 1, "id": "a" * 32, "request": {"action": "initialize"}},
            {"version": 1, "id": "b" * 32, "request": {"action": "artifact-preview", "run": fault["run_id"]}},
            {"version": 1, "id": "c" * 32, "request": {"action": "ask", "prompt": "must not execute"}},
            {"version": 1, "id": "d" * 32, "request": {"action": "refresh"}},
        ]
        read = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "gridagent.desktop_read_service", str(workspace)],
            input="".join(json.dumps(frame) + "\n" for frame in frames), text=True, encoding="utf-8",
            capture_output=True, timeout=120, check=True,
        )
        read_events = [json.loads(line) for line in read.stdout.splitlines()]
        terminals = [e for e in read_events if e["kind"] == "done"]
        assert [e["id"] for e in terminals] == [f["id"] for f in frames]
        assert [e["data"] for e in terminals] == [True, True, False, True]
        preview = next(e["data"] for e in read_events if e["kind"] == "artifact_preview")
        assert preview["schema"] == "gridagent.artifact.v1" and preview["id"] == fault["run_id"]
        assert 0 < len(preview["x"]) == len(preview["y"]) <= 240
        eigen = simulator.run("eigen", {"case": "kundur"})
        assert eigen["status"] == "ok", eigen
        pp = run_program(workspace, {"backend": "pandapower", "base": "case14"})
        assert pp["status"] == "ok", pp
        example = root.parent / "examples" / "power-flow-research.json"
        specification = ResearchManifest.model_validate_json(example.read_bytes())
        tasks = ResearchTasks(workspace)
        task_id = tasks.start(specification.objective, manifest=specification)
        task = list(tasks.resume(task_id))[-1]
        assert task["stage"] == "passed" and task["runs_used"] == 2, task
        response = run_extension(workspace, "control", {"numerator": [1], "denominator": [1, 1], "duration_s": 5})
        assert response["status"] == "ok", response
        assert abs(response["metrics"]["final_sample"] - (1-__import__("math").exp(-5))) < 1e-6
        import importlib.util
        assert importlib.util.find_spec("pypsa") is None, "PyPSA must not ship in Core"
        assert importlib.util.find_spec("pip") is not None
    print("Private interpreter, native dependencies, desktop bridge and verified AC research: OK")


if __name__ == "__main__":
    main()
