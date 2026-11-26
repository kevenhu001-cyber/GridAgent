import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .domain import CASES, CaseRequest, FaultRequest
from .models import resolve_model


class Simulator(Protocol):
    def run(self, operation: str, request: dict) -> dict: ...


class AndesSimulator:
    def __init__(self, root: Path = Path(".gridagent/runs"), timeout_s: int = 180):
        self.root = root.resolve()
        self.timeout_s = timeout_s

    def run(self, operation: str, request: dict) -> dict:
        if operation not in {"inspect", "power_flow", "fault", "eigen"}:
            raise ValueError("Operation is not allowed")
        request = (FaultRequest if operation == "fault" else CaseRequest).model_validate(request).model_dump()
        source = None if request["case"] in CASES else resolve_model(self.root.parent, request["case"])
        folder = self.root / uuid4().hex
        folder.mkdir(parents=True)
        if source is not None:
            shutil.copyfile(source, folder / "case.xlsx")
        (folder / "request.json").write_text(json.dumps({"operation": operation, "request": request}), encoding="utf-8")
        # Do not pass model-provider credentials to the solver.
        env = {k: v for k, v in os.environ.items() if k.upper() in {
            "PATH", "HOME", "USERPROFILE", "SYSTEMROOT", "WINDIR", "TEMP", "TMP",
            "LD_LIBRARY_PATH", "LANG", "LC_ALL", "VIRTUAL_ENV"
        }}
        try:
            with (folder / "solver.log").open("w", encoding="utf-8") as log:
                proc = subprocess.run(
                    [sys.executable, "-m", "gridagent.andes_worker", operation, json.dumps(request)],
                    cwd=folder, env=env, stdout=log, stderr=subprocess.STDOUT,
                    timeout=self.timeout_s, check=False,
                )
            path = folder / "result.json"
            if proc.returncode != 0 or not path.is_file():
                return {"status": "failed", "reason": "Solver process failed", "run_id": folder.name}
            result = json.loads(path.read_text(encoding="utf-8"))
            return {**result, "run_id": folder.name}
        except subprocess.TimeoutExpired:
            return {"status": "failed", "reason": "Solver timeout", "run_id": folder.name}
