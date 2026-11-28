# Isolated Jupyter kernel (stage 3)

Adopt upstream [jupyter_client](https://github.com/jupyter/jupyter_client)
and [ipykernel](https://github.com/ipython/ipykernel) as optional Python
dependencies. No web server, second UI, new database or additional Agent
loop. The Pi development tool `execute_kernel_cells` reuses the current
native job submission, authorization, job ID and artifact reader. One job
runs up to eight ordered cells in one guest Python kernel. Variables persist
within the job; errors stop subsequent cells. Output is bounded plain text
with unverified provenance. The existing sandbox controls total runtime,
memory, snapshot, external network, cancellation and cleanup. A missing
kernel dependency or unavailable sandbox fails closed, never starts a host
kernel. Current kernel mode excludes managed plugin overlays.

Install `.[core,kernel]` into the trusted private sandbox Python runtime
using the established runtime provisioning process. This change does not
alter the Windows installer or make the extra mandatory. Guest loopback
ZeroMQ transport uses a fresh per-job connection file and explicit
interpreter-specific kernelspec; the connection is never exposed to the
renderer or Agent.

The existing `execute_python` remains the reproducible script path.
Read `kernel-results.json` via the normal artifact API after the durable
job finishes. The launcher and source are hashed in the existing snapshot.
No numerical result is independently verified by the kernel.

## Verification and limits

CI runs trusted fixed-cell integration fixtures on Linux and Windows, plus
authorization and job regression tests. These do not establish actual
Windows Sandbox compatibility. Validate guest Python DLLs, ZeroMQ loopback,
real ANDES/pandapower runs, network isolation, cancellation, output limits
and cleanup on a compatible Windows machine. The optional extra currently
uses bounded version ranges rather than a release lock. The kernel does not
persist across jobs or Agent turns. A later multi-turn implementation
requires qualified sandbox lifecycle, explicit session authority, idle and
resource budgets, interruption/restart, artifact snapshots and recovery.
Do not expose a live host kernel or weaken the existing VM boundary.
