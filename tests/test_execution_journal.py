import sqlite3

import pytest

from gridagent.evidence import EvidenceRecord
from gridagent.execution_journal import ExecutionJournal
from gridagent.execution_plan import fixed_plan
from gridagent.store import ResearchStore
from gridagent.task_contracts import RequirementSpec


def setup_graph(tmp_path):
    store = ResearchStore(tmp_path / "research.sqlite3")
    task = store.engineering_tasks().create(RequirementSpec(request="Study"))
    journal = ExecutionJournal(store)
    plan = fixed_plan(family="ac_steady_state", model_sha256="a" * 64, study_sha256="b" * 64,
                      requests=[("base", {"a": 1}), ("peak", {"a": 2})], max_solver_runs=2)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        journal.register(db, task.task_id, plan)
    return store, journal, task.task_id, plan


def unavailable(plan, index, run_id):
    node = next(n for n in plan.nodes if n.id == f"solve-{index:03}")
    return EvidenceRecord(plan_sha256=plan.sha256(), solve_node_id=node.id, scenario=node.scenario,
                          run_id=run_id, request_sha256=node.request_sha256, evaluator=plan.evaluator,
                          status="unavailable", verdict_sha256="c" * 64)


def test_reservation_is_durable_and_cannot_be_replaced(tmp_path):
    store, journal, task_id, plan = setup_graph(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        journal.reserve(db, task_id, "solve-001", "1" * 32)
    reopened = ExecutionJournal(store)
    with store.connect() as db:
        _, rows = reopened.load(db, task_id, plan)
        assert rows["solve-001"]["status"] == "reserved"
        assert rows["solve-001"]["run_id"] == "1" * 32
        with pytest.raises(ValueError, match="already reserved"):
            reopened.reserve(db, task_id, "solve-001", "2" * 32)
        with pytest.raises(ValueError, match="incomplete"):
            reopened.aggregate(db, task_id)


def test_finish_and_aggregate_rejected_result(tmp_path):
    store, journal, task_id, plan = setup_graph(tmp_path)
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        for index in (1, 2):
            run_id = str(index) * 32
            journal.reserve(db, task_id, f"solve-{index:03}", run_id)
            record = unavailable(plan, index, run_id)
            journal.finish(db, task_id, record)
            journal.finish(db, task_id, record)
        assert journal.aggregate(db, task_id) == "rejected"
        assert journal.aggregate(db, task_id) == "rejected"
        _, rows = journal.load(db, task_id, plan)
        assert all(row["status"] == "done" for row in rows.values())
        assert rows["verify-001"]["evidence_sha256"] == unavailable(plan, 1, "1" * 32).sha256()


def test_wrong_run_identity_cannot_finish(tmp_path):
    store, journal, task_id, plan = setup_graph(tmp_path)
    with store.connect() as db:
        journal.reserve(db, task_id, "solve-001", "1" * 32)
        with pytest.raises(ValueError, match="does not match reservation"):
            journal.finish(db, task_id, unavailable(plan, 1, "2" * 32))


def test_reservation_rolls_back_with_checkpoint(tmp_path):
    store, journal, task_id, plan = setup_graph(tmp_path)
    with pytest.raises(sqlite3.IntegrityError), store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        journal.reserve(db, task_id, "solve-001", "1" * 32)
        db.execute("INSERT INTO execution_graphs SELECT * FROM execution_graphs WHERE task_id=?", (task_id,))
    with store.connect() as db:
        _, rows = journal.load(db, task_id, plan)
        assert rows["solve-001"]["status"] == "pending"
        assert rows["solve-001"]["run_id"] is None


def test_cancel_preserves_unknown_reserved_identity(tmp_path):
    store, journal, task_id, plan = setup_graph(tmp_path)
    with store.connect() as db:
        journal.reserve(db, task_id, "solve-001", "1" * 32)
        journal.cancel(db, task_id)
        _, rows = journal.load(db, task_id, plan)
        assert rows["solve-001"]["run_id"] == "1" * 32
        assert rows["solve-001"]["outcome"] == "unknown"
        assert rows["solve-002"]["outcome"] == "not_started"
        assert all(row["status"] == "cancelled" for row in rows.values())
        with pytest.raises(ValueError, match="already reserved"):
            journal.reserve(db, task_id, "solve-002", "2" * 32)
