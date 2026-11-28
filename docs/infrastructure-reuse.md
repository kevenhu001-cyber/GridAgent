# Open-source infrastructure reuse

Status: incremental adoption, not production acceptance.

GridAgent remains a local-first LLM-led scientific agent. Reuse mature infrastructure rather than introducing parallel implementations. Keep Pi, Proliferate, SQLite/FTS5, Pydantic, NetworkX and existing scientific solvers. Do not add a second chat, task database or Agent engine.

| Component | Upstream | Decision and acceptance gate |
| --- | --- | --- |
| Package installation | [uv](https://github.com/astral-sh/uv) | First slice: host-configured absolute executable, wheel-only installation into existing staged plugin generations; preserve import checks, metadata, rollback and locks. Test actual install on Windows. |
| Python distribution | [Python Build Standalone](https://github.com/astral-sh/python-build-standalone) | Qualify via uv-managed Python in CI. Do not replace the embedded Windows resource layout until isolated Python, native DLLs, relocation, license notices and offline installation are verified. |
| Sandbox | [Microsoft MXC](https://github.com/microsoft/mxc) | Evaluation only. Verify availability, API stability, resource limits, cancellation, credentials, network denial, filesystem boundaries and clean Windows deployment. No downgrade to host execution or weaker isolation. Retain existing Windows Sandbox until acceptance. |
| Persistent compute | [jupyter_client](https://github.com/jupyter/jupyter_client), [ipykernel](https://github.com/ipython/ipykernel) | Optional isolated kernel, no Jupyter web server. Verify transport authentication, per-project isolation, interrupt/restart, artifact provenance and reproducible batch fallback. |
| Scientific rendering | [Plotly.js](https://github.com/plotly/plotly.js), [Cytoscape.js](https://github.com/cytoscape/cytoscape.js) | Lazy-load only needed renderers into existing UI and typed evidence contracts; no model-generated executable visualization. |
| Notebook and math | [nbformat](https://github.com/jupyter/nbformat), [KaTeX](https://github.com/KaTeX/KaTeX) | Standard notebook export; reuse existing math renderer if present. Treat imported outputs as unverified and code as untrusted. |
| Optional extensions | [Docling](https://github.com/docling-project/docling), [Joblib](https://github.com/joblib/joblib) | Defer until concrete document/parallellism needs; separate optional dependency environments and measure footprint. |

## Phase 1 scope and limitations

The uv Windows CI lane uses a pinned uv release (0.13.9) and a uv-managed CPython 3.11 development environment. uv obtains managed Python distributions from Python Build Standalone. This tests scientific imports and a real lightweight plugin installation, not the production Windows Sandbox or Tauri resource bundle. Python patch and project dependency resolution remain unpinned in this experimental lane; do not claim a reproducible release. Existing pip-based update discovery remains unchanged, and the default plugin installer remains pip when no explicit trusted host configuration exists. A configured uv failure does not retry with pip. The uv child gets the existing sanitized environment; configuration files are disabled and Python downloads are disabled for plugin installs. Explicit index, wheel-only and copy mode keep plugin generations independent of the shared cache. Installing wheels and importing plugins is still a trusted host operation from the existing first-party catalog, not isolation.

## Subsequent acceptance

Before promotion: lock the supported release interpreter and dependencies, verify the Windows resource layout with native libraries, check artifact hashes and license notices, measure installation and runtime footprint, exercise rollback/uninstall, and pass actual sandbox execution and clean-machine packaging checks. Keep current host-owned permissions, durable job IDs, solver evidence and existing UI. Do not remove current implementations until the new path passes regression and security tests. Do not introduce cloud services or new databases without a measured need.
