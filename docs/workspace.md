# Analysis and local research workspace

The ANDES small-signal tool runs power flow and eigenvalue analysis on a fresh
case. It reports real and imaginary parts, oscillation frequency, damping
ratio, mode counts and the least-damped oscillatory modes. Neutral modes are
reported separately; small-signal results are not large-disturbance stability
or compliance certificates. The full modal spectrum is saved as CSV.

    gridagent --eigen
    gridagent --sweep 5 0.04 0.08 0.12 0.16
    gridagent --runs
    gridagent --study STUDY_ID
    gridagent --wave RUN_ID CHANNEL
    gridagent --study-wave STUDY_ID baseline/flat_start.csv q_deviation_pu

These commands work without a model key. Eigen and sweep require ANDES.
The bounded sweep runs at most ten distinct durations and records each
attempt before execution. It is not a critical clearing time calculation.
TUI commands /runs, /study ID, /wave ID CHANNEL and /study-wave ID PATH CHANNEL
display saved results without sending them to a model. /eigen and /sweep
start deterministic studies. The terminal plot shows an extrema-preserving
envelope and time axis; original CSV remains authoritative.

Original paper mitigation, validated physical stability classification,
participation-factor interpretation and mid-task resume remain outstanding.

Launch the read-only/standalone research workspace using `gridagent --offline`.
It does not require model credentials. Local deterministic /eigen and /sweep
remain available; free chat, /dmq and /dsr require a configured model.
