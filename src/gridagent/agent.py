"""LangGraph decision loop with deterministic, sequential tool enforcement."""
import json
import os
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import Field, ValidationError

from .domain import CASES, CaseName, FaultRequest, ScenarioRequest
from .simulator import Simulator

SYSTEM = """You are GridAgent, an offline power-system research assistant.
Use tools for numerical claims. Inspect the case before a new fault study.
Use registered model IDs, never arbitrary paths. Open IEEE39 is distinct from the paper project.
For multi-step research, use research_plan to record a short user-visible plan, then adapt using tool feedback.
Inspect topology and available buses, run baseline and targeted cases, compare matching model fingerprints,
and verify conclusions with stored numerical evidence. Do not use tools for purely conceptual questions.
If a tool fails, diagnose the reported reason and change the approach within budget, not invent results.
Open simulation tools use packaged or explicitly registered research systems. Original IEEE39 training memory is a distinct
historical data source, never a new simulation. Licensed paper studies require explicit user invocation.
Never claim solver failure proves
physical instability. Voltage severity is a proxy, not the paper's full stability
criterion. Distinguish estimated, measured and unavailable data. Cite run IDs.
Respect the remaining simulation budget. Explain conclusions and limitations.
Never request secrets, access arbitrary files, or perform live grid control."""


class State(TypedDict):
    messages: Annotated[list, add_messages]
    used: int
    calls: int
    rounds: int


