# GridAgent — repository-wide development instructions

**Owner direction (2026-11-27): LLM-first, general-purpose engineering agent.**
These instructions apply to every contributor and coding agent throughout this repository. Read [ROADMAP.md](ROADMAP.md) and [the architecture decision](docs/adr/0001-llm-first.md) before planning changes. This direction supersedes conflicting historical plans, prompts, benchmark documents, and unmerged PR proposals. Do not treat a previous implementation or roadmap as authorization to expand an obsolete architecture.

## Product identity — non-negotiable

GridAgent is a coding/research agent for electrical engineering, power systems and energy storage, not an expert system with a chat front end. The LLM is the primary research and modeling agent. GridAgent supplies the tools, professional solvers, scientific programming environment, persistent project workspace, documentation, evidence and visualization that the LLM needs to solve unfamiliar engineering problems.

The LLM owns requirements interpretation, assumptions and clarification, mathematical/physical model formulation, code authoring, solver and algorithm selection, experiment design, diagnosis, debugging, revision and evidence-grounded synthesis. It decides the research trajectory within user authorization. Numerical libraries perform calculations and optimization; the runtime enforces permissions, executes tools, preserves evidence and enforces budgets. Verification can reject invalid evidence; it must not secretly choose a different engineering objective or replace the LLM's research decisions.

## Mandatory architectural rules

- Keep one primary LLM-led tool-use loop per session across the Proliferate-based desktop, TUI and CLI. No mandatory expert-rule router, task-specific state machine, separate trained policy or hardcoded research recipe may dictate the default path. Optional specialist tools must be explicitly discoverable and callable by the LLM, not implicit controllers.
- Prioritize general scientific code execution: LLM-authored Python, workspace-scoped file read/write/edit/list, isolated commands, library introspection, documentation retrieval, solver discovery, dependency requests, artifact inspection, job management and visualization. Do not require a new C#/Python feature or typed workflow for every new research problem.
- Expose professional libraries' native APIs inside a permission-scoped, OS-isolated scientific environment. Preserve typed convenience APIs and engineering IR as useful optional paths, not the exclusive modeling language. Avoid a universal IR that suppresses solver-specific functionality.
- Keep execution safe by design: explicit workspace/session authorization, read-only source imports, isolated working directories, bounded CPU/memory/time/process/output resources, cancellable execution, no ambient credentials, network disabled by default, explicit dependency/network approval, and no live equipment control. A subprocess, import allowlist or AST inspection alone is not a security sandbox. Never silently fall back to unrestricted host execution.
- Let the model write, run, inspect, revise and rerun code within its authorized scope without asking for approval for every ordinary operation. Escalate only when permissions or material engineering assumptions exceed the granted scope.
- Return actionable runtime errors, stdout/stderr, actual artifact references and relevant library documentation to the LLM; distinguish executed, inferred and unverified results. Preserve reproducible model/code revisions, inputs, versions, solver logs, output artifacts, and independently checked evidence where available.
- Keep numerical optimization, deterministic verifiers, caching, task recovery, parallel numerical execution and plugin management as reusable infrastructure. Domain rules, fixed candidate policies, trained rankers and predefined benchmarks are optional research tools or historical experiments, not primary agent intelligence.
- The owner-approved desktop migration uses the preserved Proliferate Tauri/React workbench, with Pi as the first-party Agent engine. Pi is the only supported desktop Agent, not one choice among multiple harnesses. Retire all external Agent launch, installation, discovery, authentication, selection and packaging paths (Codex, Claude Code, OpenCode, Cursor, Grok, custom ACP harnesses and similar). Do not retain an external-Agent fallback or compatibility mode. Reuse AnyHarness code only for useful non-Agent infrastructure and event/session contracts; do not wrap Pi in another autonomous LLM loop. Multiple model providers and first-party Pi sessions remain supported. Use Pi's official SDK and direct custom-tool registration, no mandatory MCP, preserve Pi's default coding tools (read, write, edit, bash, platform PowerShell and discovery tools) and add scientific tools rather than replacing general coding capabilities. Use scoped filesystem operations and OS-isolated shell execution, never an unrestricted host shell or untrusted extension autoload. Reuse the existing GridAgent Python scientific execution core, local-first project files and on-demand solver plugins through a first-party native scientific runtime with versioned persistent IPC; MCP may remain an optional third-party tool protocol or standalone interoperability surface, but must never reintroduce external Agent hosting or be the core path. Do not build a parallel custom desktop shell or nest a second LLM loop. The owner requires removal of both WinUI and WPF source and build pipelines; recover historical code from Git only. This does not waive new desktop acceptance gates. See [migration ADR](docs/adr/0002-proliferate-desktop.md) and [native runtime ADR](docs/adr/0003-native-scientific-runtime.md).

