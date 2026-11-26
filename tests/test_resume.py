import pytest

from gridagent.dsr import Study, build_dsr, resume_dsr

from test_dsr import FakeSimulator, estimate, manifest


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
