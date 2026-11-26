# Native simulation backends

GridAgent uses mature solver libraries rather than implementing electrical
equations itself. ANDES remains the dynamic and small-signal backend.
pandapower uses its native create_* API, element tables, runpp and calc_sc.
PyPSA uses Network.add and Network.optimize with HiGHS. Install the engineering
extra for developer integration tests. Windows Core bundles ANDES and pandapower;
PyPSA is an optional first-party plugin. See [plugins](plugins.md).

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
static generators, storage, two-winding transformers and switches, edit selected native element table fields,
inspect built-in cases (14/39/118), perform AC load flow or IEC 60909 maximum
three-phase fault current with valid model data. A parent_run references an
existing pandapower run; its validated construction steps are replayed with
additional changes. Up to 200 total operations and 500 buses. Persist input,
audit, model JSON and CSV tables. Base models use pandapower IDs, not ANDES IDs.

PyPSA: fixed-capacity hourly dispatch for up to 168 hours with buses,
loads, generators, renewable availability, cyclic storage and directional
links and passive intra-voltage-level transmission lines. Native HiGHS optimization; save generation, storage dispatch/SOC,
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
The manual draft viewer leaves the sandbox open and its outputs available for
inspection. The separate verified Python workflow generates and retries scripts
with workspace opt-in, controls the sandbox lifecycle, and compares structured
output to a native reference. See [verified research tasks](research-tasks.md).

## Automatic quality checks and authorized repair

Every native run now produces quality.json and returns the independent local
quality verdict. PP checks distinguish solvability/coverage and operating
voltage/loading limits; PyPSA checks demand preservation, nodal power balance,
component limits and cyclic storage dynamics from actual exported tables.
These are local engineering screening checks, not original PowerAgentBench.
Ordinary chat receives failing checks and can retry within the shared budget;
it must not change fixed user requirements merely to pass.

For an explicit automatic loop run gridagent --model-repair MANIFEST.json
(or /model-repair in TUI, Benchmark and repair in Windows). The manifest locks
the original program and lists authorized numerical leaf paths. An initial run
and at most five repair proposals are allowed. Invalid and duplicate proposals
consume the repair budget, never execute. Demand, topology, operation and
criteria remain locked; only explicitly listed existing numeric leaves can
change. Ratings/capacity changes require explicit manifest authorization and
are a design variant, not proof the original system was correct. Best tested
candidate is retained with all artifacts. The policy sees feedback, not hidden
paper test labels. Original licensed DMQ uses its existing upstream evaluator;
these native tests do not replace it. The verified Python workflow uses a
separate bus-level numerical contract and independent reference. No LLM weight
updates or guaranteed convergence.

### Fixed modeling benchmarks

Run gridagent --modeling-benchmark two-bus or storage-dispatch (TUI also
supports /modeling-benchmark TASK). The LLM starts from a natural-language
specification, builds a typed model, receives evaluator feedback and revises
up to six attempts. Exact required inputs are checked before the solver runs.
The independent reference uses a closed-form two-bus AC voltage or the
analytic optimum of a lossless four-hour storage arbitrage case. No expected
numeric answers are injected into the policy prompt. These are public,
small developer regression benchmarks, not held-out paper tests or a
comprehensive measure of general Agent intelligence. The original paper
workflows remain available separately.

Additional public regression tasks: source-short-circuit (IEC 60909 at a known source),
lossy-storage (80% charging efficiency), and lossy-link (directional 80% efficient
transfer with renewable availability and backup generation). All use fixed inputs and
independent analytic reference checks, never supplied as answer values to the model.
These do not constitute an unseen-task test set.

### Verified engineering experience

Successful authorized native repairs are indexed in local experience.sqlite3 only
if the baseline and best run both converged, the original model failed a quality
check, the final model passed, model hashes and locked fields match, and both
saved numeric evidence sets reproduce the original evaluator verdict. The index
stores check IDs, change direction, backend/version and provenance IDs, not raw
model parameters or rationale. It is not tamper-proof. Fixed modeling benchmarks
and paper protocols are excluded. Subsequent failures receive up to five matching
historical records, which are hypotheses, not permission to alter the model or
proof of success. New runs must pass the independent evaluator again.
View entries via --experience, /experience or Windows Engineering experience.
This is retrieval-based experience learning, not weight training.
