"""Independent repeated trials; never read holdout labels in this runner."""
import os
import statistics
import time
from pathlib import Path

from .dsr import Study, digest
from .paper import PIN


def run_trials(root, task, factory, count=10, model_id="unspecified"):
    if task not in {"rank", "dmq", "dsr", "mitigate"} or not 1 <= count <= 10:
        raise ValueError("Choose rank/dmq/dsr/mitigate and 1..10 trials")
    batch = Study(Path(root) / "batches")
    config = {"protocol": "gridagent-paper-trials-v1", "upstream_commit": PIN,
              "task": task, "count": count, "model": model_id}
    with batch.lock():
        batch.write("manifest", {"manifest": config, "sha256": digest(config)})
        yield f"Batch {batch.id} · {task} · {count} independent trials · {model_id}"
        rows = []
        for i in range(1, count + 1):
            trial_root = batch.path / f"trial-{i:02}"
            trial_root.mkdir()
            batch.write(f"reservation-{i}", {"trial": i})
            start = time.monotonic()
            error = None
            try:
                for line in factory(trial_root):
                    yield f"[{i}/{count}] {line}"
            except Exception as exc:  # noqa: BLE001 - preserve failed trials in denominator
                error = type(exc).__name__
            studies = list((trial_root / "studies").glob("*/manifest.json"))
            report = None
            if len(studies) == 1 and (studies[0].parent / "report.json").is_file():
                import json

                report = json.loads((studies[0].parent / "report.json").read_text(encoding="utf-8"))
            produced = report is not None and error is None
            row = {"trial": i, "study": str(studies[0].parent.relative_to(batch.path)) if len(studies) == 1 else None,
                   "elapsed_s": time.monotonic() - start, "error": error,
                   "report_produced": produced}
            if task == "rank":
                row["outcome"] = "prediction_frozen" if produced and report.get("phase") == "predictions_frozen" else "failed"
            elif task == "dmq":
                row["outcome"] = "passed" if produced and report.get("passed") else "not_passed"
            elif task == "dsr":
                row["outcome"] = "screened" if produced and report.get("attempted") == 3 and all(
                    item.get("status") == "ok" for item in report.get("observations", [])) else "failed"
            else:
                mitigation = report.get("mitigation") if produced else None
                row["outcome"] = "improvement_measured" if isinstance(mitigation, dict) and mitigation.get(
                    "recommended") else "not_verified"
            batch.write(f"trial-{i}", row)
            rows.append(row)
        success = {"rank": "prediction_frozen", "dmq": "passed", "dsr": "screened",
                   "mitigate": "improvement_measured"}[task]
        summary = {"batch_id": batch.id, **config, "trials": rows,
                   "outcome_count": sum(row["outcome"] == success for row in rows),
                   "outcome_definition": success,
                   "median_elapsed_all_s": statistics.median(row["elapsed_s"] for row in rows),
                   "paper_full_workflow_success": "not_scored"}
        batch.write("report", summary)
        yield f"Batch {batch.id} · {summary['outcome_count']}/{count} {success} · median {summary['median_elapsed_all_s']:.1f} s"


def configured_trials(root, task, count, profile=None):
    from .agent import model_from_env
    from .paper import model_estimator, paper_rank

    if task != "rank" and not profile:
        raise ValueError("Licensed trials require an explicit dedicated simulator profile")
    if task == "dmq":
        from .paper_dmq import model_proposer, original_dmq, profile_runner

        runner = profile_runner(profile)
        def factory(workspace):
            return original_dmq(workspace, model_proposer(model_from_env()), runner)
    elif task in {"dsr", "mitigate"}:
        from .paper_dsr import mitigation_runner, profile_runner
        from .paper_mitigation import model_proposer

        runner, budget = mitigation_runner(profile) if task == "mitigate" else (profile_runner(profile), 0)
        def factory(workspace):
            model = model_from_env()
            return paper_rank(workspace, model_estimator(model), runner,
                              model_proposer(model) if task == "mitigate" else None, budget)
    elif task == "rank":
        def factory(workspace):
            return paper_rank(workspace, model_estimator(model_from_env()))
    else:
        raise ValueError("Unknown trial type")
    yield from run_trials(root, task, factory, count, os.getenv("GRIDAGENT_MODEL", "unspecified"))
