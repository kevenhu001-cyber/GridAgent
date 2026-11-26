import io
import json

from gridagent.desktop_read_service import serve


def request(action, identifier="a" * 32, **kwargs):
    return json.dumps({"version": 1, "id": identifier, "request": {"action": action, **kwargs}}) + "\n"


def test_read_service_reuses_process_and_correlates_requests(tmp_path):
    source = io.StringIO(request("initialize") + request("refresh", "b" * 32))
    output = io.StringIO()
    calls = []

    def handler(root, body, emit):
        calls.append(body["action"])
        emit("status", "ready")

    serve(tmp_path, source, output, handler=handler)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert calls == ["initialize", "refresh"]
    assert [e["id"] for e in events] == ["a" * 32] * 2 + ["b" * 32] * 2
    assert [e["kind"] for e in events] == ["status", "done"] * 2
    assert all(e["version"] == 1 for e in events)


def test_read_service_rejects_mutations_and_recovers(tmp_path):
    source = io.StringIO(request("ask", prompt="never execute") + request("initialize", "b" * 32))
    output = io.StringIO()
    calls = []
    serve(tmp_path, source, output, handler=lambda root, body, emit: calls.append(body["action"]))
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert calls == ["initialize"]
    assert [e["data"] for e in events if e["kind"] == "done"] == [False, True]


def test_read_service_real_workspace_roundtrip(tmp_path):
    source = io.StringIO(request("initialize") + request("initialize", "b" * 32))
    output = io.StringIO()
    serve(tmp_path, source, output)
    events = [json.loads(line) for line in output.getvalue().splitlines()]
    assert [e["kind"] for e in events] == ["model_settings", "sessions", "done"] * 2
