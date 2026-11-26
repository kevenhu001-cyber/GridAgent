"""Repeat controlled AC trials and persist per-trial and aggregate evidence."""
import json
import math
from collections import Counter, defaultdict
from itertools import product
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Annotated, Literal

from langchain_core.callbacks import get_usage_metadata_callback
from pydantic import Field, TypeAdapter

from .ac_benchmark import TASKS, build_case, fidelity, run_case
from .dsr import Study
from .model_quality import table
from .model_settings import active_settings
from .native_program import Strict
from .research import ResearchTasks, configured_adapters
from .research_spec import PROTOCOL, PlanDraft, ResearchManifest

VARIANTS = ("single", "multi", "single_no_repair", "single_no_experience")
ID = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


class Direction(Strict):
    component: str = Field(max_length=80)
    field: str = Field(max_length=80)
    direction: Literal["increase", "decrease"]


class ExperienceHint(Strict):
    task_id: ID
    version: str = Field(min_length=1, max_length=40)
    base: Literal["empty", "case14", "case39", "case118"]
    scenarios: list[dict] = Field(min_length=1, max_length=20)
    failed_checks: list[str] = Field(min_length=1, max_length=100)
    directions: list[Direction] = Field(max_length=20)
    baseline_runs: list[ID] = Field(max_length=20)
    verified_runs: list[ID] = Field(max_length=20)


def read_experience_snapshot(path):
    path = Path(path)
    if path.stat().st_size > 1024*1024:
        raise ValueError("Training snapshot exceeds 1 MiB")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("protocol") != PROTOCOL or not isinstance(data.get("entries"), list) or len(data["entries"]) > 200:
        raise ValueError("Unsupported training snapshot")
    rows = TypeAdapter(list[ExperienceHint]).validate_python(data["entries"])
    return [row.model_dump(mode="json") for row in rows]


def repair_contract(task):
    case = build_case(task)
    manifest = case.manifest.model_dump(mode="json")
    grid = next(idx for idx, step in enumerate(manifest["program"]["steps"]) if step["op"] == "create_ext_grid")
    manifest["program"]["steps"][grid]["vm_pu"] = 0.88
    manifest.update(editable=[{"path": f"/steps/{grid}/vm_pu", "minimum": 0.88, "maximum": 1.04}],
                    max_runs=6, max_repairs=2)
    manifest["objective"] = (
        "Build this exact power-flow network and simulate base and peak. "
        "The source starts at 0.88 p.u. You may repair only its voltage setpoint within 0.88–1.04 p.u. "
        "Use the default screening limits. Use at most six simulations and two repair proposals. "
        "The program inputs are " + json.dumps(manifest["program"]["steps"])
        + ". The scenarios are " + json.dumps(manifest["scenarios"])
        + ". Authorized parameters are " + json.dumps(manifest["editable"])
    )
    return ResearchManifest.model_validate(manifest)


def repair_trial(root, task, variant, adapters, memory=None):
    tasks = ResearchTasks(root)
    expected = repair_contract(task)
    mode = "multi" if variant == "multi" else "single"
    draft = PlanDraft.model_validate(adapters["planner"](expected.objective, [], mode))
    if draft.manifest is None:
        return {"first_pass": False, "passed": False, "reason": "missing_inputs", "runs": 0, "repairs": 0}
    actual = draft.manifest
    allowed = actual.editable == expected.editable and fidelity(
        actual.model_copy(update={"editable": []}), expected.model_copy(update={"editable": []}))
    if not allowed:
        return {"first_pass": False, "passed": False, "reason": "input_fidelity", "runs": 0, "repairs": 0}
    identifier = tasks.start(expected.objective, mode, manifest=expected, benchmark=True,
                             use_repair=variant != "single_no_repair",
                             use_experience=variant != "single_no_experience", benchmark_memory=memory)
    for _ in tasks.resume(identifier, proposer=adapters["proposer"]):
        pass
    summary = tasks.summary(identifier, full=True)
    passed = summary["stage"] == "passed"
    reason = summary["termination"]
    if passed:
        case = build_case(task)
        winner = next(item for item in summary["record"]["attempts"] if item["passed"])
        source_pu = next(row["vm_pu"] for row in winner["program"]["steps"] if row["op"] == "create_ext_grid")
        for scenario, evidence in zip(expected.scenarios, winner["runs"], strict=True):
            observed = table(tasks.root / "runs" / evidence["run_id"], "res_bus").at[case.terminal, "vm_pu"]
            if not math.isclose(observed, case.voltage(scenario.load_scale, source_pu), abs_tol=1e-5):
                passed = False
                reason = "analytic_reference_failed"
    return {"task_id": identifier, "first_pass": summary["record"]["attempts"][0]["passed"],
            "passed": passed, "reason": reason,
            "runs": summary["runs_used"], "repairs": summary["repairs_used"]}


