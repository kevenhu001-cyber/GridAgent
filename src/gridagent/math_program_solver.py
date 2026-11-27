"""Deterministic LP/MILP lowering and solver-independent primal/KKT checks."""

import math
from importlib.metadata import version

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp

from .math_program_ir import MathematicalProgram

FEAS_TOL = 1e-6
OBJECTIVE_TOL = 1e-7
STATUS = {0: "optimal_reported", 1: "limit_reached", 2: "infeasible_reported",
          3: "unbounded_reported", 4: "solver_error"}


def _finite(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)


def _close(a, b):
    return abs(a-b) <= FEAS_TOL + OBJECTIVE_TOL * max(abs(a), abs(b))


def _evaluate(expression, values):
    return math.fsum(term.coefficient * values[term.variable] for term in expression.terms)


def verify_primal(spec, values, claimed_objective):
    """Recompute original equations and integrality, never trust solver feasibility."""
    spec = MathematicalProgram.model_validate(spec)
    if not isinstance(values, dict) or set(values) != {v.id for v in spec.variables} or not all(
            _finite(value) for value in values.values()):
        return {"passed": False, "reason": "invalid_or_missing_primal", "objective": None, "checks": []}
    if any(abs(value) > 1e9 + FEAS_TOL for value in values.values()):
        return {"passed": False, "reason": "primal_outside_supported_numeric_range",
                "objective": None, "checks": []}
    checks = []
    for v in spec.variables:
        x = values[v.id]
        violation = max(0.0, v.lower-x, x-v.upper)
        checks.append({"id": "bounds:" + v.id, "passed": violation <= FEAS_TOL, "violation": violation})
        if v.kind != "continuous":
            violation = abs(x-round(x))
            checks.append({"id": "integer:" + v.id, "passed": violation <= FEAS_TOL, "violation": violation})
    for constraint in spec.constraints:
        value = _evaluate(constraint, values)
        violation = max(0.0, constraint.lower-value if constraint.lower is not None else 0,
                        value-constraint.upper if constraint.upper is not None else 0)
        checks.append({"id": "row:" + constraint.id, "passed": violation <= FEAS_TOL,
                       "activity": value, "violation": violation})
    objective = _evaluate(spec.objective, values) + spec.objective.constant
    valid = _finite(claimed_objective) and _close(objective, claimed_objective)
    checks.append({"id": "objective", "passed": valid,
                   "violation": abs(objective-claimed_objective) if _finite(claimed_objective) else None})
    return {"passed": all(row["passed"] for row in checks), "objective": objective, "checks": checks}


def _lower(spec):
    ids = [v.id for v in spec.variables]
    indices = {name: index for index, name in enumerate(ids)}

    def vector(terms):
        row = np.zeros(len(ids))
        for term in terms:
            row[indices[term.variable]] = term.coefficient
        return row

    sign = 1 if spec.objective.sense == "minimize" else -1
    c = sign * vector(spec.objective.terms)
    matrix = np.array([vector(row.terms) for row in spec.constraints]).reshape(-1, len(ids))
    low = np.array([row.lower if row.lower is not None else -np.inf for row in spec.constraints])
    high = np.array([row.upper if row.upper is not None else np.inf for row in spec.constraints])
    bounds = [(v.lower, v.upper) for v in spec.variables]
    return ids, sign, c, matrix, low, high, bounds


def _lp_rows(spec, matrix, low, high):
    a_ub, b_ub, a_eq, b_eq, inequalities, equalities = [], [], [], [], [], []
    for i, row in enumerate(spec.constraints):
        if low[i] == high[i]:
            a_eq.append(matrix[i])
            b_eq.append(high[i])
            equalities.append(row.id)
        else:
            if row.upper is not None:
                a_ub.append(matrix[i])
                b_ub.append(high[i])
                inequalities.append(row.id + ":upper")
            if row.lower is not None:
                a_ub.append(-matrix[i])
                b_ub.append(-low[i])
                inequalities.append(row.id + ":lower")
    return a_ub, b_ub, a_eq, b_eq, inequalities, equalities


