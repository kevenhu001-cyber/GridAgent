"""Local nonlinear solve, independent primal verification and local derivatives."""

import math
import time
from importlib.metadata import version

import numpy as np
from scipy.optimize import minimize

from .nonlinear_ir import NonlinearProgram

FEAS_TOL = 1e-6


def polynomial_value(expression, values):
    """Evaluate the original term list independently of the compiled solver arrays."""
    return math.fsum(term.coefficient * math.prod(values[p.variable] ** p.exponent for p in term.powers)
                     for term in expression.terms)


def _valid_point(spec, values):
    return (isinstance(values, dict) and set(values) == {v.id for v in spec.variables}
            and all(isinstance(x, (float, int)) and not isinstance(x, bool)
                    and abs(x) <= 1000 + FEAS_TOL and math.isfinite(x) for x in values.values()))


def verify_primal(spec, values, claimed_objective):
    spec = NonlinearProgram.model_validate(spec)
    if not _valid_point(spec, values):
        return {"passed": False, "objective": None, "checks": [], "reason": "invalid_primal"}
    checks = []
    for v in spec.variables:
        residual = max(0.0, v.lower-values[v.id], values[v.id]-v.upper)
        checks.append({"id": "bounds:" + v.id, "passed": residual <= FEAS_TOL, "violation": residual})
    for row in spec.constraints:
        activity = polynomial_value(row, values)
        residual = max(0.0, row.lower-activity if row.lower is not None else 0,
                       activity-row.upper if row.upper is not None else 0)
        checks.append({"id": "row:" + row.id, "passed": residual <= FEAS_TOL,
                       "activity": activity, "violation": residual})
    objective = polynomial_value(spec.objective, values)
    valid = (isinstance(claimed_objective, (float, int)) and not isinstance(claimed_objective, bool)
             and math.isfinite(claimed_objective))
    difference = abs(objective-claimed_objective) if valid else None
    checks.append({"id": "objective", "passed": valid and difference <= 1e-6 + 1e-7*abs(objective),
                   "violation": difference})
    return {"passed": all(row["passed"] for row in checks), "objective": objective, "checks": checks}


class CompiledPolynomial:
    def __init__(self, expression, ids):
        self.coefficients = np.array([term.coefficient for term in expression.terms], dtype=float)
        indices = {name: i for i, name in enumerate(ids)}
        self.powers = np.zeros((len(expression.terms), len(ids)), dtype=int)
        for i, term in enumerate(expression.terms):
            for power in term.powers:
                self.powers[i, indices[power.variable]] = power.exponent

    def value(self, x):
        return float(self.coefficients @ np.prod(np.power(x, self.powers), axis=1))

    def gradient(self, x):
        gradient = np.zeros(len(x))
        for i in range(len(x)):
            mask = self.powers[:, i] > 0
            if np.any(mask):
                powers = self.powers[mask].copy()
                powers[:, i] -= 1
                gradient[i] = np.sum(self.coefficients[mask] * self.powers[mask, i]
                                     * np.prod(np.power(x, powers), axis=1))
        return gradient


class EvaluationLimit(RuntimeError):
    pass


def solve_nonlinear(spec):
    spec = NonlinearProgram.model_validate(spec)
    if spec.analysis is not None:
        from .nonlinear_analysis import solve_advanced

        return solve_advanced(spec)
    return solve_single(spec)


