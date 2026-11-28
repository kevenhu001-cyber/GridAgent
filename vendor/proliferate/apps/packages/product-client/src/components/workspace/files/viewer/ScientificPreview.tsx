import { useEffect, useMemo, useRef, useState } from "react";
import { parseScientificData, plotText, type ScientificData } from "#product/lib/domain/files/scientific-preview";

export default function ScientificPreview({content, filePath}: {content: string; filePath: string}) {
  const data = useMemo(() => {
    try { return parseScientificData(content, filePath); } catch { return null; }
  }, [content, filePath]);
  if (!data) return <div className="p-4 text-ui-sm text-muted-foreground" role="status">
    Invalid or oversized scientific data. Switch to source to inspect the file.
  </div>;
  return <div className="flex h-full min-h-0 flex-col overflow-auto bg-background p-4">
    <div className="mb-3 text-ui font-medium">{data.title}</div>
    <div className="mb-3 text-ui-xs text-muted-foreground">Project file preview · Unverified data</div>
    {data.kind === "table" ? <div className="overflow-auto">
      <table className="w-full text-left text-ui-sm">
        <thead><tr>{data.columns.map(c => <th key={c} className="border-b border-border p-2">{c}</th>)}</tr></thead>
        <tbody>{data.rows.map((row, i) => <tr key={i}>{row.map((v, j) =>
          <td key={j} className="border-b border-border p-2">{v === null ? "—" : String(v)}</td>)}</tr>)}</tbody>
      </table>
    </div> : <Renderer data={data}/>}
  </div>;
}

function Renderer({data}: {data: Exclude<ScientificData, {kind: "table"}>}) {
  const root = useRef<HTMLDivElement>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    const outer = root.current;
    if (!outer) return;
    setError(false);
    const host = document.createElement("div");
    host.style.width = "100%";
    host.style.height = "100%";
    outer.replaceChildren(host);
    let disposed = false;
    let cleanup = () => {};
    const run = async () => {
      if (data.kind === "topology") {
        const {default: cytoscape} = await import("cytoscape");
        if (disposed) return;
        const fg = getComputedStyle(outer).color;
        const cy = cytoscape({
          container: host,
          elements: [
            ...data.nodes.map(n => ({data: {id: "n-" + n.id, label: n.label},
              position: {x: 700 * n.x, y: 450 * n.y}})),
            ...data.edges.map((e, i) => ({data: {id: "e-" + i, source: "n-" + e.source, target: "n-" + e.target}})),
          ],
          layout: {name: "preset", fit: true, padding: 30},
          autoungrabify: true,
          style: [
            {selector: "node", style: {"background-color": "#6088bb", label: "data(label)",
              color: fg, "font-size": 12, "text-valign": "bottom", "text-margin-y": 5}},
            {selector: "edge", style: {width: 2, "line-color": "#8491a3"}},
          ],
        });
        const observer = new ResizeObserver(() => cy.resize());
        observer.observe(outer);
        cleanup = () => {observer.disconnect(); cy.destroy();};
      } else {
        const {default: plotly} = await import("plotly.js-dist-min");
        if (disposed) return;
        const fg = getComputedStyle(outer).color;
        const traces = data.kind === "chart" ? data.series.map(s => ({
          type: "scatter", mode: data.scatter ? "markers" : "lines", x: s.x, y: s.y, name: plotText(s.name),
        })) : [{type: data.kind, x: data.x, y: data.y, z: data.z,
          colorbar: {title: {text: plotText(data.value_label)}}}];
        const axes = {xaxis: {title: {text: plotText(data.x_label)}},
          yaxis: {title: {text: plotText(data.y_label)}}};
        const layout = {autosize: true, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
          font: {color: fg}, margin: {l: 60, r: 30, t: 20, b: 60},
          ...(data.kind === "surface" ? {scene: {...axes, zaxis: {title: {text: plotText(data.value_label)}}}} : axes)};
        cleanup = () => {plotly.purge(host);};
        await plotly.newPlot(host, traces, layout, {responsive: true, displaylogo: false, displayModeBar: false});
        if (disposed) {plotly.purge(host); return;}
        const observer = new ResizeObserver(() => {void plotly.Plots.resize(host);});
        observer.observe(outer);
        cleanup = () => {observer.disconnect(); plotly.purge(host);};
      }
    };
    void run().catch(() => {if (!disposed) {cleanup(); setError(true);}});
    return () => {disposed = true; cleanup(); host.remove();};
  }, [data]);
  return <>
    {error && <div role="status" className="text-ui-sm text-muted-foreground">Scientific renderer unavailable. Switch to source to inspect the data.</div>}
    <div ref={root} className="min-h-[320px] min-w-0 flex-1" role="img" aria-label={data.title}/>
  </>;
}