def verify_lp_certificate(spec, values, certificate):
    """Independent dual feasibility and primal/dual gap for the normalized minimization LP."""
    spec = MathematicalProgram.model_validate(spec)
    spec = MathematicalProgram.model_validate(spec.canonical())
    if spec.route() != "scipy-highs-lp" or not isinstance(certificate, dict):
        return {"passed": False, "reason": "missing_lp_certificate"}
    if not isinstance(values, dict) or set(values) != {v.id for v in spec.variables} or not all(
            _finite(value) for value in values.values()):
        return {"passed": False, "reason": "invalid_primal"}
    ids, sign, c, matrix, low, high, bounds = _lower(spec)
    a_ub, b_ub, a_eq, b_eq, inequalities, equalities = _lp_rows(spec, matrix, low, high)
    groups = {"inequality": inequalities, "equality": equalities, "lower": ids, "upper": ids}
    dual = {}
    for group, keys in groups.items():
        row = certificate.get(group)
        if not isinstance(row, dict) or set(row) != set(keys) or not all(
                _finite(x) and abs(x) <= 1e100 for x in row.values()):
            return {"passed": False, "reason": "invalid_dual_dimensions"}
        dual[group] = np.array([row[key] for key in keys], dtype=float)
    u, e, l, h = (dual[group] for group in ("inequality", "equality", "lower", "upper"))
    residual = c - l - h
    if a_ub:
        residual -= np.array(a_ub).T @ u
    if a_eq:
        residual -= np.array(a_eq).T @ e
    sign_violation = max(0.0, max(u, default=0), max(-l, default=0), max(h, default=0))
    stationarity = float(np.max(np.abs(residual)))
    primal = sign * _evaluate(spec.objective, values)
    dual_value = float(np.dot(b_ub, u) + np.dot(b_eq, e)
                       + np.dot([x[0] for x in bounds], l) + np.dot([x[1] for x in bounds], h))
    # Project multiplier signs, then conservatively account for residual stationarity
    # over the explicit finite variable box. A tiny residual alone is not enough
    # when variable bounds are large.
    u_safe, l_safe, h_safe = np.minimum(u, 0), np.maximum(l, 0), np.minimum(h, 0)
    correction = c - l_safe - h_safe
    if a_ub:
        correction -= np.array(a_ub).T @ u_safe
    if a_eq:
        correction -= np.array(a_eq).T @ e
    safe_dual = float(np.dot(b_ub, u_safe) + np.dot(b_eq, e)
                      + np.dot([x[0] for x in bounds], l_safe)
                      + np.dot([x[1] for x in bounds], h_safe))
    safe_dual += math.fsum(min(float(r)*lo, float(r)*hi)
                           for r, (lo, hi) in zip(correction, bounds, strict=True))
    gap = primal-safe_dual
    if not all(math.isfinite(x) for x in (stationarity, sign_violation, dual_value, safe_dual, gap)):
        return {"passed": False, "reason": "nonfinite_dual_arithmetic"}
    primal_ok = verify_primal(spec, values, _evaluate(spec.objective, values)+spec.objective.constant)["passed"]
    passed = (primal_ok and sign_violation <= FEAS_TOL and stationarity <= FEAS_TOL
              and _close(primal, safe_dual))
    return {"passed": bool(passed), "stationarity_residual": stationarity,
            "dual_sign_violation": float(sign_violation), "primal_dual_gap": gap,
            "normalized_dual_objective": dual_value, "normalized_corrected_dual_bound": safe_dual}


def solve_program(spec):
    spec = MathematicalProgram.model_validate(spec)
    spec = MathematicalProgram.model_validate(spec.canonical())
    route = spec.route()
    ids, sign, c, matrix, low, high, bounds = _lower(spec)
    certificate = None
    if route == "scipy-highs-lp":
        a_ub, b_ub, a_eq, b_eq, inequalities, equalities = _lp_rows(spec, matrix, low, high)
        raw = linprog(c, A_ub=a_ub or None, b_ub=b_ub or None, A_eq=a_eq or None, b_eq=b_eq or None,
                      bounds=bounds, method="highs", options={"time_limit": spec.time_limit_s})
        if raw.status == 0:
            certificate = {group: dict(zip(keys, map(float, marginal), strict=True))
                           for group, keys, marginal in (
                               ("inequality", inequalities, raw.ineqlin.marginals),
                               ("equality", equalities, raw.eqlin.marginals),
                               ("lower", ids, raw.lower.marginals), ("upper", ids, raw.upper.marginals))}
    else:
        raw = milp(c, integrality=[int(v.kind != "continuous") for v in spec.variables],
                   bounds=Bounds(*zip(*bounds, strict=True)),
                   constraints=LinearConstraint(matrix, low, high) if len(matrix) else None,
                   options={"time_limit": spec.time_limit_s, "node_limit": spec.node_limit, "mip_rel_gap": 0.0})
    values = dict(zip(ids, map(float, raw.x), strict=True)) if raw.x is not None and np.isfinite(raw.x).all() else None
    objective = sign * float(raw.fun) + spec.objective.constant if _finite(raw.fun) else None
    gap = getattr(raw, "mip_gap", None)
    bound = getattr(raw, "mip_dual_bound", None)
    return {"route": route, "scipy_version": version("scipy"), "status": STATUS.get(raw.status, "solver_error"),
            "values": values, "objective": objective, "lp_certificate": certificate,
            "solver_reported_mip_gap": float(gap) if _finite(gap) else None,
            "solver_reported_bound": sign * float(bound) + spec.objective.constant if _finite(bound) else None}


def verify_result(spec, result):
    spec = MathematicalProgram.model_validate(spec)
    if result.get("route") != spec.route():
        raise ValueError("Solver route does not match mathematical program")
    primal = verify_primal(spec, result.get("values"), result.get("objective"))
    certificate = verify_lp_certificate(spec, result.get("values"), result.get("lp_certificate")) if (
        primal["passed"] and spec.route() == "scipy-highs-lp") else None
    certified = bool(certificate and certificate["passed"])
    return {"primal": primal, "lp_certificate": certificate, "optimality_independently_checked": certified,
            "classification": "lp_optimal_within_tolerance" if certified else (
                "verified_feasible_candidate" if primal["passed"] else "no_verified_candidate")}
