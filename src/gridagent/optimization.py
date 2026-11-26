"""Budgeted numerical comparison on the open DMQ surrogate, not WECC tuning."""
import math
from pathlib import Path

import numpy as np
from scipy.optimize import minimize

from .dmq import Gains, initial_gains
from .dmq_model import run_suite
from .dsr import Study, digest

KEYS = ("kqp", "kqi", "kvp", "kvi")


def quality(tests):
    """Prefer feasible test suites; within each tier minimize normalized errors."""
    failed = sum(not row["passed"] for row in tests)
    errors = []
    for row in tests:
        peak = row.get("peak_deviation_pu")
        tail = row.get("tail_error_pu")
        if peak is None or tail is None or not math.isfinite(peak) or not math.isfinite(tail):
            errors.append(100.0)
        else:
            errors.append(min(100.0, max(peak / 0.3, tail / 0.025)))
    return failed * 101.0 + float(np.mean(errors))


def optimize_updates(root: Path, budget: int = 24):
    if not 2 <= budget <= 60:
        raise ValueError("Optimization budget must be 2..60 objective evaluations")
    study = Study(root)
    config = {"objective_budget": budget, "optimizer": "scipy-powell-log-gains",
              "bounds": [0.05, 100], "seed": [1, 0.5, 1, 0.5]}
    with study.lock():
        study.write("manifest", {"protocol": "open-qv-optimization-v1", "manifest": config,
                                 "manifest_sha256": digest(config)})
        yield "study", {"id": study.id}
        initial = initial_gains().model_dump()
        baseline = run_suite(initial, study.path / "baseline")
        study.write("baseline", {"gains": initial, "tests": baseline})
        evaluations = []
        best = None

        def objective(log_gains):
            nonlocal best
            if len(evaluations) >= budget:
                return best["objective"]
            gains = Gains.model_validate(dict(zip(KEYS, np.clip(np.exp(log_gains), 0.05, 100)))).model_dump()
            index = len(evaluations) + 1
            study.write(f"reservation-{index}", {"gains": gains})
            tests = run_suite(gains, None)
            result = {"gains": gains, "objective": quality(tests),
                      "tests_passed": sum(t["passed"] for t in tests), "tests": tests}
            study.write(f"evaluation-{index}", result)
            evaluations.append(result)
            if best is None or result["objective"] < best["objective"]:
                best = result
            return result["objective"]

        result = minimize(objective, np.log(config["seed"]), method="Powell",
                          bounds=[(math.log(0.05), math.log(100))] * 4,
                          options={"maxfev": budget})
        if best is None:
            raise RuntimeError("Optimizer returned without a numerical evaluation")
        final = run_suite(best["gains"], study.path / "verification")
        report = {"study_id": study.id, "protocol": "open-qv-optimization-v1",
                  "completed": True, "initial_gains": initial, "final_gains": best["gains"],
                  "baseline_passed": sum(t["passed"] for t in baseline),
                  "tests_passed": sum(t["passed"] for t in final), "tests_total": len(final),
                  "objective_evaluations": len(evaluations), "objective_budget": budget,
                  "total_suites": len(evaluations) + 2, "objective": quality(final),
                  "optimizer_converged": bool(result.success), "tests": final,
                  "original_paper_reproduction": False}
        study.write("report", report)
        yield "report", report


def format_update(node, value):
    if node == "study":
        return f"Numerical gain optimization · {value['id']}"
    return (f"Verified {value['tests_passed']}/{value['tests_total']} tests · "
            f"{value['objective_evaluations']}/{value['objective_budget']} objective evaluations · "
            f"{value['total_suites']} total numerical suites")
