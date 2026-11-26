import pytest

from gridagent.model_repair import Manifest, repair_updates


def spec():
    return {"initial": {"backend": "pandapower", "steps": [
        {"op": "create_bus", "index": 0, "vn_kv": 110},
        {"op": "create_ext_grid", "bus": 0, "vm_pu": 0.88},
        {"op": "create_load", "index": 0, "bus": 0, "p_mw": 20}]},
        "editable_paths": ["/steps/1/vm_pu"], "max_repairs": 3}


def test_repair_rejects_locked_changes_and_stops_on_pass(tmp_path):
    requests = []
    choices = iter([{"path": "/steps/2/p_mw", "value": 1},
                    {"path": "/steps/1/vm_pu", "value": 1}])

    def solver(root, program):
        requests.append(program)
        ok = program["steps"][1]["vm_pu"] == 1
        return {"status": "ok", "run_id": str(len(requests)),
                "quality": {"passed": ok, "tests": [{"id": "voltage", "passed": ok}]}}

    def propose(obs):
        assert obs["best_program"]["steps"][2]["p_mw"] == 20
        return {"changes": [next(choices)], "rationale": "test"}

    rows = list(repair_updates(tmp_path, spec(), propose, solver))
    assert rows[1]["status"] == "denied"
    assert len(requests) == 2
    assert rows[-1]["passed"] and rows[-1]["repair_attempts"] == 2


def test_demand_cannot_be_authorized():
    manifest = spec()
    manifest["editable_paths"] = ["/steps/2/p_mw"]
    with pytest.raises(ValueError):
        Manifest.model_validate(manifest)


def test_best_is_not_overwritten_by_failed_repair(tmp_path):
    manifest = spec()
    manifest["max_repairs"] = 1
    calls = []

    def solver(root, program):
        calls.append(program)
        return {"status": "ok" if len(calls)==1 else "failed", "run_id": str(len(calls)),
                "quality": {"passed": False, "tests": [{"id": "a", "passed": len(calls)==1},
                                                       {"id": "b", "passed": False}]}}

    rows = list(repair_updates(tmp_path, manifest, lambda obs: {
        "changes": [{"path": "/steps/1/vm_pu", "value": 1}], "rationale": "test"}, solver))
    assert rows[-1]["best_run_id"] == "1" and not rows[-1]["passed"]
