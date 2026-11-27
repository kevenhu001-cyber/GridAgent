# GridAgent / Proliferate integration

## First-party native integration (current direction)

[ADR 0003](../../docs/adr/0003-native-scientific-runtime.md) supersedes core MCP. The initial native protocol (read-only by default) is implemented in `src/gridagent/native_service.py` and registered in the Tauri host; the production read lane does not expose model-generated writes or execution. Debug builds can explicitly opt into the job and write lane with GRIDAGENT_NATIVE_TASKS=1; the existing workspace grant is independently required. For developer-only testing set absolute `GRIDAGENT_NATIVE_PYTHON` (installed Python interpreter) and `GRIDAGENT_NATIVE_WORKSPACE` (existing explicitly chosen directory) before starting the desktop. Install `.[core]` in that interpreter. `scientific_read` is the direct Tauri command; the TypeScript client lives in `apps/desktop/src/lib/access/scientific/client.ts` inside the vendor tree. The host retains the child for successive requests and discards failed connections without replay. The developer task lane supports hash-guarded source writes (48,000 characters within the 64 KiB frame), stable job IDs, a detached trusted worker, polling and cooperative cancellation. Lost connections never automatically re-execute a job. Interrupted job journals conservatively block further native submissions until recovery is implemented. Packaged discovery, user workspace selection, agent registration, push events, explicit recovery and UI remain pending.

## Historical MCP integration (optional external compatibility)

The desktop baseline is the preserved Proliferate 0.4.27 monorepo at
`vendor/proliferate/`, imported from the public mirror
https://github.com/kumpraj/proliferate at commit
`7c95cc94974290dbf06251e0f4a6db446ac18a47`.
Preserve the upstream LICENSE, notices and provenance. The imported snapshot
is AGPL-3.0; GridAgent's existing GPL-3.0-or-later files retain their notices.
Review combined distribution and network-source obligations before release.

## Architecture

The target desktop embeds Pi as its sole Agent engine with direct scientific tool registration. Reuse Proliferate UI and only useful non-Agent/session infrastructure from AnyHarness. External Agent hosting, installation, discovery, authentication, selection and packaging must be removed. Pi integration and the external-Agent code removal remain pending. The historical MCP instructions below describe standalone interoperability outside the desktop, not a supported desktop Agent connection. GridAgent supplies Python scientific capability; the original workspace-scoped MCP server remains available as optional external interoperability, not another LLM Agent.
The owner requested removal of WinUI and WPF; historical code remains in Git history.

## Developer connection (manual first)

From the GridAgent root, in a Python virtual environment:

```sh
python -m pip install -e ".[core,mcp]"
python -m gridagent.mcp_server --workspace /absolute/path/to/existing/workspace
```

The process speaks MCP over stdin/stdout; do not launch it as a web server.
In an independent MCP client outside GridAgent, register the absolute Python executable and arguments from
`mcp.example.json`. Replace both placeholder paths before use.
This is a conventional stdio MCP configuration example, not a verified
Proliferate configuration-file schema. Actual UI registration and transport
compatibility must be verified in the desktop build.

Enable the existing scientific execution grant explicitly from the GridAgent
workspace configuration when needed. Never enable it on behalf of the user.
The optional `--allow-native-solvers` argument exposes the typed simulation
program tool; it still requires that existing grant. General Python execution
uses only GridAgent's existing isolated runtime, with no host fallback.

Use `agent-instructions.md` as the domain instruction text for the selected
harness or project. Do not inject provider credentials into MCP arguments.
This standalone interface does not authorize GridAgent to launch or manage external Agent processes.

## Acceptance gates

- Import and verify the source tree and license.
- Run the real stdio protocol and permission regression tests.
- Build the desktop locally and register native scientific tools in the embedded Pi SDK; test MCP separately for compatibility.
- Validate workspace selection, cancellation, permission prompts and data boundaries.
- Remove upstream cloud endpoints, update channels, telemetry and trademark
  assets from the distributable application; retain original attribution.
- Integrate charts, tables, topology and scientific artifacts into the existing
  design system. Do not create a second unrelated desktop shell.
- Verify Windows packaging and real native solver runs before distributing the new desktop.

No desktop end-to-end test or sandbox implementation is claimed by this phase.
