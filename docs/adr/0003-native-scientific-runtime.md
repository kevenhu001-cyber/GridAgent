# ADR 0003: First-party scientific runtime

Accepted direction by product owner, 2026-11-28. Supersedes the core MCP
transport decision in ADR 0002; does not supersede its Proliferate design
baseline or ADR 0001 (LLM-first research).

## Decision
Scientific workspace, solvers, execution, knowledge, artifacts and verification
are product-owned capabilities, not external integrations. Tauri/Rust owns
process lifecycle, permissions, task identities and event delivery. Python
retains the numerical implementation and isolated execution boundary.
Pi (https://github.com/earendil-works/pi, MIT) is the owner-selected sole desktop Agent engine. Embed its TypeScript SDK in a trusted local worker; Proliferate supplies desktop presentation; reuse AnyHarness only for non-Agent infrastructure and event/session contracts when useful, not as a multi-harness manager or second LLM loop around Pi. External Agent hosting (Codex, Claude Code, OpenCode, Cursor, Grok and custom harnesses) is retired by owner decision. No external-Agent fallback. Native scientific tool
descriptors and calls must share one runtime contract with the desktop.
No nested LLM loop, no arbitrary host shell fallback.

Internal calls use a versioned persistent IPC contract. Use bounded control
messages, artifact IDs and paginated previews; benchmark binary/file-based
bulk data before choosing a format. MCP may remain an optional external tool protocol or standalone interoperability surface; it is not a means to host external Agents and is never a core dependency.

## First milestone
A desktop-owned, workspace-bound native read lane with strict request IDs,
bounded frames, no shell, no automatic retry, and no credentials passed from
model or renderer. The development host selects Python and workspace through
environment variables. The default Python lane has no execution or mutation endpoint. A separately opted-in debug lane exposes hash-guarded writes and durable asynchronous jobs, still requiring the existing workspace grant.
Desktop TypeScript client calls Tauri directly.

## Reuse-first clarification (owner, 2026-11-28)

Proliferate's existing product behavior is the baseline, not just its visual
style. Follow the [reuse inventory](../proliferate-reuse-audit.md) and repository
contract: adapt existing model picker, credential settings, chat/session
state, workspace and tool-rendering contracts to Pi; do not build parallel
generic product features. Native preview components are temporary qualification
adapters and must converge on the original UI. Reuse the existing keychain
worker when suitable; do not reuse plaintext provider-secret files as secure
Windows storage. The credential UI currently depends on a cloud vault and
must be adapted without retaining that cloud dependency solely for convenience.

## Next gates
1. Integrate workspace selection and packaged runtime discovery in the host.
2. Developer task/write lane with durable job IDs and cooperative cancellation is implemented; complete event delivery and explicit interrupted-job recovery, then enable only through authorized production host controls. Preserve sandbox fail-closed behavior.
3. Pin and integrate the official Pi SDK (`@earendil-works/pi-coding-agent` and related packages as needed). Register scientific functions directly via its custom tool interface, adapt Pi session events to the desktop event contract, and validate model tool calls. Preserve Pi default coding tools and bind their operations to the authorized workspace and isolated shell, without unrestricted host execution. Disable automatic discovery of untrusted executable extensions; use application-owned credentials and resources, scoped IPC, explicit grants and the existing OS sandbox. Remove external Agent discovery, catalogs, installer, seed bundles, launch routes, authentication and selection UI after the dependency audit. Fail closed on unsupported Agent launch requests, including stale persisted settings and deep links. No external binary fallback if Pi fails. Keep separate model-provider configuration.
4. Verify only Pi can create/resume desktop Agent sessions; preserve old session data read-only if conversion is unsupported. Remove external Agent installation and executable packaging, and test that no external executable launches. Use the same native service for solver management, documentation, evidence
   and scientific viewers; keep large results out of the LLM context.
5. Remove upstream cloud/telemetry/update dependencies and verify Windows build,
   sandbox isolation, user permissions and end-to-end modeling.

No measured performance improvement, agent-native tool invocation, or Windows runtime
acceptance is established by the initial IPC implementation.
