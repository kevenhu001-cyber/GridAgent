# General research agent (first milestone)

The normal chat path uses the same LangGraph decision loop in native Windows,
TUI and CLI. It is no longer restricted to fixed DMQ/DSR commands. The paper
protocols remain isolated, including their model, evaluator and test-data rules.

## Models

Built-in ANDES cases: Kundur, IEEE14, IEEE39 (open ANDES model, not the paper's
PowerFactory project). User explicitly imports a trusted native ANDES workbook
using the Windows picker, /import-model PATH in TUI, or:

    gridagent --import-model my_case.xlsx
    gridagent --models

Files are copied under models/model-SHA256/case.xlsx. Each solver run uses a
fresh copy; hash mismatch is rejected. Workbook checks are size and structure
guards, not a security sandbox or electrical validation. Only trusted workbooks
should be imported; the worker performs actual ANDES setup on inspect_case.
Bus faults currently use numeric bus IDs; arbitrary named buses, RAW/DYR import,
custom scripts and arbitrary model edits are not supported. Agent cannot import
arbitrary local paths. Model names and numerical tool results may be sent to
the configured model provider.

## Agent tools

List models, inspect case/topology, baseline power flow, bounded hypothetical
PQ load scaling (0.5–1.5) and one existing line outage, eigenanalysis, bus fault,
research plan, run listing/reading, paginated network branch lookup, shortest branch-hop path, voltage waveform
statistics, fault comparison, power-flow comparison, and published training
history. Numerical attempts share one budget; read-only evidence calls share
the total tool-call limit. Model planning is prompt-guided, not a formal proof
of correctness. The plan is a visible persisted tool result; the agent may
revise it using observations. At the call limit it gets a final synthesis
without new tools.

Example questions:
- Inspect IEEE14 and identify connected components. Compare base voltages with
  a 10% PQ load increase and summarize the most affected buses.
- For Kundur bus 5 compare 80 ms and 160 ms faults with identical end time.
  Analyze the saved voltage channel and cite each run ID.

Topology uses in-service branch hops, not impedance/electrical distance.
Power-flow comparison is not a thermal or transient-stability certificate.
Fault voltage severity is an open proxy, not the paper's full stability KPI.
Fault comparisons require matching model hashes and end times; post-clearing
windows may differ. No live equipment operation is provided.
