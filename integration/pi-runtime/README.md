# GridAgent embedded Pi runtime

This is the first-party Agent worker, built on the pinned Pi 1.6.0 SDK. It
does not invoke Pi CLI, Codex, Claude Code, OpenCode or MCP. Pi core owns
the LLM/tool loop; the native scientific service owns workspace and
execution permissions. The Proliferate desktop session adapter has not
yet been switched to this worker.

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

## Remaining integration

Connect the trusted worker to the existing Rust desktop/session lifecycle,
persist and restore Pi sessions, configure user-owned model settings,
remove the external Agent catalog, discovery, installer, launch and
authentication paths from the product, and verify real desktop and sandbox
execution. Current tests exercise SDK factories, dispatch, event projection
and mocked shell job responses; they are not real model or sandbox tests.
