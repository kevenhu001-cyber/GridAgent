import copy

import pytest

from gridagent.ac_decision_dataset import FEATURES, PROTOCOL, DatasetSpec, label
from gridagent.ac_decision_model import rank, score, train


def dataset():
    rows = []
    for split, count in (("train", 4), ("validation", 8), ("test", 3)):
        for family in range(count):
            for y in (0, 1, 0, 1):
                rows.append({"family": f"{split}-{family}", "split": split, "solver_version": "3",
                             "x": [2*y-1]+[0.0]*(len(FEATURES)-1), "y": y})
    return {"protocol": PROTOCOL, "feature_names": list(FEATURES), "rows": rows,
            "excluded_unknown": {"train": 0, "validation": 0, "test": 0}}


def test_family_disjoint_authorization():
    raw = {"cases": [{"study_id": f"{i:032x}", "family": name, "split": name}
                     for i, name in enumerate(("train", "validation", "test"))]}
    assert DatasetSpec.model_validate(raw)
    raw["cases"][1]["family"] = "train"
    with pytest.raises(ValueError, match="family crosses"):
        DatasetSpec.model_validate(raw)


def test_labels_require_comparable_evidence():
    row = {"measurement": {"passed": True, "solver_version": "3"},
           "observation": {"passed": True, "native_evidence": {"status": "verified"},
                           "native_verdict": {"checks": []}, "physical": None}}
    assert label(row, "3") == 1
    assert label(row, "4") is None
    row["observation"]["passed"] = False
    assert label(row, "3") is None
    row["observation"]["physical"] = {"checks": [{"id": "reactive:g", "passed": False}]}
    assert label(row, "3") == 0
    row["observation"]["native_evidence"]["status"] = "unavailable"
    assert label(row, "3") is None
    row["measurement"] = None
    assert label(row, "3") is None


def test_test_labels_do_not_affect_fit_or_activation():
    raw = dataset()
    first = train(raw)
    altered = copy.deepcopy(raw)
    for row in altered["rows"]:
        if row["split"] == "test":
            row["y"] = 1-row["y"]
    second = train(altered)
    assert first["model"] == second["model"]
    assert first["validation"] == second["validation"]
    assert first["enabled"] == second["enabled"]
    assert first["test"] != second["test"]
    assert first["dataset_sha256"] != second["dataset_sha256"]


def test_rank_abstains_for_outside_domain_and_version():
    artifact = train(dataset())
    assert artifact["enabled"]
    good = [1.0]+[0.0]*(len(FEATURES)-1)
    bad = [-1.0]+good[1:]
    out = [2.0]+good[1:]
    result = rank(artifact, [(1, bad), (2, out), (3, good)], "3")
    assert [row["candidate_index"] for row in result["ranked"]] == [3]
    assert result["requires_independent_simulation"]
    assert rank(artifact, [(3, good)], "4")["status"] == "abstain_no_supported_candidate"
    assert score(artifact["model"], out, "3")["reason"] == "outside_training_envelope"


def test_activation_requires_validation_and_unknown_outcome_gate():
    raw = dataset()
    raw["excluded_unknown"]["validation"] = 1
    artifact = train(raw)
    assert not artifact["enabled"]
    assert rank(artifact, [], "3")["status"] == "abstain_validation_gate"
    raw["excluded_unknown"]["validation"] = 0
    raw["rows"] = [row for row in raw["rows"] if row["family"] != "validation-7"]
    assert not train(raw)["enabled"]


def test_tampered_artifact_rejected():
    artifact = train(dataset())
    artifact["threshold"] = 0.1
    with pytest.raises(ValueError, match="artifact changed"):
        rank(artifact, [], "3")


def test_training_rejects_cross_split_family_and_version():
    raw = dataset()
    raw["rows"][-1]["family"] = "train-0"
    with pytest.raises(ValueError, match="family-disjoint"):
        train(raw)
    raw = dataset()
    raw["rows"][-1]["solver_version"] = "4"
    with pytest.raises(ValueError, match="single native"):
        train(raw)
