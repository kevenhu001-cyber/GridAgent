# Authorized diagnostic experiments: contingency isolation

This first executable diagnostic protocol supports completed network unit_commitment studies that report infeasibility with no verified candidate. Use --diagnose-study ID to obtain the source report fingerprint, then explicitly review a JSON authorization:

    {"source_study_id": "<32 hex>",
     "source_report_sha256": "<64 hex>",
     "probes": [{"kind": "line", "component": "AB"},
                {"kind": "unit", "component": "local"}],
     "max_solver_calls": 3}

Use --diagnostic-experiment FILE.json or --diagnostic-experiment-resume ID (equivalent slash commands). The budget includes one base-only counterfactual and one single-contingency variant per selected probe, up to nine mathematical solver calls. Only originally authorized contingency IDs can be selected. The compiler removes security scenarios from independent diagnostic copies, never alters the original demand, topology, ratings, capacity, cost, initial conditions or original report. All variant acceptance constraints remain intact for their explicit counterfactual scope. No automatic model repair or live dispatch. LLM cannot execute this CLI-only protocol without an explicit user-supplied authorization.

The immutable manifest binds source report digest, solver version, canonical selected probes, budget and variant digests. Each case is charged before child study creation; child links bind exact variant manifests. Only fresh reservations launch; interrupted or unlinked cases stay unknown. Committed child reports are replay-verified and report digests checked on recovery, not silently retried. If an interrupted child later changes independently, the parent detects the difference instead of rewriting its conclusions. No new solver framework or dependency.

Interpretation: when the independently verified base case is feasible and a selected contingency is reported infeasible with matching solver version, the observation supports a contingency-conflict hypothesis, not a certified infeasibility proof or unique causal claim. If a selected contingency is independently feasible by itself, it does not exclude joint conflict between scenarios sharing commitment and reserve decisions. If base feasibility or comparable evidence is unavailable, the experiment abstains. Original solver-reported infeasibility is not overwritten. Diagnostic completion means interpretable case observations, not a repaired or safe original schedule. Child objective values across variants are descriptive, not proofs of optimality. Runtime version matching is limited to SciPy version, not complete environment identity.

Tests include a synthetic two-bus parallel-line example with feasible base/line-only cases but infeasible generator trip, invalid authorization, preserved nonsecurity fields, interrupted execution, version mismatch, changed child report and refusal of a feasible source. AC voltage/reactive experiments, automatic experiment selection, exact IIS/conflict certificates, combined subset search and model repair remain future work.
