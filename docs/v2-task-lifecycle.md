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

## Research workflow integration

New AC research tasks now receive a canonical task ID and revision zero in the same transaction as their existing research record. The frozen manifest hash is recorded in the planning event. Research-specific state (solver reservations, evidence, approved repair bounds, questions and clarifications) remains in the existing checkpoint payload. The canonical lifecycle is advanced atomically with each stage checkpoint:

| Existing stage | Canonical state |
| --- | --- |
| planning | draft |
| awaiting_input | needs_clarification |
| ready | planned |
| awaiting_approval | awaiting_approval |
| running / repairing | running |
| evaluating | verifying |
| passed | completed, only with passed evidence for every frozen scenario |
| failed | failed, with termination reason |
| cancelled | cancelled, after cooperative acknowledgement |

Verifying can return to running when the next scenario or authorized repair is necessary. A negative result that does not satisfy the frozen research criteria remains a failed research task in this compatibility slice; a later evidence/outcome contract will distinguish valid adverse observations from execution errors.

Cancellation sets a durable request flag first, so an active worker does not appear to have stopped before it returns. Only the worker holding the existing per-task execution lock, or an idle caller acquiring that lock, can acknowledge it. Uncertain solver reservations retain the existing recovery behavior and are not automatically repeated.

The repository allows direct reads of research-managed tasks, but mutations must use ResearchTasks so the solver checkpoint and canonical event cannot diverge. Older research tasks without V2 records remain readable and executable; their historical lifecycle is not fabricated. The public summary adds engineering_status and engineering_revision for new tasks.

## Scope and migration

This integrates the existing verified AC research path with the canonical lifecycle. Ordinary chat, CLI/TUI presentation and desktop IPC are not rewritten. The single-agent and multi-agent research benchmark variants still use their original planners; their deterministic execution and validation share the same lifecycle.

Next: factor a common orchestration service for ordinary chat and research, introduce typed plan and evidence contracts, and migrate the default path incrementally. No roadmap gate is complete solely because this adapter exists.
