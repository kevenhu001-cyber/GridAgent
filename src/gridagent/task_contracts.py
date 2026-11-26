"""Versioned, transport-independent task contracts for GridAgent 2.0."""
from datetime import UTC, datetime
from enum import Enum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

SCHEMA_VERSION = 1
TaskActor = Literal["user", "agent", "runtime", "verifier"]
RequirementSource = Literal["user", "derived", "default", "unresolved"]


def utc_now() -> datetime:
    return datetime.now(UTC)


class Contract(BaseModel):
    """Immutable contract base: reject unknown fields and non-finite numbers."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        allow_inf_nan=False,
        str_strip_whitespace=True,
    )


class RequirementFact(Contract):
    """One engineering constraint or assumption with explicit provenance."""

    key: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    value: str | int | float | bool | None
    source: RequirementSource
    unit: str | None = Field(default=None, max_length=32)
    rationale: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_provenance(self):
        if self.source == "unresolved" and self.value is not None:
            raise ValueError("Unresolved requirement facts must not claim a value")
        if self.source != "unresolved" and self.value is None:
            raise ValueError("Resolved requirement facts must include a value")
        return self


class RequirementSpec(Contract):
    """Immutable record of the user's request and its interpreted requirements."""

    schema_version: Literal[1] = SCHEMA_VERSION
    revision: int = Field(default=1, ge=1)
    request: str = Field(min_length=1, max_length=12000)
    objective: str | None = Field(default=None, max_length=4000)
    required_outputs: tuple[str, ...] = Field(default=(), max_length=32)
    constraints: tuple[RequirementFact, ...] = Field(default=(), max_length=64)
    assumptions: tuple[RequirementFact, ...] = Field(default=(), max_length=64)
    open_questions: tuple[str, ...] = Field(default=(), max_length=16)

    @model_validator(mode="after")
    def validate_unique_keys(self):
        keys = [fact.key for fact in (*self.constraints, *self.assumptions)]
        if len(keys) != len(set(keys)):
            raise ValueError("Requirement facts must have unique keys across constraints and assumptions")
        outputs = [value.casefold() for value in self.required_outputs]
        if len(outputs) != len(set(outputs)):
            raise ValueError("Required outputs must be unique")
        return self


class TaskStatus(str, Enum):
    DRAFT = "draft"
    NEEDS_CLARIFICATION = "needs_clarification"
    PLANNED = "planned"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATUSES = frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED})

_ALLOWED_TRANSITIONS = {
    TaskStatus.DRAFT: {TaskStatus.NEEDS_CLARIFICATION, TaskStatus.PLANNED, TaskStatus.CANCELLED},
    TaskStatus.NEEDS_CLARIFICATION: {TaskStatus.DRAFT, TaskStatus.CANCELLED},
    TaskStatus.PLANNED: {
        TaskStatus.AWAITING_APPROVAL, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED
    },
    TaskStatus.AWAITING_APPROVAL: {TaskStatus.PLANNED, TaskStatus.CANCELLED},
    TaskStatus.RUNNING: {
        TaskStatus.VERIFYING, TaskStatus.PARTIAL, TaskStatus.FAILED, TaskStatus.CANCELLED
    },
    TaskStatus.VERIFYING: {
        TaskStatus.COMPLETED, TaskStatus.PARTIAL, TaskStatus.FAILED, TaskStatus.CANCELLED
    },
    TaskStatus.PARTIAL: {TaskStatus.PLANNED, TaskStatus.RUNNING, TaskStatus.CANCELLED},
    TaskStatus.COMPLETED: set(),
    TaskStatus.FAILED: set(),
    TaskStatus.CANCELLED: set(),
}


class TaskTransitionError(ValueError):
    """Raised when a task lifecycle transition violates the state machine."""


