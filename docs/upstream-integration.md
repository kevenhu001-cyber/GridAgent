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
bytes. It writes an isolated case; no DMView execution yet. The licensed runner/evaluator and driver have separate adapters described below. Separate licensed simulator profiles
are required (PSS/E 36.2/DMView 3.4 and PowerFactory with compatible Python).
No commercial software is distributed. Windows remains native, TUI shares the
same commands and artifacts.

## Licensed DMQ adapter

`gridagent --paper-dmq PROFILE.json` invokes the original DMView runner and
independent evaluator in a licensed PSS/E Python, using a dedicated DMView
installation. It refuses existing RESULTs contents, makes a scratch case,
checks locked fields and reruns the original eight tests after each validated
LLM edit, at most five proposals. A simulator error stops the workflow.
This adapter is not yet tested with licensed software. The ordinary Windows
open mode still needs no external Python. See examples/paper-dmq-profile.json.

## Licensed DSR adapter

`gridagent --paper-dsr PROFILE.json` invokes the original PowerFactory driver
on a dedicated copy of the IEEE39 project. A new study case is created for each
of the frozen top three; complete RMS CSVs are scored by the original KPI code.
Prediction errors and stability agreement are recorded. Mitigation is not yet
implemented; no full-workflow success is claimed. The original project and
complete voltage/speed channel mapping must be installed and verified by the
user. This adapter has not been tested with a commercial license. See example
profile. Windows buttons and TUI /paper-dsr and /paper-dmq use the same commands.

## Independent published holdout evaluator

Run separately, outside the application and its workspace:

    python scripts/sync_evaluator.py offline-evaluation/test_memory.json
    python -m gridagent.paper_evaluation .gridagent/studies/STUDY_ID offline-evaluation/test_memory.json

The evaluator verifies the exact upstream test-memory blob and matches the ten
paper cases by location and duration_ms. It scores frozen top-three recall,
severity MAE, stability accuracy and voltage extrema errors; full workflow and
mitigation are deliberately not scored. Holdout labels are never copied into
the portable distribution, policy tool or training index. The normal Agent
now also has a bounded read-only paper_training_history tool. It reports
historical observations, not newly simulated data.
