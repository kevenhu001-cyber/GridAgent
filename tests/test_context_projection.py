import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from gridagent.context_projection import project_context
from gridagent.store import ResearchStore


def test_projection_preserves_calls_latest_results_and_audit_objects():
    messages = [HumanMessage(content="Preserve all engineering constraints")]
    for index in range(8):
        key = str(index)
        messages.extend([AIMessage(content="", tool_calls=[
            {"name": "execute_python", "args": {"entry": "model.py"}, "id": key}]),
            ToolMessage(content=json.dumps({"status": "ok", "run_id": key, "data": "x"*16000}),
                        tool_call_id=key, name="execute_python")])
    projected, metrics = project_context(messages, target=80000)
    assert metrics["compacted_tool_results"] > 0
    assert metrics["projected_chars"] < metrics["original_chars"]
    assert projected[0] == messages[0]
    assert projected[-8:] == messages[-8:]
    assert projected[1] == messages[1]
    assert projected[2].tool_call_id == "0"
    assert json.loads(projected[2].content)["context_projection"] is True
    assert json.loads(projected[2].content)["evidence_fields"]["run_id"] == "0"
    assert len(json.loads(messages[2].content)["data"]) == 16000
    _, oversized = project_context([HumanMessage(content="x"*10000)], target=10)
    assert oversized["target_exceeded"]


def test_session_evidence_is_scoped_and_paged(tmp_path):
    store = ResearchStore(tmp_path / "research.sqlite3")
    sid, other = store.create_session(), store.create_session()
    task, foreign = store.start_task(sid, "Inspect"), store.start_task(other, "Private")
    store.append(task, "tools", {"messages": [ToolMessage(content="evidence", tool_call_id="a")]})
    store.finish(task, "interrupted")
    store.append(foreign, "tools", {"messages": [ToolMessage(content="private", tool_call_id="b")]})
    assert store.history(sid) == []
    assert store.session_evidence(sid)["tasks"][0]["status"] == "interrupted"
    event = store.session_evidence(sid, task)["events"][0]["id"]
    first = store.session_evidence(sid, task, event, limit=8)
    second = store.session_evidence(sid, task, event, offset=first["next_offset"], limit=12000)
    assert json.loads(first["text"] + second["text"])["messages"][0]["data"]["content"] == "evidence"
    with pytest.raises(ValueError, match="active session"):
        store.session_evidence(sid, foreign)
    foreign_event = store.session_evidence(other, foreign)["events"][0]["id"]
    with pytest.raises(ValueError, match="selected task"):
        store.session_evidence(sid, task, foreign_event)
