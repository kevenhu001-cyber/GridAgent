# Native WinUI 3 workbench

The Windows app is a native C#/XAML application with Windows App SDK 1.8.10, not a web wrapper. The Python process protocol, workspace and sandbox policy remain unchanged. The default packaging path is self-contained and unpackaged; the WPF source is temporarily retained for regression comparison only.

## Design decisions
- NavigationView uses automatic pane modes and separate destinations for assistant, tasks, models, results, studies, tools, plugins and settings.
- TitleBar, Mica, default WinUI control styles, theme resources, system typography, InfoBar and ContentDialog follow the Windows app design system.
- Chat groups tool activity in collapsed expanders, uses selectable response text, offers research modes and keyboard send; no raw subprocess diagnostics are shown.
- Preserve explicit authorizations for repair, sandbox and plugin mutation. Do not equate a generated script with verified numerical output.
- Scientific charts and topology require dedicated accessible alternatives and manual verification.

## Microsoft references
- https://learn.microsoft.com/en-us/windows/apps/develop/ui/windows-app-sdk-app-structure
- https://learn.microsoft.com/en-us/windows/apps/design/controls/navigationview
- https://learn.microsoft.com/en-us/windows/apps/design/controls/title-bar
- https://learn.microsoft.com/en-us/windows/apps/get-started/line-of-business/design-for-lob
- https://learn.microsoft.com/en-us/windows/apps/design/accessibility/accessibility-checklist
- https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/unpackage-winui-app

## Release gates
The separate `winui-build` job compiles XAML and C# before the full packaging pipeline. The Windows packaging job also reports total portable and private Python bytes. Windows build and relocated portable smoke must pass; verify actual app startup, light/dark/high contrast, 100/150/200% scaling, narrow/wide layout, keyboard traversal, Narrator, provider configuration, offline execution, research cancellation/approval, plugin install/update/rollback, chart and topology interactions. Measure package size and cold startup against WPF. Do not delete the rollback implementation until these checks pass.

## Conversation polish and performance
The conversation uses a bounded viewport ListView with ItemsStackPanel virtualization, rather than a ScrollViewer containing all messages. Markdown is parsed using Markdig with HTML disabled and rendered into native XAML. Links and image destinations are selectable text, never automatically fetched or executed. Native headings, lists, quotes, code and tables are supported; mathematical typesetting and token streaming are implemented as described below. Tool details remain collapsed, generated lazily and bounded to the most recent 100 sanitized summaries. Dispatcher scroll updates are coalesced. Test long histories and measure memory/scroll frame timing on Windows before claiming a numerical improvement.
- https://learn.microsoft.com/en-us/windows/apps/develop/performance/optimize-gridview-and-listview
- https://learn.microsoft.com/en-us/windows/apps/develop/performance/app-startup-performance

## Startup and plotting
The WinUI initialization request loads only model settings and session metadata. The full workspace index is requested when entering an engineering list, or refreshed after mutations. Agent, simulation and research imports are deferred to the appropriate bridge actions. A subprocess regression test checks that the startup path does not import the heavy modules. Chart windows now have a series legend, nearest-sample readout and clipboard CSV of the **displayed** (possibly downsampled) samples; original data remain in the workspace. These are engineering inspection tools, not a full schematic CAD or high-rate GPU plotting engine.

## Workspace navigation and measurement
Recent conversations are reachable from the native navigation pane, searchable in the history tab, and simulation run identifiers in sanitized tool summaries provide a direct result-list shortcut. Engineering list pages use a bounded Grid and virtualizing ListView; command bars move less-used actions into overflow. The portable CI job measures isolated bridge initialization and full-index latency separately, as well as package size. This is not a measured GUI cold-start or frame-rate claim.
- https://learn.microsoft.com/en-us/windows/apps/design/controls/command-bar
- https://learn.microsoft.com/en-us/windows/apps/get-started/line-of-business/design-for-lob

Research events render in a dedicated live task card with budget usage, collapsible details and a direct task-list action. The chat scroll follows new messages only when the user is at the bottom; a jump-to-latest control is shown when reading earlier content.

