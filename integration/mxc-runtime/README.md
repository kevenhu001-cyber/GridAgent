# MXC VM backend qualification (stage 2)

This is a developer-only, separately installed adapter spike for Microsoft MXC
1.1.0 (MIT), not a production sandbox replacement. The existing
`scientific_runtime.py` / `verified_python.py` paths remain unchanged. No Agent,
renderer, project data or provider credentials enter the qualification tool.
The first-party native service and Pi stay on Node 22; this isolated test uses
Node 24.21+ because the upstream SDK requires Node 24.

## Run

On a disposable Windows 11 x64 machine with the Windows Sandbox optional
feature enabled and hardware virtualization available, install Node 24.21.0
or a compatible Node 24 release. Run from this directory:

```powershell
npm install --no-audit --no-fund --omit=optional
npm test
npm run qualify -- --experimental-vm
```

The direct SDK dependency is pinned to 1.1.0. A generated npm lock must be
reviewed and committed before release integration; this spike is not a
reproducible production bundle. Do not run on a machine with sensitive data
or an unrelated active Windows Sandbox instance. Do not enable privileged
features automatically. The manual CI VM job may fail if hosted Windows
runners lack the Sandbox feature; that is a failed qualification, not a pass.

## Why the current runtime remains the default

- [MXC 1.1.0 release](https://github.com/microsoft/mxc/releases/tag/v1.1.0)
  exposes the experimental VM through exact JSON APIs. Use its pinned
  [VM contract](https://github.com/microsoft/mxc/blob/v1.1.0/docs/backends/windows-sandbox/windows-sandbox.md)
  and explicit experimental authorization, not process isolation as fallback.
- Unlike the existing guest paths, the MXC backend maps directories at the
  same host path. The future adapter must adjust the trusted bootstrap and
  preserve immutable snapshots and separate writable outputs.
- One VM per logon session, no lifecycle idle watchdog, and best-effort
  teardown require an ownership-aware recovery design. Never force reclaim
  a potentially foreign sandbox. A successful fixture is not proof of
  confirmed cleanup after hard kill.
- The experimental backend uses a guest firewall; its documented policy
  rejects explicit network sections. Actual network denial must be tested.
- Existing 4 GiB memory budget, process/resource and output limits,
  cancellation, workspace grant revocation and durable recovery must be
  verified before switching any production path.

## Acceptance gates

| Gate | This slice |
| --- | --- |
| Fixed SDK version and VM policy construction | Implemented; CI tests pending |
| Real read-only input, writable output and unshared host-file denial | Explicit fixture runner; real VM run pending |
| Network, UI, credentials, child processes and reparse-point adversarial tests | Pending |
| Python/ANDES/pandapower and optional plugin DLLs in VM | Pending |
| 4 GiB memory cap, bounded output, cancellation and grant revocation | Pending |
| Crash/timeout, foreign VM ownership, durable job recovery | Pending |
| Signed relocatable runtime and clean-machine installation | Pending |

The next migration slice must reuse existing job IDs, journals, snapshot and
artifact validation, and replace only the sandbox adapter after equivalent
or stronger boundaries are demonstrated. No host fallback, no implicit
process-container downgrade, no new Agent loop or UI.
