import pytest
from pydantic import ValidationError

from gridagent.native_backends import ADAPTER


def test_program_blocks_code_and_bad_parameters():
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"backend": "pandapower", "steps": [{"op": "exec", "code": "pass"}]})
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"backend": "pandapower", "steps": [
            {"op": "edit", "element": "load", "index": 0, "field": "vm_pu", "value": 1}]})
    with pytest.raises(ValidationError):
        ADAPTER.validate_python({"backend": "pypsa", "hours": 2, "buses": [{"name": "b"}],
            "loads": [{"name": "l", "bus": "b", "p_set_mw": [1]}],
            "generators": [{"name": "g", "bus": "b", "p_nom_mw": 2, "marginal_cost": 1}]})


@pytest.mark.integration
def test_native_pandapower(tmp_path):
    pytest.importorskip("pandapower")
    from gridagent.native_backends import run_program

    a = run_program(tmp_path, {"backend": "pandapower", "base": "case14"})
    assert a["status"] == "ok", a
    assert a["metrics"]["solved_buses"] == 14
    b = run_program(tmp_path, {"backend": "pandapower", "base": "case14",
          "steps": [{"op": "edit", "element": "load", "index": 0, "field": "scaling", "value": 1.1}]})
    assert b["status"] == "ok", b
    assert b["audit"][0]["before"] == 1
    assert (tmp_path / "runs" / b["run_id"] / "network.json").is_file()


@pytest.mark.integration
def test_native_pypsa_storage(tmp_path):
    pytest.importorskip("pypsa")
    pytest.importorskip("highspy")
    from gridagent.native_backends import run_program

    result = run_program(tmp_path, {"backend": "pypsa", "hours": 4, "buses": [{"name": "b"}],
        "loads": [{"name": "l", "bus": "b", "p_set_mw": [5,5,5,5]}],
        "generators": [{"name": "g", "bus": "b", "p_nom_mw": 15, "marginal_cost": [10,10,100,100]}],
        "storage": [{"name": "battery", "bus": "b", "p_nom_mw": 5, "max_hours": 2}]})
    assert result["status"] == "ok", result
    assert result["metrics"]["storage_discharge_mwh"] > 0
    assert (tmp_path / "runs" / result["run_id"] / "storage_soc_mwh.csv").is_file()