class EngineeringTask(Contract):
    """Versioned task snapshot; revision is also its optimistic concurrency token."""

    schema_version: Literal[1] = SCHEMA_VERSION
    task_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    revision: int = Field(default=0, ge=0)
    status: TaskStatus = TaskStatus.DRAFT
    requirement: RequirementSpec
    plan_revision: int | None = Field(default=None, ge=1)
    model_revision: str | None = Field(default=None, min_length=1, max_length=256)
    cancel_requested: bool = False
    terminal_reason: str | None = Field(default=None, max_length=1000)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_snapshot(self):
        if self.created_at.tzinfo is None or self.updated_at.tzinfo is None:
            raise ValueError("Task timestamps must be timezone-aware")
        if self.updated_at < self.created_at:
            raise ValueError("Task update time cannot precede creation time")
        plan_required = {
            TaskStatus.PLANNED,
            TaskStatus.AWAITING_APPROVAL,
            TaskStatus.RUNNING,
            TaskStatus.VERIFYING,
            TaskStatus.COMPLETED,
            TaskStatus.PARTIAL,
        }
        if self.status in plan_required and self.plan_revision is None:
            raise ValueError("A planned or executing task must reference a plan revision")
        if self.status == TaskStatus.FAILED and not self.terminal_reason:
            raise ValueError("Failed tasks must record a terminal reason")
        if self.status == TaskStatus.CANCELLED and not self.cancel_requested:
            raise ValueError("Cancelled tasks must record a cancellation request")
        return self


class TaskEvent(Contract):
    """Append-only lifecycle event; sequence matches the resulting task revision."""

    schema_version: Literal[1] = SCHEMA_VERSION
    event_id: str = Field(default_factory=lambda: uuid4().hex, pattern=r"^[0-9a-f]{32}$")
    task_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    sequence: int = Field(ge=1)
    kind: Literal["status_transition", "cancellation_requested", "requirement_revised"]
    from_status: TaskStatus
    to_status: TaskStatus
    actor: TaskActor
    reason: str | None = Field(default=None, max_length=1000)
    requirement_revision: int | None = Field(default=None, ge=1)
    occurred_at: datetime = Field(default_factory=utc_now)

    @model_validator(mode="after")
    def validate_event(self):
        if self.occurred_at.tzinfo is None:
            raise ValueError("Event timestamp must be timezone-aware")
        if self.kind == "status_transition" and self.from_status == self.to_status:
            raise ValueError("Status transition events must change status")
        if self.kind == "cancellation_requested" and self.from_status != self.to_status:
            raise ValueError("Cancellation request events must preserve status")
        if self.kind == "requirement_revised":
            if self.requirement_revision is None:
                raise ValueError("Requirement revision events must identify the new requirement revision")
            if self.to_status not in {self.from_status, TaskStatus.DRAFT}:
                raise ValueError("Requirement revisions may preserve status or return the task to draft")
        elif self.requirement_revision is not None:
            raise ValueError("Only requirement revision events may carry a requirement revision")
        return self


def _event(task: EngineeringTask, *, kind: str, from_status: TaskStatus, to_status: TaskStatus,
           actor: TaskActor, reason: str | None, at: datetime,
           requirement_revision: int | None = None) -> TaskEvent:
    return TaskEvent(
        task_id=task.task_id,
        sequence=task.revision,
        kind=kind,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        requirement_revision=requirement_revision,
        occurred_at=at,
    )


