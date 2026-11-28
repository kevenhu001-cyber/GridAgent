import { describe, expect, it } from "vitest";
import { parseScientificData, plotText } from "./scientific-preview";
import { canPreviewAsRichFile } from "./document-preview";

const chart = {
  schema: "gridagent.chart.v1", title: "Voltage", x_label: "Time (s)", y_label: "Voltage (p.u.)",
  scatter: false, series: [{name: "Bus 1", x: [0, 1], y: [1, 0.99]}],
};
const topology = {
  schema: "gridagent.view.v1", kind: "topology", title: "Two-bus network",
  nodes: [{id: "a", label: "Bus A", x: 0, y: 0}, {id: "b", label: "Bus B", x: 1, y: 1}],
  edges: [{source: "a", target: "b"}],
};

describe("data-only scientific preview", () => {
  it("opens scientific suffixes in existing preview, not general JSON", () => {
    expect(canPreviewAsRichFile("voltage.chart.json")).toBe(true);
    expect(canPreviewAsRichFile("network.view.json")).toBe(true);
    expect(canPreviewAsRichFile("package.json")).toBe(false);
  });
  it("preserves chart samples and topology positions", () => {
    expect(parseScientificData(JSON.stringify(chart), "a.chart.json")).toMatchObject({kind: "chart", series: chart.series});
    expect(parseScientificData(JSON.stringify(topology), "a.view.json")).toMatchObject({kind: "topology", nodes: topology.nodes});
  });
  it("rejects executable renderer options and mismatched arrays", () => {
    for (const data of [{...chart, layout: {images: []}}, {...chart, series: [{name: "a", x: [1], y: [1,2]}]},
      {...chart, series: [{name: "a", x: [1], y: ["bad"]}]}]) {
      expect(() => parseScientificData(JSON.stringify(data), "a.chart.json")).toThrow();
    }
    expect(() => parseScientificData(JSON.stringify({...topology, edges: [{source: "a", target: "c"}]}), "a.view.json")).toThrow();
  });
  it("accepts bounded field and table data, rejects malformed grids", () => {
    const field = {schema: "gridagent.view.v1", kind: "surface", title: "Field", x_label: "x", y_label: "y",
      value_label: "z", x: [0,1], y: [0,1], z: [[0,1],[1,2]]};
    expect(parseScientificData(JSON.stringify(field), "a.view.json")).toMatchObject({kind: "surface", z: field.z});
    expect(() => parseScientificData(JSON.stringify({...field, z: [[1]]}), "a.view.json")).toThrow();
    expect(parseScientificData(JSON.stringify({schema: "gridagent.view.v1", kind: "table", title: "Result",
      columns: ["Voltage"], rows: [[1],[null]]}), "a.view.json")).toMatchObject({kind: "table", rows: [[1],[null]]});
  });
  it("escapes markup for Plotly text", () => {
    expect(plotText('<a href="https://example.com">&</a>')).toBe("&lt;a href=&quot;https://example.com&quot;&gt;&amp;&lt;/a&gt;");
  });
});