## Streaming responses
The assistant requests optional streaming from compatible providers. The agent aggregates complete model messages and tool-call chunks before running tools, preserving existing budget and persistence semantics. The desktop bridge emits only public text deltas, batched at roughly 45 ms or 512 characters, followed by an authoritative final message. Native UI renders inexpensive text during generation and renders Markdown on completion. Interrupted previews are labelled and are not treated as completed history. Settings allow streaming to be disabled for incompatible providers. Hidden reasoning and tool arguments are not forwarded. Verified research workflows still emit stage updates rather than token streams.

## Local mathematical typesetting
Markdig mathematics recognizes dollar-delimited inline and display TeX; CSharpMath with pinned SkiaSharp renders supported equations offline, without HTML or WebView. The native control supplies accessible source text and a fallback when parsing or rendering fails. Rendering is deferred off the UI thread and uses a bounded 96-entry/8 MiB cache with theme-aware keys. Inputs are limited to 512 characters and bounded brace depth; unsupported constructs and long expressions remain selectable source. This is not a full LaTeX compiler. Verify formula examples, theme switching and package audit on Windows before release.

## Native scientific rendering
Scientific plot windows now use Microsoft's Win2D CanvasControl (Direct2D) instead of constructing per-sample XAML elements. Cached sorted samples support logarithmic nearest-point lookup; pointer redraw is throttled, series visibility and axis range can be updated, and displayed data can be copied as CSV. Native resources are detached on close. This is an implementation change, not a measured GPU or FPS claim. Reference: https://learn.microsoft.com/en-us/windows/apps/develop/win2d/quick-start .

## Topology inspection
A separate native topology window supports voltage-level or circular layout, zoom, bus/branch selection, branch-specific parameter filtering, numeric range validation, and explicit revision confirmation. The original run remains immutable. The source workspace is checked again before saving. Bus-to-device ownership is not inferred from missing metadata; bus selection shows connected-branch counts and global editable parameters. Drag-and-drop schematic creation and multi-operation topology editing are not implemented.

## Transport architecture (version 1)
WinUI uses a workspace-scoped resident metadata/read service over local JSON Lines for initialize, history, index and chart reads. Every frame has a version and request ID; responses terminate explicitly. The allowlisted service never dispatches model/provider calls, solver jobs, plugin installs, research mutations or arbitrary commands. It is recycled after 64 calls or settings/workspace changes, has bounded requests and response frames, and is terminated on a failed request or app exit. API credentials are not passed to the read process. Mutations continue through isolated one-shot processes, including the separate cooperative research cancellation request. No mutation is automatically replayed. WPF retains the one-shot protocol. The service may initialize SQLite metadata schemas; it is not an OS-level read-only sandbox. Performance measurements must distinguish process reuse from solver execution.

## Artifact presentation contract
The desktop bridge optionally emits versioned `gridagent.artifact.v1` run cards. Card metadata and scalar metrics are projected from persisted result/quality files, not LLM output. Solver status and local check counts are distinct. The client validates the schema, uses typed DTOs and renders native cards; unknown schemas are ignored. A user-requested preview reads a bounded first chart (at most 240 points, line extrema retained, scatter previews sampled) through the read service. Original artifacts remain untouched; full chart access uses the existing result view. History reconstructs cards from stored tool messages. No model-generated executable UI, paths or chart values are accepted. This first schema is intentionally extensible to studies, tables and model revisions, but those kinds are not yet implemented.

## Application state boundary
ConversationState owns message lifecycle, grouping, streaming reconciliation, artifact identity and research-card updates without depending on XAML or a dispatcher. MainWindow.Conversation handles scroll/focus/commands; MainWindow.EngineEvents translates transport events into presentation state. Native controls only render that state. A cross-platform .NET contract test exercises stream finalization, interrupted previews, deduplication, malformed schema handling and research updates before WinUI compilation. This is the first state extraction, not a claim that every desktop page is MVVM yet.
