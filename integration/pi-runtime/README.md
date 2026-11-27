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
