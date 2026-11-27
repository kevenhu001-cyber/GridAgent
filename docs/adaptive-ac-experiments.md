# Adaptive AC diagnostic selection

The fixed AC diagnostic protocol remains unchanged. A new explicit authorization accepts an experiment object containing the complete existing ACDiagnosticExperiment contract (including every candidate and its full-pool max_solver_runs), run_budget (actual adaptive cap, 2..9 and at most baseline plus pool size), and use_history (default false).

    {"experiment": {"source_study_id": "<32 hex>", "source_report_sha256": "<64 hex>",
                    "snapshot": {"hour": 0}, "target_scope": "ac_native",
                    "target_check": "voltage_operating_range",
                    "probes": [{"kind": "voltage_setpoint", "device": "slackA", "value_pu": 0.95},
                               {"kind": "voltage_setpoint", "device": "slackA", "value_pu": 1.0}],
                    "max_solver_runs": 3},
     "run_budget": 2, "use_history": true}

Use --adaptive-ac-experiment FILE.json and --adaptive-ac-experiment-resume ID or equivalent slash commands. The existing compiler validates every candidate and freezes exact native requests. It cannot invent new setpoints, combine edits or relax constraints. A fresh failed baseline must reproduce the original observation before a probe launches. The policy groups candidates by device, intervention and direction; prioritizes comparable measured improvement, then unexplored directions, then previously non-improving directions. Within a tier, rank by measured reduction, fewer previous tries, optional historical direction score, normalized step size, stable index. History is optional, replay-verified at start and frozen, excludes same-source, wrong-target, wrong-snapshot-kind, wrong-version and inconclusive records; no numerical historical settings. Scores are heuristic, not probability or expected information gain.

After each run, independent AC observations determine the next choice. Stop on a target-resolving candidate that passes every selected snapshot check, baseline not reproduced, budget exhausted or pool exhausted. Unknown probes are charged, never repeated, and do not count as measured improvements. The report explicitly lists untried candidates and termination, and indexes tested candidates by original canonical pool index rather than execution order. Single-snapshot success is not full-scope feasibility. The existing AC evidence repair protocol accepts a tested adaptive winner under separate explicit repair authorization, then checks all original snapshots and storage apparent power as before. The experience index supports those repair reports. No automatic application.

Reservations bind step, chosen job, selection reason, prior observation hash, run ID. On recovery the deterministic policy is replayed against the frozen prior and revalidated observations, never requerying changing history. Charged runs never relaunched. Evidence or selection mismatch rejected. The plan hash detects unintended changes, not malicious authenticated storage. History can become stale after initial authorization. No learned surrogate, multi-factor search, globally optimal policy, or measured efficiency gains. Tests exercise deterministic selection, history exclusion, budget, early stop, interruption and tamper detection, with mocked observations plus a native integration workflow.
