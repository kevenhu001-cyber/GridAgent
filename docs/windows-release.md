# Windows packaging and release

## Scope

The root GitHub Actions workflows are independent of the vendored Proliferate
release infrastructure. Existing compile checks remain unchanged. This first
milestone produces **unsigned x64 packaging previews**, not a usable production
GridAgent distribution. Packaged Windows builds initialize Pi from host-owned Tauri resources, with
bundled Node and CPython 3.11, locked Pi dependencies, core scientific
libraries, Jupyter Client/IPyKernel and nbformat. Docling and other large
managed plugins remain optional; MXC remains qualification-only. The staging script checks imports and offline Node/Python handshake
from a relocated path. Fixed trusted kernel and notebook fixtures also run
with the relocated private interpreter; the CI log reports runtime component
bytes, dependency versions and fixture timings. These are not cold GUI startup
or actual VM timings. Clean-machine validation, dependency locking for Python,
managed-agent seed support and code signing remain release blockers. The Windows diagnostics
collector is unsupported upstream. Do not enable the debug gate in release
builds or publish a draft as stable to work around these limitations.

## Build a preview

Run **Windows installer preview** from Actions with the desired branch.
Changes to the packaging workflow/scripts also trigger it in PRs.
A successful build uploads one MSI, one NSIS setup EXE and SHA256SUMS.txt in
`gridagent-windows-x64-preview`. Artifacts are retained for 14 days. The source
of the preview installer version is the Python project version in pyproject.toml.
The packaging script sets the GridAgent product identity in the disposable
checkout, without changing the upstream UI or enabling its updater feed.

## Draft a release

After reviewing and merging the workflows, push a version tag matching
pyproject.toml (currently `v0.1.0`) on a commit reachable from main:

```sh
git tag v0.1.0
git push origin v0.1.0
```

The release workflow validates the tag, invokes the same Windows package job,
verifies checksums, and creates a draft prerelease with generated notes and
both installers. It never publishes a stable release or overwrites an existing
release. Manual dispatch is supported on a matching tag only.

## Production acceptance gates

- Validate the staged runtime, installation resource layout and core solver
  imports on the Windows runner; pin Python transitive dependencies before stable.
- Verify installed native Pi using a real provider and the existing OS picker,
  local credential store, per-project execution grant and Windows Sandbox.
  No arbitrary host execution is permitted.
- Verify fresh Windows installation, launch, real Pi tool call, scientific solver
  invocation, uninstall and update isolation; verify application identity and icon.
- Review upstream cloud/deep-link/telemetry behavior and provide GridAgent-owned
  update configuration and signing. Publish only after these gates pass.
