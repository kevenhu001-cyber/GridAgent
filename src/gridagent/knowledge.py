"""Structured, dependency-aware retrieval for engineering tool contracts.

Inspired by Jia, Cui and Hug, IEEE TSG 2025, DOI 10.1109/TSG.2025.3589114.
Independent implementation; no upstream supplemental material is redistributed.
"""
import json
import os
import re
import sqlite3
from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

ALIASES = {
    "pypower_case_flow": "PYPOWER IEEE AC load flow 潮流 基准",
    "powsybl_case_flow": "PowSyBl AC load flow 潮流 大电网",
    "ramp_tracking_qp": "OSQP sparse quadratic ramp tracking 二次规划 爬坡 跟踪",
    "transmission_line_sparameters": "scikit-rf scattering transmission line 传输线 散射参数",
    "fluid_thermophysical_state": "CoolProp fluid thermal properties 热物性 冷却 热管理",
    "rainflow_cycle_count": "rainflow cycle counting 雨流 循环计数 疲劳",
    "wind_power_curve": "windpowerlib wind turbine generation curve 风电 功率曲线",
    "quadratic_dispatch": "CVXPY convex quadratic economic dispatch 凸优化 经济调度",
    "unit_commitment": "Pyomo HiGHS MILP startup unit commitment 机组组合 启停",
    "equivalent_cell_response": "CasADi Thevenin RC cell battery voltage 等效电路 电池 动态",
    "solar_dc_power": "pvlib PVWatts solar photovoltaic DC power 光伏 辐照度 温度 功率",
    "control_step_response": "control transfer function step response poles 控制 传递函数 阶跃 极点",
    "opendss_feeder": "OpenDSS distribution feeder 配电网 三相 电压",
    "battery_discharge": "PyBaMM SPM DFN lithium battery discharge 电池 电化学 放电",
    "pandapower_program": "pandapower create_bus create_line runpp calc_sc AC power flow short circuit 建模 潮流 短路 线路 变压器",
    "pypsa_dispatch": "PyPSA Network add optimize HiGHS energy storage dispatch battery renewable 储能 调度 优化 新能源 电池",
    "read_native_table": "result CSV table dispatch voltage SOC 结果 表格 电压 荷电状态",
    "inspect_case": "model topology bus network 模型 拓扑 母线 检查",
    "power_flow": "power flow load flow baseline 潮流 基准 电压",
    "scenario_power_flow": "load scaling outage contingency PQ loading 负荷 线路 退出 潮流",
    "simulate_fault": "transient fault duration clearing bus 暂态 短路 故障 切除 持续",
    "eigenanalysis": "eigenvalue damping frequency small signal 特征值 阻尼 小信号",
    "analyze_voltage_waveform": "waveform voltage recovery RMS 波形 电压 恢复",
    "compare_flow_runs": "compare scenario voltage delta 比较 潮流 电压",
    "compare_fault_runs": "compare fault severity transient 对比 故障 暂态",
    "list_network_branches": "branch line outage identifier 线路 支路 编号",
    "list_model_devices": "device PQ load generator setpoint parameter 设备 负荷 发电机 参数",
    "paper_training_history": "historical training memory IEEE39 历史 记忆",
}
OPTION_HINTS = {
    "case": "Registered model ID or packaged case; open IEEE39 differs from paper project.",
    "bus": "For faults use an actual numeric bus identifier from inspect_case.",
    "duration_s": "Fault duration in seconds, not milliseconds; fault starts at 1 s.",
    "end_s": "Absolute simulation stop time in seconds; must extend beyond clearing.",
    "load_scale": "Uniform multiplier for in-service static PQ loads; 1.0 leaves them unchanged.",
    "outage_branch": "Exact in-service Line ID from list_network_branches; not a bus number.",
    "edits": "Explicit device IDs and fields; applied only to a fresh hypothetical model.",
    "channel": "Exact stored waveform channel, not a guessed label.",
    "run_id": "Full stored run identifier, not a filesystem path.",
}
DEPENDENCIES = {
    "pandapower_program": ["list_simulation_backends"],
    "pypsa_dispatch": ["list_simulation_backends"],
    "read_native_table": ["pandapower_program", "pypsa_dispatch"],
    "simulate_fault": ["inspect_case"],
    "scenario_power_flow": ["inspect_case", "list_network_branches", "list_model_devices"],
    "network_path": ["inspect_case"],
    "list_network_branches": ["inspect_case"],
    "list_model_devices": ["inspect_case"],
    "analyze_voltage_waveform": ["simulate_fault"],
    "compare_flow_runs": ["power_flow", "scenario_power_flow"],
    "compare_fault_runs": ["simulate_fault"],
}
Short = Annotated[str, Field(min_length=1, max_length=160)]


class OptionQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    description: Short
    value: str | None = Field(default=None, max_length=120)
    function: Short | None = None


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    functions: list[Short] = Field(default_factory=list, max_length=8)
    options: list[OptionQuery] = Field(default_factory=list, max_length=12)


def tokens(text):
    # FTS5 unicode61 treats Chinese runs as single tokens; add individual CJK
    # characters and bigrams while retaining exact English identifiers.
    words = re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff]+", text.lower())
    result = []
    for word in words:
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            result.extend(word)
            result.extend(word[i:i+2] for i in range(len(word)-1))
        else:
            result.append(word)
            result.extend(word.split("_"))
    return list(dict.fromkeys(x for x in result if x))[:64]


