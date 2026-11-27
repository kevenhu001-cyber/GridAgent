# Independent physics validation (initial implementation)

The reference AC solver rebuilds each named public network, converts it using the same pandapower network conversion, independently stamps the admittance matrix (including shunts, transformer taps and phase shifts), and solves polar AC power balance equations using SciPy's root solver from flat PQ and angle initialization. No native calculated voltage is passed to the reference solver. It compares all bus voltages and relative angles with declared tolerances and reports the reference residual. The closed-form two-bus reactive-load case provides an analytic regression test. Shared conversion means that the comparison cannot certify the correctness of the underlying network data, transformer conversion or engineering limits. It is not an independent MATPOWER dataset comparison.

The frequency benchmark is a synthetic single-area linear swing/governor model with PI feedback. It uses deterministic bounded log-space sampling on three training plants, freezes the selected gains, evaluates two held-out plants, checks poles, and compares matrix-exponential trajectories with independently integrated DOP853 trajectories. No live-grid control, nonlinear saturation, multi-machine stability or grid-code certification is implied.

    python -m gridagent.dynamic_control_benchmark --budget 24 --output frequency-benchmark.json
    pytest -m integration tests/test_independent_physics.py -q

Remaining work includes external source/reference data, nonlinear and multi-machine controller tuning, pure-LLM comparison, and end-to-end GUI acceptance.
