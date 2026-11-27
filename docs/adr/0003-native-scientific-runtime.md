# ADR 0003: First-party scientific runtime

Accepted direction by product owner, 2026-11-28. Supersedes the core MCP
transport decision in ADR 0002; does not supersede its Proliferate design
baseline or ADR 0001 (LLM-first research).

## Decision
Scientific workspace, solvers, execution, knowledge, artifacts and verification
are product-owned capabilities, not external integrations. Tauri/Rust owns
process lifecycle, permissions, task identities and event delivery. Python
retains the numerical implementation and isolated execution boundary.
Pi (https://github.com/earendil-works/pi, MIT) is the owner-selected first-party Agent engine. Embed its TypeScript SDK in a trusted local worker; Proliferate/AnyHarness supplies desktop presentation and optional external harness interoperability, not a second LLM loop around Pi. Native scientific tool
descriptors and calls must share one runtime contract with the desktop.
No nested LLM loop, no arbitrary host shell fallback.

Internal calls use a versioned persistent IPC contract. Use bounded control
messages, artifact IDs and paginated previews; benchmark binary/file-based
bulk data before choosing a format. MCP remains optional for external clients
or for external harnesses that cannot register native tools; compatibility
must be explicit, not the default core dependency.

## First milestone
A desktop-owned, workspace-bound native read lane with strict request IDs,
bounded frames, no shell, no automatic retry, and no credentials passed from
model or renderer. The development host selects Python and workspace through
environment variables. The default Python lane has no execution or mutation endpoint. A separately opted-in debug lane exposes hash-guarded writes and durable asynchronous jobs, still requiring the existing workspace grant.
Desktop TypeScript client calls Tauri directly.

## Next gates
1. Integrate workspace selection and packaged runtime discovery in the host.
2. Developer task/write lane with durable job IDs and cooperative cancellation is implemented; complete event delivery and explicit interrupted-job recovery, then enable only through authorized production host controls. Preserve sandbox fail-closed behavior.
3. Pin and integrate the official Pi SDK (`@earendil-works/pi-coding-agent` and related packages as needed). Register scientific functions directly via its custom tool interface, adapt Pi session events to the desktop event contract, and validate model tool calls. Disable unrestricted shell/filesystem tools and automatic discovery of untrusted executable extensions; use application-owned credentials and resources, scoped IPC, explicit grants and the existing OS sandbox. External CLI providers may require compatibility adapters.
4. Use the same native service for solver management, documentation, evidence
   and scientific viewers; keep large results out of the LLM context.
5. Remove upstream cloud/telemetry/update dependencies and verify Windows build,
   sandbox isolation, user permissions and end-to-end modeling.

No measured performance improvement, agent-native tool invocation, or Windows runtime
acceptance is established by the initial IPC implementation.
