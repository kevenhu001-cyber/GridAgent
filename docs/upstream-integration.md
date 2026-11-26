# Original benchmark integration

Pinned source: https://github.com/Power-Agent/PowerAgentBench/tree/77fe638482af94dd20ce28bfa4301658660d283d
(MIT, copyright Power Agent). Build-time sync copies exact Git blobs and the
license into a local benchmark-assets directory. Only allowlisted assets are
included; test_memory.json and published solution/baseline files are excluded.
The original harness config contains reference constants; it is never exposed
to the ranking agent. No unrestricted upstream MCP tool is exposed.

The paper DSR ranking uses original ten fault definitions and original training
JSON, excludes exact target entries, and persists a structured prediction and
top-three ranking. This is a deliberately prediction-only stage until a licensed
PowerFactory backend is configured. Matching is location, fault type and duration,
not topology-aware semantic embedding. No benchmark success is reported.

Original KPI analysis invokes the published compute_kpis.py unchanged, with an
explicit recovery offset of 0.1 s; rejects missing generator-speed channels rather
than silently reporting stable. User supplies absolute clearing time and original
two-header PowerFactory CSV. The upstream instability threshold is a benchmark
rule, not a general certificate.

Original DMQ editing calls published dyr_tools.py in a separate process, checks
the target model identity, compares all non-gain spans and checks locked SAV
bytes. It writes an isolated case; no DMView execution yet. The actual licensed
DMView runner/evaluator and PowerFactory driver are staged for next integration,
not invoked by the user-facing Agent yet. Separate licensed simulator profiles
are required (PSS/E 36.2/DMView 3.4 and PowerFactory with compatible Python).
No commercial software is distributed. Windows remains native, TUI shares the
same commands and artifacts.
