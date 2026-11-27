"""Bounded multistart, first-order diagnostics and authorized RHS reoptimization."""

import math
import time
from importlib.metadata import version

import numpy as np
from scipy.optimize import lsq_linear

from .nonlinear_ir import NonlinearProgram, analysis_cases
from .nonlinear_solver import polynomial_value, sensitivity, solve_single, verify_primal

ACTIVE_TOL = 1e-5
KKT_TOL = 1e-5


def independent_gradient(expression, values, ids):
    """Differentiate the original monomial records without solver-compiled arrays."""
    return np.array([
        math.fsum(term.coefficient * power.exponent * math.prod(
            values[p.variable] ** (p.exponent - int(p.variable == name)) for p in term.powers)
            for term in expression.terms for power in term.powers if power.variable == name)
        for name in ids
    ], dtype=float)


def kkt_diagnostic(spec, values):
    """Fit multipliers for active constraints; check necessary first-order conditions only."""
    spec = NonlinearProgram.model_validate(spec)
    if not verify_primal(spec, values, polynomial_value(spec.objective, values))["passed"]:
        return {"status": "primal_infeasible", "passed": False}
    ids = [v.id for v in spec.variables]
    sign = 1 if spec.objective.sense == "minimize" else -1
    objective = sign * independent_gradient(spec.objective, values, ids)
    active = []

    def include(name, gradient, slack, equality=False):
        if equality or slack <= ACTIVE_TOL:
            active.append((name, gradient, slack, equality))

    for i, variable in enumerate(spec.variables):
        direction = np.zeros(len(ids))
        direction[i] = 1
        x = values[variable.id]
        include("bound:" + variable.id + ":lower", -direction, x-variable.lower)
        include("bound:" + variable.id + ":upper", direction, variable.upper-x)
    for row in spec.constraints:
        value = polynomial_value(row, values)
        gradient = independent_gradient(row, values, ids)
        if row.lower == row.upper:
            include("row:" + row.id + ":eq", gradient, value-row.lower, True)
        else:
            if row.lower is not None:
                include("row:" + row.id + ":lower", -gradient, value-row.lower)
            if row.upper is not None:
                include("row:" + row.id + ":upper", gradient, row.upper-value)
    if active:
        matrix = np.column_stack([item[1] for item in active])
        lower = np.array([-np.inf if item[3] else 0.0 for item in active])
        fit = lsq_linear(matrix, -objective, bounds=(lower, np.full(len(active), np.inf)),
                         tol=1e-12, max_iter=200)
        multipliers = fit.x
        residual = objective + matrix @ multipliers
        rank = int(np.linalg.matrix_rank(matrix))
    else:
        multipliers = np.array([])
        residual = objective
        rank = 0
    stationarity = float(np.max(np.abs(residual)))
    dual = max((max(0.0, -float(mu)) for item, mu in zip(active, multipliers, strict=True)
                if not item[3]), default=0.0)
    complementarity = max((abs(float(mu)*item[2]) for item, mu in zip(active, multipliers, strict=True)
                           if not item[3]), default=0.0)
    passed = stationarity <= KKT_TOL and dual <= KKT_TOL and complementarity <= KKT_TOL
    return {"status": "first_order_conditions_satisfied" if passed else "first_order_conditions_not_verified",
            "passed": bool(passed), "stationarity_inf": stationarity, "dual_violation": dual,
            "complementarity_inf": complementarity, "active_gradient_rank": rank,
            "active_constraints": len(active), "active_gradients_independent": rank == len(active),
            "multipliers": [{"constraint": item[0], "value": float(mu), "slack": item[2]}
                            for item, mu in zip(active, multipliers, strict=True)],
            "tolerance": KKT_TOL, "global_optimality_proven": False}


def planned_runs(spec):
    """Allocate the entire callback budget deterministically before launching any solve."""
    cases = analysis_cases(spec)
    points = [spec.initial, *spec.analysis.additional_initials]
    count = len(cases)*len(points)
    quota, extra = divmod(spec.max_evaluations, count)
    jobs = []
    for case, perturbation, variant in cases:
        for index, point in enumerate(points, 1):
            budget = quota + int(len(jobs) < extra)
            data = variant.canonical()
            data["initial"] = point
            model = NonlinearProgram.model_validate(data)
            jobs.append(({"case": case, "perturbation": perturbation, "start": index,
                          "initial": point, "program_sha256": model.sha256(),
                          "callback_limit": budget}, model))
    return jobs


def _select(spec, rows):
    sign = 1 if spec.objective.sense == "minimize" else -1
    candidates = [row for row in rows if row["primal"]["passed"]]
    return min(candidates, key=lambda row: (sign*row["primal"]["objective"], row["start"]), default=None)


