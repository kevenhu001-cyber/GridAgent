# Evidence-gated AC repair

The repair protocol consumes a committed AC diagnostic experiment report. It independently replays the experiment and its original source evidence, then compiles only explicitly selected candidate indices (the one-based observation indices, not the baseline index 0). A candidate must have reproduced the original failure, resolved the target constraint and passed all checks at the diagnostic snapshot. A single-point improvement is not a repair.

Reviewed authorization example:

    {"diagnostic_study_id": "<32 hex>", "diagnostic_report_sha256": "<64 hex>",
     "candidate_indices": [1], "storage_apparent_limits_mva": {}, "max_solver_runs": 24}

Use --ac-evidence-repair FILE.json or /ac-evidence-repair PATH. Resume with --ac-evidence-repair-resume ID or the corresponding slash command. The report fingerprint is the canonical SHA-256 of the diagnostic report (engineering_ir.fingerprint). The input order defines recommendation priority; the engine does not optimize cost, rank interventions across incompatible units, or infer permission to make changes. One to four distinct single-factor candidates, at most sixty fresh AC solver reservations. The budget must cover every original snapshot for every selected candidate; no adaptive skipping or combination of interventions.

Each candidate restores the original AC study's exact snapshot list, preserving dispatch, topology, demand, ratings, thermal Q limits and all acceptance conditions. For a storage Q candidate, explicitly supply its positive apparent-power limit in storage_apparent_limits_mva. The scheduled P/Q magnitude plus the dispatch tolerance in each coordinate must fit inside that declared circular envelope at every original snapshot. This is a conservative check of the selected operating point, not independent certification of the inverter rating or its detailed voltage-dependent capability curve.

Each native request is frozen, linked to the candidate and reserved before execution. The original AC verification machinery recomputes the evidence on recovery. Reserved runs are never relaunched automatically; unavailable evidence or solver-version mismatches prevent recommendation. A candidate is eligible only if every originally selected snapshot passes the native and supplementary checks with the original native solver version. The first verified candidate in the explicitly authorized order is recommended, with a complete proposed AC spec and evidence report. If none qualify, no model is recommended.

The original model, study and DC schedule remain immutable. A recommendation is not applied automatically. Full original AC snapshot coverage is not necessarily full DC schedule coverage; the report preserves the distinction and does not certify dynamic stability, unsupported contingencies or real-grid operational safety. Future work includes jointly optimized repairs, independent revalidation of additional scenarios, reusable verified repair experience and held-out evaluation.

Tests cover candidate eligibility, preservation of original scope, budget, storage apparent power, partial/mismatched evidence and a native two-snapshot workflow. Native integration results require CI confirmation.
