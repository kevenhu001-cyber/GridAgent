# GridAgent — active development roadmap

**Owner:** TopoDrive / GridAgent  
**Direction:** LLM-first scientific coding and execution platform  
**Effective:** 2026-11-27  
**Status:** Owner-approved product direction; implementation and validation remain pending unless separately demonstrated.

[AGENTS.md](AGENTS.md) is the repository-wide development contract. [ADR 0001](docs/adr/0001-llm-first.md) records the architectural decision. The [previous PGHA roadmap](docs/history/roadmap-pgha-2026-11-26.md) is archived for reference only and is no longer normative.

## 1. Product objective

GridAgent = LLM coding agent + professional electrical engineering solvers + isolated scientific execution environment + engineering knowledge + scientific visualization.

The LLM should independently interpret a new engineering question, formulate its mathematical and physical model, author code, select the numerical method and native solver, execute experiments, read results and errors, revise the model, design new experiments and produce evidence-backed deliverables. The runtime provides capabilities and safeguards; it does not prescribe the solution method. The target is generalization to problems not anticipated by the developers.

This is a local-first research application, not a certified engineering system, operational grid controller or expert system. A user may choose any supported model provider. Keep one primary LLM-led loop.

## 2. Architecture and boundaries

- **Agent:** LLM-led planning, code generation, tool calls, model debugging, experimental decisions and synthesis. Shared state and model context across clients.
- **Scientific workspace:** persistent scoped code, model files, inputs, logs, data and results; source snapshots and versioned artifacts.
- **Execution runtime:** OS-isolated authorized Python/command execution, bounded resource use, cancellation, dependency requests, provenance and actionable feedback. Never fall back to unsafe host execution.
- **Professional libraries:** ANDES, pandapower, NumPy/SciPy, SymPy, HiGHS and Python Control as core capabilities; on-demand PyPSA, OpenDSS, PyBaMM, CVXPY, Pyomo, CasADi and other supported plugins. Expand access to native APIs, not only narrow wrappers.
- **Knowledge:** version-specific official API documentation, signatures, examples, units and methods, available to the LLM on demand.
- **Evidence:** independent mathematical/physical checks when supported, numerical provenance, logs and reusable artifacts. Solver success does not establish full physical validity.
- **Presentation:** native WinUI and shared Python core, with charts, topology, equations, code and artifact views. UI must not own scientific decisions.
- **Optional research tools:** typed IR, fixed workflow benchmarks, optimization, diagnostic rules, retrieval-based policies and lightweight learned rankers. LLM may invoke useful subroutines; none controls the default research path.

## 3. Implementation priorities and acceptance gates

| Priority | Milestone | Acceptance gate (target, not a current claim) |
| --- | --- | --- |
| P0 | General scientific sandbox | Agent writes and executes a novel Python program, receives stdout/stderr and artifacts, revises and reruns without leaving an authorized workspace. Isolation, resource limits, cancellation and denied unauthorized access tested. |
| P0 | Persistent engineering workspace | Scoped list/read/write/edit, model/code revisions, project isolation, explicit imported inputs, immutable run snapshots and reproducible outputs. |
| P0 | Native API access and dependencies | Discover versions and native capabilities, use installed libraries directly from code, request missing dependencies with user approval; do not rely on a new wrapper for every operation. |
| P1 | Documentation and domain knowledge | Retrieve exact versioned API signatures, solver examples and physical assumptions; measure retrieval quality and recovery from errors. |
| P1 | Long-horizon LLM loop | Multiple code/compute/inspect/revise cycles, model context and task continuity, structured tool errors, safe cancellation and recovery; no silent duplicate jobs. |
| P1 | Scientific artifact UX | Native WinUI project explorer, code/model inspection, plots, topology and numerical tables with provenance, progress and clear errors. |
| P1 | Generalization benchmarks | Unseen tasks across AC networks, storage dispatch, dynamics, control and numerical modeling; evaluate model correctness, completion, recovery, resources and evidence against explicit baselines. |
| P2 | Optional accelerators and release | Add tested specialist tools only when useful; avoid mandatory policies. Verify real desktop behavior, packaging, signing and release readiness. |

No milestone is complete merely because a module exists. Record CI, actual runtime evidence and remaining limitations. Reuse existing implementation where it advances these goals, but do not continue the old roadmap by inertia.

## 4. Primary tool surface (target)

Generic tools: execute Python/authorized commands; list/read/write/edit project files; inspect installed library APIs; discover solvers; request dependencies; search documentation; inspect artifacts; render visualizations; manage jobs. Exact tool names and schemas should be designed around concrete execution and security requirements.

The normal workflow is a single LLM deciding what to do next after actual tool feedback. Long computation batches may be delegated to numerical algorithms; the LLM need not participate in every solver iteration. Avoid one API per narrowly prescribed engineering task. Use typed interfaces where they improve correctness or ergonomics, while keeping the general code path available.

## 5. Transition from existing code

- Retain LangGraph Agent, native WinUI, plugin management, numerical backends, model revisions, journals, independent verification and artifacts.
- Generalize existing sandbox code beyond the special AC reference workflow; use secure implementation and fail closed on unsupported platforms. Do not equate dependency/process isolation with OS-level isolation.
- Review existing specialist policies as optional tools, isolate benchmarks from the primary chat flow, and avoid adding new mandatory controllers. Do not delete verified implementation before migration and tests.
- Re-review open PRs #6–#8 under the new direction. Keep generic workbench, reference solvers and useful research artifacts; do not merge expert-system behavior as default. These are review instructions, not assertions that PRs have merged.
- Keep previous research benchmarks as historical or optional experiments with explicit scope, not acceptance substitutes for unseen-task autonomous modeling.

## 6. Governance

Every substantial PR must satisfy [AGENTS.md](AGENTS.md) and the [architecture decision](docs/adr/0001-llm-first.md). A change that shifts research authority away from the LLM or limits general execution to fixed workflows requires explicit product-owner approval. Use real tests, do not conceal failures, and distinguish planned functionality from verified capability.
