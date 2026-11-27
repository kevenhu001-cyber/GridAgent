"""Bounded frequency-control tuning on a synthetic linear swing/governor plant."""

import json
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp
from scipy.linalg import expm
from scipy.stats.qmc import Halton

PROTOCOL = "frequency-governor-benchmark-v1"
# M, D, governor time constant, load step (all on a consistent p.u. base).
TRAIN = ((4.0, 1.0, 0.4, 0.08), (2.5, 0.8, 0.7, 0.12), (6.0, 1.4, 0.3, 0.10))
TEST = ((2.0, 0.6, 0.9, 0.10), (5.0, 0.9, 0.55, 0.15))
BASELINE = (3.0, 0.8)
TIMES = np.linspace(0, 30, 301)


def plant_matrix(case, gains):
    m, d, t, load = case
    kp, ki = gains
    if not np.isfinite([m, d, t, load, kp, ki]).all() or min(m, d, t, kp, ki) <= 0 or load < 0:
        raise ValueError("Invalid linear plant or controller parameters")
    a = np.array([[-d/m, 1/m, 0], [-kp/t, -1/t, ki/t], [-1, 0, 0]])
    b = np.array([-load/m, 0, 0])
    return a, b


def simulate(case, gains, *, independent=False):
    a, b = plant_matrix(case, gains)
    pole = float(np.max(np.linalg.eigvals(a).real))
    if pole >= -1e-8:
        return {"stable": False, "max_real_pole": pole, "passed": False}
    if independent:
        solved = solve_ivp(lambda t, x: a @ x + b, (0, float(TIMES[-1])), np.zeros(3),
                           t_eval=TIMES, rtol=1e-10, atol=1e-12, method="DOP853")
        if not solved.success:
            raise ValueError("Independent integration failed")
        states = solved.y.T
    else:
        augmented = np.zeros((4, 4))
        augmented[:3, :3], augmented[:3, 3] = a, b
        transition = expm(augmented * (TIMES[1]-TIMES[0]))
        state = np.array([0., 0., 0., 1.])
        states = np.zeros((len(TIMES), 3))
        for i in range(1, len(TIMES)):
            state = transition @ state
            states[i] = state[:3]
    if not np.isfinite(states).all():
        raise ValueError("Nonfinite controller response")
    frequency = states[:, 0]
    peak = float(np.max(np.abs(frequency)))
    tail = float(np.max(np.abs(frequency[-51:])))
    effort = float(np.max(np.abs(states[:, 1])))
    # Synthetic acceptance, not a grid-code or continuous-time certificate.
    passed = peak <= 0.04 and tail <= 0.003 and effort <= 0.35
    return {"stable": True, "max_real_pole": pole, "passed": bool(passed), "peak_frequency_pu": peak,
            "tail_frequency_pu": tail, "peak_mechanical_power_pu": effort,
            "states": states.tolist()}


def score(rows):
    if not all(row["stable"] for row in rows):
        return 1e6
    failures = sum(not row["passed"] for row in rows)
    return float(100*failures+max(row["peak_frequency_pu"]/.04+row["tail_frequency_pu"]/.003
                                  +row["peak_mechanical_power_pu"]/.35 for row in rows))


def verify(case, gains):
    primary = simulate(case, gains)
    secondary = simulate(case, gains, independent=True)
    if not primary["stable"]:
        return {**primary, "numerically_verified": False}
    difference = float(np.max(np.abs(np.array(primary.pop("states"))-np.array(secondary.pop("states")))))
    return {**primary, "independent_max_state_difference": difference,
            "numerically_verified": bool(difference <= 1e-7 and primary["passed"] == secondary["passed"])}


def run_benchmark(budget=24):
    if not 2 <= budget <= 60:
        raise ValueError("Candidate budget must be 2..60")
    # Deterministic, prespecified log-space candidates. No test case enters selection.
    lower, upper = np.log([0.5, 0.1]), np.log([12.0, 8.0])
    samples = Halton(2, scramble=False).random(budget-1)
    candidates = [BASELINE, *map(tuple, np.exp(lower+samples*(upper-lower)))]
    observations = []
    for gains in candidates:
        rows = [simulate(case, gains) for case in TRAIN]
        observations.append({"gains": list(gains), "training_score": score(rows)})
    best = min(observations, key=lambda row: row["training_score"])
    evaluations = {}
    for label, gains in (("baseline", BASELINE), ("selected", best["gains"])):
        evaluations[label] = {split: [verify(case, gains) for case in cases]
                              for split, cases in (("train", TRAIN), ("heldout", TEST))}
    return {"protocol": PROTOCOL, "candidate_budget": budget, "candidates": observations,
            "selected_gains": best["gains"], "train_cases": TRAIN, "heldout_cases": TEST,
            "evaluations": evaluations, "candidate_plant_evaluations": budget*len(TRAIN),
            "verification_plant_evaluations": 2*2*(len(TRAIN)+len(TEST)),
            "scope": "linear unsaturated synthetic single-area model; sampled limits; no deployment authorization"}


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--budget", type=int, default=24)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = json.dumps(run_benchmark(args.budget), indent=2, allow_nan=False)
    if args.output:
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