## Mandatory UI design contract

Follow [docs/ui-design.md](docs/ui-design.md) for every native UI change. ChatGPT-inspired neutral, minimal, content-first design is an owner requirement, not optional styling. Reuse the selected Proliferate design system; do not introduce inconsistent layouts, ornamental gradients or nested cards. Preserve accessibility and visible evidence provenance. Real visual acceptance requires Windows screenshots and interaction checks; do not claim fidelity based only on source code.

## Mandatory reuse-first migration (owner clarification, 2026-11-28)

Preserve the existing Proliferate UI and mature non-Agent infrastructure. Before proposing or implementing a feature, inspect the vendored source, existing GridAgent code, contracts and tests; identify the existing component, data owner, reusable backend and actual missing capability. Consult [the reuse inventory](docs/proliferate-reuse-audit.md). Classify each item as KEEP, ADAPT, ADD or RETIRE. Do not treat a missing Pi binding as a missing UI feature.

- KEEP existing layout, visual tokens, model picker, API-key settings and dialogs, session/tab/sidebar/transcript UI, composer, file browser/editor, tools presentation, keyboard shortcuts, themes and accessibility. Reuse behavior and state contracts where compatible, not merely styling.
- ADAPT at existing data/transport seams. Feed the retained model selector from Pi models/providers; route existing credential forms to a local secure vault; map Pi lifecycle and public events into existing session directory, outbox and transcript contracts. Reuse storage, persistence and workspace infrastructure when its dependencies and security permit.
- ADD only demonstrated missing behavior (e.g. scientific artifact viewers, Pi transport, scoped compute and Windows-specific security/release support). No second chat store, independent model picker, replacement settings pane, separate file browser or duplicate session database without an explicit documented incompatibility and owner approval of a material UI redesign.
- RETIRE external Agent executables, installers, selectors, authentication and launch paths, not their reusable provider-neutral UI or non-Agent infrastructure. Preserve old session data read-only when needed; never silently relaunch an external Agent.
- The temporary NativePiChat/NativePiChatGate and PiConversation preview UI/state have been removed from this branch. ChatView is restored to the Proliferate baseline. Use the typed Pi event adapter and existing directory, ingest and transcript contracts; do not reintroduce the preview UI or a duplicate product conversation store. Production Pi cutover is not yet complete.
- Every implementation PR must identify reused paths, adaptation seams, genuinely new gaps and retirement scope. Explain any new UI component, durable store or service by concrete unmet requirements; no broad visual changes without separate owner approval. Validate interactions and desktop builds before calling migration complete.

## Open-source-first infrastructure

Before adding general infrastructure, inspect existing repository capabilities and mature upstream libraries. Prefer existing implementations, then maintained dependencies via their documented APIs, and write only the GridAgent-specific adapter. Avoid duplicating package managers, sandbox engines, kernel protocols, databases or renderers. Record license, Windows support, maintenance, dependencies, distribution and security implications; pin release dependencies and test them. Heavy optional capabilities must not increase the base install unnecessarily. Replacements require compatibility and security regression tests; never weaken isolation or add a second Agent loop. See [infrastructure reuse plan](docs/infrastructure-reuse.md).

## Review and implementation discipline

Before opening or merging a PR, ask: does this increase the LLM's ability to solve an engineering problem that the developers did not anticipate? Prefer reusable tools and safe native-library access over adding a hardcoded domain procedure. If a solver-specific adapter is useful, justify its scope and show that it does not block general code execution.

Every substantial PR must document: (1) LLM capability enabled, (2) ownership of engineering decisions, (3) execution/permission boundary, (4) real tests and limitations, (5) how the change avoids expanding mandatory expert-system logic. For a research feature, include an unseen-task or held-out benchmark when applicable; never claim real numerical performance from mock tests or replay projections.

Do not merge the former expert-system direction wholesale. Review old modules and PRs against this policy, preserve reusable tested components, isolate or retire the rest after checking dependencies. No mass deletion without migration and regression evidence. The owner must explicitly approve any change to this product direction; record it in an ADR and update this file and the roadmap together.

## Current priority

1. General isolated scientific execution and persistent workspace.
2. Native solver API access and versioned documentation/introspection.
3. LLM-led long-horizon tool loop with error recovery, context, cancellation and provenance.
4. Generic scientific artifacts and visualization in the Proliferate-based desktop.
5. Unseen engineering task benchmarks and real end-to-end validation.
6. Optional domain accelerators only after the core platform supports them.

The general execution environment is a target capability, not a claim that existing sandbox support already meets all requirements. Consult current code and report gaps honestly.
