# Hourly dispatch IR

The second engineering model family is fixed-capacity, hourly linear economic dispatch. It is intentionally separate from AC steady-state ModelIR. It supports 1–168 one-hour snapshots, fixed demand, conventional and renewable generator profiles, storage, lossless passive linear transmission and one-way lossy links. Prices use one explicit three-letter currency label; no conversion is performed.

Storage has independent fixed MW and MWh capacities, symmetric charge/discharge power limits, explicit efficiencies and nonnegative discharge cost. The compiler derives max_hours = MWh / MW. Select cyclic SOC or fixed-initial SOC; fixed-initial optionally specifies an exact final SOC. Cyclic storage must not supply initial or final SOC values. PyPSA 1.x StorageUnit state_of_charge_initial and state_of_charge_set implement the fixed boundaries (https://docs.pypsa.org/v1.0.7/user-guide/components/storage-units/). Native legacy inputs retain cyclic behavior by default.

The model compiler maps stable IDs to native component names. It does not change loads, cost profiles, capacities or efficiency. Model and study fingerprints bind the compiled input to the canonical task lifecycle.

Use DispatchModelIR and DispatchStudySpec from gridagent.dispatch_ir to create a DispatchStudy document; set model_sha256 to model.sha256(), then serialize with model_dump_json(). Start with:

    gridagent --dispatch-ir dispatch.json

Resume, inspect or request cancellation with --dispatch-resume ID, --dispatch-status ID and --dispatch-cancel ID. Equivalent TUI commands start with a slash.

The runtime reserves one solver run transactionally before launch and rechecks persisted artifacts on resume. Unknown reserved runs are charged and never silently repeated. Canonical task state and dispatch evidence are written atomically. Direct repository writes to dispatch-managed tasks are rejected. Cancellation is acknowledged at the native call boundary; it does not yet interrupt a running PyPSA subprocess.

Independent checks cover hourly alignment, demand, nodal balance, component limits, intertemporal SOC, fixed terminal SOC (if set) and recomputed operating cost. Cost reconciliation checks consistency, not mathematical proof of optimality; solver termination supplies the optimization status. Test coverage includes a two-hour analytic optimum fixture. The model is a linear relaxation that may allow simultaneous charging/discharging, with no integer commitment, ramp constraints, standing losses, degradation, stochastic optimization, capacity expansion or AC feasibility guarantee. Full CI and native GUI integration must be separately validated.
