# Native simulation backends

GridAgent uses mature solver libraries rather than implementing electrical
equations itself. ANDES remains the dynamic and small-signal backend.
pandapower uses its native create_* API, element tables, runpp and calc_sc.
PyPSA uses Network.add and Network.optimize with HiGHS. Install the engineering
extra; Windows packages all three libraries and verifies them after relocation.

    gridagent --backends
    gridagent --native-program examples/pandapower-two-bus.json
    gridagent --native-program examples/pypsa-storage.json
    gridagent --native-table RUN_ID res_bus

Agent tools accept typed programs, validate them and run them in independent
subprocesses. Each numerical attempt consumes one shared simulation budget.
The program is a declarative sequence of native API calls, not arbitrary
Python. There is no exec/eval or arbitrary import/path support. Subprocess
isolation is not an OS security sandbox.

pandapower: construct buses, external grids, lines, loads, PV generators,
static generators and storage, edit selected native element table fields,
inspect built-in cases (14/39/118), perform AC load flow or IEC 60909 maximum
three-phase fault current with valid model data. A parent_run references an
existing pandapower run; its validated construction steps are replayed with
additional changes. Up to 200 total operations and 500 buses. Persist input,
audit, model JSON and CSV tables. Base models use pandapower IDs, not ANDES IDs.

PyPSA: fixed-capacity hourly dispatch for up to 168 hours with buses,
loads, generators, renewable availability, cyclic storage and directional
links. Native HiGHS optimization; save generation, storage dispatch/SOC,
link flow and marginal prices. No capacity expansion, unit commitment or AC
network analysis yet. Cost units must be consistent across all inputs.
A non-optimal solver result is not an optimum.

Native table reads are bounded and restricted by backend. Existing paper
protocols are unchanged. The knowledge index derives contracts from tool
schemas, with native API keywords; upstream manuals have not been ingested.
Official references: https://pandapower.readthedocs.io/ and
https://docs.pypsa.org/. No automatic backend model conversion is implemented.

## Optional free-form Python drafting and execution

The Agent may save standalone Python drafts under drafts/ID/script.py. Drafts
are syntax checked but never executed by the host. The Windows client offers
Review Python draft, displays the exact source, and requires explicit approval
before launching a separate Windows Sandbox session. This requires a supported
Windows edition with the optional Windows Sandbox feature enabled and the
bundled runtime. No host-Python fallback. A fresh sandbox job maps only the
runtime and approved input read-only and a dedicated new output folder writable;
network, clipboard, printer, audio/video and vGPU redirection are disabled.
The user must close the sandbox when finished. Output files are untrusted and
are not automatically ingested or claimed as measured results. No automatic
arbitrary-code execution, sandbox result verification, or TUI launch yet.
The sandbox integration is untested on a virtualization-enabled Windows host.
