from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from gridagent.task_contracts import (
    EngineeringTask,
    RequirementFact,
    RequirementSpec,
    TaskStatus,
    TaskTransitionError,
    request_cancellation,
    revise_requirement,
    transition_task,
)


def new_task():
    return EngineeringTask(requirement=RequirementSpec(
        request="Study voltage constraints for the IEEE 14-bus case",
        objective="Identify voltage violations after a load increase",
        required_outputs=("bus_voltage_table", "violations"),
        constraints=(RequirementFact(key="voltage_min", value=0.95, unit="p.u.", source="user"),),
    ))


def move(task, status, **kwargs):
    return transition_task(task, status, **kwargs)


def test_requirement_facts_keep_provenance_and_reject_unresolved_values():
    fact = RequirementFact(key="nominal_voltage", value=None, source="unresolved")
    assert fact.source == "unresolved"
    with pytest.raises(ValidationError):
        RequirementFact(key="nominal_voltage", value=110, unit="kV", source="unresolved")
    with pytest.raises(ValidationError):
        RequirementFact(key="nominal_voltage", value=None, source="user")


def test_requirement_contract_is_immutable_and_strict():
    requirement = new_task().requirement
    with pytest.raises(ValidationError):
        requirement.request = "changed"
    with pytest.raises(ValidationError):
        RequirementSpec(request="Study a feeder", unexpected=True)
    with pytest.raises(ValidationError):
        RequirementSpec(request="Study a feeder", required_outputs=("voltage", "Voltage"))


def test_complete_lifecycle_requires_plan_approval_and_verification():
    task = new_task()
    planned, event = move(task, TaskStatus.PLANNED, plan_revision=1)
    assert planned.revision == event.sequence == 1
    assert event.from_status == TaskStatus.DRAFT

    awaiting, _ = move(planned, TaskStatus.AWAITING_APPROVAL)
    with pytest.raises(TaskTransitionError, match="approved"):
        move(awaiting, TaskStatus.PLANNED)
    approved, _ = move(awaiting, TaskStatus.PLANNED, approved=True)
    running, _ = move(approved, TaskStatus.RUNNING)
    verifying, _ = move(running, TaskStatus.VERIFYING, actor="verifier")
    completed, final_event = move(verifying, TaskStatus.COMPLETED, actor="verifier")

    assert completed.status == TaskStatus.COMPLETED
    assert completed.revision == 6
    assert final_event.sequence == completed.revision
    assert final_event.from_status == TaskStatus.VERIFYING


def test_execution_cannot_skip_verification_or_start_without_a_plan():
    task = new_task()
    with pytest.raises(TaskTransitionError, match="plan revision"):
        move(task, TaskStatus.PLANNED)
    planned, _ = move(task, TaskStatus.PLANNED, plan_revision=1)
    running, _ = move(planned, TaskStatus.RUNNING)
    with pytest.raises(TaskTransitionError, match="not allowed"):
        move(running, TaskStatus.COMPLETED)


def test_failed_task_requires_a_reason_and_is_terminal():
    planned, _ = move(new_task(), TaskStatus.PLANNED, plan_revision=1)
    with pytest.raises(TaskTransitionError, match="reason"):
        move(planned, TaskStatus.FAILED)
    failed, _ = move(planned, TaskStatus.FAILED, reason="Unsupported solver capability")
    assert failed.terminal_reason == "Unsupported solver capability"
    with pytest.raises(TaskTransitionError, match="not allowed"):
        move(failed, TaskStatus.PLANNED, plan_revision=2)


def test_cancellation_is_a_request_until_runtime_acknowledges_it():
    task = new_task()
    requested, event = request_cancellation(task, reason="User stopped the study")
    assert requested.status == TaskStatus.DRAFT
    assert requested.cancel_requested
    assert event.kind == "cancellation_requested"
    assert event.from_status == event.to_status == TaskStatus.DRAFT
    with pytest.raises(TaskTransitionError, match="only transition to cancelled"):
        move(requested, TaskStatus.PLANNED, plan_revision=1)
    cancelled, final_event = move(requested, TaskStatus.CANCELLED, actor="runtime")
    assert cancelled.status == TaskStatus.CANCELLED
    assert final_event.sequence == cancelled.revision == 2


def test_partial_task_can_resume_with_a_new_plan_revision():
    planned, _ = move(new_task(), TaskStatus.PLANNED, plan_revision=1)
    running, _ = move(planned, TaskStatus.RUNNING)
    partial, _ = move(running, TaskStatus.PARTIAL, reason="One scenario lacks evidence")
    resumed, _ = move(partial, TaskStatus.PLANNED, plan_revision=2)
    assert resumed.plan_revision == 2
    assert resumed.status == TaskStatus.PLANNED


def test_task_timestamps_must_be_timezone_aware_and_monotonic():
    task = new_task()
    with pytest.raises(TaskTransitionError, match="monotonic"):
        move(task, TaskStatus.PLANNED, plan_revision=1, at=task.updated_at - timedelta(seconds=1))
    with pytest.raises(ValidationError, match="timezone-aware"):
        EngineeringTask(
            requirement=task.requirement,
            created_at=datetime(2026, 1, 1),
            updated_at=datetime(2026, 1, 1),
        )


def test_requirement_revision_invalidates_an_existing_plan():
    planned, _ = move(new_task(), TaskStatus.PLANNED, plan_revision=1)
    revised_input = RequirementSpec(
        request="Study voltage constraints for the IEEE 14-bus case under a 20% load increase",
        objective="Identify voltage violations and report bus-level evidence",
        required_outputs=("bus_voltage_table", "violations", "evidence_manifest"),
    )
    revised, event = revise_requirement(planned, revised_input, reason="User clarified the scenario")
    assert revised.requirement.revision == 2
    assert revised.revision == event.sequence == planned.revision + 1
    assert revised.status == TaskStatus.DRAFT
    assert revised.plan_revision is None
    assert event.kind == "requirement_revised"
    assert event.requirement_revision == 2


def test_requirement_cannot_change_after_execution_starts():
    planned, _ = move(new_task(), TaskStatus.PLANNED, plan_revision=1)
    running, _ = move(planned, TaskStatus.RUNNING)
    with pytest.raises(TaskTransitionError, match="execution has started"):
        revise_requirement(running, RequirementSpec(request="Changed request"), reason="New scope")


def test_plan_revision_cannot_move_backwards():
    planned, _ = move(new_task(), TaskStatus.PLANNED, plan_revision=3)
    running, _ = move(planned, TaskStatus.RUNNING)
    partial, _ = move(running, TaskStatus.PARTIAL)
    with pytest.raises(TaskTransitionError, match="move backwards"):
        move(partial, TaskStatus.PLANNED, plan_revision=2)


def test_approval_cannot_replace_the_pending_plan():
    planned, _ = move(new_task(), TaskStatus.PLANNED, plan_revision=1)
    awaiting, _ = move(planned, TaskStatus.AWAITING_APPROVAL)
    with pytest.raises(TaskTransitionError, match="exact pending plan revision"):
        move(awaiting, TaskStatus.PLANNED, approved=True, plan_revision=2)


def test_cancellation_requires_request_and_runtime_acknowledgement():
    task = new_task()
    with pytest.raises(TaskTransitionError, match="recorded request"):
        move(task, TaskStatus.CANCELLED)
    requested, _ = request_cancellation(task)
    with pytest.raises(TaskTransitionError, match="runtime acknowledgement"):
        move(requested, TaskStatus.CANCELLED, actor="agent")
