# AC single-factor diagnostic experiments

Starting from a committed AC cross-check report, obtain the source fingerprint with --diagnose-study ID. Supply a reviewed JSON authorization to --ac-diagnostic-experiment FILE.json (or the TUI equivalent). Example fields:

    {"source_study_id": "<32 hex>", "source_report_sha256": "<64 hex>",
     "snapshot": {"hour": 0}, "target_scope": "ac_native",
     "target_check": "voltage_operating_range",
     "probes": [{"kind": "voltage_setpoint", "device": "slackA", "value_pu": 1.0}],
     "max_solver_runs": 2}

One to eight probes and a fresh baseline, maximum nine native runs, each with the original per-run timeout. Only a selected snapshot of the original AC study may be tested. Voltage probes change an existing online generator/slack setpoint within the original IR's 0.8–1.2 p.u. range. Storage reactive probes use kind storage_reactive, device, value_mvar, minimum_mvar and maximum_mvar. The explicit declared range must contain original and proposed Q; negative Q means injection. This range is experiment authorization, not independent inverter capability certification. No changes to P, demand (including Q demand), topology, branch ratings, thermal Q limits, original AC acceptance limits, or DC commitment. No simultaneous changes. Offline, ineffective and duplicate native requests are rejected.

The target must be an observed failed check with complete identity-checked evidence and valid input, bus coverage and power balance. Supported targets: native voltage_operating_range, res_line_loading, and supplementary reactive:UNIT or active-limit:LINE. Supplementary observations require native acceptance. The source and fresh baseline must reproduce the failed metric within 1e-6 absolute/1e-4 relative tolerance, with matching native solver versions. Otherwise results abstain. The report distinguishes resolved target, reduced/increased violation, no material change and inconclusive; separately records all-snapshot acceptance. A reduced target does not imply overall feasibility or a unique cause. No recommendations for operational control or automatic edits.

The frozen manifest binds source/DC report digests through replay, exact authorization, variant and request fingerprints, and source measurement. Each run is reserved before native execution, with unique run ID; recovery never launches a previously reserved run. Recompute all AC evidence and compare committed observations on resume with --ac-diagnostic-experiment-resume ID. No extra solver dependencies. This is a single snapshot diagnostic protocol, not whole-horizon repair, causal certification, or dynamic stability. CLI/TUI only for experiment execution; authorization is not inferred by LLM. Tests cover locked fields, invalid probes, storage Q sign, baseline drift/version mismatch, and native voltage recovery. Native integration results require CI confirmation.
