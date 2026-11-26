import json

import pytest

from gridagent.desktop_bridge import dispatch
from gridagent.model_revisions import create_revision, run_revision, topology
from gridagent.native_backends import run_program
from gridagent.research import ResearchTasks


def manifest(*, with_repairs=False, scenarios=None, max_runs=4):
    return {
        "objective": "Verify AC voltage and power balance across both voltage levels",
        "program": {"steps": [
            {"op": "create_bus", "index": 0, "vn_kv": 110},
            {"op": "create_bus", "index": 1, "vn_kv": 20},
            {"op": "create_bus", "index": 2, "vn_kv": 20},
            {"op": "create_ext_grid", "bus": 0, "vm_pu": 0.88 if with_repairs else 1.0},
            {"op": "create_transformer_from_parameters", "index": 0, "hv_bus": 0, "lv_bus": 1,
             "sn_mva": 40, "vn_hv_kv": 110, "vn_lv_kv": 20, "vkr_percent": 0.5, "vk_percent": 7,
             "pfe_kw": 0, "i0_percent": 0},
            {"op": "create_switch", "index": 0, "bus": 1, "element": 2, "et": "b", "closed": True},
            {"op": "create_load", "index": 0, "bus": 2, "p_mw": 5, "q_mvar": 1},
        ]},
        "scenarios": scenarios or [{"name": "base"}],
        "editable": [{"path": "/steps/3/vm_pu", "minimum": 0.88, "maximum": 1.04}] if with_repairs else [],
        "max_runs": max_runs,
    }


@pytest.mark.integration
def test_real_multi_scenario_research_repairs_and_exports(tmp_path):
    pytest.importorskip("pandapower")
    tasks = ResearchTasks(tmp_path)
    spec = manifest(with_repairs=True, scenarios=[{"name": "base"}, {"name": "peak", "load_scale": 1.2}])
    identifier = tasks.start(spec["objective"], manifest=spec)
    choices = iter([{"path": "/steps/6/p_mw", "value": 0}, {"path": "/steps/3/vm_pu", "value": 1.02}])
    list(tasks.resume(identifier, proposer=lambda _: {"changes": [next(choices)], "rationale": "Voltage check"}))
    final = tasks.summary(identifier, full=True)
    assert final["stage"] == "passed", final
    assert final["runs_used"] == 4 and final["repairs_used"] == 2
    assert final["record"]["rejected_repairs"] == ["Proposal modifies a locked parameter"]
    assert not final["record"]["attempts"][0]["passed"]
    assert len({row["version"] for row in final["best_runs"]}) == 1
    assert all(any(check["id"] == "power_balance_mva" and check["passed"]
                   for check in row["evaluation"]["checks"]) for row in final["best_runs"])
    assert final["record"]["attempts"][1]["program"]["steps"][6]["p_mw"] == 5
    run_id = final["best_runs"][0]["run_id"]
    graph = topology(tmp_path, run_id)
    assert {node["kv"] for node in graph["nodes"]} == {20, 110}
    assert {link["type"] for link in graph["links"]} == {"trafo", "switch"}
    revision = create_revision(tmp_path, run_id, {"op": "edit", "element": "load", "index": 0,
                                                    "field": "p_mw", "value": 6})
    assert revision["diff"]["before"] == 5
    assert run_revision(tmp_path, revision["id"])["quality"]["passed"]
    report = tmp_path / "report.json"
    events = []
    dispatch(tmp_path, {"action": "research", "command": "research-report", "args": [identifier, str(report)]},
             lambda kind, data: events.append((kind, data)))
    assert json.loads(report.read_text(encoding="utf-8"))["manifest_sha256"] == final["manifest_sha256"]
    assert any(kind == "research_tasks" and rows[0]["id"] == identifier for kind, rows in events)


@pytest.mark.integration
def test_resume_reuses_committed_native_result(tmp_path):
    pytest.importorskip("pandapower")
    tasks = ResearchTasks(tmp_path)
    spec = manifest()
    identifier = tasks.start(spec["objective"], manifest=spec)

    def interrupted_after_result(*args, **kwargs):
        run_program(*args, **kwargs)
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        list(tasks.resume(identifier, solver=interrupted_after_result))

    def unexpected_solve(*args, **kwargs):
        pytest.fail("Resume tried to repeat a committed native run")

    list(ResearchTasks(tmp_path).resume(identifier, solver=unexpected_solve))
    assert tasks.summary(identifier)["stage"] == "passed"
    assert tasks.summary(identifier)["runs_used"] == 1


