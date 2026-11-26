import copy
import json
import sqlite3
from contextlib import closing

import pytest

from gridagent import ac_repair_experience as memory
from gridagent.dsr import Study


def ac_spec():
    return {
        "commitment_study_id": "a"*32,
        "model": {"model_id": "grid", "buses": [{"id": "A", "nominal_kv": 10}],
                  "devices": [{"kind": "slack", "id": "g", "bus": "A", "voltage_pu": 0.89},
                              {"kind": "load", "id": "load", "bus": "A", "active_mw": 1}]},
        "unit_devices": {"g": "g"}, "slack_unit": "g",
        "unit_reactive_limits": {"g": {"minimum_mvar": -1, "maximum_mvar": 1}},
        "reactive_demand_mvar": {"A": [0]}, "snapshots": [{"hour": 0}],
        "slack_max_deviation_mw": 0.2,
    }


def observed(status="verified", version="3", passed=True, failed_check=None):
    checks = [{"id": key, "passed": True} for key in (
        "model_input_fidelity", "solver_success", "active_bus_coverage", "power_balance_mva")]
    if failed_check:
        checks.append({"id": failed_check, "passed": False})
    return {"observation": {"passed": passed, "native_evidence": {"status": status,
                                                                  "solver_version": version},
                            "native_verdict": {"checks": checks}, "physical": None}}


def test_outcome_distinguishes_rejected_and_unknown():
    assert memory.outcome([observed()], "3", True, 1)["outcome"] == "verified_original_scope"
    rejected = observed("rejected", passed=False, failed_check="voltage_operating_range")
    unknown = observed("unavailable", passed=False)
    result = memory.outcome([rejected, unknown], "3", False, 2)
    assert result["outcome"] == "rejected_observed_violation"
    assert result["failed_rule_ids"] == ["voltage"]
    assert result["unavailable_or_noncomparable_snapshots"] == 1
    assert memory.outcome([unknown], "3", False, 1)["outcome"] == "inconclusive"
    assert memory.outcome([observed(version="4")], "3", False, 1)["outcome"] == "inconclusive"
    with pytest.raises(ValueError, match="Inconsistent"):
        memory.outcome([unknown], "3", True, 1)


def test_features_exclude_parameters_and_identifiers():
    raw = ac_spec()
    first = memory.features(raw)
    raw["model"]["devices"][0]["voltage_pu"] = 1.02
    raw["model"]["devices"][1]["active_mw"] = 99
    assert memory.features(raw) == first
    assert set(first) == {"buses", "lines", "regulating_units", "storage", "snapshots", "outage_snapshots"}
    assert memory.similarity(first, first) == 1
    other = {**first, "buses": 50, "lines": 60}
    assert 0 < memory.similarity(first, other) < 1


def test_unfinished_study_not_replayed(tmp_path):
    study = Study(tmp_path / "studies")
    with pytest.raises(ValueError, match="committed repair report"):
        memory.remember_ac_repair(tmp_path, study.id)
    assert not (tmp_path / "experience.sqlite3").exists()


@pytest.fixture
def mocked_index(tmp_path, monkeypatch):
    source = Study(tmp_path / "studies")
    source.write("manifest", {"spec": ac_spec()})
    monkeypatch.setattr(memory, "diagnose_study", lambda *_: {
        "source_protocol": memory.AC_PROTOCOL, "source_report_sha256": "a"*64,
        "findings": [{"rule_id": "voltage", "evidence": [{"context": {"snapshot": {"hour": 0}}}]}]})
    records = {}

    def fake_replay(root, identifier):
        return copy.deepcopy(records[identifier])

    monkeypatch.setattr(memory, "replay_records", fake_replay)

    def add(identifier, index=1, **changes):
        row = {"protocol": memory.PROTOCOL, "repair_study_id": identifier, "candidate_index": index,
               "repair_report_sha256": "b"*64, "source_report_sha256": "a"*64, "target_rule_id": "voltage",
               "features": memory.features(ac_spec()), "snapshot_kind": "base",
               "solver_version": "3", "outcome": "verified_original_scope", "intervention": "voltage_setpoint",
               "direction": "increase", "scope": memory.SCOPE, **changes}
        records.setdefault(identifier, []).append(row)
        return row

    return source.id, records, add


def test_index_is_idempotent_and_search_rechecks(tmp_path, mocked_index):
    source, records, add = mocked_index
    add("a"*32)
    add("b"*32, snapshot_kind="outage", outcome="rejected_observed_violation")
    add("c"*32, target_rule_id="loading")
    for identifier in records:
        memory.remember_ac_repair(tmp_path, identifier)
        memory.remember_ac_repair(tmp_path, identifier)
    report = memory.search_ac_experience(tmp_path, source)
    assert [row["repair_study_id"] for row in report["matches"]] == ["a"*32, "b"*32]
    assert report["solver_calls"] == 0
    assert report["replayed_studies"] == 2
    assert report["matches"][1]["outcome"] == "rejected_observed_violation"
    records["a"*32][0]["direction"] = "decrease"
    assert len(memory.search_ac_experience(tmp_path, source)["matches"]) == 1
    with pytest.raises(ValueError, match="differs"):
        memory.remember_ac_repair(tmp_path, "a"*32)


def test_index_payload_tampering_is_not_returned(tmp_path, mocked_index):
    source, _, add = mocked_index
    row = add("a"*32)
    memory.remember_ac_repair(tmp_path, "a"*32)
    with closing(sqlite3.connect(tmp_path / "experience.sqlite3")) as db, db:
        altered = {**row, "outcome": "inconclusive"}
        db.execute("UPDATE ac_repair_experience SET payload=?", (json.dumps(altered),))
    assert memory.search_ac_experience(tmp_path, source)["matches"] == []


def test_replay_budget_is_bounded(tmp_path, mocked_index):
    source, _, add = mocked_index
    for index in range(memory.MAX_REPLAY_STUDIES+1):
        identifier = f"{index:032x}"
        add(identifier)
        memory.remember_ac_repair(tmp_path, identifier)
    report = memory.search_ac_experience(tmp_path, source, limit=3)
    assert report["scan_truncated"]
    assert report["replayed_studies"] == memory.MAX_REPLAY_STUDIES
    assert len(report["matches"]) == 3
