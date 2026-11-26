"""Structured, dependency-aware retrieval for engineering tool contracts.

Inspired by Jia, Cui and Hug, IEEE TSG 2025, DOI 10.1109/TSG.2025.3589114.
Independent implementation; no upstream supplemental material is redistributed.
"""
import json
import re
import sqlite3
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

ALIASES = {
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
    return " ".join([row["id"], row["function"], row["description"],
                     ALIASES.get(row["function"], ""), json.dumps(row.get("schema", {}), ensure_ascii=False)])


class KnowledgeIndex:
    def __init__(self, rows):
        self.rows = {row["id"]: row for row in rows}

    def search(self, query, kind, function=None, limit=3):
        candidates = [row for row in self.rows.values() if row["kind"] == kind
                      and (function is None or row["function"] == function)]
        if not candidates:
            return []
        exact = [row for row in candidates if query.casefold() in {
            row["id"].casefold(), row.get("option", "").casefold()}]
        words = tokens(query)
        if not words:
            return exact[:limit]
        with sqlite3.connect(":memory:") as db:
            try:
                db.execute("CREATE VIRTUAL TABLE docs USING fts5(id UNINDEXED, terms)")
                db.executemany("INSERT INTO docs VALUES (?, ?)",
                               [(r["id"], " ".join(tokens(search_text(r)))) for r in candidates])
                expr = " OR ".join('"' + word + '"' for word in words)
                ids = [r[0] for r in db.execute(
                    "SELECT id FROM docs WHERE docs MATCH ? ORDER BY bm25(docs), id LIMIT ?", (expr, limit))]
            except sqlite3.OperationalError:
                # Standard-library fallback for Python builds without FTS5.
                query_words = set(words)
                ranks = [(len(query_words & set(tokens(search_text(row)))), row["id"]) for row in candidates]
                ids = [key for score, key in sorted(ranks, key=lambda x: (-x[0], x[1])) if score][:limit]
        return [self.rows[key] for key in dict.fromkeys([r["id"] for r in exact] + ids)][:limit]

    def retrieve(self, plan):
        plan = QueryPlan.model_validate(plan)
        functions, options = {}, {}
        for query in plan.functions:
            for row in self.search(query, "function"):
                functions[row["id"]] = row
        for query in plan.options:
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
                "dependencies": dependencies, "method": "separate function/option lexical retrieval",
                "note": "Contracts are authoritative for syntax; requested values are not validated by retrieval."}

    def feedback(self, name, fields):
        rows = [row for row in self.rows.values() if row["function"] == name]
        selected = [row for row in rows if row["kind"] == "function" or not fields
                    or row.get("option") in {field.split(".")[0] for field in fields}]
        # Limit returned schema size; never search arbitrary error text or file paths.
        return {"function": name, "contracts": selected[:12], "hint": "Correct the parameters or choose another method."}
