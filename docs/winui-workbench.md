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
The conversation uses a bounded viewport ListView with ItemsStackPanel virtualization, rather than a ScrollViewer containing all messages. Markdown is parsed using Markdig with HTML disabled and rendered into native XAML. Links and image destinations are selectable text, never automatically fetched or executed. Native headings, lists, quotes, code and tables are supported; mathematical typesetting and token streaming are not yet implemented. Tool details remain collapsed, generated lazily and bounded to the most recent 100 sanitized summaries. Dispatcher scroll updates are coalesced. Test long histories and measure memory/scroll frame timing on Windows before claiming a numerical improvement.
- https://learn.microsoft.com/en-us/windows/apps/develop/performance/optimize-gridview-and-listview
- https://learn.microsoft.com/en-us/windows/apps/develop/performance/app-startup-performance
