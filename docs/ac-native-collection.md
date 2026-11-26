# Prospective AC decision data collection

Two separate workflows are available. The first generates small, synthetic balanced AC networks and real numerical observations suitable for the existing AC decision dataset builder. It does not call these models IEEE networks or field data. The second runs the unmodified built-in pandapower public cases (case14, case39 New England, case118) under base and 110% load with independent checks. The latter is screening, not reference-solution comparison or training data: transformer and shunt mappings are outside the current DC-to-AC contract.

## Native collection

Create a JSON authorization, e.g.

    {"families": ["grid-03", "grid-04", "grid-08"], "levels": ["nominal"],
     "max_dc_calls": 3, "max_ac_runs": 21}

Run:

    python -m gridagent.ac_native_collection WORKSPACE COLLECTION.json --plan-only
    python -m gridagent.ac_native_collection WORKSPACE --resume COLLECTION_ID

Without --plan-only the first command runs the frozen plan. There are 13 predeclared topology families (3–15 buses, radial and meshed) and three load levels. Training families: grid-03, grid-06, grid-15; test families: grid-08, grid-13; other families are validation. Group membership is fixed before collection. All families are synthetic and related design variations, not proven independent real-grid populations. Up to 39 cases, one DC MILP and seven AC runs each (original snapshot, fresh baseline, five authorized voltage probes). Full planned upper bound is charged per case before child launches. Interrupted reserved cases are retained as unknown, with child links if present, never automatically restarted. Completed cases replay child evidence without solving. Original settings, load and bounds remain immutable. Cases with missing/nonreproduced source evidence cannot become eligible. Unknown individual probe outcomes are filtered by the existing dataset builder. The collection report contains linked study IDs, digests, observed reservation counts and dataset_authorization if all three splits are represented. Copy that object into SPLITS.json and explicitly invoke the existing training CLI. The training gate may legitimately abstain; collection success does not mean a trained model is enabled. This first generator covers one-hour, single-slack, voltage-setting experiments only.

## Standard public-network screening

    python -m gridagent.standard_ac_benchmark WORKSPACE --networks case14 case39 case118

Uses native pandapower factories, the existing research task evidence and fixed two-scenario budget per network, no LLM or repair. Reports stage, scenario evidence, observed launches/cache hits and elapsed workflow time. No claims of reference power-flow accuracy, N-1 safety or optimality. Existing installed optional engineering backend is required. Integration tests run a three-family collection and case14 screening. Full collection is opt-in due to solver cost; no real benchmark results or trained weights are shipped in this commit.
