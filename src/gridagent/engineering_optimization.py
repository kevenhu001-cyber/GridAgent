"""Durable mixed-coordinate AC optimization using verified child research tasks."""

import math
import re
from functools import partial
from pathlib import Path

from .dsr import Study
from .engineering_compiler import compile_study
from .engineering_ir import fingerprint
from .evidence import verify_record
from .execution_plan import ac_plan
from .model_quality import table
from .native_backends import run_program
from .optimization_ir import ACOptimizationSpec, next_candidate
from .research import ResearchTasks, evaluate_candidate, recover_run
from .workspace import artifact_folder

PROTOCOL = "ac-mixed-coordinate-v1"


def start_optimization(root, spec):
    spec = ACOptimizationSpec.model_validate(spec)
    study = Study(Path(root) / "studies")
    study.write("manifest", {"protocol": PROTOCOL, "spec": spec.model_dump(mode="json"),
                             "sha256": spec.sha256()})
    return study.id


def observe(root, tasks, child_id, source, objective):
    """Recheck immutable child input, native evidence and objective independently."""
    compiled = compile_study(source)
    plan = ac_plan(compiled.manifest, compiled.provenance)
    task = tasks.summary(child_id, full=True)
    state = task["record"]
    if (state.get("engineering_ir") != compiled.provenance
            or state.get("manifest") != compiled.manifest.model_dump(mode="json")
            or state.get("execution_plan_sha256") != plan.sha256()):
        raise ValueError("Optimization child differs from authorized candidate")
    runs = task["best_runs"]
    result = {"child_id": child_id, "status": "infeasible", "objective": None,
              "run_ids": [row["run_id"] for row in runs], "evidence_sha256": []}
    if task["stage"] not in {"passed", "failed", "cancelled"}:
        raise ValueError("Optimization child is not settled")
    if task["stage"] != "passed":
        return result
    scenarios = compiled.manifest.scenarios
    if [row["scenario"] for row in runs] != [scenario.name for scenario in scenarios]:
        raise ValueError("Optimization child lacks complete scenario evidence")
    scores = []
    versions = set()
    program = compiled.manifest.program.model_dump(mode="json")
    for scenario, row in zip(scenarios, runs, strict=True):
        request = scenario.materialize(program)
        native = recover_run(root, row)
        verdict = evaluate_candidate(root, native, request, compiled.manifest, program)
        evidence = verify_record(root, row["evidence_record"], plan, scenario.name,
                                 row["run_id"], request, row["evaluation"])
        if (not verdict["passed"] or evidence.status != "verified"
                or fingerprint(verdict) != evidence.verdict_sha256
                or native.get("cache_origin_run_id") is not None
                or native.get("version") != evidence.solver_version):
            raise ValueError("Optimization candidate no longer passes fresh evidence checks")
        versions.add(evidence.solver_version)
        result["evidence_sha256"].append(evidence.sha256())
        folder = artifact_folder(root, "runs", row["run_id"])
        if objective == "minimize_worst_voltage_deviation":
            buses = table(folder, "bus")
            active = buses.index[buses.in_service.eq(True)]
            voltage = table(folder, "res_bus").reindex(active).vm_pu
            score = float((voltage - 1).abs().max())
        else:
            score = 0.0
            for name, first, second in (("line", "from", "to"), ("trafo", "hv", "lv")):
                branches = table(folder, "res_" + name)
                devices = table(folder, name)
                active = devices.index[devices.in_service.eq(True)]
                power = branches.reindex(active)[[f"p_{first}_mw", f"p_{second}_mw"]]
                if power.isna().any().any():
                    raise ValueError("Missing branch loss evidence")
                score += float(power.sum().sum())
            if score < -1e-6:
                raise ValueError("Negative passive network losses")
            score = max(score, 0.0)
        if not math.isfinite(score):
            raise ValueError("Non-finite optimization objective")
        scores.append(score)
    if len(versions) != 1:
        raise ValueError("Mixed native solver versions within candidate")
    result.update(status="feasible", objective=max(scores) if objective == "minimize_worst_voltage_deviation"
                  else sum(scores) / len(scores), solver_version=versions.pop(), scenario_objectives=scores)
    return result


def _reserve(study, index, phase, values, source):
    record = {"phase": phase, "values": list(values), "model_sha256": source.model.sha256()}
    study.write(f"reservation-{index}", record)
    return record


