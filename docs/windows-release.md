# Windows packaging and release

## Scope

The root GitHub Actions workflows are independent of the vendored Proliferate
release infrastructure. Existing compile checks remain unchanged. This first
milestone produces **unsigned x64 packaging previews**, not a usable production
GridAgent distribution. Native Pi is explicitly debug-only today; Python and Node
installation/resource discovery, managed-agent seed support, clean-machine
validation and code signing remain release blockers. The Windows diagnostics
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

- Bundle a locked Node/Pi worker and a relocatable Python environment with the
  intended solver dependencies; verify resource discovery without developer PATH.
- Enable native Pi via a reviewed production runtime configuration, not debug flags;
  verify workspace authorization, credential isolation and native service startup.
- Verify fresh Windows installation, launch, real Pi tool call, scientific solver
  invocation, uninstall and update isolation; verify application identity and icon.
- Review upstream cloud/deep-link/telemetry behavior and provide GridAgent-owned
  update configuration and signing. Publish only after these gates pass.
