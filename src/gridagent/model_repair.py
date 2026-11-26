"""Explicitly authorized, bounded native benchmark repair loop."""
import copy
import json
from pathlib import Path
from typing import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import Field, TypeAdapter, model_validator

from .dsr import Study, digest
from .native_backends import run_program
from .native_program import PPProgram, Program, Strict

ADAPTER = TypeAdapter(Program)
# A manifest authorizes particular existing numeric leaves, not changes to tests,
# topology, time horizon, demanded energy, or component ratings by default.
ALLOWED = {"vm_pu", "q_mvar", "tap_pos", "value", "p_mw", "p_nom_mw",
           "max_hours", "efficiency_store", "efficiency_dispatch",
           "r_ohm_per_km", "x_ohm_per_km", "c_nf_per_km", "max_i_ka"}
PathKey = Annotated[str, Field(pattern=r"^/(steps|generators|storage|links)/[0-9]+/[a-zA-Z0-9_]+$")]


def leaf(program, path):
    group, index, field = path[1:].split("/")
    item = program[group][int(index)]
    if field not in ALLOWED or field not in item:
        raise ValueError("Unrecognized editable field")
    if group == "steps" and item.get("op") == "edit" and item.get("field") == "in_service":
        raise ValueError("Service-state edits cannot be optimized")
    if group == "steps" and item.get("op") == "create_load":
        raise ValueError("Demand is locked")
    value = item[field]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError("Only existing numerical parameters can be optimized")
    if group == "steps" and item.get("op") == "edit" and item.get("element") == "load":
        raise ValueError("Demand edits are locked")
    return item, field


class Manifest(Strict):
    initial: Program
    editable_paths: list[PathKey] = Field(min_length=1, max_length=30)
    max_repairs: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def check(self):
        if isinstance(self.initial, PPProgram) and (self.initial.parent_run or self.initial.analysis != "power_flow"):
            raise ValueError("Use a self-contained power-flow program")
        if len(set(self.editable_paths)) != len(self.editable_paths):
            raise ValueError("Duplicate editable paths")
        data = self.initial.model_dump(mode="json")
        for path in self.editable_paths:
            try:
                leaf(data, path)
            except (IndexError, KeyError, TypeError) as exc:
                raise ValueError("Editable path does not exist") from exc
        return self


class Change(Strict):
    path: PathKey
    value: float = Field(allow_inf_nan=False, ge=-1e7, le=1e7)


class Proposal(Strict):
    changes: list[Change] = Field(min_length=1, max_length=30)
    rationale: str = Field(min_length=1, max_length=1500)


def apply(current, proposal, permitted):
    data = copy.deepcopy(current)
    paths = [c.path for c in proposal.changes]
    if len(set(paths)) != len(paths) or not set(paths) <= set(permitted):
        raise ValueError("Proposal modifies locked or duplicate fields")
    for change in proposal.changes:
        item, field = leaf(data, change.path)
        item[field] = change.value
    return ADAPTER.validate_python(data).model_dump(mode="json")


def rank(result):
    quality = result.get("quality", {})
    tests = quality.get("tests", [])
    passed = sum(t.get("passed") is True for t in tests)
    return (quality.get("passed") is True, result.get("status") == "ok",
            passed / len(tests) if tests else 0, passed)


def model_proposer(model):
    bound = model.with_structured_output(Proposal, method="function_calling")

    def propose(observation):
        return bound.invoke([
            SystemMessage(content="Repair a research model using the fixed numerical evaluator feedback. "
                          "Only propose listed editable paths. Preserve locked demand, topology and test criteria. "
                          "Do not invent solver results. Explain why the proposed parameter changes are useful."),
            HumanMessage(content=json.dumps(observation, allow_nan=False)),
        ])
    return propose


def repair_updates(root, manifest, propose, solver=run_program):
    manifest = Manifest.model_validate(manifest)
    study = Study(Path(root) / "studies")
    frozen = manifest.model_dump(mode="json")
    with study.lock():
        study.write("manifest", {"protocol": "gridagent-native-repair-v1", "manifest": frozen,
                                 "manifest_sha256": digest(frozen)})
        current = frozen["initial"]
        seen = {digest(current)}
        history = []
        best = None
        attempts = 0
        solver_calls = 0
        for index in range(manifest.max_repairs + 1):
            # Charge every attempted proposal; a rejected proposal never calls the solver.
            study.write(f"reservation-{index}", {"candidate_base": digest(current)})
            if index:
                attempts += 1
                try:
                    observation = {"best_program": current, "editable_paths": manifest.editable_paths,
                                   "best_feedback": best["result"]["quality"], "history": history,
                                   "remaining_repairs": manifest.max_repairs-index+1}
                    proposal = Proposal.model_validate(propose(observation))
                    candidate = apply(current, proposal, manifest.editable_paths)
                    if digest(candidate) in seen:
                        raise ValueError("Repeated candidate")
                except (ValueError, TypeError, KeyError, IndexError) as exc:
                    row = {"iteration": index, "status": "denied", "reason": str(exc)[:300]}
                    study.write(f"iteration-{index}", row)
                    history.append(row)
                    yield row
                    continue
                study.write(f"proposal-{index}", proposal.model_dump(mode="json"))
            else:
                candidate = current
            seen.add(digest(candidate))
            study.write(f"candidate-{index}", candidate)
            solver_calls += 1
            try:
                result = solver(root, candidate)
            except Exception as exc:  # noqa: BLE001 - keep failed reserved runs auditable
                result = {"status": "failed", "reason": type(exc).__name__}
            if not isinstance(result.get("quality"), dict):
                result["quality"] = {"passed": False, "tests": [{"id": "solver_evidence", "passed": False}],
                                     "reason": result.get("reason", "Missing evaluation")}
            row = {"iteration": index, "status": "evaluated", "result": result,
                   "candidate_sha256": digest(candidate)}
            study.write(f"iteration-{index}", row)
            history.append({"iteration": index, "run_id": result.get("run_id"),
                            "quality": result["quality"], "reason": result.get("reason")})
            if best is None or rank(result) > rank(best["result"]):
                best, current = row, candidate
            yield row
            if result["quality"].get("passed") is True:
                break
        passed = bool(best and best["result"]["quality"].get("passed"))
        report = {"study_id": study.id, "protocol": "gridagent-native-repair-v1",
                  "phase": "native_repair_finished", "completed": passed, "passed": passed,
                  "repair_attempts": attempts, "solver_calls": solver_calls,
                  "best_iteration": best["iteration"] if best else None,
                  "best_run_id": best["result"].get("run_id") if best else None,
                  "best_quality": best["result"]["quality"] if best else None,
                  "termination": "passed" if passed else "repair_budget_exhausted"}
        study.write("best-program", current)
        study.write("report", report)
        yield report


def format_update(row):
    if "study_id" in row:
        return (f"Benchmark {row['study_id']} · {row['termination']} · "
                f"best run {row['best_run_id']} · {row['solver_calls']} solver calls")
    if row["status"] == "denied":
        return f"Repair {row['iteration']} · denied · {row['reason']}"
    quality = row["result"]["quality"]
    failed = ", ".join(t["id"] for t in quality["tests"] if not t["passed"])
    return (f"Benchmark iteration {row['iteration']} · "
            f"{sum(t['passed'] for t in quality['tests'])}/{len(quality['tests'])} passed · "
            f"{'failed: '+failed if failed else 'all passed'}")
