"""Deterministic, bounded AC probe selection; scores are not probabilities."""

from .diagnosis_rules import rule_for

POLICY = "adaptive-ac-probe-selection-v1"


def direction(change):
    return "increase" if change["after"] > change["before"] else "decrease"


def group(job):
    return job["probe"]["kind"], job["change"]["device"], direction(job["change"])


def step_size(job, anchor):
    change = job["change"]
    probe = job["probe"]
    span = 0.4 if probe["kind"] == "voltage_setpoint" else probe["maximum_mvar"]-probe["minimum_mvar"]
    return abs(change["after"]-anchor)/max(span, 1e-12)


def history_hints(spec, matches, version):
    """Freeze direction-only priors, excluding the same source and inconclusive records."""
    target = rule_for(spec.target_scope, spec.target_check)
    kind = "outage" if spec.snapshot.outage_line else "base"
    hints = []
    for row in matches:
        if (row["same_source_report"] or row["target_rule_id"] != target
                or row["snapshot_kind"] != kind or row["solver_version"] != version
                or row["outcome"] not in {"verified_original_scope", "rejected_observed_violation"}):
            continue
        hint = {key: row[key] for key in ("repair_study_id", "repair_report_sha256",
                "candidate_index", "intervention", "direction", "outcome", "structure_similarity")}
        # Preserve the v1 frozen hint format; the weight is a retrieval score, not a probability.
        hint["structure_similarity"] = row.get("retrieval_score", row["structure_similarity"])
        hints.append(hint)
    return hints


def prior(job, hints):
    intervention, _, sign = group(job)
    return sum(row["structure_similarity"]*(1 if row["outcome"] == "verified_original_scope" else -1)
               for row in hints if row["intervention"] == intervention and row["direction"] == sign)


def choose(jobs, rows, hints):
    """Prefer comparable measured improvements; explore untested groups before known failures."""
    tested = {row["index"] for row in rows}
    if not rows:
        return {"index": 0, "reason": "reproduce_baseline"}
    base = rows[0]["measurement"]
    if base is None:
        return None
    candidates = []
    for job in jobs[1:]:
        if job["index"] in tested:
            continue
        previous = [row for row in rows[1:] if group(row) == group(job)]
        comparable = [row for row in previous if row["measurement"] is not None
                      and row["measurement"]["solver_version"] == base["solver_version"]]
        best = min(comparable, key=lambda row: (row["measurement"]["violation"], row["index"])) if comparable else None
        improvement = base["violation"]-best["measurement"]["violation"] if best else 0.0
        # Prioritize measured improvement, then exploration, then measured non-improvement.
        tier = 2 if improvement > 1e-6 else 1 if not comparable else 0
        anchor = best["change"]["after"] if tier == 2 else job["change"]["before"]
        score = (tier, round(improvement, 12) if tier == 2 else 0.0,
                 -len(previous), round(prior(job, hints), 12), -step_size(job, anchor), -job["index"])
        candidates.append((score, job["index"], tier))
    if not candidates:
        return None
    _, index, tier = max(candidates)
    return {"index": index, "reason": ("observed_improvement" if tier == 2 else
                                      "explore_direction" if tier == 1 else "remaining_authorized_probe")}
