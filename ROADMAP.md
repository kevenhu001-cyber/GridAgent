# GridAgent — active development roadmap

**Owner:** TopoDrive / GridAgent  
**Direction:** LLM-first scientific coding and execution platform  
**Effective:** 2026-11-27  
**Status:** Owner-approved product direction; implementation and validation remain pending unless separately demonstrated.

**Desktop migration (2026-11-28):** Use the preserved Proliferate 0.4.27 source as the new desktop baseline rather than building another UI from scratch. [ADR 0002](docs/adr/0002-proliferate-desktop.md) records the transition. The first integration lives in [integration/proliferate](integration/proliferate/README.md). Owner-approved [ADR 0003](docs/adr/0003-native-scientific-runtime.md) supersedes mandatory core MCP: migrate first-party scientific tools into the runtime, retain MCP only for external compatibility. Pi is the owner-approved sole desktop Agent engine; pin and validate its SDK. External Agent hosting is out of scope, not a fallback.

[AGENTS.md](AGENTS.md) is the repository-wide development contract. [ADR 0001](docs/adr/0001-llm-first.md) records the architectural decision. The [previous PGHA roadmap](docs/history/roadmap-pgha-2026-11-26.md) is archived for reference only and is no longer normative.

## 1. Product objective

GridAgent = LLM coding agent + professional electrical engineering solvers + isolated scientific execution environment + engineering knowledge + scientific visualization.

The LLM should independently interpret a new engineering question, formulate its mathematical and physical model, author code, select the numerical method and native solver, execute experiments, read results and errors, revise the model, design new experiments and produce evidence-backed deliverables. The runtime provides capabilities and safeguards; it does not prescribe the solution method. The target is generalization to problems not anticipated by the developers.

This is a local-first research application, not a certified engineering system, operational grid controller or expert system. A user may choose any supported model provider. Keep one primary LLM-led loop.

## 2. Architecture and boundaries

- **Agent:** Pi is the sole supported desktop Agent engine; embed its SDK in a local worker and adapt its event stream to the retained Proliferate UI/session contracts. Remove external Agent catalogs, launchers, installers, provider-specific Agent login screens and binary seeds. Retain model selection, not Agent selection. Retain Pi's default general coding tools with workspace-scoped file operations and isolated shell execution; add scientific custom tools directly. The native Pi worker and IPC lane exist. The temporary independent chat preview was removed to preserve the original UI; existing session contracts are being adapted. The existing workspace and Home composers share native session admission and the original outbox in opt-in development mode, limited to existing authorized local workspaces. Durable history, multiple workers, standalone workspace/file transport and production packaging remain pending. LLM-led planning, code generation, tool calls, model debugging, experimental decisions and synthesis. Shared state and model context across clients.
- **Scientific workspace:** persistent scoped code, model files, inputs, logs, data and results; source snapshots and versioned artifacts.
- **Execution runtime:** OS-isolated authorized Python/command execution, bounded resource use, cancellation, dependency requests, provenance and actionable feedback. Never fall back to unsafe host execution.
- **Professional libraries:** ANDES, pandapower, NumPy/SciPy, SymPy, HiGHS and Python Control as core capabilities; on-demand PyPSA, OpenDSS, PyBaMM, CVXPY, Pyomo, CasADi and other supported plugins. Expand access to native APIs, not only narrow wrappers.
- **Knowledge:** version-specific official API documentation, signatures, examples, units and methods, available to the LLM on demand.
- **Evidence:** independent mathematical/physical checks when supported, numerical provenance, logs and reusable artifacts. Solver success does not establish full physical validity.
- **Presentation:** Proliferate Tauri/React and shared Python scientific core via first-party persistent IPC, with charts, topology, equations, code and artifact views. UI must not own scientific decisions.
- **Optional research tools:** typed IR, fixed workflow benchmarks, optimization, diagnostic rules, retrieval-based policies and lightweight learned rankers. LLM may invoke useful subroutines; none controls the default research path.

## 3. Implementation priorities and acceptance gates

| Priority | Milestone | Acceptance gate (target, not a current claim) |
| --- | --- | --- |
| P0 | General scientific sandbox | Agent writes and executes a novel Python program, receives stdout/stderr and artifacts, revises and reruns without leaving an authorized workspace. Isolation, resource limits, cancellation and denied unauthorized access tested. |
| P0 | Persistent engineering workspace | Scoped list/read/write/edit, model/code revisions, project isolation, explicit imported inputs, immutable run snapshots and reproducible outputs. |
| P0 | Native API access and dependencies | Discover versions and native capabilities, use installed libraries directly from code, request missing dependencies with user approval; do not rely on a new wrapper for every operation. |
| P1 | Documentation and domain knowledge | Retrieve exact versioned API signatures, solver examples and physical assumptions; measure retrieval quality and recovery from errors. |
| P1 | Long-horizon LLM loop | Multiple code/compute/inspect/revise cycles, model context and task continuity, structured tool errors, safe cancellation and recovery; no silent duplicate jobs. |
| P1 | Scientific artifact UX | Proliferate-based project explorer, code/model inspection, plots, topology and numerical tables with provenance, progress and clear errors. |
| P1 | Generalization benchmarks | Unseen tasks across AC networks, storage dispatch, dynamics, control and numerical modeling; evaluate model correctness, completion, recovery, resources and evidence against explicit baselines. |
| P2 | Optional accelerators and release | Add tested specialist tools only when useful; avoid mandatory policies. Verify real desktop behavior, packaging, signing and release readiness. |

