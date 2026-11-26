# GridAgent 2.0: versioned task lifecycle contracts

This module is the first implementation slice of Phase 1 in ROADMAP.md. It establishes a transport-independent contract before the existing CLI, TUI, desktop bridge and research workflows are migrated.

## What it defines

- RequirementSpec: an immutable, versioned record of the original request, objective, required outputs, constraints, assumptions and unresolved questions.
- RequirementFact: a typed engineering fact with explicit provenance (user, derived, default or unresolved) and an optional unit. Unresolved facts cannot carry an invented value.
- EngineeringTask: a versioned task snapshot with a monotonic revision, lifecycle status, requirement revision, plan revision, model revision and cancellation state.
- TaskEvent: an append-ready lifecycle event whose sequence matches the resulting task revision.
- transition_task, request_cancellation and revise_requirement: pure transition functions. They return a new immutable snapshot and its corresponding event; they do not perform I/O or execute engineering work.

## Lifecycle

~~~text
draft -> needs_clarification -> draft -> planned
                                      |       |
                                      |       +-> awaiting_approval -> planned
                                      |                                  |
                                      +---------------------------------> running
                                                                         |
                                                                         v
                                                                     verifying
                                                                    /    |    \
                                                              completed partial failed
~~~

Cancellation may be requested from any non-terminal state. A request is recorded separately from the runtime acknowledging cancellation; after a request, the only valid status transition is to cancelled.

partial is resumable. Resuming it may attach a newer plan revision. A task cannot move directly from running to completed: it must pass through verifying. A plan must be versioned before execution, and an awaiting_approval plan cannot be approved implicitly.

## Invariants

1. Contracts reject unknown fields, are immutable and disallow non-finite numeric values.
2. Requirement facts retain provenance and units; duplicate keys and duplicate required outputs are rejected.
3. Every task mutation increments its revision. Events use that revision as their sequence, providing a future optimistic-concurrency and event-log boundary.
4. Timestamps are timezone-aware and monotonic.
5. Revising requirements creates a new immutable requirement revision. If a plan already exists, the plan is invalidated and the task returns to draft.
6. Failed tasks require a reason. Terminal tasks cannot be resumed or silently rewritten.
7. Cancellation requests do not claim that a running subprocess has stopped; runtime acknowledgement remains explicit.

## Persistence

Open the canonical repository through the existing workspace store:

```python
from pathlib import Path
from gridagent.store import ResearchStore
from gridagent.task_contracts import RequirementSpec, TaskStatus

tasks = ResearchStore(Path(".gridagent/research.sqlite3")).engineering_tasks()
task = tasks.create(RequirementSpec(request="Check voltage limits"))
task, event = tasks.transition(task.task_id, task.revision, TaskStatus.PLANNED, plan_revision=1)
```

Two additive tables hold a head revision and immutable snapshots with matching lifecycle events. Revision zero contains the initial requirement snapshot and no event. Subsequent mutations append a snapshot and event and advance the head within one SQLite transaction. A stale expected revision raises TaskRevisionConflict; callers must reload and reconsider, not blindly retry.

A reopened workspace can read historical requirements, inspect event continuity, and discover unfinished tasks. Discovery is not execution: the runtime must reconcile unknown solver operations before resuming them. No automatic replay or claim of solver verification is made here.

## Scope and migration

The V2 contract and repository coexist with the existing session and research task tables. Existing ResearchTasks, recorded_task, CLI/TUI flows and desktop IPC still use their original orchestration. The next integration slice is to route one existing workflow through the canonical repository and define its evidence and execution checkpoints before expanding to the other entry points. No roadmap gate is complete solely because the repository exists.

No simulator calls, provider calls or background workers are performed by this module.