def measured_trial(workspace, identifier, variant, track, adapters, memory):
    started = perf_counter()
    with get_usage_metadata_callback() as usage:
        try:
            if track == "repair":
                result = repair_trial(workspace, identifier, variant, adapters, memory)
            else:
                score = run_case(workspace, identifier, variant, adapters["planner"])
                result = {"passed": score["passed"], "first_pass": score["passed"],
                          "reason": score.get("reason", "passed" if score["passed"] else "evaluation"),
                          "runs": score.get("runs", 0), "repairs": 0, "task_id": score.get("task_id")}
        except Exception as exc:  # noqa: BLE001 - preserve failed trials without provider payloads
            result = {"passed": False, "first_pass": False, "reason": type(exc).__name__,
                      "runs": None, "repairs": None}
    measured = usage.usage_metadata
    return {**result, "elapsed_s": perf_counter()-started,
            "tokens": sum(data.get("total_tokens", 0) for data in measured.values()) if measured else None}


def summarize_trials(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["model"], row["variant"], row["track"]].append(row)
    return [{"model": name, "variant": variant, "track": track, "trials": len(group),
             "first_pass_rate": sum(item["first_pass"] for item in group)/len(group),
             "final_pass_rate": sum(item["passed"] for item in group)/len(group),
             "repairs": sum(item["repairs"] or 0 for item in group),
             "simulation_attempts": sum(item["runs"] or 0 for item in group),
             "median_elapsed_s": median(item["elapsed_s"] for item in group),
             "tokens_reported": sum(item["tokens"] or 0 for item in group),
             "token_measurement_count": sum(item["tokens"] is not None for item in group),
             "failure_counts": dict(Counter(item["reason"] for item in group if not item["passed"]))}
            for (name, variant, track), group in groups.items()]


def compare(root, task, names, repeats=10, *, memory=None, model_factory=None):
    from .agent import model_from_env

    if len(set(names)) < 2 or len(names) != len(set(names)) or not 1 <= repeats <= 10:
        raise ValueError("Select at least two distinct models and 1–10 repetitions")
    if "/" in task:
        track, task = task.split("/", 1)
        if track not in {"modeling", "repair"}:
            raise ValueError("Use the modeling/ or repair/ task prefix")
        tracks = (track,)
    else:
        tracks = ("modeling", "repair")
    selected = TASKS if task == "all" else (task,)
    if any(item not in TASKS for item in selected):
        raise ValueError("Unknown AC benchmark task")
    root = Path(root).resolve()
    settings = active_settings(root)
    factory = model_factory or model_from_env
    models = {name: factory(settings=settings.model_copy(update={"model": name})) for name in names}
    batch = Study(root / "studies")
    # Scored cases run in a fresh workspace. Only an explicit training snapshot supplies historical hints.
    workspace = batch.path / "evaluation-workspace"
    rows = []
    with batch.lock():
        batch.write("manifest", {"protocol": "gridagent-ac-comparison-v1", "modality": "public_development",
                                 "cases": list(selected), "tracks": list(tracks), "models": names, "repeats": repeats,
                                 "experience_snapshot": memory is not None})
        for name, model in models.items():
            adapters = configured_adapters(workspace, lambda model=model: model)
            for track in tracks:
                variants = VARIANTS if track == "repair" else ("single", "multi")
                for variant, trial, identifier in product(variants, range(1, repeats+1), selected):
                    row = measured_trial(workspace, identifier, variant, track, adapters, memory)
                    row.update(model=name, variant=variant, trial=trial, case=identifier, track=track)
                    batch.write(f"trial-{len(rows):05d}", row)
                    rows.append(row)
                    yield f"{batch.id} · {name} · {variant} · {trial} · {track}/{identifier} · {row['reason']}"
        batch.write("report", {"study_id": batch.id, "phase": "ac_comparison_finished",
                               "groups": summarize_trials(rows)})
        yield f"Saved comparison {batch.id} · {len(rows)} trials · {batch.path / 'report.json'}"
