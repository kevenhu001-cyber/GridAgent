# Bounded autonomous AC engineering research

This first closed loop accepts a reviewed EngineeringStudy and ACOptimizationSpec, plus a finite list of allowed candidate parameter vectors. The user locks the model, scenarios, acceptance criteria and total solver budget. The controller compiles all approved candidates before any solve. It runs the baseline, distinguishes physical-limit violations from unavailable or invalid numerical evidence, and chooses a previously untested candidate. A voltage-direction heuristic prioritizes increasing/decreasing authorized voltage setpoints if the observed voltage range is uniformly low/high; it is not a causal model. It stops at the first feasible candidate and reserves a separate fresh whole-scope verification suite. It does not claim optimization or global optimality.

    gridagent --closed-loop reviewed.json
    gridagent --closed-loop-resume STUDY_ID

TUI uses /closed-loop and /closed-loop-resume. Format: {"optimization": <ACOptimizationSpec>, "candidates": [[...], [...]]}. Each candidate follows the declared variable order. Baseline must not be repeated in the candidate pool. No change to limits, demands, topology or ratings is allowed. A reservation is written before creating its child task. Unlinked reservations are conservatively charged, and linked tasks recover their own solver journals. Completed results are replayed from the recorded evidence, not simply trusted from a report. No LLM calls or automatic live-grid actions. Parent cooperative cancellation and a natural-language authorization editor remain future work.

## Optional model-provider comparison

    python -m gridagent.ac_llm_policy_benchmark WORKSPACE FIXED_STUDY_ID --budget 3 --allow-provider-data --output replay.json

Uses separately collected complete fixed AC diagnostic pools. The fixed, adaptive and LLM policies receive the same pool and observation budget, including a baseline. The LLM is explicitly allowed to receive candidate descriptions and revealed measurements only; future outcomes remain hidden. Invalid choices terminate without retry at the policy layer. Provider retries may still be counted by the shared scheduler. No automatic model API calls from the closed-loop runtime. Replay is not a live solver speedup or a pure-LLM numerical solver comparison. Use held-out cases chosen before evaluation.
