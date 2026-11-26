"""Original DMQ suite, using a dedicated licensed simulator installation."""
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Annotated, Literal

from filelock import FileLock
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field

from .dsr import Study, digest
from .paper import LEVEL1, PIN, asset

Gain = Annotated[float, Field(gt=0, le=100, allow_inf_nan=False)]


class Gains(BaseModel):
    model_config = ConfigDict(extra="forbid")
    Kqp: Gain
    Kqi: Gain
    Kvp: Gain
    Kvi: Gain


class Repair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    gains: Gains
    rationale: str = Field(min_length=1, max_length=1500)


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dedicated_install: Literal[True]
    python: Path
    dmview_root: Path
    suite_timeout_s: int = Field(default=1800, ge=30, le=1800)


def profile_runner(path):
    profile = Profile.model_validate_json(Path(path).read_text(encoding="utf-8"))
    root = profile.dmview_root.resolve()
    if (os.name != "nt" or not profile.python.is_absolute() or not profile.python.is_file()
            or not profile.dmview_root.is_absolute() or not (root / "DMView.py").is_file()):
        raise ValueError("Licensed DMQ needs a dedicated Windows DMView install and compatible interpreter")
    harness = asset(f"{LEVEL1}/harness/config.py").parent
    for name in ("dyr_tools.py", "dmview_runner.py", "evaluator.py", "channels.py", "ini_gen.py", "criteria.json"):
        asset(f"{LEVEL1}/harness/{name}")
    source = asset("cases/solar_wecc/psse/Solar.dyr").parent
    asset("cases/solar_wecc/psse/Solar.sav")
    script = Path(__file__).with_name("paper_dmq_worker.py").resolve()

    def run(gains, folder, iteration):
        folder = folder.resolve()
        folder.mkdir()
        request = {"harness": str(harness), "source": str(source),
                   "dmview_root": str(root), "python": str(profile.python),
                   "timeout": profile.suite_timeout_s, "gains": gains, "iteration": iteration}
        (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            "COMMONPROGRAMFILES", "COMPUTERNAME", "USERNAME", "PSSE_LICENSE_FILE",
            "LM_LICENSE_FILE", "SPLM_LICENSE_SERVER"
        }}
        with FileLock(str(root / ".gridagent-exclusive.lock"), timeout=0), (folder / "worker.log").open(
            "w", encoding="utf-8"
        ) as log:
            try:
                proc = subprocess.run([str(profile.python), "-I", "-X", "utf8", str(script), str(folder)],
                                      cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=profile.suite_timeout_s + 180, check=False)
            except subprocess.TimeoutExpired:
                return {"status": "failed", "reason": "Worker timed out; inspect dedicated installation"}
        result = folder / "worker-result.json"
        if proc.returncode != 0 or not result.is_file():
            return {"status": "failed", "reason": "Licensed worker failed; inspect worker.log"}
        return json.loads(result.read_text(encoding="utf-8"))
    return run


def original_dmq(root, propose, run, max_iterations=5):
    if not 1 <= max_iterations <= 5:
        raise ValueError("Original DMQ iteration budget is 1..5")
    study = Study(Path(root) / "studies")
    initial = {"Kqp": 10., "Kqi": 50., "Kvp": 10., "Kvi": 50.}
    manifest = {"upstream_commit": PIN, "iteration_budget": max_iterations, "initial": initial}
    study.write("manifest", {"protocol": "poweragentbench-dmq-v1", "manifest": manifest,
                             "manifest_sha256": digest(manifest)})
    start = time.monotonic()
    with study.lock():
        current = initial
        study.write("baseline-reservation", {"gains": current})
        yield f"Paper DMQ · {study.id} · original WECC baseline"
        result = run(current, study.path / "baseline", 0)
        study.write("baseline", result)
        attempts, edits = 0, 0
        feedback = []
        while (result.get("status") == "ok" and not result["evaluation"]["overall_pass"]
               and attempts < max_iterations):
            attempts += 1
            study.write(f"reservation-{attempts}", {"before": current})
            try:
                proposal = Repair.model_validate(propose({"gains": current, "evaluation": result["evaluation"],
                                                         "history": feedback, "remaining": max_iterations-attempts+1}))
            except (ValueError, TypeError):
                item = {"status": "denied", "reason": "Invalid or unauthorized proposal"}
                study.write(f"proposal-{attempts}", item)
                feedback.append(item)
                continue
            gains = proposal.gains.model_dump()
            if gains == current:
                item = {"status": "denied", "reason": "No change"}
                study.write(f"proposal-{attempts}", item)
                feedback.append(item)
                continue
            item = {"status": "accepted", "before": current, "after": gains, "rationale": proposal.rationale}
            study.write(f"proposal-{attempts}", item)
            result = run(gains, study.path / f"iteration-{attempts}", attempts)
            study.write(f"iteration-{attempts}", result)
            feedback.append(item)
            current = gains
            edits += 1
            yield f"Repair {attempts}/{max_iterations} · {result.get('status')}"
        evaluation = result.get("evaluation", {})
        ok = result.get("status") == "ok" and bool(evaluation.get("overall_pass"))
        report = {"study_id": study.id, "protocol": "poweragentbench-dmq-v1",
                  "completed": result.get("status") == "ok", "passed": ok,
                  "tests_passed": evaluation.get("n_pass", 0), "tests_total": 8,
                  "attempts": attempts, "accepted_edits": edits, "initial_gains": initial,
                  "final_gains": current, "tests": evaluation.get("tests", {}),
                  "elapsed_s": time.monotonic() - start}
        study.write("report", report)
        yield f"Original DMQ · {report['tests_passed']}/8 passed · {attempts} repair attempts"


def model_proposer(model):
    structured = model.with_structured_output(Repair, method="function_calling")

    def propose(observation):
        return structured.invoke([
            SystemMessage(content="Diagnose original WECC REECAU1 DMView test observations. Only propose "
                          "Kqp,Kqi,Kvp,Kvi in (0,100]; all other model fields are locked. Explain "
                          "the evidence for each edit. Never treat an infrastructure failure as a pass."),
            HumanMessage(content=json.dumps(observation, allow_nan=False)),
        ])
    return propose
