# Open DSR baseline (ANDES)

This is an independent voltage-proxy benchmark inspired by the paper, not its
original PowerFactory case. Ten packaged Kundur bus faults are ranked before
at most three simulations. The separate evaluator can simulate all ten.

Run:

    gridagent --dsr examples/dsr-kundur.json
    # or in TUI: /dsr examples/dsr-kundur.json

Historical memory is derived from completed ANDES fault result files in the
workspace's runs directory. Use ordinary chat to run historical fault cases
first. Same network and recovery horizon are required for retrieval; exact
fault matches take priority, then same bus and clearing duration. No embedding
index, topology distance, multiple operating points or automatic training yet.
Use a fixed, isolated workspace for an unseen-candidate benchmark; do not add
candidate outcomes to memory before a trial. The exact-match behavior is
intended for engineering reuse, not hidden-test evaluation.

Each study stores manifest and memory snapshots, retrieval evidence, frozen
ranking, attempted action reservations and results, and a compact report in
studies/<id>. These files are write-once through the application, not
cryptographically tamper-proof. Crash recovery and cross-process locks are
not yet implemented. Interrupted studies retain partial artifacts.

Offline evaluator, using a separate directory outside the agent workspace:

    python -m gridagent.evaluation truth examples/dsr-kundur.json ./offline/truth.json
    python -m gridagent.evaluation score .gridagent/studies/<id> ./offline/truth.json

It reports top-k recall and severity-proxy MAE with deterministic tie-breaking.
It does not feed labels into the policy and does not score physical instability
or mitigation. The paper's full S=1 instability override requires a validated
stability classifier; synchronous condenser placement and PowerFactory
integration are future work. The published ten contingencies are not these
Kundur examples. LLM structured tool/function calling support is required.

For repeatability use fresh, isolated workspaces containing identical history
snapshots and record the exact installed versions and model. Live LLM behavior
has not been verified in CI.

## Fixed-snapshot holdout mode

    gridagent --snapshot-memory ./history.json
    gridagent --dsr examples/dsr-kundur.json --memory ./history.json --holdout
    gridagent --studies

Holdout mode requires an explicitly selected snapshot and filters exact target
faults from it. Use the same snapshot across trials. Ordinary engineering mode
permits exact historical matches, but is not an unseen-case benchmark.
The TUI also supports /studies; start it with --memory and --holdout to apply
the same restrictions to /dsr. Study reports are independent of chat history.
