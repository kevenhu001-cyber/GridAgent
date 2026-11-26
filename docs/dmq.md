# Dynamic model quality review

The paper starts with a modified WECC solar model, allows only four REECAU1
gains (Kqp, Kqi, Kvp, Kvi), executes eight DMView tests, and permits five
repair iterations. This implementation reproduces the workflow constraints,
not the proprietary model or its test results.

## Open numerical surrogate

Two independent second-order PI feedback loops use states y, dy/dt and
integral error. The plant obeys

    y'' + 2*zeta*omega*y' + omega^2*y = omega^2*(plant_gain*u + disturbance)
    u = kp*(reference-y) + ki*integral_error
    integral_error' = reference-y

omega=2 rad/s, damping ratio 0.4 (0.3 for the weak-grid analogue), plant gain
1 (0.75 for the weak-grid analogue). Classical RK4, 20 seconds, 20 ms steps.
Eight fixed synthetic tests: flat start, positive and negative Q/V steps,
combined step, brief voltage disturbance, reduced damping/plant gain.
Pass if peak absolute deviation <=0.3 pu and final two-second tracking error
<=0.025 pu. These are intentionally synthetic criteria, not grid-code limits.
There is no active-power/frequency ride-through model, network or SCR test.

Run with a configured LLM:

    gridagent --dmq

Or type /dmq in the TUI. The numerical tests run without ANDES. Initial gains
are (10,50,10,50), matching the paper's starting values but applied to a different
model. Only the four numeric gains in [0.05,100] can be proposed. All four fields
are required, extra fields are rejected, and the deterministic suite is fixed.
A baseline precedes at most five proposed edits; rejected attempts consume
budget, so repeated malformed proposals cannot loop indefinitely. The suite
reruns after every accepted change. Each attempt, waveform and verdict is
persisted. No automatic modification to user files or operational equipment.

A PSS/E/DMView adapter still requires the actual case, model identity and
field mapping, original eight test configurations, licensed PSS/E, and an
independent evaluator. Do not report results from this surrogate as a
reproduction of the WECC case.

## Deterministic comparison

    gridagent --dmq-reference

This mode requires no LLM credentials. It applies one fixed reference gain
set after observing a failed baseline, and uses the identical numerical
suite and constraints. It is a smoke test and comparison baseline, not an
Agent success result. The policy type is recorded in policy.json.
