// Data-only projection of the existing Python chart/view contracts.
// Project files are not committed run evidence; never imply verification.
type RecordValue = Record<string, unknown>;
type Point = { id: string; label: string; x: number; y: number };
type Edge = { source: string; target: string };
type Cell = string | number | boolean | null;
export type ScientificData =
  | { kind: "chart"; title: string; x_label: string; y_label: string; scatter: boolean;
      series: { name: string; x: number[]; y: number[] }[] }
  | { kind: "heatmap" | "surface"; title: string; x_label: string; y_label: string;
      value_label: string; x: number[]; y: number[]; z: number[][] }
  | { kind: "topology"; title: string; nodes: Point[]; edges: Edge[] }
  | { kind: "table"; title: string; columns: string[]; rows: Cell[][] };

function fail(): never { throw new Error("Invalid or oversized scientific data"); }
function object(value: unknown, keys: string[]): RecordValue {
  if (!value || typeof value !== "object" || Array.isArray(value) ||
      Object.keys(value).length !== keys.length ||
      !keys.every(key => Object.prototype.hasOwnProperty.call(value, key))) return fail();
  return value as RecordValue;
}
function array(value: unknown, max: number, min = 1): unknown[] {
  if (!Array.isArray(value) || value.length < min || value.length > max) return fail();
  return value;
}
function label(value: unknown): string {
  if (typeof value !== "string" || !value.trim() || value.length > 160 || /[\x00-\x1f]/.test(value)) return fail();
  return value;
}
function number(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value) || Math.abs(value) > 1e100) return fail();
  return value;
}
function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[a-zA-Z0-9_-]{1,48}$/.test(value)) return fail();
  return value;
}
function axis(value: unknown, max: number): number[] {
  const a = array(value, max, 2).map(number);
  const step = (a[a.length - 1] - a[0]) / (a.length - 1);
  if (step <= 0 || a.slice(1).some((v, i) => v <= a[i] ||
      Math.abs(v - a[i] - step) > Math.max(Math.abs(v - a[i]), step) * 1e-6)) return fail();
  return a;
}

export function parseScientificData(content: string, path: string): ScientificData {
  if (new TextEncoder().encode(content).length > 1024 * 1024) return fail();
  const raw: unknown = JSON.parse(content);
  if (path.toLowerCase().endsWith(".chart.json")) {
    const a = object(raw, ["schema", "title", "x_label", "y_label", "scatter", "series"]);
    if (a.schema !== "gridagent.chart.v1" || typeof a.scatter !== "boolean") return fail();
    let points = 0;
    const series = array(a.series, 6).map(item => {
      const row = object(item, ["name", "x", "y"]);
      const x = array(row.x, 12000).map(number);
      const y = array(row.y, 12000).map(number);
      points += x.length;
      if (x.length !== y.length || points > 12000) return fail();
      return { name: label(row.name), x, y };
    });
    return { kind: "chart", title: label(a.title), x_label: label(a.x_label), y_label: label(a.y_label),
      scatter: a.scatter, series };
  }
  if (!path.toLowerCase().endsWith(".view.json") || !raw || typeof raw !== "object") return fail();
  const r = raw as RecordValue;
  if (r.schema !== "gridagent.view.v1") return fail();
  const title = label(r.title);
  if (r.kind === "heatmap" || r.kind === "surface") {
    const a = object(r, ["schema", "kind", "title", "x_label", "y_label", "value_label", "x", "y", "z"]);
    const limit = r.kind === "heatmap" ? 64 : 32;
    const x = axis(a.x, limit), y = axis(a.y, limit);
    const z = array(a.z, limit).map(row => array(row, limit).map(number));
    if (z.length !== y.length || z.some(row => row.length !== x.length)) return fail();
    return { kind: r.kind, title, x_label: label(a.x_label), y_label: label(a.y_label),
      value_label: label(a.value_label), x, y, z };
  }
  if (r.kind === "topology") {
    const a = object(r, ["schema", "kind", "title", "nodes", "edges"]);
    const ids = new Set<string>(), positions = new Set<string>(), links = new Set<string>();
    const nodes = array(a.nodes, 100).map(item => {
      const n = object(item, ["id", "label", "x", "y"]);
      const id = identifier(n.id), x = number(n.x), y = number(n.y), pos = x + ":" + y;
      if (ids.has(id) || positions.has(pos) || x < 0 || x > 1 || y < 0 || y > 1) return fail();
      ids.add(id); positions.add(pos);
      return { id, label: label(n.label), x, y };
    });
    const edges = array(a.edges, 200, 0).map(item => {
      const e = object(item, ["source", "target"]);
      const source = identifier(e.source), target = identifier(e.target), key = [source, target].sort().join(":");
      if (source === target || !ids.has(source) || !ids.has(target) || links.has(key)) return fail();
      links.add(key);
      return { source, target };
    });
    return { kind: "topology", title, nodes, edges };
  }
  if (r.kind === "table") {
    const a = object(r, ["schema", "kind", "title", "columns", "rows"]);
    const columns = array(a.columns, 12).map(label);
    if (new Set(columns).size !== columns.length) return fail();
    const rows = array(a.rows, 100).map(row => {
      const cells = array(row, 12);
      if (cells.length !== columns.length) return fail();
      return cells.map((v): Cell => {
        if (v === null || typeof v === "boolean") return v;
        if (typeof v === "string" && v.length <= 160 && !/[\x00-\x1f]/.test(v)) return v;
        return number(v);
      });
    });
    return { kind: "table", title, columns, rows };
  }
  return fail();
}

// Plotly interprets some HTML in text fields. Use escaped text only,
// never pass through model-supplied trace/layout/configuration objects.
export function plotText(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}
