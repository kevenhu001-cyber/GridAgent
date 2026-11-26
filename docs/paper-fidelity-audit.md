# Paper fidelity audit

Reviewed against PowerAgentBench-Dyn (arXiv:2606.20401, sections II–V)
and the public upstream dynamic level1/level2 artifacts on 2026-11-26.
GridAgent is a working open research prototype, not an original benchmark
reproduction. Keep open and original protocols separately versioned.

## General task contract

Implemented: bounded typed tool calls, feedback loops, isolated numerical runs,
manifest and prediction artifacts, per-study reservations, partial DSR resume,
local sessions, CLI/TUI/Windows frontend. Missing: common machine-readable
task package (O,A,E,C,G,M), arbitrary user-provided model cases, locked-file
hash verification, task-wide wall-clock enforcement, separate compliance
evaluator, multi-model ten-run aggregation and full agent engineering reports.

## DMQ (original level1)

Upstream:
https://github.com/Power-Agent/PowerAgentBench/tree/main/benchmarks/dynamic/level1
and cases/solar_wecc/psse. The upstream task has Solar.sav and Solar.dyr,
PSS/E 36.2, DMView 3.4, eight named tests, evaluator thresholds in
harness/criteria.json, actionspace.json, a DYR edit harness and trial driver.
Only REECAU1 bus 91003 machine S1, tokens 24–27, gains in (0,100], may change.
Five repair iterations. Tests: flat start; voltage down/up; frequency down/up;
HVRT; LVRT; graded SCR (5,3,1.5 graded; 1.2 informational).

Current DMQ: independent two-channel PI surrogate, different eight tests
and thresholds; gains [0.05,100]; no SAV/DYR parse or write, real P/Q/frequency
or SCR criteria, independent locked-model audit, licensed simulator or original
test outputs. Current deterministic reference is not an original reference
solution. Proposed: integrate the original action contract and evaluator,
isolated per-run copies and exact structural diff; use separate licensed
Python environment compatible with PSS/E (upstream notes NumPy 1.x).
Do not replace the bundled open engine or bundle commercial software.

## DSR (original level2)

Upstream:
https://github.com/Power-Agent/PowerAgentBench/tree/main/benchmarks/dynamic/level2

Original: IEEE 39-bus PowerFactory, bus and line contingencies, training and
held-out semantic memory, MCP, freeze estimates, simulate top three, compare
estimates with observations, evaluate fresh SC configurations. The published
KPI script uses generator speed >1.05 pu in its recovery window as its
benchmark instability flag; not a universal physical-stability criterion.
It assigns unstable cases S=1. Original paper also requires bus locations
of voltage extrema, ranking, mitigation, time and compliance.

Current: Kundur bus faults only; memory matched by case, horizon, bus and
duration; no topology/operating-point representation, line faults, speed
channels, stable flag, or SC mitigation. The open IoV proxy clips per sample
and trapezoid-integrates from clearing. The released compute_kpis.py uses
right-sample time weights, clips the aggregate, and has a configurable
post-clearing offset (function and CLI defaults differ). Do not assume
numerical equivalence: freeze exact upstream version and parameters and use
golden waveform comparisons. Missing speed must be unknown in engineering
mode, not stable by default. Independent current evaluator scores only
top-k recall and severity MAE, not realized workflow compliance.

Proposed: versioned upstream KPI adapter, generator-speed/rotor-angle export,
explicit fault and topology model, fixed split with hidden evaluator,
measured-vs-predicted comparison, authorized SC placements (04/16/26, up to
two 250 MVA units) with fresh simulations and a separately configured budget.
Add PowerFactory/PowerMCP backend after validating the licensed environment
and original project. The original repository lists prebuilt memory and KPI
scripts; availability of the entire original PowerFactory project/raw data
has not been established.

## Priorities

P0: complete self-contained Windows distribution and separate simulator
profiles; importable task manifests, original asset provenance and licensing.
P1: independent original DMQ adapter/evaluator and original DSR KPI golden
tests; expand ANDES open cases separately.
P2: original DSR memory and tool protocol, physical channels and mitigation;
auditable action budgets and elapsed time.
P3: ten independent trials/model, aggregate success, errors, time and
compliance, compare deterministic baselines; integrate results in native GUI
and TUI. No web frontend.

Do not hardcode published answers into agent prompts or historical memory.
Reference results are evaluator-only. Verify upstream license before reusing
source or redistributing case data. Windows bundles open dependencies only.
