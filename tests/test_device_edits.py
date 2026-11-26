from types import SimpleNamespace as NS

import pytest
from pydantic import ValidationError

from gridagent.device_edits import apply_edits
from gridagent.domain import DeviceEdit, ScenarioRequest


def test_parameter_constraints_and_audit():
    with pytest.raises(ValidationError):
        DeviceEdit(model="Slack", device="1", field="p0", value=1)
    with pytest.raises(ValidationError):
        DeviceEdit(model="PV", device="1", field="v0", value=1.5)
    edit = DeviceEdit(model="PQ", device="load1", field="p0", value=0.7)
    calls = []
    model = NS(idx=NS(v=["load1"]), u=NS(v=[1]), p0=NS(v=[0.5]),
               set=lambda *args: calls.append(args))
    changes = apply_edits(NS(PQ=model), [edit])
    assert calls == [("p0", "load1", 0.7)]
    assert changes[0]["before"] == 0.5
    with pytest.raises(ValidationError):
        ScenarioRequest(edits=[edit, edit])
