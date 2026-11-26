"""Bridge the existing AC research checkpoints to the V2 engineering lifecycle."""

from .task_contracts import (
    RequirementSpec,
    TaskStatus,
    request_cancellation,
    transition_task,
)


class ResearchLifecycle:
    """Use the same SQLite transaction for legacy checkpoints and canonical events.

    The frozen manifest and reserved solver runs remain the execution contract.
    Existing tasks without a V2 head remain readable; no history is fabricated.
    """

    def __init__(self, repository):
        self.repository = repository

    def create(self, db, identifier, prompt, state, stage):
        model_hash = state.get("engineering_ir", {}).get("model_sha256")
        self.repository._create_in(db, RequirementSpec(request=prompt), task_id=identifier,
                                   model_revision=model_hash)
        self.checkpoint(db, identifier, state, stage)

    def checkpoint(self, db, identifier, state, stage, *, approved=False):
        task = self.repository._find_in(db, identifier)
        if task is None:
            return

        def move(target, **kwargs):
            nonlocal task
            if task.status != target:
                task, _ = self.repository._mutate_in(
                    db, identifier, task.revision, lambda current: transition_task(current, target, **kwargs)
                )

        if stage == "planning":
            if task.status == TaskStatus.NEEDS_CLARIFICATION:
                move(TaskStatus.DRAFT)
        elif stage == "awaiting_input":
            move(TaskStatus.NEEDS_CLARIFICATION)
        elif stage in {"ready", "awaiting_approval"}:
            if task.status == TaskStatus.DRAFT:
                move(TaskStatus.PLANNED, plan_revision=1,
                     reason="Frozen research manifest: " + state["manifest_sha256"])
            if stage == "awaiting_approval":
                move(TaskStatus.AWAITING_APPROVAL)
            elif task.status == TaskStatus.AWAITING_APPROVAL:
                move(TaskStatus.PLANNED, approved=approved, actor="user")
        elif stage in {"running", "repairing"}:
            move(TaskStatus.RUNNING)
        elif stage == "evaluating":
            move(TaskStatus.VERIFYING)
        elif stage == "passed":
            attempts = state.get("attempts", [])
            last = attempts[-1] if attempts else {}
            scenarios = state.get("manifest", {}).get("scenarios", [])
            expected = {item["name"] for item in scenarios}
            runs = last.get("runs", [])
            if (not expected or len(runs) != len(expected) or {r["scenario"] for r in runs} != expected
                    or not last.get("finished") or not last.get("passed")
                    or not all(r.get("status") == "ok" and r.get("evaluation", {}).get("passed")
                               and r["evaluation"].get("checks")
                               and all(check.get("passed") for check in r["evaluation"]["checks"])
                               for r in runs)):
                raise ValueError("Cannot complete research without verified evidence for every scenario")
            move(TaskStatus.VERIFYING)
            move(TaskStatus.COMPLETED, actor="verifier", reason="All frozen scenario checks passed")
        elif stage == "failed":
            move(TaskStatus.FAILED, reason=state.get("termination") or "Research criteria not satisfied")
        elif stage == "cancelled":
            move(TaskStatus.CANCELLED)
        else:
            raise ValueError(f"Unknown research checkpoint: {stage}")

    def request_cancel(self, db, identifier):
        task = self.repository._find_in(db, identifier)
        if task is not None and not task.cancel_requested:
            self.repository._mutate_in(db, identifier, task.revision, request_cancellation)