def _settle(root, study, tasks, spec, index, reservation, *, fresh, solver):
    source = spec.candidate(reservation["values"])
    if source.model.sha256() != reservation["model_sha256"]:
        raise ValueError("Optimization reservation model changed")
    link = f"child-{index}"
    output = f"evaluation-{index}"
    if fresh:
        # Reserve the full scenario budget before creating the child. A crash between
        # creation and link publication leaves an unknown charged reservation.
        child_id = tasks.start_ir(source)
        study.write(link, {"child_id": child_id})
    if study.exists(link):
        child_id = study.read(link)["child_id"]
        task = tasks.summary(child_id, full=True)
        if task["record"].get("engineering_ir") != compile_study(source).provenance:
            raise ValueError("Linked child does not match candidate")
        if task["stage"] not in {"passed", "failed", "cancelled"}:
            list(tasks.resume(child_id, solver=solver))
        observed = observe(root, tasks, child_id, source, spec.objective)
    else:
        observed = {"child_id": None, "status": "unknown", "objective": None,
                    "run_ids": [], "evidence_sha256": []}
    result = {**reservation, **observed}
    if study.exists(output):
        if study.read(output) != result:
            raise ValueError("Committed optimization observation changed")
    else:
        study.write(output, result)
    return result


def resume_optimization(root, identifier, *, solver=run_program):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    # A wrapper disables AC cross-task cache, including for final verification.
    native = partial(solver)
    with study.lock():
        frozen = study.read("manifest")
        spec = ACOptimizationSpec.model_validate(frozen["spec"])
        if frozen.get("protocol") != PROTOCOL or frozen["sha256"] != spec.sha256():
            raise ValueError("Frozen optimization manifest changed")
        if study.exists("report"):
            yield study.read("report")
            return
        tasks = ResearchTasks(root)
        scenario_count = len(spec.source.study.scenarios)
        capacity = spec.max_solver_runs // scenario_count
        search_capacity = capacity - 1
        reservations = set()
        for path in study.path.glob("reservation-*.json"):
            match = re.fullmatch(r"reservation-([1-9][0-9]*)\.json", path.name)
            if not match:
                raise ValueError("Invalid optimization reservation filename")
            reservations.add(int(match.group(1)))
        if reservations != set(range(1, len(reservations) + 1)) or len(reservations) > capacity:
            raise ValueError("Invalid optimization budget history")
        for prefix in ("child", "evaluation"):
            for path in study.path.glob(prefix + "-*.json"):
                match = re.fullmatch(prefix + r"-([1-9][0-9]*)\.json", path.name)
                if not match or int(match.group(1)) not in reservations:
                    raise ValueError("Optimization evidence without reservation")
        observations = []
        final = None

        def best():
            feasible = [row for row in observations if row["status"] == "feasible"]
            if len({row["solver_version"] for row in feasible}) > 1:
                raise ValueError("Solver version changed between optimization candidates")
            return min(feasible, key=lambda row: (row["objective"], tuple(row["values"])), default=None)

        for index in sorted(reservations):
            reservation = study.read(f"reservation-{index}")
            if final is not None:
                raise ValueError("Reservation after final verification")
            candidate = next_candidate(spec, observations) if len(observations) < search_capacity else None
            if reservation["phase"] == "verify":
                winner = best()
                if winner is None or candidate is not None or reservation["values"] != winner["values"]:
                    raise ValueError("Final verification does not match selected candidate")
                final = _settle(root, study, tasks, spec, index, reservation, fresh=False, solver=native)
            else:
                if reservation["phase"] != "search" or candidate is None or list(candidate) != reservation["values"]:
                    raise ValueError("Reservation differs from deterministic search")
                observations.append(_settle(root, study, tasks, spec, index, reservation, fresh=False, solver=native))
        while final is None and len(observations) < search_capacity:
            values = next_candidate(spec, observations)
            if values is None:
                break
            index = len(observations) + 1
            reservation = _reserve(study, index, "search", values, spec.candidate(values))
            row = _settle(root, study, tasks, spec, index, reservation, fresh=True, solver=native)
            observations.append(row)
            yield {"study_id": identifier, "phase": "search", "observation": row,
                   "reserved_solver_runs": index * scenario_count, "budget": spec.max_solver_runs}
        winner = best()
        if winner is not None and final is None:
            index = len(observations) + 1
            reservation = _reserve(study, index, "verify", winner["values"], spec.candidate(winner["values"]))
            final = _settle(root, study, tasks, spec, index, reservation, fresh=True, solver=native)
        verified = bool(winner and final and final["status"] == "feasible"
                        and winner["solver_version"] == final["solver_version"]
                        and math.isclose(winner["objective"], final["objective"], rel_tol=1e-7, abs_tol=1e-8))
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "optimization_finished",
                  "completed": verified, "termination": "verified_candidate" if verified else (
                      "no_feasible_candidate" if winner is None else "fresh_verification_failed"),
                  "objective": spec.objective, "objective_unit": "p.u." if
                  spec.objective == "minimize_worst_voltage_deviation" else "MW",
                  "baseline": observations[0], "best_observed": winner, "verification": final,
                  "observations": observations, "reserved_solver_runs": (len(observations) + int(final is not None))
                  * scenario_count, "budget": spec.max_solver_runs, "global_optimality_proven": False}
        study.write("report", report)
        yield report
