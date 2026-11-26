# Native Windows desktop

GridAgent.Windows is a Windows-only WPF/.NET 10 application. It does not use
Electron, a browser, WebView, JavaScript, HTTP or a web service. The existing
Python LangGraph, ANDES and SQLite research engine remains shared with TUI.
The client starts one local Python process per operation with a JSON-lines
stdin/stdout protocol. API keys are held for the current app session only,
passed via the child environment rather than command arguments, and not saved.
The bridge does not show raw tool JSON or stderr.

## Developer setup (Windows PowerShell)

Install Python 3.11 and the .NET 10 SDK. From the repository root:

    py -3.11 -m venv .venv
    .\.venv\Scripts\python.exe -m pip install -e ".[andes]"
    $env:GRIDAGENT_PYTHON = (Resolve-Path .\.venv\Scripts\python.exe).Path
    dotnet run --project desktop/GridAgent.Windows

The developer override is only used when no bundled runtime is present. The published app automatically uses its private runtime; users do not select an interpreter.
The default Windows workspace is %LOCALAPPDATA%\GridAgent; use
gridagent --workspace "$env:LOCALAPPDATA\GridAgent" to share it with TUI.
Set an OpenAI-compatible
model, base URL and API key for online model tasks. Offline history, DMQ
reference, eigenanalysis and optimization do not require a model key.

## Current capabilities

Native session, study and run lists, history replay, natural-language tasks with
stage updates, DMQ/reference, manifest picker for DSR, eigenanalysis,
optimization, run listing and DSR resume. Select a fault run in the Runs tab to open a native voltage chart with channel selection and
extrema-preserving display sampling. Original CSV remains unchanged. The transcript is selectable plain
text. No rich Markdown, plot zoom/pan, model picker, persistent desktop
preferences or cancel button yet. Closing is blocked during active work.
The model key is not stored in SQLite or configuration.

## Portable Windows distribution

Run from the repository root on Windows x64 with the build SDKs installed:

    ./desktop/package-windows.ps1 -Output desktop-publish

CI publishes the complete directory as GridAgent-Windows-x64. Extract it and
launch GridAgent.exe. The distribution contains a self-contained .NET runtime,
private CPython 3.11, installed GridAgent/ANDES/SciPy/NumPy/LangGraph packages,
example cases, dependency version inventory, and a gridagent-tui.cmd launcher.
No system Python, pip, PATH configuration, or first-launch dependency download
is required. Model APIs require network access and credentials; licensed
commercial simulators are not included. Do not move the EXE out of its folder.
The build checks relocation to a path with spaces with system Python off PATH,
then runs a real bridge session, ANDES fault and eigenanalysis. Package contents
and runtime checks remain subject to CI. The distribution is a portable folder,
not yet a signed installer. Dependency versions are recorded per build, not
fully locked across builds. Retain upstream package license metadata; a full
third-party notice/source compliance review is still required before release.
