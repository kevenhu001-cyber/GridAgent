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