No milestone is complete merely because a module exists. Record CI, actual runtime evidence and remaining limitations. Reuse existing implementation where it advances these goals, but do not continue the old roadmap by inertia.

## 3a. Reuse-first desktop cutover (active execution order)

The owner requires reusing existing functionality rather than developing it again. The [source-level inventory](docs/proliferate-reuse-audit.md) classifies what to keep, adapt, add and retire. This sequence supersedes plans to build new generic chat, settings, session management, model selection or file explorer UI.

| Priority | Work | Acceptance gate |
| --- | --- | --- |
| P0 | Existing model picker and provider settings | Retain ComposerModelSelectorControl/ComposerModelPickerPopover, existing settings rows and API-key dialog; replace Agent-catalog and cloud-vault dependencies with Pi-backed data and an authorized local credential service. Test model selection, provider credentials and secret handling on Windows. |
| P0 | Existing chat/session contract cutover | Feed Pi events into the existing session directory, transcript reducer/ingest, prompt outbox, session controls and original ChatView/ChatInput. Verify normal and long streaming turns, cancellation, errors, tab switching and history. The temporary preview UI/store has been removed; no duplicate product chat stack. |
| P0 | Existing workspace and persistence integration | Reuse workspace inventory, file tree, editor, session tabs, selection and persistence contracts. Inspect existing durable stores before adding a Pi-specific persistence adapter; prove isolated sessions, restoration, context continuity and read-only legacy history. |
| P0 | Remove external Agent execution | Audit and cut every launch, install, discovery, auth, seed and resume path; retain provider-neutral and non-Agent components. Pi failure must not launch another Agent. |
| P0 | Real desktop validation | Compile retained shared ProductClient and Tauri desktop on Windows; test existing interactions and native Pi integration. Restore Windows packaging with private runtimes, signing and dependency validation. |
| P1 | Scientific additions only | Extend existing tool rows, file previews and artifact surfaces with scientific data, charts, network topology, numerical evidence and provenance only where the existing components cannot represent them. |
| P1 | Engineering validation | Real provider-driven unseen modeling tasks, sandbox execution, solver feedback, artifact verification and performance measurements. |

Existing Python solvers, plugin management, evidence/revision records and job APIs should similarly be reused before adding new scientific services. A completed source-level component is not evidence of an operational Pi-backed feature. Changes requiring significant UI redesign need owner approval.

## 4. Primary tool surface (target)

Generic tools: execute Python/authorized commands; list/read/write/edit project files; inspect installed library APIs; discover solvers; request dependencies; search documentation; inspect artifacts; render visualizations; manage jobs. Exact tool names and schemas should be designed around concrete execution and security requirements.

The normal workflow is a single LLM deciding what to do next after actual tool feedback. Long computation batches may be delegated to numerical algorithms; the LLM need not participate in every solver iteration. Avoid one API per narrowly prescribed engineering task. Use typed interfaces where they improve correctness or ergonomics, while keeping the general code path available.

## 5. Transition from existing code

- Retain plugin management, numerical backends, model revisions, journals, independent verification and artifacts. Retain LangGraph for TUI and CLI; the Proliferate-based desktop uses Pi as its sole LLM loop. The existing Python CLI/TUI are first-party development surfaces, not external Agents; their eventual Pi convergence is separate work. Remove the retired WinUI and WPF clients and their build infrastructure.
- Generalize existing sandbox code beyond the special AC reference workflow; use secure implementation and fail closed on unsupported platforms. Do not equate dependency/process isolation with OS-level isolation.
- Review existing specialist policies as optional tools, isolate benchmarks from the primary chat flow, and avoid adding new mandatory controllers. Do not delete verified implementation before migration and tests.
- Re-review open PRs #6–#8 under the new direction. Keep generic workbench, reference solvers and useful research artifacts; do not merge expert-system behavior as default. These are review instructions, not assertions that PRs have merged.
- Keep previous research benchmarks as historical or optional experiments with explicit scope, not acceptance substitutes for unseen-task autonomous modeling.

## 6. Governance

Every substantial PR must satisfy [AGENTS.md](AGENTS.md) and the [architecture decision](docs/adr/0001-llm-first.md). A change that shifts research authority away from the LLM or limits general execution to fixed workflows requires explicit product-owner approval. Use real tests, do not conceal failures, and distinguish planned functionality from verified capability.
