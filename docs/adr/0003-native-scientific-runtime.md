# ADR 0003: First-party scientific runtime

Accepted direction by product owner, 2026-11-28. Supersedes the core MCP
transport decision in ADR 0002; does not supersede its Proliferate design
baseline or ADR 0001 (LLM-first research).

## Decision
Scientific workspace, solvers, execution, knowledge, artifacts and verification
are product-owned capabilities, not external integrations. Tauri/Rust owns
process lifecycle, permissions, task identities and event delivery. Python
retains the numerical implementation and isolated execution boundary.
AnyHarness supplies model and session infrastructure. Native scientific tool
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
environment variables. Python service has no execution or mutation endpoint.
Desktop TypeScript client calls Tauri directly.

## Next gates
1. Integrate workspace selection and packaged runtime discovery in the host.
2. Provide a separate, authorized task/write lane with run cancellation,
   events, durable job IDs and recovery. Preserve sandbox fail-closed behavior.
3. Inspect AnyHarness adapter/session tool registration, implement native
   scientific tool routing for a verified adapter, and test with actual LLM
   calls. External CLI providers may require compatibility adapters.
4. Use the same native service for solver management, documentation, evidence
   and scientific viewers; keep large results out of the LLM context.
5. Remove upstream cloud/telemetry/update dependencies and verify Windows build,
   sandbox isolation, user permissions and end-to-end modeling.

No performance improvement, agent-native tool invocation, or Windows runtime
acceptance is established by the initial IPC implementation.
