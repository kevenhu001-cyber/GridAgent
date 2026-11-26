# Paper-faithful roadmap

## Scope and protocol separation

PowerAgentBench-Dyn evaluates an agent, not a foundation model. Preserve the
task tuple (O,A,E,C,G,M), independent deterministic evaluator and stochastic
repeated runs. Keep free chat separate from benchmark graphs. Never expose
ground truth to the policy or retrieval index. No production control.

## DMQ: Dynamic Model Quality Review

- Load locked case, model, test configuration and machine-readable policy.
- Baseline: execute all eight DMView tests and record per-test results, logs,
  flat-start P/Q drift, oscillation, LVRT recovery and SCR performance.
- Only four REECAU1 gains (Kqp, Kqi, Kvp, Kvi) are authorized. Verify exact
  field identity against the parsed source model, whitelist, explicit bounds
  and unchanged locked fields before each mutation. Use isolated copies.
- Agent diagnoses failed tests, proposes a justified edit; deterministic
  policy validates it, optionally pauses for approval, then runs full suite.
- Stop on all tests passing or five iterations. Log every proposed and
  applied edit, failed tool call, result and elapsed time.
- Original fidelity requires PSS/E and DMView plus released cases and rules.
  ANDES alternative must be a separately labeled benchmark with its own model.

## DSR: Dynamic Security Risk Screening

- Load candidate CSV (ten in the paper) and fixed semantic-memory snapshot.
- Verify exact match; retrieve similar cases using topology, operating point,
  fault location and duration. Record similarity evidence, not hidden labels.
- Agent estimates KPIs and ranks all ten before selection. Freeze predictions.
- Simulate only the top three; compute voltage extrema, normalized violation
  integrals and a validated physical stability classifier. Solver failure
  alone is not instability. The original formula gives unstable cases S=1.
- Mitigation: fresh runs for authorized synchronous-condenser configurations
  on buses 04, 16 and 26, at most two 250 MVA units per configuration. Enforce
  a separate explicit run budget; original exact limits must be verified from
  released configuration. No semantic-memory lookup for mitigation.
- Offline evaluator sees all ten ground-truth runs; score top-k recall,
  ranking, absolute KPI error, mitigation, runtime and policy compliance.
- Reproduce PowerFactory/PowerMCP protocol with licensed installation when
  available; use separate open ANDES benchmark for development.

## Reproducibility

Record case hashes, policy version, memory snapshot, simulator and solver
configuration, provider/model, run IDs, estimates, tool attempts, audit
events and waveform references. Use ten independent trials per model as in
the paper. Report success counts, median time, iteration count and uncertainty.
Compare against simple heuristic and numerical baselines before claiming
improvements. Store original evaluator assets separately from agent inputs.

## Persistence and interface

SQLite sessions, tasks and append-only node events are the first milestone.
Completed conversations replay; failed/incomplete tasks retain audit without
reinjecting orphan tool calls. A process crash may leave a running task;
interrupted-task recovery and checkpointed mid-task resume are next.
Add projects, experiment manifests, typed artifacts, budget reservations,
LangGraph checkpointing, structured retrieval and evaluator runs. The TUI
should show short human-readable tool summaries and budgets, with opt-in
details and waveform exports. The native Windows client uses the same engine and workspace via local process events.
