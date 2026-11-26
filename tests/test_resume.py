import pytest

from gridagent.domain import FaultRequest
from gridagent.dsr import Candidate, Manifest, Study, build_dsr, resume_dsr


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
        self.calls.append(request)
        return {"status": "ok", "metrics": {"voltage_severity_proxy": 0.2}}


def test_resume_charges_unknown_and_does_not_repeat(tmp_path):
    study = Study(tmp_path)
    sim = FakeSimulator(study)
    events = build_dsr(manifest(), [], estimate, sim, study).stream({}, stream_mode="updates")
    for event in events:
        if "estimate" in event:
            break
    events.close()
    selected = study.read("predictions")["selected"]
    candidate = next(c for c in manifest().candidates if c.id == selected[0])
    study.write("attempt-1", {"id": candidate.id, "request": candidate.fault.model_dump(mode="json")})
    calls = []

    class Solver:
        def run(self, operation, request):
            calls.append(request)
            return {"status": "ok", "metrics": {"voltage_severity_proxy": 0.2}}

    result = list(resume_dsr(tmp_path, study.id, Solver()))[-1][1]["report"]
    assert len(calls) == 2
    assert result["attempted"] == 3
    assert result["observed"][0]["status"] == "unknown"
    assert not result["completed"]
    list(resume_dsr(tmp_path, study.id, Solver()))
    assert len(calls) == 2


def test_resume_rejects_unfrozen_study(tmp_path):
    study = Study(tmp_path)
    sim = FakeSimulator(study)
    build_dsr(manifest(), [], estimate, sim, study)
    with pytest.raises(ValueError, match="No frozen predictions"):
        list(resume_dsr(tmp_path, study.id, sim))
    assert not sim.calls
