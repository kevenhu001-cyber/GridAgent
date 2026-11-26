"""Public AC development benchmark with closed-form receiving-end voltages."""
import json
import math
from dataclasses import dataclass

from .model_quality import table
from .research import ResearchTasks, configured_adapters, recover_run
from .research_spec import PlanDraft, ResearchManifest

FAMILIES = ("single-line", "parallel-lines", "series-lines", "closed-tie", "transformer")
TASKS = tuple(f"{family}-{level}" for family in FAMILIES for level in range(1, 5))


@dataclass(frozen=True)
class Case:
    manifest: ResearchManifest
    terminal: int
    nominal_kv: float
    resistance: float
    reactance: float
    load_mw: float
    load_mvar: float

    def voltage(self, scale, source_pu=1):
        p, q = self.load_mw * scale, self.load_mvar * scale
        r, x, v = self.resistance, self.reactance, self.nominal_kv
        a = (v*source_pu)**2 - 2*(r*p + x*q)
        v2 = (a + math.sqrt(a*a - 4*(r*r + x*x)*(p*p + q*q)))/2
        return math.sqrt(v2)/v


def line(index, origin, destination):
    return {"op": "create_line_from_parameters", "index": index, "from_bus": origin, "to_bus": destination,
            "length_km": 10, "r_ohm_per_km": 0.1, "x_ohm_per_km": 0.4, "c_nf_per_km": 0, "max_i_ka": 0.5}


def build_case(task):
    if task not in TASKS:
        raise ValueError("Unknown AC development benchmark task")
    family, level = task.rsplit("-", 1)
    loads = {"p_mw": 4*int(level), "q_mvar": int(level)}
    voltage = 20 if family == "transformer" else 110
    terminal = 2 if family in {"closed-tie", "series-lines"} else 1
    steps = [{"op": "create_bus", "index": idx, "vn_kv": voltage if idx else 110} for idx in range(terminal+1)]
    steps.append({"op": "create_ext_grid", "bus": 0, "vm_pu": 1})
    r, x = 1, 4
    if family == "transformer":
        steps.append({"op": "create_transformer_from_parameters", "index": 0, "hv_bus": 0, "lv_bus": 1,
                      "sn_mva": 60, "vn_hv_kv": 110, "vn_lv_kv": 20, "vkr_percent": 0.5, "vk_percent": 6,
                      "pfe_kw": 0, "i0_percent": 0})
        r = 0.005 * voltage**2/60
        x = math.sqrt(0.06**2-0.005**2) * voltage**2/60
    else:
        steps.append(line(0, 0, 1))
        if family == "parallel-lines":
            steps.append(line(1, 0, 1))
            r, x = r/2, x/2
        elif family == "series-lines":
            steps.append(line(1, 1, 2))
            r, x = r*2, x*2
        elif family == "closed-tie":
            steps.append({"op": "create_switch", "index": 0, "bus": 1, "element": 2, "et": "b", "closed": True})
    steps.append({"op": "create_load", "index": 0, "bus": terminal, **loads})
    scenarios = [{"name": "base"}, {"name": "peak", "load_scale": 1.25}]
    prompt = ("Build the balanced AC network from the following exact input specification. "
              "Use the specified devices and no additional devices or edits. "
              "Solve both scenarios with the default limits and a two-run budget. "
              "Network devices (native parameter units): " + json.dumps(steps) + ". "
              "Scenarios: " + json.dumps(scenarios))
    manifest = ResearchManifest(objective=prompt, program={"steps": steps}, scenarios=scenarios, max_runs=2)
    return Case(manifest, terminal, voltage, r, x, loads["p_mw"], loads["q_mvar"])


def fidelity(actual, expected):
    def normalize(manifest):
        program = manifest.program.model_dump(mode="json")
        program["steps"] = sorted(program["steps"], key=lambda step: json.dumps(step, sort_keys=True))
        return program, sorted((s.name, s.load_scale, s.outage) for s in manifest.scenarios), manifest.limits
    return not actual.editable and normalize(actual) == normalize(expected)


def run_case(root, task, mode="reference", plan=None):
    from time import perf_counter

    case = build_case(task)
    started = perf_counter()
    tasks = ResearchTasks(root)
    if mode == "reference":
        manifest = case.manifest
    else:
        planner = plan or configured_adapters(root)["planner"]
        draft = PlanDraft.model_validate(planner(case.manifest.objective, [], mode))
        if draft.manifest is None or not fidelity(draft.manifest, case.manifest):
            return {"task": task, "mode": mode, "passed": False, "reason": "input_fidelity",
                    "elapsed_s": perf_counter()-started}
        manifest = draft.manifest.model_copy(update={"max_runs": 2, "max_repairs": 0})
    identifier = tasks.start(case.manifest.objective, "single" if mode == "reference" else mode,
                             manifest=manifest, use_repair=False, use_experience=False, benchmark=True)
    for item in tasks.resume(identifier):
        continue
    verdicts = []
    for scenario in manifest.scenarios:
        run = next((row for row in item["best_runs"] if row["scenario"] == scenario.name), None)
        observed = None
        if run and recover_run(tasks.root, run).get("status") == "ok":
            observed = float(table(tasks.root / "runs" / run["run_id"], "res_bus").at[case.terminal, "vm_pu"])
        expected = case.voltage(scenario.load_scale)
        verdicts.append({"scenario": scenario.name, "observed_pu": observed, "expected_pu": expected,
                         "passed": observed is not None and abs(observed-expected) <= 1e-5})
    return {"task": task, "mode": mode, "task_id": identifier, "passed": item["stage"] == "passed"
            and all(row["passed"] for row in verdicts), "checks": verdicts, "runs": item["runs_used"],
            "elapsed_s": perf_counter()-started}
