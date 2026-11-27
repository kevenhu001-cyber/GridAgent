# AC engineering optimization v1

This Phase 5 increment adds a typed, offline mixed continuous/discrete operating-point search over existing AC EngineeringStudy models. It deliberately does not replace the PyPSA dispatch optimizer or the existing surrogate PI-gain optimization.

## Input and authorization

Use ACOptimizationSpec with a frozen source EngineeringStudy, 1–8 named device/parameter variables, one objective and a total solver-run budget (3–60). Continuous intervals and finite ordered discrete choices must include the baseline and satisfy the underlying model schema. Only slack voltage, generator voltage/active power and storage reactive power setpoints are allowed. Loads, topology, equipment ratings, operating criteria and scenarios remain locked. Authorized ranges must reflect actual equipment capability; the AC IR does not yet model generator or inverter capability curves.

Objectives: minimize worst absolute active-bus voltage deviation from 1 p.u. across all scenarios, or minimize mean passive line and transformer active loss (MW) across scenarios. Every candidate must pass all existing independent AC checks. The deterministic coordinate search uses bounded coarse-to-fine normalized steps and discrete alternatives, with the best feasible observed candidate as anchor. It is not an AC OPF or proof of global optimality.

## Execution and recovery

Each candidate is a new immutable IR revision evaluated using the existing canonical fixed-IR research lifecycle and solver journal. The optimization parent uses the existing write-once Study filesystem protocol. It reserves a whole scenario suite before creating its child; linked interrupted children resume, and missing links are conservatively charged, never silently relaunched. The budget includes baseline, all candidate suites and a reserved final independent suite. The optimizer rechecks successful child evidence and recomputes its objective from native tables; only feasible candidates can win. The final candidate must pass a fresh independent run with equivalent objective and solver version. Cross-task caching is disabled for the search and verification. Existing per-task AC worker limits still apply.

Run:
    gridagent --optimize-ir optimization.json
    gridagent --optimize-resume STUDY_ID

Equivalent TUI commands: /optimize-ir PATH and /optimize-resume ID. The study report records the baseline, candidate observations, child task IDs, run IDs, evidence fingerprints, charged budget and fresh verification. No global optimum is claimed. The parent study does not yet have a canonical engineering task ID or dedicated cancellation action; stop with interruption and resume. There is no automatic LLM proposal, MILP/NLP routing, transient optimization, surrogate learning, generalized constraints, hard global resource quota, or performance claim in this increment.