def test_resume_charges_unknown_attempt_once_and_exhausts_budget(tmp_path):
    tasks = ResearchTasks(tmp_path)
    identifier = tasks.start("Interrupt a run", manifest=manifest(max_runs=1))

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        list(tasks.resume(identifier, solver=interrupted))
    list(tasks.resume(identifier, solver=interrupted))
    final = tasks.summary(identifier)
    assert final["termination"] == "simulation_budget_exhausted"
    assert final["runs_used"] == 1
    assert final["best_runs"][0]["status"] == "unknown"


def test_clarification_approval_and_cancellation_are_durable(tmp_path):
    tasks = ResearchTasks(tmp_path)
    identifier = tasks.start("Check a transformer", mode="multi")
    responses = iter([{"questions": ["What is the nominal voltage?"]}, {"manifest": manifest(with_repairs=True)}])

    def plan(prompt, clarifications, mode):
        assert mode == "multi"
        return next(responses)

    assert list(tasks.resume(identifier, planner=plan))[-1]["stage"] == "awaiting_input"
    assert list(tasks.resume(identifier, planner=plan))[-1]["stage"] == "awaiting_input"
    assert list(tasks.resume(identifier, planner=plan, clarification="110/20 kV"))[-1]["stage"] == "awaiting_approval"
    assert list(tasks.resume(identifier))[-1]["runs_used"] == 0
    stream = tasks.resume(identifier, approve=True)
    assert next(stream)["runs_used"] == 1
    ResearchTasks(tmp_path).cancel(identifier)
    assert list(stream)[-1]["stage"] == "cancelled"
    assert list(tasks.resume(identifier))[-1]["stage"] == "cancelled"


def test_multi_planning_calls_research_and_modeling_roles(tmp_path):
    from gridagent.knowledge import QueryPlan
    from gridagent.research import research_planner

    calls = []

    class Model:
        def with_structured_output(self, schema, **kwargs):
            class Bound:
                def invoke(self, messages):
                    data = json.loads(messages[-1].content)
                    calls.append((schema, data))
                    if schema is QueryPlan:
                        return {"functions": ["create_transformer_from_parameters"]}
                    return {"manifest": manifest()}
            return Bound()

    tasks = ResearchTasks(tmp_path)
    identifier = tasks.start("need a transformer", mode="multi")
    progress = tasks.resume(identifier, planner=research_planner(tmp_path, Model()))
    next(progress)
    progress.close()
    assert len(calls) == 2
    assert calls[1][1]["references"][0]["source"].startswith("https://pandapower.readthedocs.io/")


def test_comparison_records_both_models_and_each_variant(tmp_path, monkeypatch):
    from gridagent import ac_comparison

    seen = []

    def trial(root, task, variant, adapters, memory):
        seen.append((root, task, variant, memory))
        return {"passed": variant != "single_no_repair", "first_pass": False, "reason": "fixture",
                "runs": 2, "repairs": 1}

    monkeypatch.setattr(ac_comparison, "repair_trial", trial)
    list(ac_comparison.compare(tmp_path, "repair/transformer-1", ["one", "two"], 1,
                               model_factory=lambda **_: object()))
    report_path = next((tmp_path / "studies").glob("*/report.json"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert len(seen) == 8
    assert {item["model"] for item in report["groups"]} == {"one", "two"}
    assert {item["variant"] for item in report["groups"]} == set(ac_comparison.VARIANTS)
    assert {item["token_measurement_count"] for item in report["groups"]} == {0}


@pytest.mark.integration
def test_n_minus_one_requires_an_actual_contingency(tmp_path):
    pytest.importorskip("pandapower")
    spec = manifest(scenarios=[{"name": "base"}, {"name": "outage", "outage": {"element": "trafo", "index": 0}}])
    tasks = ResearchTasks(tmp_path)
    identifier = tasks.start(spec["objective"], manifest=spec)
    report = list(tasks.resume(identifier))[-1]
    assert report["stage"] == "failed"
    base, outage = report["best_runs"]
    assert base["evaluation"]["passed"]
    assert not outage["evaluation"]["passed"]
    request = json.loads((tmp_path / "runs" / outage["run_id"] / "request.json").read_text(encoding="utf-8"))
    assert request["contingency"] == {"element": "trafo", "index": 0}
