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


def test_general_agent_plan_and_scenario_budget(tmp_path):
    class Model:
        def __init__(self):
            self.turn = 0

        def bind_tools(self, tools):
            self.names = {t.name for t in tools}
            return self

        def invoke(self, messages):
            self.turn += 1
            if self.turn == 1:
                return AIMessage(content="", tool_calls=[
                    {"name": "research_plan", "args": {"objective": "Compare loading",
                     "steps": ["Solve baseline", "Solve scenario"], "verification": "Compare voltages"}, "id": "a"},
                    {"name": "scenario_power_flow", "args": {"case": "ieee14", "load_scale": 1.1}, "id": "b"},
                    {"name": "scenario_power_flow", "args": {"case": "ieee14", "load_scale": 1.2}, "id": "c"}])
            return AIMessage(content="Partial comparison; budget reached.")

    model, sim = Model(), FakeSimulator()
    result = build_agent(model, sim, budget=1, workspace=tmp_path).invoke(
        {"messages": [HumanMessage(content="Compare loading")], "used": 0, "calls": 0, "rounds": 0})
    assert {"network_path", "compare_flow_runs", "analyze_voltage_waveform"} <= model.names
    assert len(sim.requests) == 1
    assert sim.requests[0][0] == "scenario_flow"
    assert result["used"] == 1
    assert json.loads(result["messages"][-2].content)["status"] == "denied"


def test_plugins_are_bound_with_corresponding_guidance(tmp_path, monkeypatch):
    from gridagent import plugins

    class Model:
        def bind_tools(self, tools):
            self.names = {t.name for t in tools}
            return self

        def invoke(self, messages):
            self.prompt = messages[0].content
            return AIMessage(content="Done.")

    monkeypatch.setenv("GRIDAGENT_PLUGIN_ROOT", str(tmp_path / "plugins"))
    monkeypatch.setattr(plugins.importlib.util, "find_spec", lambda name: None)
    before = Model()
    build_agent(before, FakeSimulator(), workspace=tmp_path).invoke(
        {"messages": [HumanMessage(content="test")], "used": 0, "calls": 0, "rounds": 0})
    assert "battery_discharge" not in before.names
    assert "Chen2020" not in before.prompt
    monkeypatch.setattr(plugins.importlib.util, "find_spec", lambda name: object() if name == "pybamm" else None)
    after = Model()
    build_agent(after, FakeSimulator(), workspace=tmp_path).invoke(
        {"messages": [HumanMessage(content="test")], "used": 0, "calls": 0, "rounds": 0})
    assert "battery_discharge" in after.names
    assert "Chen2020" in after.prompt
    assert "pypsa_dispatch" not in after.names
    assert "plugin-install" not in after.names
