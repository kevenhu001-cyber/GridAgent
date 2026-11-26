from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from gridagent.store import ResearchStore


def test_reopen_and_replay(tmp_path):
    db = tmp_path / "research.sqlite3"
    store = ResearchStore(db)
    sid = store.create_session()
    task = store.start_task(sid, "Study")
    store.append(task, "agent", {"messages": [AIMessage(content="Answer")]})
    store.finish(task, "completed")
    reopened = ResearchStore(db)
    history = reopened.history(sid)
    assert isinstance(history[0], HumanMessage)
    assert history[0].content == "Study"
    assert history[1].content == "Answer"
    assert reopened.sessions()[0]["tasks"] == 1


def test_incomplete_tool_messages_retained_but_not_replayed(tmp_path):
    store = ResearchStore(tmp_path / "research.sqlite3")
    sid = store.create_session()
    task = store.start_task(sid, "Failure")
    store.append(task, "tools", {"messages": [ToolMessage(content="{}", tool_call_id="1")], "used": 1})
    store.finish(task, "failed", "TimeoutError")
    assert store.history(sid) == []
    assert store.events(task)[0]["payload"]["used"] == 1
    assert store.tasks(sid)[0]["status"] == "failed"
