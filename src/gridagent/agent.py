"""LangGraph decision loop with deterministic, sequential tool enforcement."""
import json
import os
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

from .domain import CASES, CaseName, FaultRequest
from .simulator import Simulator

SYSTEM = """You are GridAgent, an offline power-system research assistant.
Use tools for numerical claims. Inspect the case before a new fault study.
Open simulation tools use packaged research systems. Original IEEE39 training memory is a distinct
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


def build_agent(model, simulator: Simulator, budget: int = 3, max_calls: int = 12):
    if not 0 <= budget <= 30 or not 1 <= max_calls <= 60:
        raise ValueError("Invalid budget")

    @tool
    def list_cases() -> dict:
        """List the built-in offline research cases."""
        return {"cases": list(CASES)}

    @tool
    def inspect_case(case: CaseName = "kundur") -> dict:
        """Inspect the packaged case and available bus identifiers."""
        return simulator.run("inspect", {"case": case})

    @tool
    def power_flow(case: CaseName = "kundur") -> dict:
        """Solve the initial power flow and return bus voltage magnitudes."""
        return simulator.run("power_flow", {"case": case})

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

    tools = {t.name: t for t in [list_cases, inspect_case, power_flow, eigenanalysis,
                                  simulate_fault, paper_training_history]}
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
                elif name in {"power_flow", "simulate_fault", "eigenanalysis"} and used >= budget:
                    result = {"status": "denied", "reason": "Simulation budget exhausted"}
                else:
                    if name in {"power_flow", "simulate_fault", "eigenanalysis"}:
                        used += 1  # Charge attempted runs, including failures.
                    try:
                        result = tools[name].invoke(call["args"])
                    except Exception as exc:  # noqa: BLE001 - isolate third-party tool failures
                        result = {"status": "failed", "reason": type(exc).__name__}
            messages.append(ToolMessage(content=json.dumps(result, allow_nan=False),
                                        tool_call_id=call["id"], name=name))
        return {"messages": messages, "used": used, "calls": calls}

    def after_tools(state: State):
        return "stop" if state["calls"] >= max_calls or state["rounds"] >= max_calls else "agent"

    def stop(state: State):
        return {"messages": [AIMessage(content="Tool-call limit reached. Review completed tool results; no further simulation was executed.")]}

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
    yield from graph.stream(state, {"recursion_limit": 2 * max_calls + 5}, stream_mode="updates")
