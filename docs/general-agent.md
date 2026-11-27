# General research agent (first milestone)

**Implementation snapshot:** the target is the [LLM-first execution platform](adr/0001-llm-first.md). The limitations documented below describe current capability, not permanent restrictions on scientific modeling. General isolated code execution and native library access are priorities in the [active roadmap](../ROADMAP.md).

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


## Structured engineering retrieval and device scenarios

Inspired by Jia, Cui & Hug (IEEE TSG 2025, DOI 10.1109/TSG.2025.3589114).
Their public repository https://github.com/JarvisETHZ/LLM4Simulation contains
a supplemental ZIP without a declared license. No files from it are bundled.
The implementation derives function/option/dependency triples from registered
Pydantic tool schemas, plus curated local descriptions and dependency links.
The main LLM uses a structured query-planning tool, with separate function and
option queries. SQLite FTS5 BM25 (in-memory) provides lexical ranking, exact
identifier priority and a token-overlap fallback. Automatic failure feedback
returns the offending function's schema and relevant option triples. No vector
embeddings, separate retrieval LLM, raw PDF ingestion or measured retrieval
quality yet; this is an initial implementation, not reproduction of the paper.
The tool schema and policy remain the source of truth. Raw upstream manuals
and benchmark solutions are not indexed.

The model inspection saves a device catalog (PQ/PV/Slack) and the Agent can
retrieve it using list_model_devices. Scenario power flow accepts up to 20
distinct allowlisted edits: PQ p0/q0, PV p0/v0, Slack v0. Values are native
ANDES per-unit inputs; v0 is bounded to 0.8–1.2, other fields to -20..20.
Uniform load scaling is applied first, then explicit absolute overrides.
Only in-service existing devices can be changed; before/after values are
recorded. No workbook mutation, dynamic controller edits, equipment creation,
or general code execution is supported.


### Local reference packs

Use gridagent --import-knowledge examples/engineering-knowledge.json and
gridagent --knowledge (also TUI /import-knowledge and /knowledge or Windows
file picker). Curated JSON entries contain a type, function, optional option,
description, source, and version. SQLite stores deduplicated packs locally.
Retrieved references are separately labeled, never replace live tool contracts
or expand the action space. Only import material you may use and trust; matched
reference text is shared with the configured LLM. No external vector API is
required. This is structured pack import, not automatic PDF extraction.
