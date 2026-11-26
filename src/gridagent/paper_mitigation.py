"""Fresh-simulation mitigation policy; no historical labels or memory."""
import json
import math
from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

PLANS = ("04", "16", "26", "04+16", "04+26", "16+26")
Plan = Literal["04", "16", "26", "04+16", "04+26", "16+26"]


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan: Plan
    rationale: str = Field(min_length=1, max_length=1500)


class Variant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project_path: str = Field(min_length=1)
    base_study_case: str = Field(min_length=1)


class MitigationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    simulation_budget: int = Field(default=6, ge=1, le=6)
    device_names: dict[Literal["04", "16", "26"], str]
    variants: dict[Plan, Variant]

    @model_validator(mode="after")
    def check_variants(self):
        if set(self.device_names) != {"04", "16", "26"} or len(set(self.device_names.values())) != 3:
            raise ValueError("Provide three distinct condenser names")
        if any(not n.strip() or "*" in n or "?" in n for n in self.device_names.values()):
            raise ValueError("Use exact condenser names")
        if set(self.variants) != set(PLANS):
            raise ValueError("Provide all six dedicated project variants")
        if len({v.project_path.casefold() for v in self.variants.values()}) != 6:
            raise ValueError("Variants must be distinct project copies")
        return self


def valid_kpi(result):
    if result.get("status") != "ok":
        return None
    kpi = result.get("kpi", {})
    s, stable = kpi.get("severity_score"), kpi.get("stable")
    if (not isinstance(s, (int, float)) or isinstance(s, bool) or not math.isfinite(s)
            or not 0 <= s <= 1 or stable not in (0, 1) or (not stable and s != 1)):
        return None
    return {"severity": float(s), "stable": bool(stable),
            "vmin_aft": kpi.get("vmin_aft"), "vmax_aft": kpi.get("vmax_aft")}


def run_mitigation(study, case, baseline, propose, simulator, budget=6):
    if not 1 <= budget <= 6:
        raise ValueError("Mitigation budget must be 1..6")
    before = valid_kpi(baseline)
    if before is None:
        raise ValueError("A measured baseline is required")
    case = {k: case[k] for k in ("location", "duration_ms")}
    study.write("mitigation-manifest", {"case": case, "baseline": before,
                "allowed_plans": list(PLANS), "unit_rating_mva": 250,
                "max_units": 2, "attempt_budget": budget})
    rows = []
    used = set()
    for index in range(1, budget + 1):
        available = [p for p in PLANS if p not in used]
        study.write(f"mitigation-reservation-{index}", {"available": available})
        observation = {"fault": case, "baseline": before, "fresh_results": rows,
                       "available_plans": available, "remaining": budget-index+1,
                       "unit_rating_mva": 250, "max_units": 2}
        try:
            choice = Proposal.model_validate(propose(observation))
            if choice.plan not in available:
                raise ValueError("Repeated configuration")
        except (ValueError, TypeError):
            row = {"attempt": index, "status": "denied", "reason": "Invalid or repeated plan"}
        else:
            used.add(choice.plan)
            study.write(f"mitigation-proposal-{index}", choice.model_dump())
            result = simulator({**case, "condenser_plan": choice.plan}, study.path / f"mitigation-run-{index}")
            measured = valid_kpi(result)
            row = {"attempt": index, "plan": choice.plan, "status": "ok" if measured else "failed",
                   "measurement": measured}
            if measured:
                row["severity_reduction"] = before["severity"] - measured["severity"]
            study.write(f"mitigation-raw-{index}", result)
        study.write(f"mitigation-result-{index}", row)
        rows.append(row)
        yield row
    viable = [r for r in rows if r.get("measurement") and r["measurement"]["stable"]
              and r["measurement"]["severity"] < before["severity"]]
    best = min(viable, key=lambda r: (r["measurement"]["severity"], len(r["plan"].split("+")),
                                      r["plan"])) if viable else None
    study.write("mitigation-report", {"case": case, "baseline": before, "attempted": len(rows),
                "simulation_attempts": len(used), "budget": budget, "results": rows,
                "recommended": best, "scope": "best measured stable improvement among tested plans",
                "all_plans_verified": sum(r["status"] == "ok" for r in rows) == len(PLANS)})


def model_proposer(model):
    structured = model.with_structured_output(Proposal, method="function_calling")

    def propose(observation):
        return structured.invoke([
            SystemMessage(content="Select an available synchronous condenser placement. Each unit is 250 MVA. "
                          "At most two units at buses 04,16,26. Only fresh simulation observations are evidence. "
                          "Investigate informative untested options. Do not invent outcomes."),
            HumanMessage(content=json.dumps(observation, allow_nan=False)),
        ])
    return propose
