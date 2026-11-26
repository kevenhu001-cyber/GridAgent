import json

from langchain_core.messages import AIMessage, HumanMessage

from gridagent.agent import build_agent


class ScriptedModel:
    def __init__(self):
        self.turn = 0
    def bind_tools(self, tools):
        return self
    def invoke(self, messages):
        self.turn += 1
        if self.turn == 1:
            return AIMessage(content="", tool_calls=[
                {"name": "simulate_fault", "args": {"case": "kundur", "bus": 5, "duration_s": 0.1}, "id": "1"},
                {"name": "simulate_fault", "args": {"case": "kundur", "bus": 6, "duration_s": 0.1}, "id": "2"},
            ])
        return AIMessage(content="Finished.")


class FakeSimulator:
    def __init__(self):
        self.requests = []
    def run(self, operation, request):
        self.requests.append((operation, request))
        return {"status": "ok", "backend": "test_double"}


def test_parallel_requested_calls_cannot_bypass_budget():
    sim = FakeSimulator()
    graph = build_agent(ScriptedModel(), sim, budget=1)
    result = graph.invoke({"messages": [HumanMessage(content="test")], "used": 0, "calls": 0, "rounds": 0})
    assert len(sim.requests) == 1
    assert result["used"] == 1
    assert json.loads(result["messages"][-2].content)["status"] == "denied"
    assert result["messages"][-1].content == "Finished."
