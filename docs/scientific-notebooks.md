# Standard scientific notebook and math (stage 5)

Reuse nbformat for standard Jupyter notebook creation/validation, rather than a
new research file format. The optional notebook extra is installed into the
trusted native Python runtime, not an untrusted guest or a new web server.
Pi's developer-only export_scientific_notebook tool writes an authorized
project .ipynb with existing storage bounds and SHA-256 overwrite guard.

Export successful ordinary Python scientific runs only. Recheck the original
source snapshot and recorded stdout artifact hash, preserve run ID, inputs,
arguments, dependency inventory and provenance. The exported code cell is
unexecuted; captured stdout is plain text in a raw cell. Never execute on
export or import. No active HTML output or trust metadata is generated.
The notebook is a record, not a complete reproducible project bundle; users
must restore inputs, environment and arguments and review code before rerun.
Kernel-batch and shell/probe exports are deferred.

Math reuses MarkdownBody through remark-math 6.0.0 and KaTeX 0.19.0, with
pinned local dependencies and fonts. Inline dollar math, display double-dollar
math and explicit math code fences render via KaTeX. Code spans and ordinary
fences retain the existing renderer. KaTeX trust is false, strict mode is
enabled, expression length and macro expansion are bounded; invalid equations
remain readable source text. No arbitrary HTML input or external font CDN.
Math CSS is bundled with the retained renderer.

The pnpm lock entries are based on public upstream consumer lockfiles.
Registry install, real WebView rendering, font/CSP behavior, streaming/search
regression and release packaging still require CI and desktop validation.
Notebook import, a dedicated notebook editor, and full multi-turn kernel
execution are not introduced. No new Agent, server, UI shell or database.
