"""Small regularized logistic ranker with validation-only conservative activation."""

import math

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit
from scipy.stats import beta

from .ac_decision_dataset import FEATURES
from .ac_decision_dataset import PROTOCOL as DATASET_PROTOCOL
from .engineering_ir import fingerprint

PROTOCOL = "ac-candidate-logistic-v1"
THRESHOLD = 0.8
MIN_VALIDATION_FAMILIES = 8
MIN_FAMILY_LOWER_BOUND = 0.5


def fit(rows):
    if len(rows) < 12 or len({r["family"] for r in rows}) < 3 or {r["y"] for r in rows} != {0, 1}:
        raise ValueError("Training requires at least 12 labeled probes, three families and both outcomes")
    x = np.asarray([r["x"] for r in rows], dtype=float)
    y = np.asarray([r["y"] for r in rows], dtype=float)
    if x.shape != (len(rows), len(FEATURES)) or not np.isfinite(x).all():
        raise ValueError("Invalid training matrix")
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-9] = 1
    z = (x-mean)/scale
    # Each family contributes equal total weight.
    counts = {r["family"]: sum(s["family"] == r["family"] for s in rows) for r in rows}
    w = np.asarray([1/counts[r["family"]] for r in rows])
    w /= w.sum()

    def objective(theta):
        logits = z @ theta[:-1]+theta[-1]
        loss = np.dot(w, np.logaddexp(0, logits)-y*logits)+0.05*np.dot(theta[:-1], theta[:-1])
        residual = w*(expit(logits)-y)
        gradient = np.r_[z.T @ residual+0.1*theta[:-1], residual.sum()]
        return float(loss), gradient

    result = minimize(objective, np.zeros(len(FEATURES)+1), jac=True, method="L-BFGS-B",
                      options={"maxiter": 500, "ftol": 1e-12})
    if not result.success or not np.isfinite(result.x).all():
        raise ValueError("Logistic fit did not converge")
    return {"weights": result.x[:-1].tolist(), "intercept": float(result.x[-1]),
            "mean": mean.tolist(), "scale": scale.tolist(), "lower": x.min(axis=0).tolist(),
            "upper": x.max(axis=0).tolist(), "training_rows": len(rows),
            "training_families": len(counts), "solver_version": rows[0]["solver_version"]}


def score(model, values, version):
    """No score outside the training box or on a different simulator version."""
    x = np.asarray(values, dtype=float)
    if x.shape != (len(FEATURES),) or not np.isfinite(x).all():
        return {"score": None, "reason": "invalid_features"}
    if version != model["solver_version"]:
        return {"score": None, "reason": "solver_version_mismatch"}
    lo, hi = np.asarray(model["lower"]), np.asarray(model["upper"])
    if (x < lo-1e-9).any() or (x > hi+1e-9).any():
        return {"score": None, "reason": "outside_training_envelope"}
    z = (x-np.asarray(model["mean"]))/np.asarray(model["scale"])
    value = float(expit(z @ np.asarray(model["weights"])+model["intercept"]))
    return {"score": value, "reason": "in_envelope"}


def evaluate(model, rows):
    scored, selected = [], []
    for row in rows:
        prediction = score(model, row["x"], row["solver_version"])
        value = prediction["score"]
        if value is not None:
            scored.append((value, row["y"]))
            if value >= THRESHOLD:
                selected.append(row)
    groups = {}
    for row in selected:
        groups.setdefault(row["family"], []).append(row["y"])
    passed = sum(all(outcomes) for outcomes in groups.values())
    total = len(groups)
    lower = float(beta.ppf(0.05, passed, total-passed+1)) if passed else 0.0
    return {"labeled_rows": len(rows), "scored_rows": len(scored), "high_score_rows": len(selected),
            "high_score_correct": sum(r["y"] for r in selected),
            "high_score_precision": sum(r["y"] for r in selected)/len(selected) if selected else None,
            "brier_on_scored_rows": sum((p-y)**2 for p, y in scored)/len(scored) if scored else None,
            "selected_families": total, "all_selected_correct_families": passed,
            "family_lower_bound_diagnostic": lower,
            "coverage": len(selected)/len(rows) if rows else 0.0}


def train(dataset):
    if dataset["protocol"] != DATASET_PROTOCOL or dataset["feature_names"] != list(FEATURES):
        raise ValueError("Unsupported dataset features")
    rows = dataset["rows"]
    splits = {name: [r for r in rows if r["split"] == name] for name in ("train", "validation", "test")}
    groups = [{r["family"] for r in items} for items in splits.values()]
    if any(not g for g in groups) or any(groups[i] & groups[j] for i in range(3) for j in range(i+1, 3)):
        raise ValueError("Labeled family-disjoint splits required")
    if len({r["solver_version"] for r in rows}) != 1:
        raise ValueError("Train and evaluation require a single native solver version")
    model = fit(splits["train"])
    validation = evaluate(model, splits["validation"])
    enabled = (validation["selected_families"] >= MIN_VALIDATION_FAMILIES
               and validation["family_lower_bound_diagnostic"] >= MIN_FAMILY_LOWER_BOUND
               and dataset["excluded_unknown"]["validation"] == 0)
    # The test split never participates in fitting, threshold choice or activation.
    test = evaluate(model, splits["test"])
    artifact = {"protocol": PROTOCOL, "dataset_sha256": fingerprint(dataset),
                "feature_names": list(FEATURES), "model": model, "threshold": THRESHOLD,
                "validation": validation, "test": test, "enabled": enabled,
                "excluded_unknown": dataset["excluded_unknown"],
                "activation_rule": {"threshold": THRESHOLD, "minimum_validation_families": MIN_VALIDATION_FAMILIES,
                                    "minimum_family_lower_bound": MIN_FAMILY_LOWER_BOUND,
                                    "requires_no_unknown_validation_outcomes": True},
                "scope": "heuristic ranking score; not calibrated probability or operational authorization"}
    return {**artifact, "artifact_sha256": fingerprint(artifact)}


def rank(artifact, candidates, version):
    body = {key: value for key, value in artifact.items() if key != "artifact_sha256"}
    if (artifact["protocol"] != PROTOCOL or artifact["feature_names"] != list(FEATURES)
            or artifact["threshold"] != THRESHOLD or artifact["artifact_sha256"] != fingerprint(body)):
        raise ValueError("Decision artifact changed")
    if not artifact["enabled"]:
        return {"status": "abstain_validation_gate", "ranked": [], "requires_independent_simulation": True}
    ranked = []
    for index, values in candidates:
        prediction = score(artifact["model"], values, version)
        value = prediction["score"]
        if value is not None and math.isfinite(value) and value >= THRESHOLD:
            ranked.append({"candidate_index": index, "score": value})
    ranked.sort(key=lambda row: (-row["score"], row["candidate_index"]))
    return {"status": "ranking_only" if ranked else "abstain_no_supported_candidate",
            "ranked": ranked, "requires_independent_simulation": True}
