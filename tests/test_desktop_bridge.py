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