def solve_single(spec, *, shared_deadline=None, callback_limit=None):
    spec = NonlinearProgram.model_validate(spec)
    spec = NonlinearProgram.model_validate(spec.canonical())
    ids = [v.id for v in spec.variables]
    bounds = [(v.lower, v.upper) for v in spec.variables]
    initial = np.array([spec.initial[name] for name in ids])
    objective = CompiledPolynomial(spec.objective, ids)
    sign = 1 if spec.objective.sense == "minimize" else -1
    calls = 0
    deadline = time.monotonic() + spec.time_limit_s
    if shared_deadline is not None:
        deadline = min(deadline, shared_deadline)
    limit = spec.max_evaluations if callback_limit is None else min(spec.max_evaluations, callback_limit)
    best = None

    def charge():
        nonlocal calls
        if calls >= limit or time.monotonic() >= deadline:
            raise EvaluationLimit
        calls += 1

    def fun(x):
        nonlocal best
        charge()
        value = objective.value(x)
        point = dict(zip(ids, map(float, x), strict=True))
        if verify_primal(spec, point, value)["passed"] and (best is None or sign*value < sign*best[0]):
            best = (value, point)
        return sign*value

    def jac(x):
        charge()
        return sign*objective.gradient(x)

    def callbacks(poly, bound, direction):
        def value(x):
            charge()
            return direction*(poly.value(x)-bound)

        def gradient(x):
            charge()
            return direction*poly.gradient(x)

        return value, gradient

    constraints = []
    for row in spec.constraints:
        poly = CompiledPolynomial(row, ids)
        if row.lower == row.upper:
            f, g = callbacks(poly, row.lower, 1)
            constraints.append({"type": "eq", "fun": f, "jac": g})
        else:
            for bound, direction in ((row.lower, 1), (row.upper, -1)):
                if bound is not None:
                    f, g = callbacks(poly, bound, direction)
                    constraints.append({"type": "ineq", "fun": f, "jac": g})
    try:
        raw = minimize(fun, initial, jac=jac, bounds=bounds, constraints=constraints,
                       method="SLSQP", options={"maxiter": spec.max_iterations, "ftol": 1e-9})
        status = "local_convergence_reported" if raw.success else "solver_stopped"
        iterations = int(raw.nit)
        point = dict(zip(ids, map(float, raw.x), strict=True))
        value = objective.value(raw.x)
        if verify_primal(spec, point, value)["passed"] and (best is None or sign*value < sign*best[0]):
            best = (value, point)
    except EvaluationLimit:
        status, iterations = "evaluation_or_time_limit", None
    return {"route": spec.route(), "scipy_version": version("scipy"), "status": status,
            "values": best[1] if best else None, "objective": best[0] if best else None,
            "callback_evaluations": calls, "iterations_reported": iterations}


def sensitivity(spec, values):
    """Local partial derivatives of the objective/rows, not optimal-value sensitivities."""
    spec = NonlinearProgram.model_validate(spec)
    spec = NonlinearProgram.model_validate(spec.canonical())
    if not _valid_point(spec, values):
        raise ValueError("Sensitivity requires a finite point")
    ids = [v.id for v in spec.variables]
    x = np.array([values[name] for name in ids])
    rows = []
    for name, expression in [("objective", spec.objective), *[("row:" + c.id, c) for c in spec.constraints]]:
        analytic = CompiledPolynomial(expression, ids).gradient(x)
        for i, v in enumerate(spec.variables):
            center = values[v.id]
            step = 1e-5*max(1.0, abs(center))
            lo = max(v.lower, center-step)
            hi = min(v.upper, center+step)
            if hi-lo <= 1e-12*max(1.0, abs(center)):
                rows.append({"expression": name, "variable": v.id, "analytic": float(analytic[i]),
                             "finite_difference": None, "absolute_error": None,
                             "method": "insufficient_step", "agreement": False,
                             "unit": expression.unit + "/" + v.unit})
                continue
            low_values, high_values = {**values, v.id: lo}, {**values, v.id: hi}
            numerical = (polynomial_value(expression, high_values)-polynomial_value(expression, low_values))/(hi-lo)
            exact = float(analytic[i])
            error = abs(numerical-exact)
            rows.append({"expression": name, "variable": v.id, "analytic": exact, "finite_difference": numerical,
                         "absolute_error": error, "method": "centered" if lo < center < hi and
                         math.isclose(center-lo, hi-center, rel_tol=1e-6) else "bounded_secant",
                         "agreement": error <= 1e-4 + 1e-3*max(abs(exact), abs(numerical)),
                         "unit": expression.unit + "/" + v.unit})
    objective_rows = [row for row in rows if row["expression"] == "objective"]
    ranges = {v.id: v.upper-v.lower for v in spec.variables}
    ranking = sorted(({"variable": row["variable"],
                       "local_range_scaled_magnitude": abs(row["analytic"])*ranges[row["variable"]]}
                      for row in objective_rows), key=lambda row: (-row["local_range_scaled_magnitude"], row["variable"]))
    return {"kind": "local_partial_derivatives", "rows": rows, "objective_ranking": ranking,
            "all_derivatives_agree": bool(rows) and all(row["agreement"] for row in rows)}


def verify_nonlinear(spec, result):
    spec = NonlinearProgram.model_validate(spec)
    if result.get("route") != spec.route():
        raise ValueError("Solver route does not match nonlinear program")
    if spec.analysis is not None:
        from .nonlinear_analysis import verify_advanced

        return verify_advanced(spec, result)
    primal = verify_primal(spec, result.get("values"), result.get("objective"))
    return {"primal": primal, "lp_certificate": None, "optimality_independently_checked": False,
            "classification": "verified_feasible_candidate" if primal["passed"] else "no_verified_candidate",
            "sensitivity": sensitivity(spec, result["values"]) if primal["passed"] else None}
