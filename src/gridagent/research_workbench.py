"""Explicit desktop/CLI entry points for bounded v2 research workflows."""

import json


def workbench_command(root, command, args):
    if command == "ac-collection-plan" and len(args) == 1:
        from .ac_decision_train import read_json
        from .ac_native_collection import start_collection

        identifier = start_collection(root, read_json(args[0]))
        yield f"Frozen AC collection plan: {identifier}. No solver was launched."
        return
    if command == "ac-collection-resume" and len(args) == 1:
        from .ac_native_collection import resume_collection

        report = resume_collection(root, args[0])
        yield (f"Collection {report['study_id']}: {report['eligible_cases']} eligible cases, "
               f"{report['observed_ac_runs']} observed AC launches; "
               f"all splits represented: {report['all_splits_represented']}.")
        return
    if command in {"ac-train", "ac-train-collection"} and len(args) == 1:
        from .ac_decision_train import read_json, train_study

        if command == "ac-train":
            authorization = read_json(args[0])
        else:
            from .ac_native_collection import resume_collection
            from .dsr import Study

            study = Study.reopen(root / "studies", args[0])
            if not study.exists("report"):
                raise ValueError("Finish the collection before training")
            authorization = resume_collection(root, study.id)["dataset_authorization"]
            if authorization is None:
                raise ValueError("Collection does not contain all required splits")
        result = train_study(root, authorization)
        artifact = result["artifact"]
        yield json.dumps({"study_id": result["study_id"], "enabled": artifact["enabled"],
                          "validation": artifact["validation"], "test": artifact["test"],
                          "scope": result["scope"]}, indent=2, allow_nan=False)
        return
    if command == "ac-standard-screening" and not args:
        from .standard_ac_benchmark import run_benchmark

        result = run_benchmark(root)
        yield json.dumps(result, indent=2, allow_nan=False)
        return
    raise ValueError("Invalid research workbench command arguments")
