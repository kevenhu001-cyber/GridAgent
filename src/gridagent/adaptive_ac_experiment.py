"""Adaptive AC diagnostic runs with frozen policy inputs and replayable selection."""

from pathlib import Path
from uuid import uuid4

from .ac_check import observe
from .ac_diagnostic_experiment import interpret, measure, prepare
from .ac_repair_experience import search_ac_experience
from .adaptive_ac_ir import AdaptiveACExperiment
from .adaptive_ac_policy import POLICY, choose, history_hints
from .dsr import Study
from .engineering_ir import fingerprint
from .native_backends import run_program

PROTOCOL = "adaptive-ac-experiment-v1"


def start_adaptive(root, auth):
    root = Path(root).resolve()
    auth = AdaptiveACExperiment.model_validate(auth)
    cases, metric = prepare(root, auth.experiment)
    hints = []
    if auth.use_history:
        history = search_ac_experience(root, auth.experiment.source_study_id, limit=10)
        hints = history_hints(auth.experiment, history["matches"], metric["solver_version"])
    study = Study(root / "studies")
    plan = {"protocol": PROTOCOL, "policy": POLICY, "spec": auth.canonical(),
            "sha256": auth.sha256(), "source_metric": metric, "history_hints": hints,
            "cases": [job for job, *_ in cases]}
    study.write("manifest", {**plan, "plan_sha256": fingerprint(plan)})
    return study.id


def progress(spec, metric, rows, budget, pool_size):
    if not rows:
        return None, False, []
    reproduced, updates = interpret(spec, metric, rows)
    updates = [{**update, "index": row["index"]} for row, update in zip(rows[1:], updates, strict=True)]
    if not reproduced:
        stop = "baseline_not_reproduced"
    elif any(update["status"] == "target_resolved_in_counterfactual"
             and update["all_snapshot_checks_passed"] for update in updates):
        stop = "verified_single_snapshot_candidate"
    elif len(rows) == pool_size:
        stop = "pool_exhausted"
    elif len(rows) == budget:
        stop = "budget_exhausted"
    else:
        stop = None
    return stop, reproduced, updates


def resume_adaptive(root, identifier, *, solver=run_program):
    root = Path(root).resolve()
    study = Study.reopen(root / "studies", identifier)
    with study.lock():
        frozen = study.read("manifest")
        auth = AdaptiveACExperiment.model_validate(frozen["spec"])
        plan = {key: value for key, value in frozen.items() if key != "plan_sha256"}
        if (frozen["protocol"] != PROTOCOL or frozen["policy"] != POLICY or frozen["sha256"] != auth.sha256()
                or frozen["plan_sha256"] != fingerprint(plan)):
            raise ValueError("Frozen adaptive authorization or plan changed")
        cases, metric = prepare(root, auth.experiment)
        jobs = [job for job, *_ in cases]
        hints = frozen["history_hints"]
        if frozen["cases"] != jobs or frozen["source_metric"] != metric or (hints and not auth.use_history):
            raise ValueError("Frozen adaptive inputs changed")
        # History is an immutable heuristic snapshot; never re-query a changing index during replay.
        rows, seen = [], set()
        stop, reproduced, updates = progress(auth.experiment, metric, rows, auth.run_budget, len(jobs))
        while stop is None:
            step = len(rows)
            decision = choose(jobs, rows, hints)
            if decision is None:
                raise ValueError("No eligible adaptive probe despite remaining budget")
            job, variant, commitment, case = cases[decision["index"]]
            reservation, output = f"reservation-{step}", f"evaluation-{step}"
            expected = {"step": step, "decision": decision, "job": job,
                        "prior_observations_sha256": fingerprint(rows)}
            fresh = not study.exists(reservation)
            if fresh:
                if study.exists(output) or study.exists("report"):
                    raise ValueError("Adaptive evidence without reservation")
                study.write(reservation, {**expected, "run_id": uuid4().hex})
            reserved = study.read(reservation)
            if {key: reserved.get(key) for key in expected} != expected or reserved["run_id"] in seen:
                raise ValueError("Adaptive reservation or selection changed")
            seen.add(reserved["run_id"])
            if fresh:
                try:
                    solver(root, case[-1], run_id=reserved["run_id"], timeout_s=variant.timeout_s)
                except Exception as exc:  # noqa: BLE001 - preserve charged reservation
                    study.write(f"launch-error-{step}", {"error_type": type(exc).__name__})
            observation = observe(root, variant, commitment, case, {
                "run_id": reserved["run_id"], "request_sha256": job["request_sha256"]})
            row = {**job, "step": step, "decision": decision, "observation": observation,
                   "measurement": measure(auth.experiment, observation, variant.acceptance)}
            if study.exists(f"launch-error-{step}"):
                row["launch_error_type"] = study.read(f"launch-error-{step}")["error_type"]
            if study.exists(output):
                if study.read(output) != row:
                    raise ValueError("Committed adaptive observation changed")
            else:
                study.write(output, row)
            rows.append(row)
            stop, reproduced, updates = progress(auth.experiment, metric, rows, auth.run_budget, len(jobs))
        if any(study.exists(f"{prefix}-{step}") for step in range(len(rows), 10)
               for prefix in ("reservation", "evaluation", "launch-error")):
            raise ValueError("Unexpected evidence after adaptive termination")
        winner = next((update["index"] for update in updates if
                       update["status"] == "target_resolved_in_counterfactual"
                       and update["all_snapshot_checks_passed"]), None)
        report = {"study_id": identifier, "protocol": PROTOCOL, "phase": "adaptive_ac_experiment_finished",
                  "source_study_id": auth.experiment.source_study_id,
                  "source_report_sha256": auth.experiment.source_report_sha256,
                  "authorization_sha256": auth.sha256(), "policy": POLICY,
                  "reserved_solver_runs": len(rows), "max_solver_runs": auth.run_budget,
                  "authorized_pool_size": len(jobs)-1, "source_measurement": metric,
                  "baseline_reproduced": reproduced, "observations": rows, "hypothesis_updates": updates,
                  "untried_candidate_indices": sorted({job["index"] for job in jobs}-{row["index"] for row in rows}),
                  "history_hints": hints, "termination": stop, "verified_candidate_index": winner,
                  "completed": winner is not None, "root_cause_confirmed": False,
                  "original_model_modified": False, "scope": "single_snapshot_candidate_requires_full_scope_repair"}
        if study.exists("report"):
            if study.read("report") != report:
                raise ValueError("Committed adaptive report changed")
        else:
            study.write("report", report)
        return report
