# Scientific renderers (stage 4)

Reuse the retained file viewer, its source/rendered toggle, workspace transport
and file identity. Add Plotly.js 3.3.1 (minified distribution) and Cytoscape.js
3.33.1 as pinned local dependencies with pnpm lock entries. No CDN, second
desktop shell, iframe, arbitrary HTML or model-supplied chart options.
Only scientific previews load these renderers.

Supported project-file formats: existing gridagent.chart.v1 (.chart.json:
line/scatter) and gridagent.view.v1 (.view.json: heatmap, surface, topology,
table). Reconstruct renderer options from bounded fields; escape Plotly labels,
reject unexpected fields, invalid coordinates and invalid topology links.
The graph retains supplied positions and undirected links; it is not a
professional single-line diagram, editable model or power-flow result.
Source mode remains available. Project files are always labeled unverified;
this is NOT a committed run-artifact viewer or an independent verifier.
The Python artifact validators and hashes remain authoritative for runs.
The next integration step is a project-bound, hash-checked committed run
reader using the existing native scientific service and viewer surface.

Dependency integrity entries were cross-checked against public lockfiles;
the actual registry download and frozen pnpm install must pass CI. Current
environment cannot access npm, so no local install or browser rendering
measurement is claimed. Windows desktop CI includes parser and retained
viewer tests. Real WebView rendering, CSP/WebGL, accessibility, theme changes,
offline operation and bundle/latency measurement remain release gates.
