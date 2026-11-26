"""Licensed original PowerFactory screening backend."""
import json
import os
import subprocess
from pathlib import Path
from typing import Literal

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field

from .dsr import digest
from .paper import LEVEL2, asset, original_kpis
from .paper_mitigation import MitigationProfile


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dedicated_project: Literal[True]
    python: Path
    powerfactory_python_path: Path
    project_path: str = Field(min_length=1)
    base_study_case: str = Field(min_length=1)
    result_name: str = "All calculations.ElmRes"
    timeout_s: int = Field(default=600, ge=30, le=1800)
    mitigation: MitigationProfile | None = None


def profile_runner(path, *, with_mitigation=False):
    profile = Profile.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if (os.name != "nt" or not profile.python.is_absolute() or not profile.python.is_file()
            or not profile.powerfactory_python_path.is_absolute() or not profile.powerfactory_python_path.is_dir()):
        raise ValueError("Licensed DSR requires Windows and compatible PowerFactory Python bindings")
    if with_mitigation and profile.mitigation is None:
        raise ValueError("Configure all six dedicated condenser variants")
    if profile.mitigation and any(v.project_path.casefold() == profile.project_path.casefold()
                                  for v in profile.mitigation.variants.values()):
        raise ValueError("Baseline project must be separate from mitigation copies")
    driver = asset(f"{LEVEL2}/Agent_DIgSILENT.py")
    script = Path(__file__).with_name("paper_dsr_worker.py").resolve()
    lock_root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "GridAgent" / "locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_id = digest({"backend": "powerfactory-local"})[:20]

    def run(case, folder):
        folder = folder.resolve()
        folder.mkdir()
        location, ms = case["location"], case["duration_ms"]
        plan = case.get("condenser_plan")
        if plan is not None and (not with_mitigation or profile.mitigation is None
                                 or plan not in profile.mitigation.variants):
            raise ValueError("Unauthorized mitigation configuration")
        variant = profile.mitigation.variants[plan] if plan else None
        request = {"driver": str(driver), "project_path": variant.project_path if variant else profile.project_path,
                   "base_study_case": variant.base_study_case if variant else profile.base_study_case,
                   "condenser_plan": plan,
                   "device_names": profile.mitigation.device_names if with_mitigation else {},
                   "result_name": profile.result_name,
                   "location": location, "duration_ms": ms, "binding": str(profile.powerfactory_python_path)}
        (folder / "request.json").write_text(json.dumps(request), encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "HOME", "USERPROFILE",
            "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)",
            "COMMONPROGRAMFILES", "COMPUTERNAME", "USERNAME", "LM_LICENSE_FILE"
        }}
        env["POWERFACTORY_PYTHON_PATH"] = str(profile.powerfactory_python_path)
        with FileLock(str(lock_root / f"pf-{lock_id}.lock"), timeout=0), (folder / "worker.log").open(
            "w", encoding="utf-8"
        ) as log:
            try:
                proc = subprocess.run([str(profile.python), "-I", "-X", "utf8", str(script), str(folder)],
                                      cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                                      timeout=profile.timeout_s, check=False)
            except subprocess.TimeoutExpired:
                return {"status": "failed", "reason": "PowerFactory worker timed out; result unknown"}
        path = folder / "worker-result.json"
        if proc.returncode != 0 or not path.is_file():
            return {"status": "failed", "reason": "PowerFactory worker failed; inspect worker.log"}
        result = json.loads(path.read_text(encoding="utf-8"))
        if result.get("status") != "ok":
            return result
        csv_path = Path(result["csv_path"]).resolve()
        if not csv_path.is_relative_to(folder) or not csv_path.is_file():
            return {"status": "failed", "reason": "Missing isolated RMS CSV"}
        try:
            kpi = original_kpis(csv_path, 1 + ms / 1000, require_full=True)
        except (ValueError, OSError) as exc:
            return {"status": "failed", "reason": str(exc)}
        return {"status": "ok", "csv_path": str(csv_path), "kpi": kpi}
    return run


def mitigation_runner(path):
    profile = Profile.model_validate_json(Path(path).read_text(encoding="utf-8"))
    if profile.mitigation is None:
        raise ValueError("Missing mitigation configuration")
    return profile_runner(path, with_mitigation=True), profile.mitigation.simulation_budget
