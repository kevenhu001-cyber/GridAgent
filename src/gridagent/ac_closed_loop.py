"""Bounded autonomous AC study: compile, diagnose, repair and independently verify.

Only a reviewed finite candidate pool may be executed. No LLM or live-grid
mutation is required. The parent journal delegates numerical work to IR tasks.
"""

import math
import re
from functools import partial
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from .diagnosis_rules import RULES, VERSION, rule_for
from .dsr import Study
from .engineering_compiler import compile_study
from .engineering_ir import fingerprint
from .engineering_optimization import observe
from .evidence import verify_record
from .execution_plan import ac_plan
from .native_backends import run_program
from .optimization_ir import ACOptimizationSpec
from .research import ResearchTasks, evaluate_candidate, recover_run
from .task_contracts import Contract

PROTOCOL = "ac-closed-loop-v1"
POLICY = "voltage-direction-first-v1"
TERMINAL = {"passed", "failed", "cancelled"}


class ClosedLoopSpec(Contract):
    schema_version: Literal[1] = 1
    optimization: ACOptimizationSpec
    candidates: tuple[tuple[float, ...], ...] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def authorize(self):
        opt = self.optimization
        if len(set(self.candidates)) != len(self.candidates) or opt.baseline() in self.candidates:
            raise ValueError("Candidate pool must be unique and exclude the baseline")
        for values in self.candidates:
            opt.candidate(values)
        return self

    def pool(self):
        return (self.optimization.baseline(), *self.candidates)


def start_loop(root, spec):
    spec = ClosedLoopSpec.model_validate(spec)
    # Compile the whole approved pool before allocating solver resources.
    for values in spec.pool():
        compile_study(spec.optimization.candidate(values))
    body = spec.model_dump(mode="json")
    study = Study(Path(root) / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "policy": POLICY, "spec": body,
                             "sha256": fingerprint(body)})
    return study.id


def diagnosis(checks):
    findings = []
    for row in checks:
        if row["passed"]:
            continue
        rule = RULES[rule_for("ac_native", row["id"])]
        findings.append({"scenario": row["scenario"], "check_id": row["id"],
                         "observed": row.get("observed"), "criterion": row.get("criterion"),
                         "symptom": rule.symptom, "hypotheses": list(rule.hypotheses),
                         "discriminating_tests": list(rule.discriminate)})
    return findings


def next_index(spec, observations):
    """Use only revealed evidence; prioritize a directional voltage probe."""
    if not observations:
        return 0
    last = observations[-1]
    if last["status"] != "physical_violation":
        return None
    available = [i for i in range(1, len(spec.pool()))
                 if i not in {row["candidate_index"] for row in observations}]
    low = high = False
    for row in last["findings"]:
        if row["check_id"] == "voltage_operating_range" and row["observed"] is not None:
            low |= row["observed"][0] < row["criterion"][0]
            high |= row["observed"][1] > row["criterion"][1]
    current = spec.pool()[last["candidate_index"]]
    direction = 1 if low and not high else -1 if high and not low else 0

    def rank(index):
        values = spec.pool()[index]
        aligned = sum(direction * (value - before) > 0
                      for variable, value, before in zip(spec.optimization.variables, values, current, strict=True)
                      if variable.parameter == "voltage_pu")
        distance = 0.0
        for variable, value, before in zip(spec.optimization.variables, values, current, strict=True):
            span = (variable.maximum-variable.minimum if variable.kind == "continuous"
                    else variable.choices[-1]-variable.choices[0])
            distance += abs(value-before)/span
        return (-aligned, distance, index)

    return min(available, key=rank, default=None)


def observe_child(root, tasks, child_id, spec, index):
    opt = spec.optimization
    source = opt.candidate(spec.pool()[index])
    compiled = compile_study(source)
    plan = ac_plan(compiled.manifest, compiled.provenance)
    task = tasks.summary(child_id, full=True)
    state = task["record"]
    if (state.get("engineering_ir") != compiled.provenance
            or state.get("manifest") != compiled.manifest.model_dump(mode="json")
            or state.get("execution_plan_sha256") != plan.sha256()):
        raise ValueError("Closed-loop child does not match frozen candidate")
    if task["stage"] not in TERMINAL:
        raise ValueError("Closed-loop child is not settled")
    runs = task["best_runs"]
    row = {"candidate_index": index, "values": list(spec.pool()[index]), "child_id": child_id,
           "run_ids": [r["run_id"] for r in runs], "status": "unavailable",
           "findings": [], "objective": None, "evidence_sha256": [], "solver_version": None}
    if [r["scenario"] for r in runs] != [s.name for s in compiled.manifest.scenarios]:
        return row
    checks, versions, statuses = [], set(), set()
    program = compiled.manifest.program.model_dump(mode="json")
    for scenario, run in zip(compiled.manifest.scenarios, runs, strict=True):
        request = scenario.materialize(program)
        evidence = verify_record(root, run["evidence_record"], plan, scenario.name,
                                 run["run_id"], request, run["evaluation"])
        row["evidence_sha256"].append(evidence.sha256())
        native = recover_run(root, run)
        if evidence.status == "unavailable":
            return row
        if native.get("cache_origin_run_id") is not None or native.get("version") != evidence.solver_version:
            raise ValueError("Closed-loop requires fresh, version-matched native evidence")
        verdict = evaluate_candidate(root, native, request, compiled.manifest, program)
        if fingerprint(verdict) != evidence.verdict_sha256:
            raise ValueError("Closed-loop independent evaluator differs from recorded evidence")
        versions.add(evidence.solver_version)
        statuses.add(verdict["category"])
        checks.extend({**check, "scenario": scenario.name} for check in verdict["checks"])
    if len(versions) != 1:
        raise ValueError("Mixed solver versions in closed-loop child")
    row["solver_version"] = versions.pop()
    row["findings"] = diagnosis(checks)
    if task["stage"] == "passed" and statuses == {"passed"}:
        verified = observe(root, tasks, child_id, source, opt.objective)
        if verified["status"] != "feasible":
            raise ValueError("Candidate lacks independent verification")
        row.update(status="feasible", objective=verified["objective"])
    elif task["stage"] == "failed" and statuses <= {"passed", "physical_limit"} and "physical_limit" in statuses:
        # Never use model-integrity or numerical failures as proof of a physical violation.
        row["status"] = "physical_violation"
    return row


