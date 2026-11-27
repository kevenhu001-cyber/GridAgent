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
- The owner-approved desktop migration uses the preserved Proliferate Tauri/React workbench and its external Agent harness. Reuse the existing GridAgent Python scientific execution core, local-first project files and on-demand solver plugins via scoped MCP. Do not build a parallel custom desktop shell or nest a second LLM loop. The owner requires removal of both WinUI and WPF source and build pipelines; recover historical code from Git only. This does not waive new desktop acceptance gates. See [migration ADR](docs/adr/0002-proliferate-desktop.md).

## Mandatory UI design contract

Follow [docs/ui-design.md](docs/ui-design.md) for every native UI change. ChatGPT-inspired neutral, minimal, content-first design is an owner requirement, not optional styling. Reuse the selected Proliferate design system; do not introduce inconsistent layouts, ornamental gradients or nested cards. Preserve accessibility and visible evidence provenance. Real visual acceptance requires Windows screenshots and interaction checks; do not claim fidelity based only on source code.

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