def transition_task(
    task: EngineeringTask,
    target: TaskStatus,
    *,
    actor: TaskActor = "runtime",
    reason: str | None = None,
    approved: bool = False,
    plan_revision: int | None = None,
    at: datetime | None = None,
) -> tuple[EngineeringTask, TaskEvent]:
    """Apply one validated lifecycle transition and emit its matching event."""
    target = TaskStatus(target)
    if target not in _ALLOWED_TRANSITIONS[task.status]:
        raise TaskTransitionError(f"Transition {task.status.value} -> {target.value} is not allowed")
    if task.cancel_requested and target != TaskStatus.CANCELLED:
        raise TaskTransitionError("A cancellation-requested task may only transition to cancelled")
    if target == TaskStatus.CANCELLED and (not task.cancel_requested or actor != "runtime"):
        raise TaskTransitionError("Cancellation requires a recorded request and runtime acknowledgement")
    if task.status == TaskStatus.AWAITING_APPROVAL and target == TaskStatus.PLANNED:
        if not approved:
            raise TaskTransitionError("The current plan must be explicitly approved before execution")
        if plan_revision is not None and plan_revision != task.plan_revision:
            raise TaskTransitionError("Approval must refer to the exact pending plan revision")
    if target == TaskStatus.FAILED and not (reason and reason.strip()):
        raise TaskTransitionError("Failed tasks must include a reason")

    next_plan_revision = task.plan_revision
    if target == TaskStatus.PLANNED:
        if plan_revision is not None:
            if task.plan_revision is not None and plan_revision < task.plan_revision:
                raise TaskTransitionError("Plan revisions cannot move backwards")
            next_plan_revision = plan_revision
        if next_plan_revision is None:
            raise TaskTransitionError("A plan revision is required before a task can be planned")
    elif plan_revision is not None and plan_revision != task.plan_revision:
        raise TaskTransitionError("Plan revisions may only change when entering the planned state")

    timestamp = at or utc_now()
    if timestamp.tzinfo is None or timestamp < task.updated_at:
        raise TaskTransitionError("Transition timestamp must be timezone-aware and monotonic")
    updated = EngineeringTask.model_validate({
        **task.model_dump(),
        "revision": task.revision + 1,
        "status": target,
        "plan_revision": next_plan_revision,
        "cancel_requested": task.cancel_requested or target == TaskStatus.CANCELLED,
        "terminal_reason": reason.strip() if target == TaskStatus.FAILED and reason else None,
        "updated_at": timestamp,
    })
    return updated, _event(
        updated, kind="status_transition", from_status=task.status, to_status=target, actor=actor,
        reason=reason.strip() if reason else None, at=timestamp,
    )


def request_cancellation(
    task: EngineeringTask,
    *,
    actor: TaskActor = "user",
    reason: str | None = None,
    at: datetime | None = None,
) -> tuple[EngineeringTask, TaskEvent]:
    """Record a cooperative cancellation request without pretending work has stopped."""
    if task.status in TERMINAL_STATUSES:
        raise TaskTransitionError("Terminal tasks cannot be cancelled again")
    if task.cancel_requested:
        raise TaskTransitionError("Cancellation has already been requested")
    timestamp = at or utc_now()
    if timestamp.tzinfo is None or timestamp < task.updated_at:
        raise TaskTransitionError("Cancellation timestamp must be timezone-aware and monotonic")
    updated = EngineeringTask.model_validate({
        **task.model_dump(),
        "revision": task.revision + 1,
        "cancel_requested": True,
        "updated_at": timestamp,
    })
    return updated, _event(
        updated, kind="cancellation_requested", from_status=task.status, to_status=task.status,
        actor=actor, reason=reason.strip() if reason else None, at=timestamp,
    )


def revise_requirement(
    task: EngineeringTask,
    requirement: RequirementSpec,
    *,
    actor: TaskActor = "user",
    reason: str,
    at: datetime | None = None,
) -> tuple[EngineeringTask, TaskEvent]:
    """Create a new immutable requirement revision and invalidate any stale plan."""
    if task.status in TERMINAL_STATUSES or task.status in {TaskStatus.RUNNING, TaskStatus.VERIFYING}:
        raise TaskTransitionError("Requirements cannot be revised after execution has started or terminated")
    if task.cancel_requested:
        raise TaskTransitionError("A cancellation-requested task cannot change requirements")
    if not reason or not reason.strip():
        raise TaskTransitionError("Requirement revisions must include an audit reason")
    timestamp = at or utc_now()
    if timestamp.tzinfo is None or timestamp < task.updated_at:
        raise TaskTransitionError("Requirement revision timestamp must be timezone-aware and monotonic")

    revised = RequirementSpec.model_validate({
        **requirement.model_dump(),
        "revision": task.requirement.revision + 1,
    })
    next_status = task.status
    next_plan_revision = task.plan_revision
    if task.status in {TaskStatus.PLANNED, TaskStatus.AWAITING_APPROVAL, TaskStatus.PARTIAL}:
        next_status = TaskStatus.DRAFT
        next_plan_revision = None
    updated = EngineeringTask.model_validate({
        **task.model_dump(),
        "revision": task.revision + 1,
        "status": next_status,
        "requirement": revised,
        "plan_revision": next_plan_revision,
        "terminal_reason": None,
        "updated_at": timestamp,
    })
    return updated, _event(
        updated, kind="requirement_revised", from_status=task.status, to_status=next_status,
        actor=actor, reason=reason.strip(), at=timestamp, requirement_revision=revised.revision,
    )
