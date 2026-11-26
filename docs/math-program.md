# Typed LP/MILP mathematical programs

The Phase 5 mathematical programming slice accepts a versioned MathematicalProgram JSON document. Variables have stable IDs, explicit finite bounds and descriptive units. Continuous, integer and binary domains are supported. Linear constraints may have lower/upper/equality bounds; objective supports minimization/maximization and constant offset. Units are recorded, not dimensionally inferred: the author must provide consistent coefficients. No arbitrary expressions or executable Python are accepted.

The deterministic router selects SciPy HiGHS linprog for all-continuous problems and scipy.optimize.milp for integer/binary problems. Uses existing SciPy dependency, up to 200 variables, 500 rows, 120 seconds solver time limit and 100,000 MILP nodes. Time and node limits are solver options, not hard OS isolation. Integer/binary domains are verified independently. A feasible candidate is not necessarily optimal.

The independent verifier recomputes original bounds, integer residuals, all constraint activities and the objective from the returned primal. For LP it additionally checks the normalized dual multiplier signs, stationarity and primal-dual gap; a residual correction over finite bounds makes the approximate dual bound more conservative. This is a floating-point tolerance check, not an exact rational proof. MILP solver-reported bound, gap and termination are recorded separately; no independent branch-and-bound certificate is claimed. Infeasibility/unboundedness are solver-reported, not independently certified. Primal feasibility tolerance 1e-6 absolute; objective comparison 1e-6 plus 1e-7 relative. Ill-scaled problems may need rescaling.

Run gridagent --math-program FILE.json or gridagent --math-resume STUDY_ID (TUI slash equivalents). The write-once study records frozen input, one solver-call reservation, raw result and recomputed verification digests. Interrupted calls with no committed result are marked unknown and never replayed. Completed reports are recomputed on resume. Parent studies do not yet have canonical task IDs or active solver cancellation. This is mathematical programming only: no automatic AC-OPF conversion, nonlinear programming, generic expressions, or inferred physical constraints.

Example: two dispatch variables, minimize cost with a demand equality:
```json
{
  "description": "Two generators supply 10 MW",
  "variables": [
    {"id": "g1", "lower": 0, "upper": 6, "unit": "MW"},
    {"id": "g2", "lower": 0, "upper": 10, "unit": "MW"}
  ],
  "constraints": [
    {"id": "balance", "terms": [
      {"variable": "g1", "coefficient": 1},
      {"variable": "g2", "coefficient": 1}
    ], "lower": 10, "upper": 10, "unit": "MW"}
  ],
  "objective": {"sense": "minimize", "unit": "CNY/h", "terms": [
    {"variable": "g1", "coefficient": 20},
    {"variable": "g2", "coefficient": 50}
  ]}
}
```
The analytic solution is g1=6 MW, g2=4 MW, objective 320 CNY/h. Actual CI must validate the implementation.
