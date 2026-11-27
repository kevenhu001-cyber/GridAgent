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


def test_prompt_prefix_is_stable_and_budget_notice_is_not_replayed():
    class Model(ScriptedModel):
        def __init__(self):
            super().__init__()
            self.requests = []

        def bind_tools(self, tools):
            self.tool_names = [tool.name for tool in tools]
            return self

        def invoke(self, messages):
            self.requests.append(messages)
            return super().invoke(messages)

    model = Model()
    result = build_agent(model, FakeSimulator(), budget=1).invoke(
        {"messages": [HumanMessage(content="Compare faults")], "used": 0, "calls": 0, "rounds": 0})
    assert len(model.requests) == 2
    assert model.requests[0][0].content == model.requests[1][0].content
    assert "budget: 1" in model.requests[0][-1].content
    assert "budget: 0" in model.requests[1][-1].content
    assert model.tool_names == sorted(model.tool_names)
    assert not any("runtime budget notice" in message.content
                   for message in result["messages"] if isinstance(message.content, str))


def test_llm_can_author_execute_debug_and_revise_project(tmp_path, monkeypatch):
    from gridagent import scientific_runtime as runtime
    from gridagent import scientific_workspace as ws

    ws.set_enabled(tmp_path, True)
    launches = []

    def fake_execute(root, entry, plugin=None, arguments=None):
        source = ws.read_project(root, entry)["text"]
        launches.append(source)
        return {"status": "failed" if len(launches) == 1 else "ok",
                "stdout_stderr_tail": "NameError: x" if len(launches) == 1 else "test-double output"}

    monkeypatch.setattr(runtime, "execute", fake_execute)

    class Model:
        def __init__(self):
            self.turn = 0
            self.digest = None

        def bind_tools(self, tools):
            assert {"scientific_environment", "write_project_file", "execute_python",
                    "read_scientific_artifact"} <= {t.name for t in tools}
            return self

        def invoke(self, messages):
            self.turn += 1
            if self.turn == 1:
                name, args = "write_project_file", {"path": "study.py", "text": "print(x)"}
            elif self.turn == 2:
                self.digest = json.loads(messages[-2].content)["sha256"]
                name, args = "execute_python", {"entry": "study.py"}
            elif self.turn == 3:
                assert json.loads(messages[-2].content)["stdout_stderr_tail"] == "NameError: x"
                name, args = "write_project_file", {"path": "study.py", "text": "x = 2\nprint(x)",
                                                   "expected_sha256": self.digest}
            elif self.turn == 4:
                name, args = "execute_python", {"entry": "study.py"}
            else:
                return AIMessage(content="Test double finished.")
            return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": str(self.turn)}])

    sim = FakeSimulator()
    result = build_agent(Model(), sim, budget=2, workspace=tmp_path).invoke(
        {"messages": [HumanMessage(content="Build a new model")], "used": 0, "calls": 0, "rounds": 0})
    assert launches == ["print(x)", "x = 2\nprint(x)"]
    assert result["used"] == 2 and result["calls"] == 4 and not sim.requests
