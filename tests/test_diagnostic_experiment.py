import copy
import json

import pytest

from gridagent.diagnosis import diagnose_study
from gridagent.diagnostic_experiment import resume_experiment, start_experiment
from gridagent.diagnostic_experiment_ir import DiagnosticExperiment, compile_probes
from gridagent.math_program_router import solve
from gridagent.math_program_tasks import resume_program, start_program
from gridagent.optimization_benchmark import network_example


def original():
    raw = network_example()
    net = raw["network"]
    net["lines"][0]["limit_mw"] = 2
    net["lines"].append({**net["lines"][0], "id": "AB2"})
    net["unit_reserve_capability_mw"]["cheap"] = 2
    net["security"] = {"outage_lines": ["AB"], "outage_units": ["local"]}
    return raw


@pytest.fixture
def authorization(tmp_path):
    identifier = start_program(tmp_path, original())
    report = resume_program(tmp_path, identifier)
    assert report["solver_result"]["status"] == "infeasible_reported"
    diagnosis = diagnose_study(tmp_path, identifier)
    return {"source_study_id": identifier, "source_report_sha256": diagnosis["source_report_sha256"],
            "probes": [{"kind": "unit", "component": "local"}, {"kind": "line", "component": "AB"}],
            "max_solver_calls": 3}


def test_counterfactual_isolates_unit_contingency(tmp_path, authorization):
    identifier = start_experiment(tmp_path, authorization)
    report = resume_experiment(tmp_path, identifier)
    assert report["completed"]
    assert report["reserved_solver_calls"] == 3
    assert report["observations"][0]["objective"] == pytest.approx(140)
    assert report["observations"][1]["status"] == "verified_feasible_candidate"
    assert report["observations"][2]["status"] == "infeasible_reported"
    updates = {r["probe"]["kind"]: r["status"] for r in report["hypothesis_updates"]}
    assert updates == {"line": "single_contingency_feasible_in_isolation",
                       "unit": "supports_contingency_conflict_hypothesis"}
    assert not report["root_cause_confirmed"]
    assert not report["original_model_modified"]
    assert resume_experiment(tmp_path, identifier, solver=lambda _: pytest.fail("Repeated solve")) == report
    assert diagnose_study(tmp_path, authorization["source_study_id"])["source_report_sha256"] == (
        authorization["source_report_sha256"])


def test_compiler_preserves_all_nonsecurity_fields(authorization):
    from gridagent.commitment_ir import UnitCommitment

    raw = UnitCommitment.model_validate(original()).canonical()
    expected = copy.deepcopy(raw)
    expected["network"].pop("security")
    spec = DiagnosticExperiment.model_validate(authorization)
    jobs = compile_probes(spec, raw)
    for job, variant in jobs:
        data = variant.canonical()
        security = data["network"].pop("security", None)
        assert data == expected
        if job["probe"] is None:
            assert security is None
        else:
            assert sum(len(security.get(key, [])) for key in ("outage_lines", "outage_units")) == 1
    auth = copy.deepcopy(authorization)
    auth["probes"].reverse()
    assert DiagnosticExperiment.model_validate(auth).sha256() == spec.sha256()


@pytest.mark.parametrize("fault", ["budget", "duplicate", "unapproved", "wrong_hash"])
def test_invalid_authorization_rejected(tmp_path, authorization, fault):
    if fault == "budget":
        authorization["max_solver_calls"] = 2
    elif fault == "duplicate":
        authorization["probes"][1] = authorization["probes"][0]
    elif fault == "unapproved":
        authorization["probes"][1]["component"] = "AB2"
    else:
        authorization["source_report_sha256"] = "0"*64
    with pytest.raises(ValueError):
        start_experiment(tmp_path, authorization)


def test_interrupted_reservation_not_replayed(tmp_path, authorization):
    identifier = start_experiment(tmp_path, authorization)
    calls = []

    def interrupt(_):
        calls.append("interrupted")
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        resume_experiment(tmp_path, identifier, solver=interrupt)

    def counted(spec):
        calls.append("new")
        return solve(spec)

    report = resume_experiment(tmp_path, identifier, solver=counted)
    assert calls == ["interrupted", "new", "new"]
    assert report["observations"][0]["status"] == "unknown_reserved_call"
    assert not report["completed"]
    assert all(row["status"] == "inconclusive" for row in report["hypothesis_updates"])
    assert resume_experiment(tmp_path, identifier, solver=lambda _: pytest.fail("Repeated solve")) == report


def test_version_mismatch_is_not_causal_evidence(tmp_path, authorization):
    identifier = start_experiment(tmp_path, authorization)

    def mismatched(spec):
        return {**solve(spec), "scipy_version": "different-version"}

    report = resume_experiment(tmp_path, identifier, solver=mismatched)
    assert not report["completed"]
    assert all(not row["comparable"] for row in report["observations"])
    assert all(row["status"] == "inconclusive" for row in report["hypothesis_updates"])


def test_child_result_tampering_rejected(tmp_path, authorization):
    identifier = start_experiment(tmp_path, authorization)
    report = resume_experiment(tmp_path, identifier)
    child = report["observations"][0]["child_study_id"]
    path = tmp_path / "studies" / child / "report.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["completed"] = False
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError, match="evidence changed"):
        resume_experiment(tmp_path, identifier)


def test_source_feasible_rejected(tmp_path):
    raw = network_example()
    raw["network"]["security"] = {"outage_lines": ["AB"]}
    identifier = start_program(tmp_path, raw)
    assert resume_program(tmp_path, identifier)["completed"]
    diagnosis = diagnose_study(tmp_path, identifier)
    with pytest.raises(ValueError, match="infeasibility"):
        start_experiment(tmp_path, {"source_study_id": identifier,
                                   "source_report_sha256": diagnosis["source_report_sha256"],
                                   "probes": [{"kind": "line", "component": "AB"}], "max_solver_calls": 2})
