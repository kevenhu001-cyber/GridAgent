import copy

import pytest

from gridagent import adaptive_ac_experiment as adaptive
from gridagent.adaptive_ac_ir import AdaptiveACExperiment
from gridagent.adaptive_ac_policy import choose, history_hints
from gridagent.dsr import Study


def authorization():
    return {"experiment": {"source_study_id": "a"*32, "source_report_sha256": "b"*64,
                           "snapshot": {"hour": 0}, "target_scope": "ac_native",
                           "target_check": "voltage_operating_range",
                           "probes": [{"kind": "voltage_setpoint", "device": "g", "value_pu": v}
                                      for v in (0.87, 0.91, 0.94, 1.0)],
                           "max_solver_runs": 5},
            "run_budget": 3}


def job(index, value=None):
    probe = None if value is None else {"kind": "voltage_setpoint", "device": "g", "value_pu": value}
    change = None if value is None else {"device": "g", "field": "voltage_pu", "before": 0.89, "after": value}
    return {"index": index, "probe": probe, "change": change, "request_sha256": f"{index:064x}",
            "ac_spec_sha256": f"{index+10:064x}"}


def metric(violation=0.01, passed=False, version="3"):
    return {"violation": violation, "passed": passed, "solver_version": version,
            "unit": "p.u.", "observed": [0.9-violation, 1]}


def row(j, measurement, passed=False):
    return {**j, "measurement": measurement, "observation": {"passed": passed}}


def test_adaptive_policy_prioritizes_improvement_and_never_repeats():
    jobs = [job(0), job(1, 0.87), job(2, 0.91), job(3, 0.94), job(4, 1)]
    rows = [row(jobs[0], metric())]
    assert choose(jobs, [], [])["index"] == 0
    hints = [{"intervention": "voltage_setpoint", "direction": "increase",
              "outcome": "verified_original_scope", "structure_similarity": 1}]
    assert choose(jobs, rows, hints)["index"] == 2
    rows.append(row(jobs[2], metric(0.004)))
    assert choose(jobs, rows, hints) == {"index": 3, "reason": "observed_improvement"}
    rows.append(row(jobs[3], metric(0.015)))
    assert choose(jobs, rows, hints)["index"] == 4
    rows.append(row(jobs[4], None))
    assert choose(jobs, rows, hints)["index"] == 1
    rows.append(row(jobs[1], metric()))
    assert choose(jobs, rows, hints) is None


def test_unexplored_direction_precedes_measured_nonimprovement():
    jobs = [job(0), job(1, 0.87), job(2, 0.91), job(3, 0.94)]
    rows = [row(jobs[0], metric()), row(jobs[2], metric(0.02))]
    assert choose(jobs, rows, [])["index"] == 1


def test_history_excludes_same_source_inconclusive_and_wrong_version():
    auth = AdaptiveACExperiment.model_validate(authorization())
    item = {"same_source_report": False, "target_rule_id": "voltage", "snapshot_kind": "base",
            "solver_version": "3", "outcome": "verified_original_scope", "repair_study_id": "a"*32,
            "repair_report_sha256": "b"*64, "candidate_index": 1, "intervention": "voltage_setpoint",
            "direction": "increase", "structure_similarity": 0.9}
    matches = [item, {**item, "same_source_report": True}, {**item, "solver_version": "4"},
               {**item, "outcome": "inconclusive"}, {**item, "snapshot_kind": "outage"},
               {**item, "target_rule_id": "loading"}]
    hints = history_hints(auth.experiment, matches, "3")
    assert len(hints) == 1
    assert "same_source_report" not in hints[0]


def test_budget_and_canonical_pool():
    raw = authorization()
    auth = AdaptiveACExperiment.model_validate(raw)
    raw["experiment"]["probes"].reverse()
    assert AdaptiveACExperiment.model_validate(raw).sha256() == auth.sha256()
    raw["run_budget"] = 6
    with pytest.raises(ValueError, match="exceeds"):
        AdaptiveACExperiment.model_validate(raw)