def model_from_env():
    name = os.getenv("GRIDAGENT_MODEL")
    key = os.getenv("GRIDAGENT_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not name or not key:
        raise ValueError("Set GRIDAGENT_MODEL and GRIDAGENT_API_KEY before starting.")
    return ChatOpenAI(model=name, api_key=key,
                      base_url=os.getenv("GRIDAGENT_BASE_URL") or None,
                      timeout=60, max_retries=1)


def build_agent(model, simulator: Simulator, budget: int = 3, max_calls: int = 12, workspace=None):
    if not 0 <= budget <= 30 or not 1 <= max_calls <= 60:
        raise ValueError("Invalid budget")

    @tool
    def list_cases() -> dict:
        """List built-in offline cases and user-registered immutable model IDs."""
        from .models import list_models

        return {"cases": list(CASES), "models": list_models(Path(workspace)) if workspace is not None else []}

    @tool
    def inspect_case(case: CaseName = "kundur") -> dict:
        """Inspect the packaged case and available bus identifiers."""
        return simulator.run("inspect", {"case": case})

    @tool
    def power_flow(case: CaseName = "kundur") -> dict:
        """Solve the initial power flow and return bus voltage magnitudes."""
        return simulator.run("power_flow", {"case": case})

    @tool(args_schema=ScenarioRequest)
    def scenario_power_flow(case: CaseName = "kundur", load_scale: float = 1.0,
                            outage_branch: str | None = None) -> dict:
        """Run a fresh steady-state scenario: scale active PQ loads 0.5..1.5 and optionally remove one line.
        Inspect the case first. Does not alter source models or prove transient/thermal security.
        """
        return simulator.run("scenario_flow", {"case": case, "load_scale": load_scale,
                                               "outage_branch": outage_branch})

    @tool
    def eigenanalysis(case: CaseName = "kundur") -> dict:
        """Compute small-signal eigenvalues, modal frequency and damping; not transient stability."""
        return simulator.run("eigen", {"case": case})

    @tool(args_schema=FaultRequest)
    def simulate_fault(bus: int, duration_s: float, case: CaseName = "kundur", end_s: float = 5.0) -> dict:
        """Run a three-phase bus fault on a research case; return post-fault metrics and waveform."""
        return simulator.run("fault", {"case": case, "bus": bus,
                                      "duration_s": duration_s, "end_s": end_s})

    @tool
    def paper_training_history(location: str) -> dict:
        """Retrieve author-published IEEE39 training KPIs for Bus NN or Line NN - NN; not test labels."""
        from .paper import PIN, training_history

        return {"source": "PowerAgentBench training memory", "commit": PIN,
                "location": location, "historical": training_history(location)}

    @tool
    def research_plan(objective: Annotated[str, Field(min_length=1, max_length=500)],
                      steps: Annotated[list[str], Field(min_length=1, max_length=8)],
                      verification: Annotated[str, Field(min_length=1, max_length=500)]) -> dict:
        """Record a concise user-facing engineering plan or update it; does not execute simulations."""
        if any(not step.strip() or len(step) > 300 for step in steps):
            raise ValueError("Plan steps must be short and nonempty")
        return {"status": "ok", "objective": objective, "steps": steps, "verification": verification}

    tool_list = [list_cases, inspect_case, power_flow, scenario_power_flow, eigenanalysis, simulate_fault,
                 paper_training_history, research_plan]
    if workspace is not None:
        from .research_tools import (analyze_voltage, compare_faults, compare_power_flows,
                                     recent_runs, run_record, topology_path)

        root = Path(workspace)

        @tool
        def list_research_runs(limit: Annotated[int, Field(ge=1, le=30)] = 12) -> dict:
            """Find existing numerical runs before repeating simulations."""
            return {"runs": recent_runs(root, limit)}

        @tool
        def read_research_run(run_id: str) -> dict:
            """Read numerical evidence from a stored run ID, not a file path."""
            return run_record(root, run_id)

        @tool
        def network_path(run_id: str, origin: str, destination: str) -> dict:
            """Compute shortest in-service branch-hop path from an inspect_case run. Not impedance distance."""
            return topology_path(root, run_id, origin, destination)

        @tool
        def analyze_voltage_waveform(run_id: str, channel: str, start_s: float | None = None) -> dict:
            """Analyze measured voltage extrema, times and RMS deviation; defaults to post-clearing."""
            return analyze_voltage(root, run_id, channel, start_s)

        @tool
        def compare_fault_runs(baseline_id: str, candidate_id: str) -> dict:
            """Compare completed fault simulations with identical model hashes and end times."""
            return compare_faults(root, baseline_id, candidate_id)

        @tool
        def compare_flow_runs(baseline_id: str, candidate_id: str) -> dict:
            """Compare steady-state bus voltages for matching model snapshots."""
            return compare_power_flows(root, baseline_id, candidate_id)

        tool_list.extend([list_research_runs, read_research_run, network_path,
                          analyze_voltage_waveform, compare_fault_runs, compare_flow_runs])
    tools = {t.name: t for t in tool_list}
    numerical_tools = {"power_flow", "simulate_fault", "eigenanalysis", "scenario_power_flow"}
    bound = model.bind_tools(list(tools.values()))

    def decide(state: State):
        policy = f"Remaining numerical simulation budget: {budget - state['used']}; "                  f"remaining tool calls: {max_calls - state['calls']}."
        msg = bound.invoke([SystemMessage(content=SYSTEM + "\n" + policy), *state["messages"]])
        return {"messages": [msg], "rounds": state["rounds"] + 1}

    def route(state: State):
        last = state["messages"][-1]
        return "tools" if getattr(last, "tool_calls", []) else END

    def execute(state: State):
        used, calls = state["used"], state["calls"]
        messages = []
        for call in state["messages"][-1].tool_calls:
            name = call["name"]
            if calls >= max_calls:
                result = {"status": "denied", "reason": "Tool-call budget exhausted"}
            else:
                calls += 1
                if name not in tools:
                    result = {"status": "denied", "reason": "Unknown tool"}
                elif name in numerical_tools and used >= budget:
                    result = {"status": "denied", "reason": "Simulation budget exhausted"}
                else:
                    if name in numerical_tools:
                        used += 1  # Charge attempted runs, including failures.
                    try:
                        result = tools[name].invoke(call["args"])
                        # Serialization failures become a normal tool result rather than a crashed graph.
                        json.dumps(result, allow_nan=False)
                    except ValidationError as exc:
                        result = {"status": "failed", "reason": "Invalid tool parameters",
                                  "fields": [".".join(map(str, e["loc"])) for e in exc.errors()]}
                    except Exception as exc:  # noqa: BLE001 - isolate third-party tool failures
                        result = {"status": "failed", "reason": type(exc).__name__}
            messages.append(ToolMessage(content=json.dumps(result, allow_nan=False),
                                        tool_call_id=call["id"], name=name))
        return {"messages": messages, "used": used, "calls": calls}

    def after_tools(state: State):
        return "stop" if state["calls"] >= max_calls or state["rounds"] >= max_calls else "agent"

    def stop(state: State):
        # One final synthesis call without bound tools; it cannot spend more solver budget.
        msg = model.invoke([SystemMessage(content=SYSTEM +
                            "\nTool-call limit reached. Summarize available evidence, failures and remaining "
                            "uncertainty. Do not call tools or claim unfinished work is complete."),
                            *state["messages"]])
        if getattr(msg, "tool_calls", []):
            msg = AIMessage(content="Tool-call limit reached; no further simulation executed. Review saved results.")
        return {"messages": [msg]}

    graph = StateGraph(State)
    graph.add_node("agent", decide)
    graph.add_node("tools", execute)
    graph.add_node("stop", stop)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_conditional_edges("tools", after_tools, {"agent": "agent", "stop": "stop"})
    graph.add_edge("stop", END)
    return graph.compile()


def stream_task(graph, prompt: str, history=None, max_calls: int = 12):
    state = {"messages": [*(history or []), HumanMessage(content=prompt)],
             "used": 0, "calls": 0, "rounds": 0}
    yield from graph.stream(state, {"recursion_limit": max(2 * max_calls + 5, 125)}, stream_mode="updates")
