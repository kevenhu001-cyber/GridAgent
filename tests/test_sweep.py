import pytest
from pydantic import ValidationError

from gridagent.sweep import SweepRequest, sweep_updates


class FakeSimulator:
    def run(self, operation, request):
        return {"status": "ok", "metrics": {"voltage_severity_proxy": request["duration_s"]}}


def test_sweep_sorted_and_persisted(tmp_path):
    events = list(sweep_updates(SweepRequest(bus=5, durations_s=[0.2, 0.1]), FakeSimulator(), tmp_path))
    assert [p["duration_s"] for p in events[-1][1]["points"]] == [0.1, 0.2]
    folder = tmp_path / events[0][1]
    assert (folder / "attempt-2.json").is_file()
    assert (folder / "report.json").is_file()


def test_sweep_bounds():
    with pytest.raises(ValidationError):
        SweepRequest(bus=5, durations_s=[0.1, 0.1])
    with pytest.raises(ValidationError):
        SweepRequest(bus=5, durations_s=[0.7])