@pytest.fixture
def simulation(monkeypatch):
    from types import SimpleNamespace

    jobs = [job(0), job(1, 0.87), job(2, 0.91), job(3, 0.94), job(4, 1)]
    cases = [(j, SimpleNamespace(timeout_s=10, acceptance=None), None, ({"index": j["index"]},))
             for j in jobs]
    monkeypatch.setattr(adaptive, "prepare", lambda *_: (cases, metric()))
    outputs = {}
    calls = []

    def solver(root, request, *, run_id, timeout_s):
        calls.append(request["index"])
        outputs[run_id] = request["index"]

    def observe(root, variant, commitment, case, reserved):
        index = outputs.get(reserved["run_id"])
        return {"index": index, "passed": index == 3}

    results = {0: metric(), 1: metric(0.02), 2: metric(0.004), 3: metric(0, True), 4: metric(0.03)}
    monkeypatch.setattr(adaptive, "observe", observe)
    monkeypatch.setattr(adaptive, "measure", lambda spec, observation, acceptance: results.get(observation["index"]))
    monkeypatch.setattr(adaptive, "search_ac_experience", lambda *a, **kw: {"matches": [
        {"same_source_report": False, "target_rule_id": "voltage", "snapshot_kind": "base",
         "solver_version": "3", "outcome": "verified_original_scope", "repair_study_id": "c"*32,
         "repair_report_sha256": "d"*64, "candidate_index": 1, "intervention": "voltage_setpoint",
         "direction": "increase", "structure_similarity": 1}]})
    return solver, calls, results


def test_adaptive_stops_early_and_replays_frozen_policy(tmp_path, simulation, monkeypatch):
    solver, calls, _ = simulation
    auth = authorization()
    auth.update(run_budget=5, use_history=True)
    identifier = adaptive.start_adaptive(tmp_path, auth)
    monkeypatch.setattr(adaptive, "search_ac_experience", lambda *a, **kw: pytest.fail("History queried on resume"))
    report = adaptive.resume_adaptive(tmp_path, identifier, solver=solver)
    assert calls == [0, 2, 3]
    assert report["termination"] == "verified_single_snapshot_candidate"
    assert report["verified_candidate_index"] == 3
    assert report["untried_candidate_indices"] == [1, 4]
    assert report["reserved_solver_runs"] == 3
    assert report["completed"]
    assert adaptive.resume_adaptive(tmp_path, identifier, solver=lambda *a, **kw: pytest.fail("Repeated solve")) == report


def test_budget_exhaustion_does_not_claim_success(tmp_path, simulation):
    solver, calls, _ = simulation
    auth = authorization()
    auth.update(run_budget=2, use_history=True)
    identifier = adaptive.start_adaptive(tmp_path, auth)
    report = adaptive.resume_adaptive(tmp_path, identifier, solver=solver)
    assert calls == [0, 2]
    assert report["termination"] == "budget_exhausted"
    assert report["verified_candidate_index"] is None
    assert not report["completed"]


def test_interrupted_baseline_never_relaunched(tmp_path, simulation):
    identifier = adaptive.start_adaptive(tmp_path, authorization())

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        adaptive.resume_adaptive(tmp_path, identifier, solver=interrupt)
    report = adaptive.resume_adaptive(tmp_path, identifier, solver=lambda *a, **kw: pytest.fail("Repeated solve"))
    assert report["reserved_solver_runs"] == 1
    assert report["termination"] == "baseline_not_reproduced"
    assert not report["completed"]


def test_changed_selection_detected(tmp_path, simulation):
    solver, _, _ = simulation
    identifier = adaptive.start_adaptive(tmp_path, authorization())
    adaptive.resume_adaptive(tmp_path, identifier, solver=solver)
    study = Study.reopen(tmp_path / "studies", identifier)
    reservation = copy.deepcopy(study.read("reservation-1"))
    reservation["decision"]["index"] = 4
    import json

    (study.path / "reservation-1.json").write_text(json.dumps(reservation), encoding="utf-8")
    with pytest.raises(ValueError, match="selection changed"):
        adaptive.resume_adaptive(tmp_path, identifier, solver=solver)
