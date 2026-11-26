"""Versioned inputs and independent checks for power-flow research tasks."""
import math
from copy import deepcopy
from pathlib import Path

from pydantic import Field, model_validator

from .model_quality import check, pp_checks, table
from .model_repair import PathKey, leaf
from .native_program import Name, Outage, PPProgram, Strict

PROTOCOL = "gridagent-power-flow-research-v1"


class Limits(Strict):
    voltage_min_pu: float = Field(default=0.90, gt=0, le=2)
    voltage_max_pu: float = Field(default=1.10, gt=0, le=2)
    loading_max_percent: float = Field(default=100, gt=0, le=200)
    balance_tolerance_mva: float = Field(default=0.001, gt=0, le=1)

    @model_validator(mode="after")
    def check_range(self):
        if self.voltage_min_pu > self.voltage_max_pu:
            raise ValueError("Minimum voltage exceeds maximum voltage")
        return self


class Scenario(Strict):
    name: Name
    load_scale: float = Field(default=1, ge=0, le=2)
    outage: Outage | None = None

    def materialize(self, program):
        data = {**program, "load_scale": self.load_scale, "contingency": self.outage}
        return PPProgram.model_validate(data).model_dump(mode="json")


class RepairRange(Strict):
    path: PathKey
    minimum: float = Field(ge=-1e7, le=1e7)
    maximum: float = Field(ge=-1e7, le=1e7)


class ResearchManifest(Strict):
    objective: str = Field(min_length=1, max_length=4000)
    program: PPProgram
    scenarios: list[Scenario] = Field(default_factory=lambda: [Scenario(name="base")], min_length=1, max_length=20)
    limits: Limits = Field(default_factory=Limits)
    editable: list[RepairRange] = Field(default_factory=list, max_length=20)
    max_repairs: int = Field(default=2, ge=0, le=5)
    max_runs: int = Field(default=6, ge=1, le=60)

    @model_validator(mode="after")
    def validate_contract(self):
        if (self.program.analysis != "power_flow" or self.program.parent_run or self.program.load_scale != 1
                or self.program.contingency is not None):
            raise ValueError("Use an independent AC power-flow model with scaling defined per scenario")
        if self.max_runs < len(self.scenarios):
            raise ValueError("Run budget cannot cover the initial scenarios")
        if len({scenario.name for scenario in self.scenarios}) != len(self.scenarios):
            raise ValueError("Scenario names must be unique")
        if len({item.path for item in self.editable}) != len(self.editable):
            raise ValueError("Repair paths must be unique")
        data = self.program.model_dump(mode="json")
        for scenario in self.scenarios:
            scenario.materialize(data)
        for item in self.editable:
            try:
                step, field = leaf(data, item.path)
            except (IndexError, KeyError, TypeError) as exc:
                raise ValueError("Editable path must identify an existing numeric parameter") from exc
            if not item.minimum <= step[field] <= item.maximum:
                raise ValueError("Initial value must lie inside the authorized repair range")
        return self


class PlanDraft(Strict):
    manifest: ResearchManifest | None = None
    questions: list[str] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def choose(self):
        if (self.manifest is not None) == bool(self.questions):
            raise ValueError("Return a manifest or questions about missing inputs")
        return self


def model_fidelity(manifest, candidate):
    original = manifest.program.model_dump(mode="json")
    restored = deepcopy(candidate)
    try:
        for item in manifest.editable:
            step, field = leaf(restored, item.path)
            if not item.minimum <= step[field] <= item.maximum:
                return False
            baseline, _ = leaf(original, item.path)
            step[field] = baseline[field]
    except (ValueError, TypeError, KeyError, IndexError):
        return False
    return restored == original


def power_balance(folder):
    buses = table(folder, "res_bus")
    active = table(folder, "bus").in_service.eq(True)
    injections = buses.reindex(active.index[active])[["p_mw", "q_mvar"]]
    if injections.empty or injections.isna().any().any():
        raise ValueError("Missing active bus power data")
    p, q = injections.sum()
    for name, first, second in (("line", "from", "to"), ("trafo", "hv", "lv")):
        branches = table(folder, "res_" + name)
        p += branches[[f"p_{first}_mw", f"p_{second}_mw"]].sum().sum()
        q += branches[[f"q_{first}_mvar", f"q_{second}_mvar"]].sum().sum()
    error = math.hypot(p, q)
    if not math.isfinite(error):
        raise ValueError("Non-finite power balance")
    return error


def evaluate(root, run, request, limits):
    if run.get("status") != "ok":
        reason = run.get("reason", "missing_evidence")
        if reason in {"LoadflowNotConverged", "Native solver timeout", "FloatingPointError"}:
            category = "solver_failure"
        elif reason in {"ValueError", "UserWarning", "KeyError", "IndexError", "AssertionError"}:
            category = "model_error"
        else:
            category = reason
        return {"category": category, "passed": False, "checks": [check("solver_success", False, reason)]}
    folder = Path(root) / "runs" / run["run_id"]
    tests = [check("solver_success", True)]
    try:
        for row in pp_checks(folder, request):
            name = row["id"]
            if name == "voltage_operating_range":
                observed = row["observed"]
                row = check(name, observed is not None
                            and limits.voltage_min_pu <= observed[0] <= observed[1] <= limits.voltage_max_pu,
                            observed, [limits.voltage_min_pu, limits.voltage_max_pu])
            if name in {"res_line_loading", "res_trafo_loading"}:
                loading = row["observed"]
                if loading is not None:
                    row = check(name, loading <= limits.loading_max_percent + 1e-6,
                                loading, limits.loading_max_percent)
            tests.append(row)
        balance = power_balance(folder)
        tests.append(check("power_balance_mva", balance <= limits.balance_tolerance_mva,
                           balance, limits.balance_tolerance_mva))
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        tests.append(check("evidence_integrity", False, type(exc).__name__))
    passed = all(row["passed"] for row in tests)
    failures = {row["id"] for row in tests if not row["passed"]}
    category = ("passed" if passed else "invalid_evidence" if "evidence_integrity" in failures else
                "model_error" if "active_bus_coverage" in failures else "physical_limit")
    return {"category": category, "passed": passed, "checks": tests}
