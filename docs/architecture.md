# GridAgent architectural direction

**Normative update, 2026-11-27:** [ADR 0001](adr/0001-llm-first.md), [AGENTS.md](../AGENTS.md) and [the active roadmap](../ROADMAP.md) govern future development. The LLM is the primary research decision-maker; runtime and numerical tools support it. Existing descriptions below are retained as implementation context, not authorization for mandatory specialist workflows.

## Purpose

GridAgent is a local, simulation-grounded power-system research workbench. Its long-term value is the LLM's ability to independently solve unfamiliar engineering problems using a reusable scientific execution environment, with reproducible evidence. A conclusion must be traceable to an input specification, model revision, solver run and evaluation evidence where applicable.

**Desktop target (ADR 0003):** Pi is the sole Agent engine; Proliferate is the presentation baseline. External Agent hosting, executable discovery, installation and launch are excluded. Reuse non-Agent AnyHarness infrastructure selectively. Model providers remain configurable.

## Current boundaries

| Layer | Responsibility | Existing implementation |
| --- | --- | --- |
| Presentation | Accessible conversation, workspaces, result inspection | Proliferate Tauri/React; scientific viewers pending migration |
| Application state | Transient message, task and artifact projection | Proliferate client state; typed scientific artifact contracts |
| Local transport | Request correlation, lifecycle, error boundary | First-party native IPC; optional standalone MCP interoperability |
| Application workflows | Planning, research execution, approval, repair | Agent, ResearchTasks, recorded_task |
| Engineering domain | Typed programs, validation, solver-independent evidence | native_program, research_spec, model_quality, model_revisions |
| Compute adapters | Translate bounded requests to solver-specific operations | pandapower, ANDES, optional plugins, external licensed adapters |
| Durable data | Immutable run artifacts, SQLite state, model revisions | workspace, store, research, model_revisions |

The TUI, CLI and planned Proliferate desktop share the Python domain and execution layer. No GUI code belongs in a solver adapter. A presentation component must never introduce a new solver or mutation pathway. The owner requires removing retired WinUI/WPF clients; historical versions remain in Git.

## Adopted decisions

1. **Read/execute separation.** Reuse a workspace-scoped read service only for allowlisted projection and metadata requests. Provider calls, solver execution, plugin changes and durable research mutations remain isolated. Separate cooperative cancellation from process reuse. Never automatically replay a mutation after an IPC failure.
2. **Evidence-backed presentation.** The versioned artifact contract projects verified persisted run data into typed, bounded UI structures. The LLM may select typed operations or author scientific code in an explicitly authorized isolated environment; it cannot submit arbitrary UI code or label invented chart data as measured. Solver completion, local quality evaluation and benchmark success must stay distinct.
3. **State before controls.** Extract interaction and domain projections into testable state models. Views render state and send user actions; they do not own durable business logic. Use the same pattern for task, plugin, model and settings pages rather than adding generic framework abstractions without a concrete use case.
4. **Immutable engineering evidence.** Preserve original solver input and results. Parameter edits create new revisions. An explicit user authorization is required for repairs or sandbox execution when the workflow requires it. Link revisions to parent runs and preserve solver provenance.
5. **Incremental rendering.** Reuse the Proliferate design system, platform themes and accessibility semantics. Virtualize lists, batch public text, lazily load charts and use native scientific drawing. Keep rendered previews bounded and label downsampling. Do not expose hidden reasoning, provider payloads, raw tool arguments or diagnostics.
6. **Plugin isolation.** Use a versioned capability/manifest model, typed parameter schemas, separate environments and verified results. Keep optional dependencies outside the base distribution. Prioritize general native API access in the authorized sandbox, with well-tested typed shortcuts where useful. Commercial adapters have explicit licensing and verification prerequisites.

## Earlier infrastructure milestones (implementation context; see active roadmap for priority)

| Milestone | Acceptance gate |
| --- | --- |
| Reliable desktop release | Latest CI, relocated private runtime, actual Tauri startup and accessibility, portable size and latency measurements |
| Shared artifact model | Extend schema to model revisions, studies, quality-check tables and charts; versioned fixtures and history replay; generic adapter registration without model-generated UI |
| Durable job orchestration | Stable request/job IDs, cancellation and terminal states, crash recovery, read-only inspection while jobs run; mutation serialization and no silent duplicate execution |
| Engineering model workspace | Domain-level schematic graph independent of UI layout; typed operation sequence, validation, undo/redo draft, immutable revision commit, export; no unsupported solver conversions |
| Solver and plugin capability registry | Machine-readable operation, input, output, dependencies, provenance and validation contracts; conformance tests and schema negotiation for third-party adapters |
| Research capability | Cross-domain benchmarks with held-out tasks; compare baselines, repair, memory and multi-role variants on reproducible solver evidence |
| Performance and release engineering | Actual startup/working-set/latency/frame measurements, memory pressure tests, portable and signed distribution, deterministic dependency audit |

Avoid prematurely adopting microservices, general distributed execution, a marketplace or a universal simulation language. Introduce a boundary only when independent testing, isolation, measured performance or extensibility justifies it. These are target milestones, not claims of implementation.

## Validation

The Python unit/integration suites check engineering behavior. Windows CI tests the Python scientific core and solver calls; Tauri desktop compilation, interaction and packaged runtime acceptance remain pending. Dedicated interactive Windows verification remains necessary for layout, accessibility, graphics, provider streaming, cancellation and responsiveness. Report measured figures with the test environment and distinguish amortized bridge timings from actual GUI cold startup.

## Distribution boundary
The new desktop packaging must ship a private Python runtime, preserve user workspaces outside immutable application resources, and verify dependency integrity, platform support and signing. Packaging and installation tests remain outstanding; the retired MSIX pipeline is not a release path.
