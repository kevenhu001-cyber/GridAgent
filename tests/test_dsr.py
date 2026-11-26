import json

import pytest

from gridagent.dsr import Candidate, Manifest, MemoryCase, Study, build_dsr, retrieve
from gridagent.domain import FaultRequest
from gridagent.evaluation import score_study


def manifest():
    return Manifest(candidates=[Candidate(id=f"K{i}", fault=FaultRequest(bus=5 + i % 5,
                     duration_s=0.08 if i < 5 else 0.16)) for i in range(10)])


def estimate(evidence):
    return {"predictions": [{"id": cid, "score": i / 10, "v_min_pu": 0.7,
                             "v_max_pu": 1.1, "rationale": "test estimate"}
                            for i, cid in enumerate(evidence)]}


class FakeSimulator:
    def __init__(self, study):
        self.study = study
        self.calls = []

    def run(self, operation, request):
        assert (self.study.path / "predictions.json").is_file()
        assert (self.study.path / f"attempt-{len(self.calls) + 1}.json").is_file()
        self.calls.append(request)
        return {"status": "ok", "metrics": {"voltage_severity_proxy": 0.2}}


def test_freeze_and_budget(tmp_path):
    study = Study(tmp_path)
    sim = FakeSimulator(study)
    result = build_dsr(manifest(), [], estimate, sim, study).invoke({})
    assert result["selected"] == ["K9", "K8", "K7"]
    assert len(sim.calls) == 3
    assert result["report"]["completed"]
    assert result["report"]["mitigation"] == "not_implemented"
    with pytest.raises(FileExistsError):
        study.write("predictions", {})


def test_reject_incomplete_predictions(tmp_path):
    study = Study(tmp_path)
    sim = FakeSimulator(study)
    def bad(evidence):
        return {"predictions": estimate(evidence)["predictions"][:-1]}
    with pytest.raises(ValueError):
        build_dsr(manifest(), [], bad, sim, study).invoke({})
    assert not sim.calls


def test_memory_prefers_exact_match():
    fault = FaultRequest(bus=5, duration_s=0.1)
    def record(rid, bus, duration):
        return MemoryCase(run_id=rid, fault=FaultRequest(bus=bus, duration_s=duration),
                          score=0.2, v_min_pu=0.7, v_max_pu=1.1)
    records = [record("other", 6, 0.1), record("near", 5, 0.12), record("exact", 5, 0.1)]
    assert [r["run_id"] for r in retrieve(fault, records)] == ["exact", "near", "other"]


def test_offline_evaluation(tmp_path):
    study = Study(tmp_path)
    build_dsr(manifest(), [], estimate, FakeSimulator(study), study).invoke({})
    m = json.loads((study.path / "manifest.json").read_text())
    p = json.loads((study.path / "predictions.json").read_text())
    truth = {"protocol": m["protocol"], "manifest_sha256": m["manifest_sha256"],
             "results": {f"K{i}": i / 10 for i in range(10)}}
    result = score_study(m, p, truth)
    assert result["top_k_recall"] == 1
    assert result["severity_proxy_mae"] == pytest.approx(0)
    p["selected"] = ["K0", "K1", "K2"]
    with pytest.raises(ValueError):
        score_study(m, p, truth)
