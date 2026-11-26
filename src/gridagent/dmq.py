"""Constrained dynamic model quality review, independent open surrogate protocol."""
import json
from pathlib import Path
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .dmq_model import TEST_NAMES, run_suite
from .dsr import Study, digest

Gain = Annotated[float, Field(ge=0.05, le=100, allow_inf_nan=False)]


class Gains(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    kqp: Gain = 10
    kqi: Gain = 50
    kvp: Gain = 10
    kvi: Gain = 50


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    initial: Gains = Field(default_factory=Gains)
    max_iterations: int = Field(default=5, ge=1, le=5)


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gains: Gains
    rationale: str = Field(min_length=1, max_length=1500)


class State(TypedDict, total=False):
    current: dict
    results: list
    attempts: int
    accepted: int
    feedback: list
    report: dict


def build_dmq(manifest: Manifest, propose, study: Study, suite=run_suite):
    """One baseline, then at most five proposals; each accepted edit is independently tested."""
    config = manifest.model_dump(mode="json")
    study.write("manifest", {"protocol": "open-qv-surrogate-v1", "manifest": config,
                             "manifest_sha256": digest(config),
                             "locked": {"suite": list(TEST_NAMES), "plant": "open-qv-surrogate-v1"}})

    def evaluate(gains, tag):
        results = suite(gains, study.path / tag)
        if len(results) != len(TEST_NAMES) or {item["name"] for item in results} != set(TEST_NAMES):
            raise ValueError("Suite must return exactly the eight fixed test identities")
        if any(type(item["passed"]) is not bool for item in results):
            raise ValueError("Test verdict must be a boolean")
        study.write(tag, {"gains": gains, "tests": results})
        return results

    def baseline(_state):
        gains = manifest.initial.model_dump()
        results = evaluate(gains, "baseline")
        return {"current": gains, "results": results, "attempts": 0, "accepted": 0, "feedback": []}

    def step(state):
        n = state["attempts"] + 1
        if n > manifest.max_iterations:
            raise RuntimeError("Iteration budget exhausted")
        study.write(f"reservation-{n}", {"attempt": n, "current": state["current"]})
        observation = {"gains": state["current"], "tests": state["results"],
                       "prior_feedback": state["feedback"], "remaining": manifest.max_iterations - n + 1}
        try:
            raw = propose(observation)
            proposal = Proposal.model_validate(raw)
        except (ValidationError, ValueError, TypeError) as exc:
            rejection = {"attempt": n, "status": "denied", "reason": type(exc).__name__}
            study.write(f"proposal-{n}", rejection)
            return {"attempts": n, "feedback": [*state["feedback"], rejection]}
        gains = proposal.gains.model_dump()
        if gains == state["current"]:
            rejection = {"attempt": n, "status": "denied", "reason": "No parameter change"}
            study.write(f"proposal-{n}", rejection)
            return {"attempts": n, "feedback": [*state["feedback"], rejection]}
        audit = {"attempt": n, "status": "accepted", "before": state["current"],
                 "after": gains, "rationale": proposal.rationale}
        study.write(f"proposal-{n}", audit)
        results = evaluate(gains, f"iteration-{n}")
        return {"current": gains, "results": results, "attempts": n,
                "accepted": state["accepted"] + 1, "feedback": [*state["feedback"], audit]}

    def route(state):
        passed = all(item["passed"] for item in state["results"])
        return "report" if passed or state["attempts"] >= manifest.max_iterations else "repair"

    def report(state):
        count = sum(item["passed"] for item in state["results"])
        value = {"study_id": study.id, "protocol": "open-qv-surrogate-v1",
                 "completed": True, "passed": count == len(TEST_NAMES),
                 "tests_passed": count, "tests_total": len(TEST_NAMES),
                 "attempts": state["attempts"], "accepted_edits": state["accepted"],
                 "initial_gains": manifest.initial.model_dump(), "final_gains": state["current"],
                 "tests": state["results"], "original_paper_reproduction": False}
        study.write("report", value)
        return {"report": value}

    graph = StateGraph(State)
    graph.add_node("baseline", baseline)
    graph.add_node("repair", step)
    graph.add_node("report", report)
    graph.add_edge(START, "baseline")
    graph.add_conditional_edges("baseline", route, {"report": "report", "repair": "repair"})
    graph.add_conditional_edges("repair", route, {"report": "report", "repair": "repair"})
    graph.add_edge("report", END)
    return graph.compile()


def llm_proposer(model):
    structured = model.with_structured_output(Proposal, method="function_calling")
    def propose(observation):
        return structured.invoke([
            SystemMessage(content="Diagnose the independent open Q/V PI-control model using the eight "
                          "numerical tests. Only propose the four gains kqp,kqi,kvp,kvi in [0.05,100]. "
                          "The plant is a second-order lag with PI feedback; excessive integral gain may "
                          "destabilize the loop. Use measured errors and prior attempts. Explain the change. "
                          "Do not claim this is WECC or DMView or change locked settings."),
            HumanMessage(content=json.dumps(observation, allow_nan=False)),
        ])
    return propose


def study_updates(workspace, model, manifest=None):
    study = Study(Path(workspace) / "studies")
    graph = build_dmq(manifest or Manifest(), llm_proposer(model), study)
    yield "study", {"id": study.id}
    for event in graph.stream({}, stream_mode="updates"):
        yield from event.items()


def format_update(node, value):
    if node == "study":
        return f"DMQ study {value['id']} · open Q/V surrogate"
    if node == "baseline":
        return f"Baseline · {sum(t['passed'] for t in value['results'])}/8 tests passed"
    if node == "repair":
        if "results" not in value:
            return f"Attempt {value['attempts']} · rejected by parameter guard"
        return f"Attempt {value['attempts']} · {sum(t['passed'] for t in value['results'])}/8 tests passed"
    if node == "report":
        r = value["report"]
        lines = [f"DMQ · {r['tests_passed']}/8 passed · {r['accepted_edits']} applied edits"]
        lines.extend(f"{key}: {r['initial_gains'][key]:g} → {val:g}" for key, val in r["final_gains"].items())
        lines.append("Independent numerical surrogate; not the original DMView suite.")
        return "\n".join(lines)
    return node