def resume_loop(root, identifier, *, solver=run_program):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    # A distinct wrapper disables cross-task cache for all runs, including verification.
    native = partial(solver)
    with study.lock():
        frozen = study.read("manifest")
        spec = ClosedLoopSpec.model_validate(frozen["spec"])
        if (frozen["protocol"] != PROTOCOL or frozen["policy"] != POLICY
                or frozen["sha256"] != fingerprint(spec.model_dump(mode="json"))):
            raise ValueError("Closed-loop authorization changed")
        count = len(spec.optimization.source.study.scenarios)
        capacity = spec.optimization.max_solver_runs // count
        indices = set()
        for path in study.path.glob("reservation-*.json"):
            match = re.fullmatch(r"reservation-([0-9]+)\.json", path.name)
            if not match or str(int(match[1])) != match[1]:
                raise ValueError("Invalid closed-loop reservation filename")
            indices.add(int(match[1]))
        if indices != set(range(len(indices))) or len(indices) > capacity:
            raise ValueError("Invalid closed-loop reservation history")
        for prefix in ("child", "observation"):
            for path in study.path.glob(prefix + "-*.json"):
                match = re.fullmatch(prefix + r"-([0-9]+)\.json", path.name)
                if not match or int(match[1]) not in indices or str(int(match[1])) != match[1]:
                    raise ValueError("Closed-loop evidence without reservation")
        tasks = ResearchTasks(root)
        observations, final = [], None
        used_runs = set()
        version = None
        for step in range(capacity):
            winner = next((row for row in observations if row["status"] == "feasible"), None)
            phase = "verify" if winner else "search"
            index = winner["candidate_index"] if winner else next_index(spec, observations)
            if final is not None or index is None or (not winner and step == capacity-1):
                if any(i >= step for i in indices):
                    raise ValueError("Unexpected reservation after closed-loop stopping condition")
                break
            expected = {"phase": phase, "candidate_index": index,
                        "model_sha256": spec.optimization.candidate(spec.pool()[index]).model.sha256()}
            rkey, ckey, okey = (f"reservation-{step}", f"child-{step}", f"observation-{step}")
            if step in indices:
                if study.read(rkey) != expected:
                    raise ValueError("Reservation differs from closed-loop policy")
            else:
                if study.exists("report"):
                    raise ValueError("Completed closed-loop report lacks required reservation")
                study.write(rkey, expected)
                child = tasks.start_ir(spec.optimization.candidate(spec.pool()[index]))
                study.write(ckey, {"child_id": child})
            if not study.exists(ckey):
                row = {"candidate_index": index, "values": list(spec.pool()[index]), "child_id": None,
                       "run_ids": [], "status": "unavailable", "objective": None, "findings": [],
                       "evidence_sha256": [], "solver_version": None}
            else:
                child = study.read(ckey)["child_id"]
                if tasks.summary(child)["stage"] not in TERMINAL:
                    if study.exists("report") or study.exists(okey):
                        raise ValueError("Committed observation has an unfinished child")
                    # Child validates its own durable reservations before resuming.
                    list(tasks.resume(child, solver=native))
                row = observe_child(root, tasks, child, spec, index)
            if used_runs.intersection(row["run_ids"]) or len(set(row["run_ids"])) != len(row["run_ids"]):
                raise ValueError("Repeated numerical run in closed-loop evidence")
            used_runs.update(row["run_ids"])
            if row["solver_version"] is not None:
                if version is not None and row["solver_version"] != version:
                    raise ValueError("Solver version changed between candidates")
                version = row["solver_version"]
            if study.exists(okey):
                if study.read(okey) != row:
                    raise ValueError("Committed closed-loop observation changed")
            elif study.exists("report"):
                raise ValueError("Completed report lacks committed observation")
            else:
                study.write(okey, row)
            if phase == "verify":
                final = row
            else:
                observations.append(row)
        winner = next((row for row in observations if row["status"] == "feasible"), None)
        verified = bool(winner and final and final["status"] == "feasible"
                        and math.isclose(final["objective"], winner["objective"], rel_tol=1e-7, abs_tol=1e-8))
        report = {"protocol": PROTOCOL, "policy": POLICY, "diagnosis_version": VERSION,
                  "study_id": identifier, "completed": verified, "observations": observations,
                  "verification": final, "verified_candidate": winner["candidate_index"] if verified else None,
                  "reserved_solver_runs": (len(observations) + int(final is not None))*count,
                  "budget": spec.optimization.max_solver_runs, "llm_calls": 0,
                  "scope": "first feasible authorized AC point, not global optimality or causal proof"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed closed-loop report changed")
        else:
            study.write("report", report)
        return report
