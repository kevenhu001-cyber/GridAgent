# GridAgent

An open-source, simulation-grounded agent for power-system dynamics and engineering research, inspired by [PowerAgentBench-Dyn](https://arxiv.org/abs/2606.20401).

**Status: early development.** Independent implementation; not an official reproduction or production grid-control system.

## Quick start

Python 3.11–3.13. Install the editable package in a virtual environment:

    python -m venv .venv
    source .venv/bin/activate
    pip install -e '.[andes]'
    export GRIDAGENT_MODEL='your-tool-capable-model'
    export GRIDAGENT_API_KEY='your-key'
    export GRIDAGENT_BASE_URL='https://openrouter.ai/api/v1'  # optional; omit for OpenAI
    gridagent

On Windows PowerShell use .venv\Scripts\Activate.ps1 and $env:VARIABLE='value'.

One-shot mode:

    gridagent --budget 3 --ask "Inspect the Kundur case, run power flow, and simulate a 100 ms fault at bus 5."

The API key is local and must not be committed. Only OpenAI-compatible providers are supported in this milestone; native Anthropic and Gemini adapters are planned.

## Local sessions

    gridagent --sessions
    gridagent --session <full-id>
    gridagent --workspace ./research --ask "Run a baseline power flow"

In the TUI, use /sessions, /open ID and /new. The local workspace contains
research.sqlite3 and solver artifacts; keep sensitive project data private.
Failed tasks retain their audit events but are not replayed into model context.
A process crash may leave an unfinished task; automatic mid-task resume is not yet implemented.

## Dynamic risk screening (open baseline)

    gridagent --dsr examples/dsr-kundur.json

Or type /dsr examples/dsr-kundur.json in the TUI. Resume an interrupted frozen
DSR study using gridagent --resume-dsr STUDY_ID. This ranks ten candidate
faults, freezes estimates, and attempts only the selected three simulations.
See [DSR protocol and offline evaluation](docs/dsr.md) for limitations.

## Dynamic model quality review (open surrogate)

    gridagent --dmq

Or type /dmq in the TUI. Eight numerical tests on a fixed synthetic PI model,
with four permitted gains and at most five repair proposals. Every accepted
proposal triggers a new suite. See [DMQ protocol](docs/dmq.md). This is not
the original WECC/DMView benchmark.

## Scientific workspace

    gridagent --eigen
    gridagent --optimize 24
    gridagent --sweep 5 0.04 0.08 0.12
    gridagent --runs
    gridagent --study STUDY_ID
    gridagent --wave RUN_ID CHANNEL

See [workspace commands](docs/workspace.md) for TUI and offline result inspection.

## Native Windows desktop

GridAgent also has a native WPF/.NET 10 client (no Web UI, Electron or browser
server). The portable Windows build bundles CPython and numerical dependencies;
no user Python setup is intended. See [Windows setup and build](docs/windows.md). TUI and Windows use
the same Python engine and can share a local workspace.

## Architecture

Native Windows WPF / Textual TUI / CLI → LangGraph decision loop → validated tools and budget guard → isolated ANDES solver → waveform CSV and deterministic voltage metrics.

- Only packaged Kundur research system and bounded fault parameters are allowed.
- Solver runs in a separate process with a timeout and per-run working directory.
- Tool calls are executed sequentially. Attempted power flow and fault simulations consume budget.
- Each run stores solver logs and result files under .gridagent/runs.
- Solver non-convergence is not evidence of physical instability. The normalized voltage metric is a proxy, not the full paper evaluator.
- TUI and CLI persist local sessions, tasks and audit events in SQLite. DSR stage recovery is supported; general checkpoint recovery remains planned.

## Roadmap

1. Verify real ANDES integration and tool loop in CI.
2. Add project configuration, audit records and persistent sessions.
3. Add DSR case retrieval, explicit candidate budgets and hidden offline evaluator.
4. Implement DMQ with model-specific parameter whitelist, baseline tests and rollback.
5. Develop native Windows desktop workspace and interactive scientific charts (no Web frontend).
6. Add native provider adapters, MCP and optional licensed simulators.

## Development

    pip install -e '.[dev,andes]'
    pytest -m 'not integration'
    pytest -m integration

The unit test simulator is a test double and must never be represented as a real simulation. See docs/architecture.md and docs/benchmark-roadmap.md for the research boundaries.

## Original paper assets

`python scripts/sync_benchmark.py benchmark-assets` stages the pinned MIT-licensed
PowerAgentBench source, case files and training memory (not test memory).
`gridagent --paper-rank` freezes estimates for the ten original cases;
`gridagent --paper-kpi CSV CLEARING_S` calls the original KPI implementation;
`gridagent --paper-edit Kqp Kqi Kvp Kvi` creates an isolated, verified Solar model edit.
Paper ranking alone is prediction-only. Optional licensed adapters are available via
--paper-dmq PROFILE and --paper-dsr PROFILE; see docs/upstream-integration.md.
They require dedicated installed simulator environments and are not yet license-tested. Windows bundles these assets.

## General research agent

The default chat now supports recorded engineering plans, user-approved ANDES
workbook registration, Kundur/IEEE14/IEEE39, topology inspection, branch-hop
paths, existing-run retrieval, waveform analysis and fingerprinted comparisons.
Use `gridagent --import-model case.xlsx`, `gridagent --models`, then ask a
research question in chat. The Windows file picker and TUI share the registry.

General chat can also compare hypothetical steady-state scenarios with bounded
uniform PQ load scaling and one in-service branch outage, without modifying the
original workbook. See [general agent](docs/general-agent.md) for boundaries.

## Native simulation libraries

Install `.[core]` for the default ANDES/pandapower Windows runtime.
The full developer extra `.[engineering]` includes PyPSA; production installs it on demand. The normal agent can compose typed
native simulation programs and read result tables; `--native-program FILE.json`
also runs them offline. See [native backends](docs/native-backends.md).

### Simulation plugins

Use the native **Simulation Plugins** window or `gridagent --plugins`,
`gridagent --plugin-install pypsa`, `gridagent --plugin-remove pypsa`.
Optional managed backends: PyPSA, OpenDSS, PyBaMM, pvlib, windpowerlib, CVXPY, Pyomo, CasADi, PYPOWER, PyPowSyBl, OSQP, scikit-rf, CoolProp and rainflow. Tools and curated prompts are
bound on the next chat turn, without restarting the application. See [plugin design](docs/plugins.md).
