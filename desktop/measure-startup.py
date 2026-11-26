"""Measure the isolated bridge startup path with the bundled Python runtime.

This is not a GUI cold-start benchmark. It measures request-to-completion latency
for lightweight initialization and full workspace indexing on an empty workspace,
plus amortized throughput for repeated requests in one resident read process.
"""
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def measure():
    with tempfile.TemporaryDirectory(prefix="gridagent-startup-") as folder:
        root = Path(folder)
        results = {}
        for action in ("initialize", "refresh"):
            samples = []
            for _ in range(3):
                before = time.perf_counter()
                result = subprocess.run(
                    [sys.executable, "-X", "utf8", "-m", "gridagent.desktop_bridge",
                     "--workspace", str(root)],
                    input=json.dumps({"action": action}) + "\n",
                    capture_output=True, text=True, timeout=120, check=True,
                )
                events = [json.loads(line) for line in result.stdout.splitlines()]
                assert events[-1] == {"kind": "done", "data": True}
                samples.append(round((time.perf_counter() - before) * 1000, 1))
            results[action] = {"median_ms": statistics.median(samples), "samples_ms": samples}
        for action in ("initialize", "refresh"):
            samples = []
            for _ in range(3):
                frames = [
                    {"version": 1, "id": f"{index:032x}", "request": {"action": action}}
                    for index in range(5)
                ]
                before = time.perf_counter()
                result = subprocess.run(
                    [sys.executable, "-X", "utf8", "-m", "gridagent.desktop_read_service", str(root)],
                    input="".join(json.dumps(frame) + "\n" for frame in frames),
                    capture_output=True, text=True, timeout=120, check=True,
                )
                events = [json.loads(line) for line in result.stdout.splitlines()]
                terminal = [e for e in events if e["kind"] == "done"]
                assert [e["id"] for e in terminal] == [f["id"] for f in frames]
                assert all(e["version"] == 1 and e["data"] is True for e in terminal)
                samples.append(round((time.perf_counter() - before) * 1000 / len(frames), 1))
            results[action + "_resident_amortized"] = {
                "median_ms_per_request": statistics.median(samples), "samples_ms_per_request": samples,
                "requests_per_process": 5, "includes_process_start_and_exit": True,
            }
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    measure()
