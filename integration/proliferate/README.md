# GridAgent / Proliferate integration

## First-party native integration (current direction)

[ADR 0003](../../docs/adr/0003-native-scientific-runtime.md) supersedes core MCP. The initial native protocol (read-only by default) is implemented in `src/gridagent/native_service.py` and registered in the Tauri host; the production read lane does not expose model-generated writes or execution. Debug builds can explicitly opt into the job and write lane with GRIDAGENT_NATIVE_TASKS=1; the existing workspace grant is independently required. For developer-only testing set absolute `GRIDAGENT_NATIVE_PYTHON` (installed Python interpreter) and `GRIDAGENT_NATIVE_WORKSPACE` (optional legacy development root) before starting the desktop. Install `.[core]` in that interpreter. In Pi development mode, the existing Add an existing folder picker now registers canonical local roots in a host-owned per-user registry; the renderer can list those opaque IDs but cannot register an arbitrary path. Up to 32 disjoint roots are supported, and each Pi worker receives only its selected root. Agent-visible files live in that root’s `scientific-project/` subdirectory; sibling and parent files are not implicitly imported. The legacy environment root remains discoverable during migration. `scientific_read` is the direct Tauri command; the TypeScript client lives in `apps/desktop/src/lib/access/scientific/client.ts` inside the vendor tree. The host retains the child for successive requests and discards failed connections without replay. The developer task lane supports hash-guarded source writes (48,000 characters within the 64 KiB frame), stable job IDs, a detached trusted worker, polling and cooperative cancellation. Lost connections never automatically re-execute a job. Interrupted job journals conservatively block further native submissions until recovery is implemented. Packaged runtime discovery, interrupted-job recovery, push events and production permission UI remain pending. The existing scientific execution grant is not enabled by folder registration; new projects remain blocked from scientific file operations until the user separately enables that grant.

## Windows desktop build check

The [root Windows workflow](../../.github/workflows/windows-desktop.yml) builds
the retained frontend, compile-checks the Tauri host and test targets, and starts
the installed Pi worker against the Python scientific service without a provider
request. Run the desktop build checks from `vendor/proliferate` on Windows x64
with Node 22.19.0, pnpm 10.11.0, stable Rust with the MSVC x64 target and the
Windows SDK:

```powershell
pnpm install --frozen-lockfile
pnpm --filter proliferate build
cargo check --locked --target x86_64-pc-windows-msvc -p proliferate --tests
cargo test --locked --target x86_64-pc-windows-msvc -p proliferate --lib pi_history::tests
```

These commands qualify the development build inputs. Production acceptance also
requires retiring external Agent launch and seed paths, replacing the upstream
updater configuration, bundling private runtimes and testing the signed installer
on a clean Windows machine.

## Historical MCP integration (optional external compatibility)

The desktop baseline is the preserved Proliferate 0.4.27 monorepo at
`vendor/proliferate/`, imported from the public mirror
https://github.com/kumpraj/proliferate at commit
`7c95cc94974290dbf06251e0f4a6db446ac18a47`.
Preserve the upstream LICENSE, notices and provenance. The imported snapshot
is AGPL-3.0; GridAgent's existing GPL-3.0-or-later files retain their notices.
Review combined distribution and network-source obligations before release.

## Architecture

The target desktop embeds Pi as its sole Agent engine with direct scientific tool registration. The first-party worker and the retained chat integration are available in development mode. Production cutover still requires removing the remaining external Agent hosting, installation, discovery, authentication, selection and packaging paths. The historical MCP instructions below cover standalone interoperability with the existing workspace-scoped scientific tool server.
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


## Standalone scientific project file transport (milestone 3)

The native scientific IPC now exposes `workspace.tree`, `workspace.search`
and `workspace.inspect` for the already granted `scientific-project`
directory. They reuse the existing project path, size, link and revision
constraints; neither the caller nor the model supplies an arbitrary root.
The desktop scientific client maps these to the retained SDK file response
shapes and assembles bounded text pages only if their SHA-256 revisions agree.
Binary files expose metadata, not decoded content. Native project commands
now require a distinct host-issued ID derived from the canonical configured
workspace. Read and existing-file save share that identity; save additionally
requires the original SHA-256 revision, scientific grant and explicit task
opt-in. No renderer-supplied root and no fallback to an AnyHarness workspace
are allowed. The project namespace is the scientific-project subdirectory,
not the surrounding repository. This is a typed transport foundation, not a
replacement file browser or a generic filesystem. The existing product file
tree and editor are not yet routed to it: selection and cache identity must
be adapted together, and unsupported create/rename/delete and host-open
operations must not fall through to the legacy path.

The retained SDK file hooks and ProductClient cache/reload/lookup paths now
accept a typed host-native file capability for reserved scientific project IDs.
They keep the existing query keys, file tree and editor behavior. Missing
capabilities and unsupported native mutations fail closed, never using the
legacy connection. The selection/inventory flow still needs to introduce these
IDs into the product; this is a transport cutover seam, not a standalone
workspace UI or proof of interactive desktop behavior.

Native Pi development inventory can now discover the single configured host
project and project its reserved ID into the existing local/logical workspace
list. Selection revalidates that identity against the host; Pi receives the
configured authorization root while the retained file-path context resolves the
scientific-project subdirectory. This avoids requiring an AnyHarness inventory
row for this development workspace. This is still a single configured root,
not a general directory picker or multi-project registry. Other startup gates,
Git, creation/rename/delete and external Agent lifecycle remain to be migrated;
interactive desktop acceptance is pending.

Native file mutations now reuse the retained create/rename/delete hooks and
cache invalidation. Creation requires an existing parent and refuses case-folded
name collisions; file rename/delete recheck a SHA-256 observed just before the
operation. Directory rename/delete are restricted to empty directories; no
recursive deletion, replacement of existing targets, or case-only rename.
All mutations require the same host project identity, task opt-in and grant.
The existing project lock coordinates GridAgent writers; it is not a defense
against arbitrary concurrent filesystem changes from external programs.
