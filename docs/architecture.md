# Architecture and research contract

The paper defines a task as (O, A, E, C, G, M): observation, action, environment, constraints, hidden evaluator and optional semantic memory. GridAgent separates the probabilistic decision layer from deterministic engineering calculations and policy.

## First milestone

- O: structured simulation output, voltage extrema, waveform artifact, error status.
- A: list/inspect packaged cases, power flow, bounded bus fault.
- E: ANDES, with each numerical run isolated in its own process and directory.
- C: fixed cases, typed inputs, per-task call and numerical-run budgets, solver timeout.
- G: deterministic post-fault voltage metrics; independent stability classifier and benchmark scoring are not implemented yet.
- M: TUI conversation history only; structured historical fault retrieval is planned.

The DSR paper protocol selects three of ten candidates and evaluates authorized mitigation configurations. Our initial tool loop is not the DSR benchmark. The original DMQ protocol permits only four REECAU1 gains and five iterations, and must preserve locked fields. Neither benchmark is claimed reproduced. Implement those as separate explicit workflow graphs with hidden ground truth unavailable to the model.

## Next interface

Use one transport-independent event contract (task ID, tool start/end, result artifact, budget, final report, error) for TUI and a native Windows WPF client over a local JSON-lines protocol. Do not display raw tool JSON or model chain-of-thought by default. User-visible diagnostic explanations must be grounded in recorded artifacts.

## References

- PowerAgentBench-Dyn: https://arxiv.org/abs/2606.20401
- Original benchmark: https://github.com/Power-Agent/PowerAgentBench
- ANDES time-domain API: https://docs.andes.app/en/stable/tutorials/04-time-domain.html
- LangGraph: https://github.com/langchain-ai/langgraph
- Textual: https://github.com/Textualize/textual
