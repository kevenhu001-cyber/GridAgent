"""Exercise the installed Node → Python handshake without a model request."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node must be installed before running the Pi worker smoke test")

    worker = Path(__file__).resolve().with_name("worker.mjs")
    env = {key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP") if key in os.environ}
    with tempfile.TemporaryDirectory(prefix="gridagent-pi-smoke-") as workspace:
        env.update(
            GRIDAGENT_NATIVE_PYTHON=sys.executable,
            GRIDAGENT_NATIVE_WORKSPACE=workspace,
            GRIDAGENT_PI_PROVIDER="openai",
            GRIDAGENT_PI_MODEL="gpt-5.4",
            GRIDAGENT_PI_API_KEY="offline-smoke-test",
        )
        for restore in (False, True):
            expected = {"kind": "ready", "version": 1}
            request = ""
            if restore:
                env["GRIDAGENT_PI_RESTORE_TEXT"] = "1"
                request = json.dumps({
                    "method": "restore_text", "version": 1,
                    "turns": [{"user": "Earlier question", "assistant": "Earlier answer", "timestamp": 1000}],
                }) + "\n"
                expected["restored"] = True
            result = subprocess.run(
                [node, str(worker)], input=request, text=True, capture_output=True,
                timeout=45, env=env, check=False,
            )
            if result.returncode != 0:
                raise RuntimeError(f"Pi worker exited {result.returncode}: {result.stderr.strip()}")
            if json.loads(result.stdout) != expected:
                raise RuntimeError(f"Unexpected Pi startup response: {result.stdout!r}")
    print("Pi worker started the installed scientific service with and without saved text")


if __name__ == "__main__":
    main()
