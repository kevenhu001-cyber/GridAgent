"""Paginated native result tables, restricted to known per-backend artifacts."""
import csv
from pathlib import Path

from .workspace import artifact_folder, load_object

TABLES = {"pandapower": {"bus", "line", "trafo", "load", "gen", "sgen", "storage", "ext_grid",
                         "res_bus", "res_line", "res_trafo", "res_bus_sc"},
          "pypsa": {"generation_mw", "storage_mw", "storage_soc_mwh", "link_mw", "marginal_price"}}


def read_table(root, run_id, table, offset=0, limit=20):
    if not 0 <= offset <= 100000 or not 1 <= limit <= 50:
        raise ValueError("Invalid pagination")
    folder = artifact_folder(Path(root), "runs", run_id)
    result = load_object(folder / "result.json")
    if table not in TABLES.get(result.get("backend"), set()):
        raise ValueError("Unknown result table for this backend")
    path = (folder / (table + ".csv")).resolve()
    if path.parent != folder or not path.is_file():
        raise ValueError("Table not produced by this run")
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        columns = next(reader, [])
        rows = []
        total = 0
        for index, row in enumerate(reader):
            total += 1
            if offset <= index < offset + limit:
                rows.append(row)
    return {"run_id": run_id, "table": table, "columns": columns,
            "rows": rows, "total": total, "next_offset": offset+limit if offset+limit < total else None}
