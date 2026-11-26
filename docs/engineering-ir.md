# GridAgent 2.0 — AC engineering intermediate representation

The first Engineering IR implementation supports explicit AC steady-state networks and a deterministic pandapower compiler. The IR is independent of native table indices and solver API operation names. It is not a universal simulation format.

## Contracts

- ModelIR: stable globally unique bus/device IDs, schema and model revisions, nominal voltage bases and typed physical parameters.
- StudySpec: exact model fingerprint, operating scenarios, branch outage IDs, acceptance criteria and numerical-run budget.
- EngineeringStudy: the portable document pairing the two.
- CompiledStudy: the existing ResearchManifest plus compiler version, canonical source, fingerprints and stable device-to-native table/index/step mapping.

Supported devices: slack sources, fixed loads, PV generators, fixed PQ storage, passive lines and two-winding transformers. Voltage uses p.u. relative to each bus nominal kV. Power uses MW/Mvar, energy MWh, line impedance ohm/km, capacitance nF/km and transformer impedance percentages. Positive storage charging_mw means consumption; negative means discharge. Storage is a static operating point, not an energy trajectory.

Baseline references, duplicate IDs, voltage-base compatibility, self-loops and the presence of a slack source in each connected component are checked before compilation. The backend still performs numerical and physical checks. Contingencies are not silently repaired, even if they disconnect a load bus.

## Example

```python
from pathlib import Path
from gridagent.engineering_ir import EngineeringStudy, ModelIR, StudySpec

model = ModelIR.model_validate({
    "model_id": "feeder",
    "buses": [{"id": "supply", "nominal_kv": 20},
              {"id": "demand_bus", "nominal_kv": 20}],
    "devices": [
        {"kind": "slack", "id": "grid", "bus": "supply"},
        {"kind": "line", "id": "feeder_line", "from_bus": "supply",
         "to_bus": "demand_bus", "length_km": 2,
         "resistance_ohm_per_km": 0.2, "reactance_ohm_per_km": 0.3,
         "current_limit_ka": 0.4},
        {"kind": "load", "id": "load", "bus": "demand_bus",
         "active_mw": 1, "reactive_mvar": 0.2},
    ],
})
study = StudySpec(
    objective="Check voltage and loading under peak demand",
    model_sha256=model.sha256(),
    scenarios=({"name": "base"}, {"name": "peak", "load_scale": 1.2}),
    max_runs=2,
)
document = EngineeringStudy(model=model, study=study)
Path("feeder.json").write_text(document.model_dump_json(indent=2), encoding="utf-8")
```

Run without a model API key:

```sh
gridagent --research-ir feeder.json
```

The TUI also accepts /research-ir PATH. The existing report export includes the source, compiler fingerprint, native index mapping, run IDs and evaluator checks. The canonical task binds the source model hash; resume checks the frozen manifest and recompiles the IR to verify consistency before running. The compiler does not make LLM calls or invoke a simulator. Execution reuses the existing research solver and evaluator.

## Explicit boundaries

The current compiler emits a standalone pandapower AC power-flow program with no automatic repairs or hidden parameter changes. No switching, dynamic RMS/EMT models, time-series battery state, optimal dispatch, arbitrary solver code or implicit model-family conversion is supported. Unsupported families and fields fail validation. Acceptance criteria are the same existing AC screening checks, not certified grid safety or a stability proof. Stable ID mapping is local to the compiled revision; numerical indices may change when a model revision changes. Compiler provenance consistency checks are not signatures or a tamper-proof audit log.

Next: add dispatch-specific contracts, explicit authorized IR edits, typed execution-plan DAG and evidence records before integrating natural-language generation.
