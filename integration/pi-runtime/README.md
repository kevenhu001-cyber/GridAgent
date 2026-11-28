# GridAgent embedded Pi runtime

This is the first-party Agent worker, built on the pinned Pi 1.6.0 SDK. It
does not invoke Pi CLI, Codex, Claude Code, OpenCode or MCP. Pi core owns
the LLM/tool loop; the native scientific service owns workspace and
execution permissions. The temporary independent native chat preview has been removed in favor of the original Proliferate chat components. Native worker and host bridge remain available for development; production chat is not yet connected.

## Development

Requires Node >=22.19.0 and a trusted installed GridAgent Python interpreter.
From this directory, install the locked worker dependencies and run the tests:

```sh
npm ci --ignore-scripts --no-audit --no-fund
npm test
```

The lockfile covers the development worker. Production packaging still needs
private Node and Python runtimes, solver dependencies and installer validation.
With GridAgent installed in the current Python environment, run
`python smoke_install.py` to exercise worker startup and the native IPC handshake.

The worker reads JSON lines (prompt and abort, with an optional startup text seed) on stdin and emits public
text, tool status and terminal events on stdout. Configure it in the trusted
host environment: GRIDAGENT_NATIVE_PYTHON, GRIDAGENT_NATIVE_WORKSPACE,
GRIDAGENT_PI_PROVIDER (openai/anthropic/google), GRIDAGENT_PI_MODEL,
GRIDAGENT_PI_API_KEY. Do not log credentials. Developer task opt-in
GRIDAGENT_NATIVE_TASKS=1 does not bypass the existing workspace grant.

## Desktop development bridge

The debug Tauri host exposes `pi_open`, `pi_prompt`, `pi_poll`, `pi_abort` and `pi_close` via the typed desktop `embeddedPi` client. Set `GRIDAGENT_PI_DEV=1`, `GRIDAGENT_PI_NODE` to an absolute Node executable and `GRIDAGENT_PI_WORKER` to the absolute `worker.mjs`, in addition to the trusted configuration above. The host returns a unique session ID from `pi_open` for use in subsequent commands. Poll for protocol `ready` before prompting and keep polling through `settled`. Tool IDs are separate from prompt IDs. Up to four live development workers may use independently registered host-authorized workspaces. The native folder picker adds projects to a bounded persistent registry; workers receive their selected canonical root, not a renderer-supplied path. The host bounds public events and rejects unauthorized paths and cross-session requests. Failed requests are never replayed. The original Home and workspace composers use this capability in development mode. See the [Windows desktop build check](../proliferate/README.md#windows-desktop-build-check) for compile validation.

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

`ProductClient` now receives the typed native Pi capability via `DesktopBridge.pi`. The shared `PiSessionController` owns the host session ID, prompt ID, readiness, cancellation, event batches and settlement; it does not import Tauri or start any external Agent. `drainTurn` feeds the retained product session transport. The `PiEventAdapter` translates admitted prompts and public Pi events into existing SDK SessionEventEnvelope objects; it holds only active transport identity and sequence, not transcript history. Existing SDK reducers and stores remain the presentation authority. Node contract tests and a shared reducer test are provided. The existing workspace and Home launch entry points and prompt/cancel dispatcher are adapted in development mode. Real GUI/provider verification and tool context restoration remain pending.

## Model and credential data adapters

The pinned SDK model registry supplies OpenAI, Anthropic and Google chat
catalog metadata; `pi_list_models` runs a bounded credential-free discovery
process. The existing model picker contract is projected by
`buildPiModelSelector`; the original workspace composer model-selector facade now consumes this data in opt-in native mode, using the existing user-preference store and a reserved nonsecret map entry. Add provider / Settings route to the existing API Keys page. Explicit native session open accepts the selected provider/model and requires its stored credential. The original workspace and Home composers use the same native model selection and session admission in opt-in mode, limited to existing authorized local workspaces. Unknown mode refuses rather than launching an old Agent. The original API Keys settings pane, modal, rows and confirmation UI
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
legacy SSE/summary refresh does not attach to them. Multiple live native
sessions are admitted up to the host bound (currently four worker processes,
each with its own scoped scientific service); every command stays keyed to
its own session ID. Unsupported attachments/config interactions fail
explicitly. Disconnection/uncertain submission is not replayed. There is no
second conversation store. The existing workspace composer calls this materialization seam, enqueues into the original outbox and activates the original chat tab. Admission checks the host-authorized path and selection generation, retains drafts on pre-enqueue failure, and pins the running worker model. Native session dismissal closes an idle worker; pending sends prevent closure. This remains opt-in development mode, bounded live workers sharing the existing authorized local workspace inventory, text-only prompts. Eligible pure-text sessions can continue after restart. Tool context, per-session workspaces, independent workspace inventory and production desktop validation remain open.

## Desktop history and text continuation

After reopening an authorized workspace, the existing session directory and tabs
show up to 12 recent Pi sessions from the current app profile. Each session is
keyed by its original ID and the canonical configured workspace. The transport
journal commits a prompt before worker dispatch and commits bounded public
events after observing settlement. A prompt without a settlement record
appears with an unknown outcome. Startup and history reads never dispatch that
prompt or a scientific job. Dismissing a session hides it from the recent
history and retains the underlying journal.

The profile stores public prompt and assistant text and tool status. Native
credential fields, hidden reasoning, tool arguments and raw provider responses
are excluded. The host redacts an exact occurrence of the active provider key,
including across streamed text chunks. The development limits are 1 MiB per
session and 256 KiB of public events per turn. An oversized turn remains
visible live, with its recorded prompt and unknown outcome on restore. Each
durable scientific job ID is recorded against its originating turn before
dispatch, so an interrupted turn can name the job it may have submitted and the
existing job-status tools can reconcile it. Tool-bearing model context remains
separate milestone 2 work; text-only continuation is unchanged.

## Remaining integration

Follow the [reuse-first inventory](../../docs/proliferate-reuse-audit.md).
NativePiChat, NativePiChatGate and PiConversation were removed; do not reintroduce a parallel product UI or transcript store.
The original session directory, outbox, transcript, model picker and API-key UI are already adapted in opt-in mode. Follow the current [roadmap](../../ROADMAP.md): qualify the Windows build, restore full model context, detach workspace/file services from Agent lifecycle, remove remaining external Agent launch/discovery/install/auth paths, then validate real Windows desktop and sandbox execution. Current tests exercise SDK factories, dispatch, event projection
and mocked shell job responses; they are not real model or sandbox tests.

### Home and workspace selection

In opt-in native mode the existing Home composer receives the same Pi picker props and persisted model selection as the workspace composer. Existing authorized standard local workspaces only: no Cowork/worktree/cloud creation or deferred Agent launch. Both entry points use submitPiWorkspacePrompt and the original outbox. Native workspace selection reuses the original selection and shell-intent stores without bootstrapping an external Agent session. Header tabs derive native slots from the existing directory and suppress the old runtime roster/hierarchy reads. The workspace inventory and file transport still depend on retained services. Standalone runtime migration and real desktop qualification remain pending.
