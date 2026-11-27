# GridAgent

<img src="desktop/branding/gridagent-logo.webp" alt="GridAgent logo" width="220">

Developed by **TopoDrive**. Lead developer: **Adex Hu**.

An open-source **LLM-first scientific coding agent for power systems, electrical engineering and energy storage**. GridAgent provides the scientific workspace, professional solvers, documentation, execution and visualization; the LLM formulates models, writes code, designs experiments and interprets results.

**Product direction:** not an expert system with an AI front end. General-purpose isolated scientific execution and native solver API access are the highest-priority development goals. Read [AGENTS.md](AGENTS.md), the [active roadmap](ROADMAP.md) and [ADR 0001](docs/adr/0001-llm-first.md) before contributing. Existing fixed workflows are optional research tools. The [scientific workspace preview](docs/scientific-workspace.md) adds opt-in Python execution on Windows; real sandbox acceptance and stronger resource controls remain pending.

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

## Verified research tasks

In Windows, expand **Workspace and model settings** to save a model name and
OpenAI-compatible base URL and test the connection. The key stays in the running
application session. In the TUI, type `/model` or press `Ctrl+P`, including when
starting offline.

```text
gridagent --research "Check AC bus voltages for the IEEE14 base case and a 10% load increase"
gridagent --research-manifest examples/power-flow-research.json
gridagent --research-tasks
gridagent --research-resume TASK_ID
gridagent --research-report TASK_ID report.json
```

The Windows **Run research task** button and TUI `/research` command use the same
engine. Choose **Run with multiple agents**, `/research-multi`, or
`--research-mode multi` for the specialist workflow. The Tasks view can resume,
cancel, submit clarifications, approve proposed repair ranges and export JSON.
See [verified workflow and experiments](docs/research-tasks.md) for the model
contract, references, sandbox, external runtimes and public benchmarks.

## Proliferate desktop migration

The new desktop direction reuses the preserved Proliferate 0.4.27 Tauri/React workbench rather than starting another interface from scratch. GridAgent's scientific Python tools are exposed through an optional local MCP server; the external harness owns the LLM loop. See [integration setup and acceptance gates](integration/proliferate/README.md). This migration is not yet a validated desktop release.

## Native Windows desktop (legacy during migration)

GridAgent has a native WinUI 3 Windows client (no Web UI, Electron or browser server). The older WPF implementation remains temporarily for regression comparison. The portable Windows build bundles CPython and numerical dependencies;
no user Python setup is intended. See [Windows setup and build](docs/windows.md). TUI and Windows use
the same Python engine and can share a local workspace.

## Architecture

Native WinUI / Textual TUI / CLI → LLM-led LangGraph tool loop → scoped scientific workspace and execution runtime → professional numerical libraries → artifacts, logs and independent verification → LLM.

The current chat path supports typed native solver tools and script drafting. General autonomous Python execution is a target capability, not yet available through the normal chat loop. Numerical attempts are bounded and saved locally; solver non-convergence is not proof of physical instability.

## Roadmap

The [active LLM-first roadmap](ROADMAP.md) prioritizes general sandbox execution, persistent projects, native API access, versioned documentation, long-horizon agent capability, scientific visualization and unseen-task validation. Specialized benchmark and diagnostic workflows are optional, not the primary product architecture.

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

### Architecture

See [GridAgent architectural direction](docs/architecture.md) for the native workbench, execution boundaries, evidence-backed presentation contracts, and long-term acceptance gates.
