from gridagent.desktop_bridge import dispatch


def test_offline_desktop_session_roundtrip(tmp_path):
    events = []

    def emit(kind, data):
        events.append((kind, data))

    dispatch(tmp_path, {"action": "new"}, emit)
    sid = next(data for kind, data in events if kind == "session")
    events.clear()
    dispatch(tmp_path, {"action": "refresh"}, emit)
    sessions = next(data for kind, data in events if kind == "sessions")
    assert sessions[0]["id"] == sid
    dispatch(tmp_path, {"action": "history", "session": sid}, emit)
    dispatch(tmp_path, {"action": "local", "command": "runs"}, emit)


def test_desktop_reference_without_model(tmp_path, monkeypatch):
    monkeypatch.delenv("GRIDAGENT_API_KEY", raising=False)
    events = []
    dispatch(tmp_path, {"action": "dmq", "reference": True}, lambda kind, data: events.append((kind, data)))
    assert any(kind == "result" and "8/8 passed" in data for kind, data in events)
    assert any(kind == "studies" and data for kind, data in events)


def test_desktop_waveform_keeps_extrema(tmp_path):
    run_id = "a" * 32
    folder = tmp_path / "runs" / run_id
    folder.mkdir(parents=True)
    rows = ["time_s,B5"] + [f"{i / 1000},{0.2 if i == 501 else 1.0}" for i in range(3000)]
    (folder / "voltage.csv").write_text("\n".join(rows), encoding="utf-8")
    events = []
    dispatch(tmp_path, {"action": "waveform", "run": run_id},
             lambda kind, data: events.append((kind, data)))
    series = events[0][1][0]
    assert series["samples"] == 3000
    assert len(series["time"]) <= 1200
    assert min(series["value"]) == 0.2


def test_desktop_model_configuration_roundtrip(tmp_path, monkeypatch):
    from gridagent import model_settings

    events = []
    def emit(kind, data):
        events.append((kind, data))

    data = {"model": "fixture", "base_url": "http://127.0.0.1:8200/v1"}
    dispatch(tmp_path, {"action": "model-save", **data}, emit)
    dispatch(tmp_path, {"action": "model-settings"}, emit)
    assert [entry for kind, entry in events if kind == "model_settings"] == [data, data]
    monkeypatch.setattr(model_settings, "check_connection", lambda settings: "Connected to " + settings.model)
    dispatch(tmp_path, {"action": "model-test", **data}, emit)
    assert events[-1] == ("result", "Connected to fixture")


def test_connection_check_uses_configured_compatible_endpoint(tmp_path, monkeypatch):
    import json
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from threading import Thread

    monkeypatch.delenv("GRIDAGENT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    received = []

    class Fixture(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append((self.path, body["model"]))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"id": "fixture", "object": "chat.completion", "created": 0,
                                         "model": body["model"], "choices": [{"index": 0, "finish_reason": "stop",
                                         "message": {"role": "assistant", "content": "OK"}}]}).encode())

    with HTTPServer(("127.0.0.1", 0), Fixture) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            events = []
            dispatch(tmp_path, {"action": "model-test", "model": "fixture",
                                "base_url": f"http://127.0.0.1:{server.server_port}/v1"},
                     lambda kind, data: events.append((kind, data)))
        finally:
            server.shutdown()
            thread.join()
    assert received == [("/v1/chat/completions", "fixture")]
    assert events[-1] == ("result", "Connected to fixture")


def test_desktop_initialize_is_lightweight(tmp_path):
    import os
    import subprocess
    import sys

    env = dict(os.environ)
    env.pop("GRIDAGENT_MODEL", None)
    env.pop("GRIDAGENT_BASE_URL", None)
    code = """
import sys
from pathlib import Path
from gridagent.desktop_bridge import dispatch
events = []
dispatch(Path(sys.argv[1]), {"action": "initialize"}, lambda k, v: events.append((k, v)))
assert [k for k, v in events] == ["model_settings", "sessions"]
assert "gridagent.agent" not in sys.modules
assert "gridagent.simulator" not in sys.modules
assert "gridagent.research" not in sys.modules
assert "numpy" not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=False, env=env,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