def contracts(tools):
    """Build function and option triples from the exact registered tool schemas."""
    rows = []
    for name, tool in sorted(tools.items()):
        schema = tool.get_input_schema().model_json_schema()
        rows.append({"id": name, "kind": "function", "function": name,
                     "description": tool.description, "depends_on": DEPENDENCIES.get(name, []),
                     "source": "registered GridAgent tool schema", "schema": schema})
        for option, spec in schema.get("properties", {}).items():
            rows.append({"id": f"{name}.{option}", "kind": "option", "function": name,
                         "option": option, "schema": spec, "required": option in schema.get("required", []),
                         "description": (spec.get("description") or OPTION_HINTS.get(option) or option),
                         "source": "registered GridAgent tool schema"})
    return rows


def search_text(row):
    return " ".join([row["id"], row["function"], row["description"], row.get("option") or "",
                     ALIASES.get(row["function"], ""), json.dumps(row.get("schema", {}), ensure_ascii=False)])


@lru_cache(maxsize=2)
def embedding_model(path):
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(path, device="cpu", local_files_only=True, trust_remote_code=False)


@lru_cache(maxsize=8)
def reference_vectors(path, texts):
    return embedding_model(path).encode(["passage: " + text for text in texts], normalize_embeddings=True)


def semantic_ranks(query, rows, limit):
    raw = os.getenv("GRIDAGENT_EMBEDDINGS_PATH")
    if not raw or not Path(raw).is_dir():
        return []
    path = str(Path(raw).resolve())
    try:
        texts = tuple(search_text(row) for row in rows)
        vectors = reference_vectors(path, texts)
        embedding = embedding_model(path).encode(["query: " + query], normalize_embeddings=True)[0]
    except (ImportError, OSError, ValueError, RuntimeError):
        return []
    return [rows[index]["id"] for index in sorted(range(len(rows)), key=lambda n: -float(vectors[n] @ embedding))[:limit]]


def workspace_knowledge(root, contracts=()):
    from .knowledge_store import reference_rows
    from .official_knowledge import official_rows

    return KnowledgeIndex([*contracts, *official_rows(), *(reference_rows(root) if root is not None else [])])


class KnowledgeIndex:
    def __init__(self, rows):
        self.rows = {row["id"]: row for row in rows}

    def search(self, query, kind, function=None, limit=3):
        candidates = [row for row in self.rows.values() if row["kind"] == kind
                      and (function is None or row["function"] == function)]
        if not candidates:
            return []
        exact = [row for row in candidates if query.casefold() in {
            row["id"].casefold(), (row.get("option") or "").casefold()}]
        semantic = semantic_ranks(query, candidates, 12) if kind == "reference" else []
        lexical_limit = max(12, limit) if semantic else limit
        words = tokens(query)
        if not words:
            return [self.rows[key] for key in dict.fromkeys([r["id"] for r in exact] + semantic)][:limit]
        with sqlite3.connect(":memory:") as db:
            try:
                db.execute("CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, terms)")
                db.executemany("INSERT INTO docs VALUES (?, ?)",
                               [(r["id"], " ".join(tokens(search_text(r)))) for r in candidates])
                expr = " OR ".join('"' + word + '"' for word in words)
                ids = [r[0] for r in db.execute(
                    "SELECT id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs), id LIMIT ?", (expr, lexical_limit))]
            except sqlite3.OperationalError:
                # Standard-library fallback for Python builds without FTS5.
                query_words = set(words)
                ranks = [(len(query_words & set(tokens(search_text(row)))), row["id"]) for row in candidates]
                ids = [key for score, key in sorted(ranks, key=lambda x: (-x[0], x[1])) if score][:lexical_limit]
        if semantic:
            scores = {}
            for ranking in (ids, semantic):
                for position, key in enumerate(ranking, 1):
                    scores[key] = scores.get(key, 0) + 1/(60+position)
            ids = sorted(scores, key=lambda key: (-scores[key], key))
        return [self.rows[key] for key in dict.fromkeys([r["id"] for r in exact] + ids)][:limit]

    def retrieve(self, plan):
        plan = QueryPlan.model_validate(plan)
        functions, options, references = {}, {}, {}
        for query in plan.functions:
            for ref in self.search(query, "reference"):
                references[ref["id"]] = ref
            for row in self.search(query, "function"):
                functions[row["id"]] = row
        for query in plan.options:
            for ref in self.search(query.description, "reference", query.function):
                references[ref["id"]] = ref
            for row in self.search(query.description, "option", query.function):
                options[row["id"]] = {**row, "requested_value": query.value}
                parent = self.rows.get(row["function"])
                if parent:
                    functions[parent["id"]] = parent
        # Preserve explicit function dependencies, without unconstrained graph expansion.
        dependencies = {}
        for row in list(functions.values()):
            for name in row.get("depends_on", []):
                if name in self.rows:
                    dependencies[name] = self.rows[name]["description"]
        return {"functions": list(functions.values())[:12], "options": list(options.values())[:18],
                "dependencies": dependencies, "references": list(references.values())[:6],
                "method": "lexical and dependency retrieval; optional local semantic ranking for references",
                "note": "Contracts are authoritative for syntax; requested values are not validated by retrieval."}

    def feedback(self, name, fields):
        rows = [row for row in self.rows.values() if row["function"] == name and row["kind"] != "reference"]
        selected = [row for row in rows if row["kind"] == "function" or not fields
                    or row.get("option") in {field.split(".")[0] for field in fields}]
        # Limit returned schema size; never search arbitrary error text or file paths.
        return {"function": name, "contracts": selected[:12], "references": self.search(" ".join(fields) or name, "reference", name), "hint": "Correct the parameters or choose another method."}
