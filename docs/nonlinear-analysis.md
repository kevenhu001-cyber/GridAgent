# Advanced nonlinear analysis (opt-in)

The existing polynomial_nlp family accepts an optional analysis object with schema_version 1, up to seven additional initial points (eight total), and up to four authorized RHS perturbations. Each point must have exactly the same variables, satisfy their bounds, and be distinct. Perturbations identify a constraint and side (lower, upper, equality) and nonzero delta in that row's units; equality shifts both bounds. Other coefficients, bounds, objective and model structure are unchanged. The frozen original initial point and additional points are used in every variant; there is no random sampling or hidden warm start.

Example analysis:
    {"additional_initials": [{"x": 2, "y": 1}],
     "rhs_scan": [{"constraint": "balance", "side": "equality", "delta": 0.1}]}

All planned case/start combinations share the original callback budget and one cooperative deadline. Integer division assigns deterministic per-subsolve quotas, distributing the remainder in schedule order. Unused allocations are not automatically transferred. Iteration limit remains per subsolve. At most 40 subsolves. A time-exhausted case is recorded as not started. The existing study reserves the whole advanced call before execution; interruption before a committed result remains unknown, not silently replayed. It does not checkpoint individual subsolves. Solver internal work, final objective checks, KKT and sensitivity postprocessing are outside the callback limit.

Every subsolve carries case, perturbation, start, initial values, program fingerprint, callback limit and native result. On verification, the schedule is reconstructed from the immutable input, quotas checked and each candidate independently evaluated; the best feasible baseline and each RHS variant are selected deterministically. No cross-case comparison substitutes a changed problem for the original result.

KKT diagnostic: differentiate original monomial records separately from solver compilation, identify near-active constraints and box bounds, fit equality/free and inequality/nonnegative multipliers with bounded least squares, then check stationarity infinity norm, dual sign and complementarity. Active threshold and diagnostic tolerance are 1e-5 absolute. Rank is a diagnostic, not a constraint-qualification guarantee. A passing necessary first-order condition can also occur at a saddle or maximum. No second-order, local/global optimality or rigorous certificate is claimed.

Reoptimization reports the finite objective change divided by RHS perturbation, only when both cases have verified feasible candidates. It is a secant between observed solutions, not a certified derivative of the global optimum, a shadow price, or uncertainty quantification. KKT status is shown for both. For the quadratic example x^2+y^2 with x+y=3, delta=0.1, the analytic objective changes 4.5 to 4.805; secant is 3.05. Tests exercise this and asymmetric double-well search, active-bound sign, budget, invalid authorization, tampering and resume.

Omitting analysis preserves previous single-start canonical input fingerprints, reservation shape and report fields. No new dependency or CLI command. The new tests require CI confirmation; no performance or robustness claim is inferred from these analytic cases.
