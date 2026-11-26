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

## Scope and migration

This PR adds the canonical contracts and unit tests only. Existing ResearchTasks, ResearchStore, CLI/TUI flows and desktop IPC remain unchanged to avoid mixing a data-contract introduction with a persistence migration. The next integration step is to adapt the existing SQLite research task store to persist these snapshots and append-only events, then route both ordinary chat and research entry points through the shared task lifecycle.

No simulator calls, provider calls, background workers or filesystem writes are performed by this module.
