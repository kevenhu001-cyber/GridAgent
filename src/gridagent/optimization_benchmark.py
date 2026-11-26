"""Small reproducible optimization acceptance cases with analytic references.

Run python -m gridagent.optimization_benchmark for observed timings.
These synthetic cases test correctness, not large-network scalability.
"""

import argparse
import json
import math
import platform
import time
from importlib.metadata import version

from .commitment_compiler import compile_commitment
from .commitment_ir import UnitCommitment
from .math_program_router import parse_program, solve, verify


def _unit(identifier, cost):
    return {"id": identifier, "minimum_mw": 0, "maximum_mw": 10,
            "marginal_cost_per_mwh": cost, "ramp_up_mw": 8, "ramp_down_mw": 10,
            "startup_limit_mw": 10, "shutdown_limit_mw": 10, "min_up_hours": 1,
            "min_down_hours": 1, "initially_on": True, "initial_mw": 0,
            "initial_state_hours": 2}


def network_example():
    return {"family": "unit_commitment", "description": "Synthetic two-bus benchmark",
            "currency": "CNY", "demand_mw": [6],
            "units": [_unit("cheap", 10), _unit("local", 50)],
            "network": {
                "buses": [{"id": "A", "demand_mw": [0]}, {"id": "B", "demand_mw": [6]}],
                "lines": [{"id": "AB", "from_bus": "A", "to_bus": "B",
                           "susceptance_mw_per_rad": 20, "limit_mw": 4,
                           "max_angle_difference_rad": 0.3}],
                "reference_bus": "A", "angle_bound_rad": 0.5,
                "unit_buses": {"cheap": "A", "local": "B"},
                "reserve_requirement_mw": [1], "reserve_response_minutes": 15,
                "unit_reserve_capability_mw": {"cheap": 0, "local": 4}}}


def cases():
    lp = {"description": "Linear economic dispatch", "variables": [
        {"id": "x", "lower": 0, "upper": 6, "unit": "MW"},
        {"id": "y", "lower": 0, "upper": 10, "unit": "MW"}],
        "constraints": [{"id": "balance", "lower": 10, "upper": 10, "unit": "MW",
                         "terms": [{"variable": "x", "coefficient": 1},
                                   {"variable": "y", "coefficient": 1}]}],
        "objective": {"unit": "CNY/h", "terms": [{"variable": "x", "coefficient": 20},
                                                {"variable": "y", "coefficient": 50}]}}
    nlp = {"family": "polynomial_nlp", "description": "Quadratic economic dispatch",
           "variables": [{"id": "x", "lower": 0, "upper": 3, "unit": "MW"},
                         {"id": "y", "lower": 0, "upper": 3, "unit": "MW"}],
           "initial": {"x": 1, "y": 2},
           "constraints": [{"id": "balance", "lower": 3, "upper": 3, "unit": "MW", "terms": [
               {"coefficient": 1, "powers": [{"variable": "x", "exponent": 1}]},
               {"coefficient": 1, "powers": [{"variable": "y", "exponent": 1}]}]}],
           "objective": {"unit": "CNY/h", "terms": [
               {"coefficient": 1, "powers": [{"variable": "x", "exponent": 2}]},
               {"coefficient": 1, "powers": [{"variable": "y", "exponent": 2}]}]}}
    line = network_example()
    line["network"]["security"] = {"outage_lines": ["AB"]}
    unit = network_example()
    unit["network"]["security"] = {"outage_units": ["cheap"]}
    mixed = network_example()
    mixed["network"]["security"] = {"outage_lines": ["AB"], "outage_units": ["cheap"]}
    return [("lp-dispatch", lp, 320), ("nlp-quadratic", nlp, 4.5),
            ("dc-base", network_example(), 140), ("dc-line-security", line, 220),
            ("dc-unit-security", unit, 220), ("dc-mixed-security", mixed, 220)]


def run_benchmark(repeats=1):
    if type(repeats) is not int or not 1 <= repeats <= 5:
        raise ValueError("Benchmark repeats must be 1..5")
    observations = []
    for name, raw, expected in cases():
        spec = parse_program(raw)
        program = compile_commitment(spec) if isinstance(spec, UnitCommitment) else spec
        for repeat in range(repeats):
            start = time.perf_counter()
            result = solve(spec)
            elapsed = time.perf_counter()-start
            start = time.perf_counter()
            verdict = verify(spec, result)
            verification_time = time.perf_counter()-start
            objective = verdict["primal"]["objective"]
            reference_agrees = objective is not None and math.isclose(objective, expected, abs_tol=1e-5, rel_tol=1e-7)
            observations.append({"case": name, "repeat": repeat+1, "input_sha256": spec.sha256(),
                                 "route": spec.route(), "variables": len(program.variables),
                                 "constraints": len(program.constraints), "status": result["status"],
                                 "objective": objective, "analytic_reference": expected,
                                 "reference_agrees": reference_agrees, "primal_verified": verdict["primal"]["passed"],
                                 "independent_optimality_checked": verdict["optimality_independently_checked"],
                                 "solve_seconds": elapsed, "verify_seconds": verification_time})
    return {"protocol": "synthetic-optimization-benchmark-v1", "python": platform.python_version(),
            "platform": platform.platform(), "machine": platform.machine(), "scipy": version("scipy"),
            "repeats": repeats, "observations": observations,
            "passed": all(row["primal_verified"] and row["reference_agrees"] for row in observations)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=1)
    report = run_benchmark(parser.parse_args().repeats)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
