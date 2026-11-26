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

## Architecture

Textual TUI or CLI → LangGraph decision loop → validated tools and budget guard → isolated ANDES solver → waveform CSV and deterministic voltage metrics.

- Only packaged Kundur research system and bounded fault parameters are allowed.
- Solver runs in a separate process with a timeout and per-run working directory.
- Tool calls are executed sequentially. Attempted power flow and fault simulations consume budget.
- Each run stores solver logs and result files under .gridagent/runs.
- Solver non-convergence is not evidence of physical instability. The normalized voltage metric is a proxy, not the full paper evaluator.
- TUI supports multi-turn conversation in memory; persistent sessions, API and graphical UI are planned.

## Roadmap

1. Verify real ANDES integration and tool loop in CI.
2. Add project configuration, audit records and persistent sessions.
3. Add DSR case retrieval, explicit candidate budgets and hidden offline evaluator.
4. Implement DMQ with model-specific parameter whitelist, baseline tests and rollback.
5. Add FastAPI event API, interactive waveform viewer and graphical research workspace.
6. Add native provider adapters, MCP and optional licensed simulators.

## Development

    pip install -e '.[dev,andes]'
    pytest -m 'not integration'
    pytest -m integration

The unit test simulator is a test double and must never be represented as a real simulation. See docs/architecture.md for the research boundaries.
