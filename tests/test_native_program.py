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
    assert result["quality"]["passed"], result["quality"]
    assert (tmp_path / "runs" / result["run_id"] / "storage_soc_mwh.csv").is_file()


@pytest.mark.integration
def test_pandapower_construct_fault_and_replay(tmp_path):
    pytest.importorskip("pandapower")
    from gridagent.native_backends import run_program

    steps = [{"op": "create_bus", "index": 0, "vn_kv": 110},
             {"op": "create_bus", "index": 1, "vn_kv": 110},
             {"op": "create_ext_grid", "bus": 0, "s_sc_max_mva": 1000},
             {"op": "create_line_from_parameters", "index": 0, "from_bus": 0, "to_bus": 1,
              "length_km": 10, "r_ohm_per_km": 0.1, "x_ohm_per_km": 0.4, "max_i_ka": 0.5},
             {"op": "create_load", "index": 0, "bus": 1, "p_mw": 20, "q_mvar": 5}]
    first = run_program(tmp_path, {"backend": "pandapower", "steps": steps})
    assert first["status"] == "ok", first
    next_run = run_program(tmp_path, {"backend": "pandapower", "parent_run": first["run_id"],
                                     "analysis": "short_circuit", "fault_bus": 1})
    assert next_run["status"] == "ok", next_run
    assert next_run["metrics"]["ikss_ka"] > 0
    assert next_run["parent_run"] == first["run_id"]
