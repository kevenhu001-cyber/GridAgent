# GridAgent native UI design contract

Owner direction: ChatGPT-inspired, quiet, content-first interaction. Applies to all WinUI screens, including scientific workbench and future visualization. Use OpenAI's public [plugin UI guidelines](https://developers.openai.com/plugins/concepts/ui-guidelines) and [frontend guidance](https://developers.openai.com/api/docs/guides/frontend-prompt) as visual references; these are public guidance, not a claim of access to ChatGPT's internal design system. Use [Windows design guidelines](https://learn.microsoft.com/en-us/windows/apps/design/guidelines-overview) for native input, typography, focus, windowing and accessibility. GridAgent retains its own identity and WinUI implementation.

## Required decisions

- Content first: flat conversation, left-aligned assistant content, restrained right-aligned user bubble. Keep the reading column and composer aligned (820 effective pixels maximum). No redundant page headers, ornamental dividers, decorative gradients, excessive cards or artificial dashboard framing.
- Neutral shell in light and dark, using shared theme resources. Primary text near black/white; secondary metadata visually quieter, never illegible. Main send action monochrome and rounded; secondary actions subtle. Color is reserved for meaning and data series. Respect system high contrast, text scaling and keyboard focus.
- Use native Segoe UI Variable, readable 15 DIP body, 13 DIP metadata, 16–18 DIP compact artifact headings. Use a 4/8 DIP spacing rhythm, 8 DIP artifact corner radius, 16 DIP card padding; rounded input and user bubble are intentional exceptions. Use consistent semantic resources rather than local color literals. Keep native controls and icons.
- Tool activity collapsed initially with latest useful action, expand only on request. Never show raw protocol JSON, tool arguments, hidden reasoning or stack traces by default. Show genuine errors concisely with recovery actions; do not hide evidence or suppress important warnings.
- Scientific artifacts: one quiet card per artifact, title then compact data/units/provenance, one obvious action. Avoid cards inside cards. Distinguish unverified outputs from independently validated evidence in words, not color alone. Large interactive figures open only on explicit action; plots retain axis units, accessible textual values and high-contrast labels.
- Workbench pages should emphasize files, code, results and actions, not promotional descriptions, giant headings or grids of decorative buttons. Optional specialized workflows must not displace the default LLM assistant.
- Do not introduce a WebView or duplicate front-end framework solely to imitate ChatGPT; use WinUI resources and native drawing surfaces. Do not copy OpenAI branding.

## Review gate

For every UI change check light/dark/high contrast, 100/150/200% DPI, narrow/wide window, empty/loading/error/streaming/completed states, keyboard navigation, screen reader labels, scroll position, long labels and units. Keep tool and visualization results usable at narrow widths. Include actual before/after Windows screenshots and visual smoke evidence when available; otherwise explicitly mark the visual acceptance pending. Automated tests or compilation alone do not prove visual fidelity. Do not claim pixel-identical ChatGPT UI or internal design compliance.

Shared artifact card and composer styles live in App.xaml; reuse these instead of repeating local values. Subsequent workbench changes must follow this contract.


## Shell and conversation implementation pass

- Sidebar: native new-conversation and search actions, recent conversations ordered by activity and displayed with bounded first-question titles for unnamed sessions. Explicit titles remain unchanged. New conversation resets to the primary assistant mode.
- Chat: one compact model label; icon actions share sizing; composer and reading column share width, with numerical verification notice outside the composer. Optional verified/multi-agent modes remain explicitly selectable.
- Activity: a lightweight native disclosure button replaces the large Expander card. The latest action is shown on one trimmed line, and explicit expansion persists across tool updates and item recycling. The durable audit record is unchanged.
- Subpages: shared page heading typography; model-provider settings separated from execution permission settings. Markdown table content is flat rather than nested in an ornamental card.
- Tests cover the state of activity disclosure and local conversation list title/ordering. Windows screenshots, theme/focus/DPI and real native compilation remain required for acceptance.


## Workbench catalog and detail pass

- Plugins are a flat catalog with one Details action per entry. Package requirements, capabilities, versions and management operations are disclosed in a native details dialog. Download, update, rollback and uninstall retain explicit confirmation and the existing managed installation boundaries. Plugin operation summaries appear in the workbench notification rather than injecting into conversation history.
- Knowledge is a native local pack list. Exact content ID selects a bounded ten-reference page, with source and version shown and explicit imported/unverified labeling. Import and refresh stay on the page; no model request is needed.
- Tasks, model revisions, simulation results and studies use a shared two-line list template with clear title and secondary metadata. Model revision diff opens a native detail dialog without switching the active chat. Existing command handlers and simulation semantics remain unchanged.
- Regression checks cover local reference catalog, pagination and invalid offsets/IDs. Real Windows layout, keyboard navigation, high contrast and screenshots are still pending.


## Scientific viewer consistency pass

Use ScientificVisualStyle for native viewer title, icon actions, series palette and gridlines. Series labels use normal theme foreground with separate color swatches rather than colored text; swatches update when the theme changes. Reset zoom and copy actions use accessible names and tooltips. Structured tables offer tab-separated clipboard export with formula-like string cells treated as text, and numeric-looking cells aligned right. Preserve source data, units, unverified labels, native drawing and existing interaction boundaries. High-contrast palette rendering and actual Windows visual acceptance are not established by this source-only pass.


## Global feedback and empty-state pass

Use the native search FontIcon, preserve the explicit icon contract check, disable sending empty prompts, hide the idle operation footer and expose accurate loading labels for active commands. Workbench lists distinguish not-yet-loaded and confirmed empty; session search distinguishes no matches. Errors from conversational operations remain inline; other operation failures use the existing InfoBar, without injecting a second error into chat or displaying raw provider diagnostics. No speculative progress percentages or custom animation loops. Existing native transitions and focus behaviors remain. Windows high-contrast, narrow-window and visual acceptance are pending.
