# GridAgent / Proliferate integration — phase 1

The desktop baseline is the preserved Proliferate 0.4.27 monorepo at
`vendor/proliferate/`, imported from the public mirror
https://github.com/kumpraj/proliferate at commit
`7c95cc94974290dbf06251e0f4a6db446ac18a47`.
Preserve the upstream LICENSE, notices and provenance. The imported snapshot
is AGPL-3.0; GridAgent's existing GPL-3.0-or-later files retain their notices.
Review combined distribution and network-source obligations before release.

## Architecture

Proliferate's Tauri/React desktop and AnyHarness own the conversation,
provider selection and general Agent lifecycle. GridAgent supplies the Python
scientific runtime as a workspace-scoped MCP server, not another LLM Agent.
The owner requested removal of WinUI and WPF; historical code remains in Git history.

## Developer connection (manual first)

From the GridAgent root, in a Python virtual environment:

```sh
python -m pip install -e ".[core,mcp]"
python -m gridagent.mcp_server --workspace /absolute/path/to/existing/workspace
```

The process speaks MCP over stdin/stdout; do not launch it as a web server.
In Proliferate's MCP integration settings (or the selected harness's local MCP
settings), register the absolute Python executable and arguments from
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
A terminal-capable external harness must also be configured to disallow
unrestricted host execution of generated scientific code.

## Acceptance gates

- Import and verify the source tree and license.
- Run the real stdio protocol and permission regression tests.
- Build the desktop locally and register the MCP server in an actual harness.
- Validate workspace selection, cancellation, permission prompts and data boundaries.
- Remove upstream cloud endpoints, update channels, telemetry and trademark
  assets from the distributable application; retain original attribution.
- Integrate charts, tables, topology and scientific artifacts into the existing
  design system. Do not create a second unrelated desktop shell.
- Verify Windows packaging and real native solver runs before distributing the new desktop.

No desktop end-to-end test or sandbox implementation is claimed by this phase.
