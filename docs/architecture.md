# GridAgent architectural direction

## Purpose

GridAgent is a local, simulation-grounded power-system research workbench. Its long-term value is repeatable engineering workflows, not the number of model prompts, plugins, or UI controls. A conclusion must be traceable to an input specification, model revision, solver run and evaluation evidence where applicable.

## Current boundaries

| Layer | Responsibility | Existing implementation |
| --- | --- | --- |
| Native presentation | Accessible conversation, workspaces, result inspection | WinUI, Markdown/TeX, Win2D, topology inspector |
| Application state | Transient message, task and artifact projection | ConversationState, typed presentation DTOs |
| Local transport | Request correlation, lifecycle, error boundary | DesktopEngineClient, desktop_read_service v1, isolated legacy bridge |
| Application workflows | Planning, research execution, approval, repair | Agent, ResearchTasks, recorded_task |
| Engineering domain | Typed programs, validation, solver-independent evidence | native_program, research_spec, model_quality, model_revisions |
| Compute adapters | Translate bounded requests to solver-specific operations | pandapower, ANDES, optional plugins, external licensed adapters |
| Durable data | Immutable run artifacts, SQLite state, model revisions | workspace, store, research, model_revisions |

The TUI and Windows shell share the Python domain and execution layer. No GUI code belongs in a solver adapter. A presentation component must never introduce a new solver or mutation pathway. The legacy WPF is a temporary rollback implementation; remove it only after feature and runtime parity.

## Adopted decisions

1. **Read/execute separation.** Reuse a workspace-scoped read service only for allowlisted projection and metadata requests. Provider calls, solver execution, plugin changes and durable research mutations remain isolated. Separate cooperative cancellation from process reuse. Never automatically replay a mutation after an IPC failure.
2. **Evidence-backed presentation.** The versioned artifact contract projects verified persisted run data into typed, bounded UI structures. The LLM may select operations through typed tools; it cannot submit arbitrary UI code or authoritative numerical chart data. Solver completion, local quality evaluation and benchmark success must stay distinct.
3. **State before controls.** Extract interaction and domain projections into testable state models. Views render state and send user actions; they do not own durable business logic. ConversationState is the initial extraction. Use the same pattern for task, plugin, model and settings pages rather than adding generic framework abstractions without a concrete use case.
4. **Immutable engineering evidence.** Preserve original solver input and results. Parameter edits create new revisions. An explicit user authorization is required for repairs or sandbox execution when the workflow requires it. Link revisions to parent runs and preserve solver provenance.
5. **Native, incremental rendering.** Use WinUI controls, platform themes and accessibility semantics. Virtualize lists, batch public text, lazily load charts and use native scientific drawing. Keep rendered previews bounded and label downsampling. Do not expose hidden reasoning, provider payloads, raw tool arguments or diagnostics.
6. **Plugin isolation.** Use a versioned capability/manifest model, typed parameter schemas, separate environments and verified results. Keep optional dependencies outside the base distribution. Prefer a small number of well-tested capabilities per solver before broadening the catalog. Commercial adapters have explicit licensing and verification prerequisites.

## Next architectural milestones, in order

| Milestone | Acceptance gate |
| --- | --- |
| Reliable desktop release | Latest CI, relocated private runtime, real WinUI startup and accessibility, portable size and latency measurements; compare against WPF |
| Shared artifact model | Extend schema to model revisions, studies, quality-check tables and charts; versioned fixtures and history replay; generic adapter registration without model-generated UI |
| Durable job orchestration | Stable request/job IDs, cancellation and terminal states, crash recovery, read-only inspection while jobs run; mutation serialization and no silent duplicate execution |
| Engineering model workspace | Domain-level schematic graph independent of UI layout; typed operation sequence, validation, undo/redo draft, immutable revision commit, export; no unsupported solver conversions |
| Solver and plugin capability registry | Machine-readable operation, input, output, dependencies, provenance and validation contracts; conformance tests and schema negotiation for third-party adapters |
| Research capability | Cross-domain benchmarks with held-out tasks; compare baselines, repair, memory and multi-role variants on reproducible solver evidence |
| Performance and release engineering | Actual startup/working-set/latency/frame measurements, memory pressure tests, portable and signed distribution, deterministic dependency audit |

Avoid prematurely adopting microservices, general distributed execution, a marketplace or a universal simulation language. Introduce a boundary only when independent testing, isolation, measured performance or extensibility justifies it. These are target milestones, not claims of implementation.

## Validation

The Python unit/integration suites check engineering behavior. The .NET presentation contract tests verify state transitions and schema handling independent of XAML. Windows CI compiles WinUI and exercises relocated runtime protocols, optional plugins and real solver calls. Dedicated interactive Windows verification remains necessary for layout, accessibility, graphics, provider streaming, cancellation and responsiveness. Report measured figures with the test environment and distinguish amortized bridge timings from actual GUI cold startup.

## MSIX distribution boundary
The MSIX build wraps the same self-contained WinUI payload as the portable release, with no second application implementation. Package identity and signing are distribution concerns. The package uses full-trust desktop activation at medium integrity; application binaries and the embedded interpreter are read-only. Mutable plugin installations, settings and numerical caches use explicit user-local package storage. External research workspaces remain selectable, so users can retain evidence independently of package uninstall. A development signature is not a production trust claim.
