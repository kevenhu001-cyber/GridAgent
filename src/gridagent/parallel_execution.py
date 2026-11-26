"""Bounded batch execution; workers never mutate task state or journal rows."""

import os
from concurrent.futures import ThreadPoolExecutor


def ac_workers():
    """Opt in via environment, capped to four native subprocesses per task."""
    workers = int(os.getenv("GRIDAGENT_AC_WORKERS", "1"))
    if not 1 <= workers <= 4:
        raise ValueError("GRIDAGENT_AC_WORKERS must be between 1 and 4")
    return workers


def run_batch(jobs, *, workers, launch, cancelled):
    """Run only freshly reserved jobs. Join workers before releasing the task lock.

    The coordinator owns checkpoints, including the deterministic result order.
    An exception never causes an automatic retry of a potentially executed job.
    """
    if not 1 <= workers <= 4 or len(jobs) > workers:
        raise ValueError("Batch exceeds configured worker limit")

    def execute(job):
        if cancelled():
            return {"launch": "not_started"}
        try:
            return launch(job)
        except Exception as exc:  # noqa: BLE001 - a reserved native call may have executed
            return {"launch": "exception", "launch_error_type": type(exc).__name__}

    if not jobs:
        return []
    if workers == 1:
        return [execute(job) for job in jobs]
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="gridagent-ac") as pool:
        return list(pool.map(execute, jobs))
