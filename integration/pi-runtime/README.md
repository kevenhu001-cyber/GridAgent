# GridAgent embedded Pi runtime

This is the first-party Agent worker, built on the pinned Pi 1.6.0 SDK. It
does not invoke Pi CLI, Codex, Claude Code, OpenCode or MCP. Pi core owns
the LLM/tool loop; the native scientific service owns workspace and
execution permissions. The temporary independent native chat preview has been removed in favor of the original Proliferate chat components. Native worker and host bridge remain available for development; production chat is not yet connected.

## Development

Requires Node >=22.19.0 and a trusted installed GridAgent Python interpreter.
Install dependencies with npm install, then run npm test. Package versions
are pinned; transitive lockfile generation and reproducible packaging remain
release gates.

The worker reads JSON lines (prompt and abort) on stdin and emits public
text, tool status and terminal events on stdout. Configure it in the trusted
host environment: GRIDAGENT_NATIVE_PYTHON, GRIDAGENT_NATIVE_WORKSPACE,
GRIDAGENT_PI_PROVIDER (openai/anthropic/google), GRIDAGENT_PI_MODEL,
GRIDAGENT_PI_API_KEY. Do not log credentials. Developer task opt-in
GRIDAGENT_NATIVE_TASKS=1 does not bypass the existing workspace grant.

## Desktop development bridge

The debug Tauri host now exposes `pi_open`, `pi_prompt`, `pi_poll`, `pi_abort` and `pi_close` via the typed desktop `embeddedPi` client. Set `GRIDAGENT_PI_DEV=1`, `GRIDAGENT_PI_NODE` to an absolute Node executable and `GRIDAGENT_PI_WORKER` to the absolute installed `worker.mjs`, in addition to the trusted configuration above. The host returns a unique session ID from `pi_open`; pass it to every other command. Poll for protocol `ready` before prompting and keep polling through `settled`; tool IDs are separate from prompt IDs. The host admits one development session, validates and bounds public events, and never replays failed requests or launches an external Agent as fallback. The shared ProductClient DesktopBridge exposes the typed Pi capability; the original ChatView is restored and not yet wired to this capability. The selected local workspace must canonically match GRIDAGENT_NATIVE_WORKSPACE; pi_open repeats that check. Production packaging remains pending. The Rust host requires actual desktop compilation and integration testing.

## Tools

Pi's own read, edit, write, find, ls, grep, bash and PowerShell tools are
loaded through its public SDK factories. Read-only mode omits mutating
tools. Actual file I/O uses workspace-scoped native IPC; overwrites
require an observed revision. The initial grep adapter supports bounded
literal search; binary/image read and full upstream search semantics remain
pending. Large writes beyond the IPC frame budget fail rather than truncate.

Shell operations submit durable jobs to the existing Windows Sandbox
scientific runtime. They never start a host shell; requested shells must be
present in the guest. Shell changes apply to a run snapshot, not the durable
project. Use Pi write/edit for persistent source changes. Shell output is
currently a bounded final tail; live log streaming and artifact previews
remain pending. Sandbox availability and execution grants are required.

GridAgent scientific tools are registered directly on Pi core. No MCP
round-trip is required. The initial tool registry includes solver discovery,
scientific job control, project files, run listings and artifact reads.
No external executable extension discovery is enabled.

## Shared session controller

`ProductClient` now receives the typed native Pi capability via `DesktopBridge.pi`. The shared `PiSessionController` owns the host session ID, prompt ID, readiness, cancellation, event batches and settlement; it does not import Tauri or start any external Agent. `drainTurn` drives a future session transport consumer. The `PiEventAdapter` translates admitted prompts and public Pi events into existing SDK SessionEventEnvelope objects; it holds only active transport identity and sequence, not transcript history. Existing SDK reducers and stores remain the presentation authority. Node contract tests and a shared reducer test are provided. Full session lifecycle dispatch and live GUI integration are still pending.

## Model and credential data adapters

The pinned SDK model registry supplies OpenAI, Anthropic and Google chat
catalog metadata; `pi_list_models` runs a bounded credential-free discovery
process. The existing model picker contract is projected by
`buildPiModelSelector`; the original workspace composer model-selector facade now consumes this data in opt-in native mode, using the existing user-preference store and a reserved nonsecret map entry. Add provider / Settings route to the existing API Keys page. Explicit native session open accepts the selected provider/model and requires its stored credential. The original workspace composer now uses the native session dispatcher in opt-in mode; Home catalog and launch remain gated. Unknown mode refuses rather than launching an old Agent. The original API Keys settings pane, modal, rows and confirmation UI
are shared with an opt-in local credential data source in Pi development mode.
This source stores one key per supported provider using the existing serialized
keyring worker with Windows/macOS native features. The renderer can only list
configured status, write or delete; it cannot read secret values. Windows/macOS
credential backend tests and desktop compilation remain required. Explicit
developer environment configuration remains available for test runs; a stored
key takes precedence for the configured provider at worker startup. Removing
a local credential does not remotely revoke it or change an already-open
worker's credential. Linux secure-vault UI is unavailable, not a plaintext fallback.

## Native product session transport

`product-session.ts` binds an explicitly admitted native worker to the retained
session directory, transcript, ingest and prompt outbox stores. It consumes
the original prompt ID, reuses the existing stream reducer and stream patch
builder, and reconciles the outbox using the authoritative user-message echo.
The existing dispatcher and Cancel workflow recognize Pi session records;
legacy SSE/summary refresh does not attach to them. Only one live native
session is supported. Unsupported attachments/config interactions fail
explicitly. Disconnection/uncertain submission is not replayed. There is no
second conversation store. The existing workspace composer calls this materialization seam, enqueues into the original outbox and activates the original chat tab. Admission checks the host-authorized path and selection generation, retains drafts on pre-enqueue failure, and pins the running worker model. Native session dismissal closes an idle worker; pending sends prevent closure. This remains opt-in development mode, one worker, existing local workspace inventory, text-only prompts. No implicit recovery of a restored Pi session; durable history, Home launch, independent workspace inventory and production desktop validation remain open.

## Remaining integration

Follow the [reuse-first inventory](../../docs/proliferate-reuse-audit.md).
NativePiChat, NativePiChatGate and PiConversation were removed; do not reintroduce a parallel product UI or transcript store.
Adapt the existing session directory, prompt outbox, transcript ingest,
ChatView/ChatInput/SessionTranscriptPane, session persistence and model picker
contracts to Pi. Reuse the existing API-key settings and modal; adapt the
cloud-backed mutation layer to a Windows-safe local credential service.
Complete all launch-entry cutover,
remove the external Agent catalog, discovery, installer, launch and
authentication paths from the product, and verify real desktop and sandbox
execution. Current tests exercise SDK factories, dispatch, event projection
and mocked shell job responses; they are not real model or sandbox tests.
