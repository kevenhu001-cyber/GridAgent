# ADR 0002: Proliferate-based scientific desktop

Status: Accepted direction, 2026-11-28; implementation and acceptance pending.
Supersedes only desktop-specific decisions in prior documentation; ADR 0001
remains normative for LLM-first scientific modeling and execution.

## Decision

Preserve the exact Proliferate 0.4.27 Git tree from public mirror
`kumpraj/proliferate`, commit `7c95cc94974290dbf06251e0f4a6db446ac18a47`,
at `vendor/proliferate`. It is AGPL-3.0. Retain notices and separately
track modifications. Do not use an unpinned mirror, upstream binaries,
cloud credentials or original updater channels in a GridAgent release.

Reuse Proliferate's Tauri/React desktop, shared design system and AnyHarness
where appropriate, not the previously proposed from-scratch Tauri shell.
The external harness is the sole LLM loop in the new desktop.
GridAgent provides local scientific tools and evidence through a bounded,
workspace-scoped MCP service. TUI/CLI can continue to use the
existing LangGraph loop without nesting it in the new harness.

## Transition and acceptance

1. Preserve source and verify provenance; remove the retired WinUI and WPF clients per owner direction. Keep TUI and CLI operational.
2. Test MCP transport, workspace grant and failure behavior.
3. Register MCP in an actual desktop harness and prove an end-to-end
   scientific workflow with real artifacts.
4. Rebrand the application, remove upstream telemetry/cloud/updater
   assumptions, and integrate existing scientific artifacts into the
   Proliferate design system. Review license and third-party assets.
5. Verify sandbox boundaries independently of harness terminal permissions,
   Windows builds/installer, and real scientific execution before releasing
   the new client. No release until acceptance.

See [integration guide](../../integration/proliferate/README.md).
