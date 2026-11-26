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

Select the Python interpreter and workspace in the settings expander.
The default Windows workspace is %LOCALAPPDATA%\GridAgent; use
gridagent --workspace "$env:LOCALAPPDATA\GridAgent" to share it with TUI.
Use an absolute Python path if python is not on PATH. Set an OpenAI-compatible
model, base URL and API key for online model tasks. Offline history, DMQ
reference, eigenanalysis and optimization do not require a model key.

## Current capabilities

Native session and study lists, history replay, natural-language tasks with
stage updates, DMQ/reference, manifest picker for DSR, eigenanalysis,
optimization, run listing and DSR resume. The transcript is selectable plain
text. No rich Markdown, interactive plots, model picker, persistent desktop
preferences or cancel button yet. Closing is blocked during active work.
The model key is not stored in SQLite or configuration.

## Build

    dotnet publish desktop/GridAgent.Windows -c Release -r win-x64 --self-contained true

Windows CI builds and publishes a self-contained .NET x64 desktop artifact.
The Python environment and solver dependencies are **not** bundled yet:
install them separately and point the app at that interpreter. No installer,
signature or Store release is claimed. A later release should package a
version-pinned Python distribution with license notices and Windows x64/ARM64
testing as applicable. Build success does not prove visual UI correctness.
