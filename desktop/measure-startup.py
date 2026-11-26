"""Measure the isolated bridge startup path with the bundled Python runtime.

This is not a GUI cold-start benchmark. It measures request-to-completion latency
for lightweight initialization and full workspace indexing on an empty workspace.
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
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    measure()
