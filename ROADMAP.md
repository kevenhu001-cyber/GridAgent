# GridAgent — active development roadmap

**Owner:** TopoDrive / GridAgent  
**Direction:** LLM-first scientific coding and execution platform  
**Effective:** 2026-11-28  
**Status:** Active roadmap following the merge of [PR #11](https://github.com/kevenhu001-cyber/GridAgent/pull/11). Merged source is a development baseline, not a production release.

**Desktop migration (2026-11-28):** Use the preserved Proliferate 0.4.27 source as the new desktop baseline rather than building another UI from scratch. [ADR 0002](docs/adr/0002-proliferate-desktop.md) records the transition. The first integration lives in [integration/proliferate](integration/proliferate/README.md). Owner-approved [ADR 0003](docs/adr/0003-native-scientific-runtime.md) supersedes mandatory core MCP: migrate first-party scientific tools into the runtime, retain MCP only for external compatibility. Pi is the owner-approved sole desktop Agent engine; pin and validate its SDK. External Agent hosting is out of scope, not a fallback.

[AGENTS.md](AGENTS.md) is the repository-wide development contract. [ADR 0001](docs/adr/0001-llm-first.md) records the architectural decision. The [previous PGHA roadmap](docs/history/roadmap-pgha-2026-11-26.md) is archived for reference only and is no longer normative.

## 1. Product objective

GridAgent = LLM coding agent + professional electrical engineering solvers + isolated scientific execution environment + engineering knowledge + scientific visualization.

The LLM should independently interpret a new engineering question, formulate its mathematical and physical model, author code, select the numerical method and native solver, execute experiments, read results and errors, revise the model, design new experiments and produce evidence-backed deliverables. The runtime provides capabilities and safeguards; it does not prescribe the solution method. The target is generalization to problems not anticipated by the developers.

This is a local-first research application, not a certified engineering system, operational grid controller or expert system. A user may choose any supported model provider. Keep one primary LLM-led loop.

## 2. Architecture and boundaries

- **Agent:** Pi is the sole supported desktop Agent engine; embed its SDK in a local worker and adapt its event stream to the retained Proliferate UI/session contracts. Remove external Agent catalogs, launchers, installers, provider-specific Agent login screens and binary seeds. Retain model selection, not Agent selection. Retain Pi's default general coding tools with workspace-scoped file operations and isolated shell execution; add scientific custom tools directly. The native Pi worker and IPC lane exist. The temporary independent chat preview was removed to preserve the original UI; existing session contracts are being adapted. The existing workspace and Home composers share native session admission and the original outbox in opt-in development mode, limited to existing authorized local workspaces. Durable history, multiple workers, standalone workspace/file transport and production packaging remain pending. LLM-led planning, code generation, tool calls, model debugging, experimental decisions and synthesis. Durable model context and cross-client continuity are future goals, not current guarantees.
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

## 3a. Desktop baseline and active execution order (2026-11-28)

The owner requires reusing existing functionality rather than developing it again. The [source-level inventory](docs/proliferate-reuse-audit.md) classifies what to keep, adapt, add and retire. This sequence supersedes previous cutover plans and any generic replacement chat, settings, session management, model selection or file explorer UI.

### Merged baseline

[PR #11](https://github.com/kevenhu001-cyber/GridAgent/pull/11) merged at `9a4de68bf2607d946ea312852553b660f90a7900`. Retained Proliferate Tauri/React desktop and original Home/ChatView/ChatInput, picker, settings rows/dialog, preference store, directory, transcript reducer, outbox and tab contracts. Pi SDK worker, direct default coding and scientific tools, scoped native IPC, model catalog, host-only provider credentials and native session adapter are present. Both existing composers use the same native admission and outbox path in opt-in development mode. Old independent preview UI/store was removed.

**Observed verification:** Embedded Pi Runtime and Native Scientific IPC passed for the merge commit; Proliferate Integration Protocol passed for the PR head `9a2f89d29bc812d8aea1166dff853f65f3c8cfb0`. Full CI was still running at this snapshot. Shared frontend and mocked/native protocol tests are not a substitute for Windows Tauri compilation, OS credential verification, real provider-driven execution, sandbox or installer tests.

**Current constraints:** up to four live Pi workers sharing the existing authorized standard local workspaces (per-session workspaces remain milestone 3), single text block up to 8192 UTF-8 bytes, initial OpenAI/Anthropic/Google credential/catalog support, in-memory transcript and worker context, conservative uncertain-outcome handling. The workspace/file inventory still relies on retained services. Development flag and legacy paths remain transitional code, not an approved external-Agent fallback or a shipping compatibility mode. No claim of production readiness or durable session restoration.

### Ordered next milestones

| Order | Priority | Work | Acceptance gate |
| --- | --- | --- | --- |
| 0 | P0 | Stabilize merged baseline | Inspect complete main CI and fix genuine failures; verify desktop Rust/TypeScript contracts, dependency locks and Windows Tauri build early. Retain existing regression suites. No bypass of failed checks. |
| 1 | P0 | Native multi-session lifecycle | Replace singleton host/renderer binding with isolated session-scoped workers or equivalent Pi SDK sessions. Preserve original directory/outbox/selection/tab contracts. Bound process count and resources; test independent prompts, cancellation, close/reopen, tab/background switching, failures, identity isolation and cleanup. No implicit replay or cross-session context. |
| 2 | P0 | Durable history and model context | Audit existing storage ownership and SDK persistence first. Reuse compatible product storage/metadata and native event/history contracts, with atomic/versioned writes and stable session IDs. Distinguish display transcript from model/tool context. Verify restart, context continuation, interrupted job reconciliation, read-only legacy history, corruption handling, permissions and no duplicate submissions. Do not store credentials or hidden reasoning in history. |
| 3 | P0 | Standalone authorized workspace and file services | Reuse workspace inventory, file tree, editor, search, tabs, Git and existing scientific project/job/artifact APIs. Remove dependency on external Agent lifecycle; keep useful non-Agent services. Support user-authorized workspace creation/opening, canonical-path checks, per-workspace isolation and consistent file revision semantics. Verify project files survive restart and Agent shell cannot escape sandbox. |
| 4 | P0 | Retire external Agent execution | Audit direct, Home, cowork, settings, deep-link, deferred, restored-session and background paths. Remove external Agent discovery, installers, auth, catalogs, binary seeds and launch/resume paths; preserve generic model/provider controls and non-Agent functionality. Pi is the only desktop Agent, including on failure. No fallback compatibility mode in the release. |
| 5 | P0 | Production Windows runtime and packaging | Pin full dependencies; bundle trusted private Node/Python runtimes and validated solver dependencies. Verify real Windows credential manager, provider requests, streaming/tool cards, normal/failed/cancelled turns, workspace permissions and Windows Sandbox with no unsafe host fallback. Build and test installer, clean-machine installation, update and uninstall; validate signing, runtime integrity, startup, footprint and crash cleanup. |
| 6 | P1 | General scientific execution and usability | Expand safe Python/native solver access, introspection, versioned docs, dependency requests, live job progress, logs and artifacts. Reuse existing components; add only missing scientific charts, topology, equations, numerical tables and provenance. Validate novel LLM-written models and iterative debugging, not a predefined expert workflow. |
| 7 | P1 | Numerical verification and research recovery | [Issue #12](https://github.com/kevenhu001-cyber/GridAgent/issues/12): selectively port independent AC references, frequency-control checks and useful research fixtures from closed #6–#8 in small main-based PRs; fix old failed validation and verify current solver scope/tolerances. Keep research policies opt-in, never default orchestration. |
| 8 | P1 | Unseen engineering tasks and performance | Real provider-driven AC networks, storage dispatch, dynamics and control tasks; compare correctness, reproducibility, failure recovery, resource use and latency against explicit baselines. Measure actual results, not claimed autonomy. |
| 9 | P2 | Optional extensions and release hardening | Expand on-demand solver plugins and validated specialist accelerators, improve deployment and documentation, evaluate broader platform support after Windows acceptance. |

Start the next implementation PR from current main with milestones 0 and 1. Design the durable identity/context contract alongside multi-session admission so that persistence does not require another session-system rewrite. Recover useful numerical verification opportunistically without blocking core runtime independence. Do not mark milestones complete without passing relevant tests and actual runtime evidence.

Existing Python solvers, plugin management, evidence/revision records and job APIs should similarly be reused before adding new scientific services. Changes requiring significant UI redesign need owner approval.

## 4. Primary tool surface (target)

Generic tools: execute Python/authorized commands; list/read/write/edit project files; inspect installed library APIs; discover solvers; request dependencies; search documentation; inspect artifacts; render visualizations; manage jobs. Exact tool names and schemas should be designed around concrete execution and security requirements.

The normal workflow is a single LLM deciding what to do next after actual tool feedback. Long computation batches may be delegated to numerical algorithms; the LLM need not participate in every solver iteration. Avoid one API per narrowly prescribed engineering task. Use typed interfaces where they improve correctness or ergonomics, while keeping the general code path available.

## 5. Transition from existing code

- Retain plugin management, numerical backends, model revisions, journals, independent verification and artifacts. Retain LangGraph for TUI and CLI; the Proliferate-based desktop uses Pi as its sole LLM loop. The existing Python CLI/TUI are first-party development surfaces, not external Agents; their eventual Pi convergence is separate work. Remove the retired WinUI and WPF clients and their build infrastructure.
- Generalize existing sandbox code beyond the special AC reference workflow; use secure implementation and fail closed on unsupported platforms. Do not equate dependency/process isolation with OS-level isolation.
- Review existing specialist policies as optional tools, isolate benchmarks from the primary chat flow, and avoid adding new mandatory controllers. Do not delete verified implementation before migration and tests.
- PR #11 is merged; old PRs #6 (retired WinUI workbench), #7 (independent physics verification) and #8 (fixed AC research loop) are closed without merging. Preserve their source branches/commits. Recover useful scientific verification and reproducible fixtures via [Issue #12](https://github.com/kevenhu001-cyber/GridAgent/issues/12) and fresh main-based PRs. #7 and #8 had failed prior CI; #6 passed on its old branch but is architecturally obsolete. Do not restore retired UI or default expert-system behavior.
- Keep previous research benchmarks as historical or optional experiments with explicit scope, not acceptance substitutes for unseen-task autonomous modeling.

## 6. Governance

Every substantial PR must satisfy [AGENTS.md](AGENTS.md) and the [architecture decision](docs/adr/0001-llm-first.md). A change that shifts research authority away from the LLM or limits general execution to fixed workflows requires explicit product-owner approval. Use real tests, do not conceal failures, and distinguish planned functionality from verified capability.
