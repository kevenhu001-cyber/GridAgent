import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from gridagent.store import ResearchStore
from gridagent.task_contracts import RequirementSpec, TaskStatus, TaskTransitionError
from gridagent.task_repository import TaskRevisionConflict


def setup_repo(tmp_path):
    store = ResearchStore(tmp_path / "research.sqlite3")
    return store, store.engineering_tasks()


def new_task(repo):
    return repo.create(RequirementSpec(request="Check bus voltage under peak load"))


def test_reopen_keeps_snapshots_events_and_legacy_sessions(tmp_path):
    store, repo = setup_repo(tmp_path)
    session_id = store.create_session("Legacy session")
    task = new_task(repo)
    planned, event = repo.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)

    reopened_store, reopened = setup_repo(tmp_path)
    assert reopened_store.require_session(session_id) == session_id
    assert reopened.get(task.task_id) == planned
    assert reopened.get_revision(task.task_id, 0) == task
    assert reopened.get_revision(task.task_id, 1) == planned
    assert reopened.events(task.task_id) == (event,)


def test_failed_transition_leaves_head_and_event_history_unchanged(tmp_path):
    _, repo = setup_repo(tmp_path)
    task = new_task(repo)
    with pytest.raises(TaskTransitionError):
        repo.transition(task.task_id, 0, TaskStatus.COMPLETED)
    assert repo.get(task.task_id) == task
    assert repo.events(task.task_id) == ()


def test_stale_revision_cannot_overwrite_newer_state(tmp_path):
    _, repo = setup_repo(tmp_path)
    _, other = setup_repo(tmp_path)
    task = new_task(repo)
    planned, event = repo.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)
    with pytest.raises(TaskRevisionConflict, match="Expected revision 0"):
        other.request_cancel(task.task_id, 0)
    assert other.get(task.task_id) == planned
    assert other.events(task.task_id) == (event,)


def test_concurrent_writers_commit_at_most_one_mutation(tmp_path):
    _, repo = setup_repo(tmp_path)
    _, other = setup_repo(tmp_path)
    task = new_task(repo)
    barrier = Barrier(2)

    def plan(repository):
        barrier.wait(timeout=10)
        try:
            repository.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)
        except TaskRevisionConflict:
            return "stale"
        return "committed"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(plan, repo)
        second = pool.submit(plan, other)
        assert sorted([first.result(timeout=20), second.result(timeout=20)]) == ["committed", "stale"]
    assert repo.get(task.task_id).revision == 1
    assert len(repo.events(task.task_id)) == 1


def test_head_write_failure_rolls_back_the_appended_snapshot_and_event(tmp_path):
    store, repo = setup_repo(tmp_path)
    task = new_task(repo)
    with store.connect() as db:
        db.execute("""
            CREATE TRIGGER reject_head_update BEFORE UPDATE ON engineering_tasks
            BEGIN SELECT RAISE(ABORT, 'test failure'); END
        """)
    with pytest.raises(sqlite3.IntegrityError, match="test failure"):
        repo.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)
    assert repo.get(task.task_id) == task
    assert repo.events(task.task_id) == ()
    with pytest.raises(ValueError, match="Unknown"):
        repo.get_revision(task.task_id, 1)


def test_requirement_revision_and_cancellation_survive_reopen(tmp_path):
    _, repo = setup_repo(tmp_path)
    task = new_task(repo)
    planned, _ = repo.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)
    revised, event = repo.revise(
        task.task_id, planned.revision,
        RequirementSpec(request="Check peak load and N-1 outage"),
        reason="User added a scenario",
    )
    assert revised.status == TaskStatus.DRAFT
    assert revised.plan_revision is None
    assert event.requirement_revision == 2
    assert repo.get_revision(task.task_id, 0).requirement == task.requirement

    requested, _ = repo.request_cancel(task.task_id, revised.revision)
    _, reopened = setup_repo(tmp_path)
    assert reopened.get(task.task_id) == requested
    assert requested in reopened.unfinished()
    cancelled, _ = reopened.transition(task.task_id, requested.revision, TaskStatus.CANCELLED)
    assert cancelled.status == TaskStatus.CANCELLED
    assert reopened.unfinished() == ()
    assert [e.sequence for e in reopened.events(task.task_id)] == [1, 2, 3, 4]


def test_interrupted_running_task_is_discoverable_without_reexecution(tmp_path):
    _, repo = setup_repo(tmp_path)
    task = new_task(repo)
    planned, _ = repo.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)
    running, _ = repo.transition(task.task_id, planned.revision, TaskStatus.RUNNING)
    _, reopened = setup_repo(tmp_path)
    assert reopened.unfinished() == (running,)
    assert reopened.get(task.task_id).status == TaskStatus.RUNNING


def test_corrupt_snapshot_identity_is_detected(tmp_path):
    store, repo = setup_repo(tmp_path)
    task = new_task(repo)
    another = new_task(repo)
    with store.connect() as db:
        db.execute("""
            UPDATE engineering_task_revisions SET snapshot = ?
            WHERE task_id = ? AND revision = 0
        """, (another.model_dump_json(), task.task_id))
    with pytest.raises(ValueError, match="identity mismatch"):
        repo.get(task.task_id)


def test_missing_event_history_is_detected(tmp_path):
    store, repo = setup_repo(tmp_path)
    task = new_task(repo)
    planned, _ = repo.transition(task.task_id, 0, TaskStatus.PLANNED, plan_revision=1)
    repo.transition(task.task_id, planned.revision, TaskStatus.RUNNING)
    with store.connect() as db:
        db.execute("""
            DELETE FROM engineering_task_revisions WHERE task_id = ? AND revision = 1
        """, (task.task_id,))
    with pytest.raises(ValueError, match="incomplete"):
        repo.events(task.task_id)