def solve_advanced(spec):
    spec = NonlinearProgram.model_validate(spec.canonical())
    deadline = time.monotonic() + spec.time_limit_s
    runs = []
    for job, model in planned_runs(spec):
        if time.monotonic() >= deadline:
            result = {"route": model.route(), "status": "not_started_time_limit",
                      "values": None, "objective": None, "callback_evaluations": 0,
                      "iterations_reported": None, "scipy_version": version("scipy")}
        else:
            result = solve_single(model, shared_deadline=deadline, callback_limit=job["callback_limit"])
        runs.append({**job, "result": result})
    candidates = _checked_runs(spec, runs)
    selected = _select(spec, [row for row in candidates if row["case"] == "baseline"])
    return {"route": spec.route(), "scipy_version": version("scipy"),
            "status": "multistart_search_finished" if selected else "no_feasible_baseline",
            "values": selected["result"]["values"] if selected else None,
            "objective": selected["primal"]["objective"] if selected else None,
            "callback_evaluations": sum(row["result"]["callback_evaluations"] for row in runs),
            "analysis_runs": runs}


def _checked_runs(spec, runs):
    expected = planned_runs(spec)
    if not isinstance(runs, list) or len(runs) != len(expected):
        raise ValueError("Advanced result does not cover the frozen solve schedule")
    checked = []
    for row, (job, model) in zip(runs, expected, strict=True):
        if not isinstance(row, dict) or {key: row.get(key) for key in job} != job:
            raise ValueError("Advanced result differs from frozen solve schedule")
        result = row.get("result")
        if not isinstance(result, dict) or result.get("route") != model.route():
            raise ValueError("Invalid nonlinear subsolve result")
        calls = result.get("callback_evaluations")
        if type(calls) is not int or not 0 <= calls <= job["callback_limit"]:
            raise ValueError("Nonlinear subsolve exceeds reserved callback budget")
        primal = verify_primal(model, result.get("values"), result.get("objective"))
        if primal["passed"] and (calls == 0 or not isinstance(result.get("scipy_version"), str)):
            raise ValueError("Unattributed feasible subsolve")
        checked.append({**job, "result": result, "primal": primal})
    versions = {row["result"]["scipy_version"] for row in checked if row["primal"]["passed"]}
    if len(versions) > 1:
        raise ValueError("Mixed solver versions in nonlinear analysis")
    return checked


def verify_advanced(spec, result):
    """Reconstruct every variant, verify every candidate, and recompute the selected result."""
    spec = NonlinearProgram.model_validate(spec.canonical())
    if result.get("status") == "solver_exception" and "analysis_runs" not in result:
        return {"primal": verify_primal(spec, None, None), "lp_certificate": None,
                "optimality_independently_checked": False, "classification": "no_verified_candidate",
                "sensitivity": None, "advanced_analysis": None}
    checked = _checked_runs(spec, result.get("analysis_runs"))
    calls = sum(row["result"]["callback_evaluations"] for row in checked)
    if result.get("callback_evaluations") != calls or calls > spec.max_evaluations:
        raise ValueError("Advanced result callback accounting changed")
    baseline = [row for row in checked if row["case"] == "baseline"]
    winner = _select(spec, baseline)
    expected_values = winner["result"]["values"] if winner else None
    expected_objective = winner["primal"]["objective"] if winner else None
    if result.get("values") != expected_values or result.get("objective") != expected_objective:
        raise ValueError("Advanced selected candidate differs from independently verified winner")
    primal = verify_primal(spec, expected_values, expected_objective)
    diagnostic = kkt_diagnostic(spec, expected_values) if winner else None
    scans = []
    for case, perturbation, model in analysis_cases(spec)[1:]:
        selected = _select(model, [row for row in checked if row["case"] == case])
        objective = selected["primal"]["objective"] if selected else None
        scan_kkt = kkt_diagnostic(model, selected["result"]["values"]) if selected else None
        slope = ((objective-expected_objective)/perturbation["delta"]
                 if winner and selected else None)
        if slope is not None and not math.isfinite(slope):
            slope = None
        scans.append({"case": case, "perturbation": perturbation, "program_sha256": model.sha256(),
                      "status": "verified_feasible_candidate" if selected else "no_verified_candidate",
                      "objective": objective, "values": selected["result"]["values"] if selected else None,
                      "objective_change_per_rhs_unit": slope, "kkt": scan_kkt,
                      "slope_kind": "finite_reoptimization_secant_not_proven_optimal_value_derivative"})
    return {"primal": primal, "lp_certificate": None, "optimality_independently_checked": False,
            "classification": "verified_feasible_candidate" if primal["passed"] else "no_verified_candidate",
            "sensitivity": sensitivity(spec, expected_values) if winner else None,
            "advanced_analysis": {"kkt": diagnostic, "rhs_scan": scans,
                                  "baseline_feasible_starts": sum(row["primal"]["passed"] for row in baseline),
                                  "baseline_selected_start": winner["start"] if winner else None,
                                  "callback_evaluations": calls, "callback_budget": spec.max_evaluations,
                                  "subsolves": len(checked),
                                  "subsolve_verification": [{"case": row["case"], "start": row["start"],
                                                             "primal": row["primal"]} for row in checked]}}
