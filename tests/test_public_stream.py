from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from gridagent.agent import invoke_public_stream


def test_public_stream_aggregates_tool_calls_without_leaking_arguments():
    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content="Inspect ", tool_call_chunks=[
                {"name": "power_flow", "args": '{"case":', "id": "call_1", "index": 0},
            ])
            yield AIMessageChunk(content="network", tool_call_chunks=[
                {"name": None, "args": '"kundur"}', "id": None, "index": 0},
            ])

    deltas = []
    message = invoke_public_stream(Model(), [HumanMessage(content="Inspect")], deltas.append)
    assert isinstance(message, AIMessage)
    assert message.content == "Inspect network"
    assert message.tool_calls[0]["args"] == {"case": "kundur"}
    assert "".join(deltas) == "Inspect network"


def test_nonstreaming_model_unchanged():
    class Model:
        def invoke(self, messages):
            return AIMessage(content="complete")

    assert invoke_public_stream(Model(), []).content == "complete"


def test_reasoning_blocks_not_forwarded():
    class Model:
        def stream(self, messages):
            yield AIMessageChunk(content=[{"type": "reasoning", "reasoning": "private"},
                                          {"type": "text", "text": "public"}])

    deltas = []
    invoke_public_stream(Model(), [], deltas.append)
    assert "".join(deltas) == "public"
