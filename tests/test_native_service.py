import json
import subprocess
import sys

from gridagent.scientific_workspace import set_enabled


def test_native_service_real_process(tmp_path):
    def frame(number, method, params=None):
        return json.dumps({"version": 1, "id": f"{number:032x}",
                           "method": method, "params": params or {}})

    def invoke(*frames):
        result = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "gridagent.native_service", str(tmp_path)],
            input="\n".join(frames) + "\n", capture_output=True, text=True, timeout=30, check=True,
        )
        return [json.loads(row) for row in result.stdout.splitlines()]

    hello, denied, unknown, invalid = invoke(
        frame(1, "hello"), frame(2, "workspace.files"),
        frame(3, "execute_python"), frame(4, "hello", {"root": "/other"}),
    )
    assert hello["ok"] and hello["result"]["mode"] == "read-only"
    assert hello["id"] == f"{1:032x}"
    assert not denied["ok"] and not unknown["ok"] and not invalid["ok"]
    set_enabled(tmp_path, True)
    files, runs = invoke(frame(5, "workspace.files"), frame(6, "scientific.runs"))
    assert files["ok"] and files["result"]["files"] == []
    assert runs["ok"]
