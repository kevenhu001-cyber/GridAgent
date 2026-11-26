"""Execute the pinned upstream DMView runner and evaluator in licensed Python."""
import json
import shutil
import sys
from pathlib import Path
from uuid import uuid4


def main():
    folder = Path(sys.argv[1])
    request = json.loads((folder / "request.json").read_text(encoding="utf-8"))
    sys.path.insert(0, request["harness"])
    import config
    import dmview_runner
    import dyr_tools
    import evaluator

    root = Path(request["dmview_root"])
    config.DMVIEW_ROOT = root
    config.PY311 = Path(request["python"])
    config.RESULTS_GLOBAL = root / "RESULTs"
    config.RESULTS_LOCK = config.RESULTS_GLOBAL / ".harness_lock"
    config.SUITE_TIMEOUT_S = request["timeout"]
    config.INI_NAME = "GridAgent_" + uuid4().hex
    config.INI_PATH = root / (config.INI_NAME + ".ini")

    def require_empty():
        config.RESULTS_GLOBAL.mkdir(exist_ok=True)
        if any(p.name != config.RESULTS_LOCK.name for p in config.RESULTS_GLOBAL.iterdir()):
            raise ValueError("Dedicated DMView RESULTs directory is not empty")

    require_empty()
    if config.RESULTS_LOCK.exists():
        raise ValueError("Existing DMView lock")
    # The upstream runner ordinarily deletes results. Refuse rather than delete user files.
    dmview_runner._clear_results_dir = require_empty
    source = Path(request["source"])
    work = root / ("GridAgent_case_" + uuid4().hex)
    work.mkdir()
    try:
        for name in ("Solar.dyr", "Solar.sav"):
            shutil.copyfile(source / name, work / name)
        gains = request["gains"]
        if set(gains) != set(config.GAIN_NAMES):
            raise ValueError("Invalid gain keys")
        orig = (source / "Solar.dyr").read_text(encoding="utf-8")
        tokens, spans = dyr_tools._locate_record(orig)
        if tokens[0] != "91003" or tokens[2].strip("'\"") != "S1":
            raise ValueError("Incorrect model identity")
        dyr_tools.write_gains(work / "Solar.dyr", gains, folder / "changes.jsonl", request["iteration"])
        new = (work / "Solar.dyr").read_text(encoding="utf-8")
        new_tokens, new_spans = dyr_tools._locate_record(new)

        def locked(text, locations, indexes):
            for i in sorted(indexes, reverse=True):
                a, b = locations[i]
                text = text[:a] + "<GAIN>" + text[b:]
            return text

        if locked(orig, spans, dyr_tools._gain_indices(tokens)) != locked(
            new, new_spans, dyr_tools._gain_indices(new_tokens)):
            raise ValueError("Locked fields changed")
        shutil.copytree(work, folder / "model-before-test")
        result = dmview_runner.run_suite(work, folder / "archive", retry_on_license=False)
        evaluation = evaluator.evaluate_suite(result.archive_dir, gains, request["iteration"],
                                               result.status, result.elapsed_s)
        if (work / "Solar.sav").read_bytes() != (source / "Solar.sav").read_bytes():
            raise ValueError("Locked SAV changed")
        if (work / "Solar.dyr").read_bytes() != (folder / "model-before-test" / "Solar.dyr").read_bytes():
            raise ValueError("Edited DYR changed during simulation")
        status = "ok" if result.status == "completed" and all(
            t["status"] in {"pass", "fail"} for t in evaluation["tests"].values()) else "failed"
        (folder / "worker-result.json").write_text(json.dumps(
            {"status": status, "evaluation": evaluation, "locked_fields_verified": True}, allow_nan=False),
            encoding="utf-8")
    finally:
        config.INI_PATH.unlink(missing_ok=True)
        shutil.rmtree(work)


if __name__ == "__main__":
    main()
