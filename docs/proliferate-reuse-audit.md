# Proliferate reuse audit — GridAgent desktop

Owner direction, 2026-11-28. Source-level inspection of PR #11 at
`78a6c57b5376529eb478e79866d2a4dece135a25`. This is an implementation
inventory, not proof of desktop runtime readiness. Preserve the upstream
design and interaction contracts; replace only incompatible dependencies.
Paths below are relative to `vendor/proliferate/apps/packages/product-client/src/`
unless otherwise stated.

## Classification

| Area | Existing implementation | Disposition and remaining gap |
| --- | --- | --- |
| Model picker | `components/workspace/chat/input/ComposerModelSelectorControl.tsx`, `ComposerModelPickerPopover.tsx`, `hooks/chat/facade/use-chat-model-selector-state.ts` | KEEP controls, grouping, search, keyboard navigation and provider icons. ADAPT facade/catalog and existing settings navigation callbacks to Pi providers/model IDs, not external harnesses. |
| API-key settings | `components/settings/panes/agents/api-keys/ApiKeysPane.tsx`, `components/settings/panes/agent-auth/ApiKeyCreatorModal.tsx` | KEEP existing pane layout, rows, modal, error and confirmation patterns. ADAPT cloud SDK queries/mutations and authenticated control-plane gate to local credential service. Existing UI is not proof of Pi-compatible storage. |
| Local credential/config infrastructure | Desktop `src-tauri/src/commands/keychain.rs`, `src-tauri/src/app_config.rs` | ADAPT existing keyring worker and config mechanisms. Native keyring currently protects AnyHarness data key; provider credentials also use JSON files with Unix 0600, not Windows encryption. ADD narrowly scoped provider credential API backed by verified OS credential protection or equivalent authenticated encryption; no plaintext fallback, no generic secret-return command, no credential logging. Nonsecret model metadata only in normal config. Do not silently migrate or delete old keys. |
| Chat UI | `components/workspace/chat/ChatView.tsx`, `input/ChatInput.tsx`, `input/ChatComposerDock.tsx`, `input/ComposerRichTextEditor.tsx`, `surface/SessionTranscriptPane.tsx` (paths under chat) | KEEP existing UI, interaction, attachments where supported, accessibility and input behavior. ADAPT runtime facade; temporary NativePiChat/NativePiChatGate removed; restore integration via original contracts. |
| Message rendering | `components/workspace/chat/transcript/AssistantMessage.tsx`, `UserMessage.tsx`, `MarkdownBody.tsx`, `ChatTranscriptView.tsx`, `VirtualizedTranscriptRowList.tsx` | KEEP existing rendering, Markdown, scrolling, search and streaming affordances. ADAPT public event projection rather than writing another message list. |
| Sessions, outbox and recovery | `stores/sessions/session-directory-store.ts`, `session-transcript-store.ts`, `session-ingest-store.ts`, `session-intent-store.ts`, `hooks/sessions/workflows/`, `lib/access/anyharness/sessions.ts`, `session-runtime.ts` | KEEP state and interaction contracts, session identities, outbox and existing reducers where compatible. ADAPT runtime operations and Pi event mapping. Existing renderer stores are in-memory; inspect underlying persistence ownership before implementing durable Pi session history/context. Do not confuse transcript persistence with full model/tool context restoration. |
| Workspace and navigation | `components/workspace/shell/screen/StandardWorkspaceShell.tsx`, `WorkspaceContentView.tsx`, `components/workspace/shell/sidebar/`, `tabs/`, `topbar/`, `hooks/workspaces/cache/use-workspaces.ts` | KEEP shell and workspace navigation. ADAPT workspace list/identity and file transport where currently dependent on AnyHarness. Existing workspace path must match native grants; no cross-workspace context leakage. |
| File browsing/editing and terminal | `components/workspace/files/`, `components/workspace/search/`, `components/workspace/terminals/`, `components/workspace/git/`, `lib/access/anyharness/workspace-file-transport.ts` | KEEP existing components and applicable non-Agent services. ADAPT scoped operations; distinguish interactive user terminal from Agent sandbox shell. Do not create replacement generic file manager/editor/terminal. Detailed backend and component audit required before changing each path. |
| Tool activity and artifacts | `components/workspace/chat/tool-calls/`, `transcript/TranscriptToolCallItemBlock.tsx`, `TranscriptToolCallGroupBlock.tsx`, `components/workspace/files/` | KEEP tool presentation and existing artifact/file preview patterns. ADAPT sanitized Pi event contracts, tool identity, execution state and artifact references. ADD scientific plot/topology/equation/result viewers only for verified representation gaps; no raw tool payload or hidden reasoning. |
| General settings / theme | `components/settings/panes/GeneralPane.tsx`, `AppearancePane.tsx`, `components/settings/screen/`, `sidebar/` | KEEP existing layout, appearance and shared primitives. ADAPT navigation and copy where obsolete external Agent/cloud entries are removed. |
| External Agent management | `components/settings/panes/agents/harness/`, `components/agents/AgentLoginTerminalPanel.tsx`, AnyHarness launch/discovery/auth/seed paths | RETIRE external executable hosting after dependency audit. Reuse generic provider/model controls and non-Agent services rather than deleting useful shared UI. No new external Agent fallback. |
| GridAgent scientific execution | Root `src/gridagent/`, native scientific IPC, Pi tool registry | KEEP verified solver, plugin, workspace, job, evidence and artifact implementation. ADAPT native permission and execution wiring; ADD only missing safe general execution, result viewers, documentation and validated solver capability. |
| Windows release | Retained Tauri baseline and existing build infrastructure | ADAPT existing packaging/build paths, audit runtime dependencies, verify actual Windows installation and security. No separate desktop shell or redundant packaging system without demonstrated need. |

## Implementation order

The model-picker/provider UI and original Home/workspace session admission, outbox, transcript and tab adapters were merged in #11. They remain opt-in development-mode integrations, not a verified production desktop. The temporary preview UI and duplicate state were removed; do not reintroduce them. Follow the ordered [active roadmap](../ROADMAP.md#3a-desktop-baseline-and-active-execution-order-2026-11-28): stabilize main/Windows compile, isolate multiple native sessions, reuse durable history/context storage, detach workspace/file services from Agent lifecycle, retire remaining external Agent paths, and qualify real Windows packaging. Add only missing scientific-specific UI atop existing surfaces. Prove credential protection, workspace isolation and true model context recovery, not just UI rendering.

## Review checklist

Every implementation change records existing source and tests inspected;
KEEP/ADAPT/ADD/RETIRE classification; reason for any new UI/store/service;
compatibility with existing interaction/state contracts; test evidence and
remaining limits. Existing code is not necessarily usable on Windows or by Pi.
Do not claim completion solely from mocked IPC, component existence or
Python/Node unit tests. Major UI redesign requires owner approval.
