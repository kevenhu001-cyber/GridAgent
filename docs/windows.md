> **Windows desktop migration:** The default portable build uses the native WinUI 3 workbench. The old WPF project remains a temporary explicit rollback build (`-LegacyWpf`) until Windows visual and feature-parity validation is complete. Both use the same Python bridge and workspace format. See [WinUI design and verification](winui-workbench.md).

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
and runtime checks remain subject to CI. The portable distribution remains a folder. An additional signed development MSIX build is described below. Dependency versions are recorded per build, not
fully locked across builds. Retain upstream package license metadata; a full
third-party notice/source compliance review is still required before release.

The portable distribution also stages pinned PowerAgentBench training assets and original
solver/evaluator source at build time; it excludes held-out answer data. Commercial
simulator profiles are optional and separate from the embedded open runtime.

## Optional solver plugins

The default package bundles ANDES, pandapower, Python Control, HiGHS and shared scientific libraries.
PyPSA, OpenDSS and PyBaMM are installed through Simulation Plugins (internet required).
The packaged interpreter is used for installation and subprocess execution; system Python is unnecessary.

## MSIX (development and production signing)

Build from the already verified native WinUI portable directory, using Windows SDK MakeAppx and SignTool:

    ./desktop/package-windows.ps1 -Output desktop-publish
    ./desktop/package-msix.ps1 -PortableDirectory desktop-publish -Development

The package is a full-trust, medium-integrity x64 packaged desktop application (Windows 10 2004+). The .NET, Windows App SDK and CPython runtime remain self-contained; the protected installed directory is read-only. MSIX defaults to a package-local workspace, plugin directory, theme settings and writable numerical cache. To keep research data across uninstall or share it with the portable/TUI version, choose and back up an external workspace; package-local data may be removed when uninstalling. Optional plugins are still user-authorized and stored outside the install directory.

The CI development artifact contains the signed .msix, public .cer, SHA-256 inventory and package identity metadata. The self-signed test certificate is short-lived and generated per build; no PFX or private key is distributed. On a dedicated test machine, verify the source and certificate thumbprint, then explicitly trust the public certificate in LocalMachine TrustedPeople (administrator approval required). Install through Windows App Installer or Add-AppxPackage. Remove the test certificate when finished. Do not use development signing for public distribution. No trust settings are modified by the build script.

For public sideload distribution use a trusted production signing identity; supply its certificate in CurrentUser\\My and a stable identity name, for example:

    ./desktop/package-msix.ps1 -PortableDirectory desktop-publish -CertificateThumbprint <thumbprint> -IdentityName <publisher-owned-identity> -Version 0.1.0.0

The publisher is derived from the certificate and production signing is timestamped. Store association and automatic updates are separate release tasks. Validate package activation, child Python, optional plugins and Windows Sandbox on real Windows installations before calling MSIX release-ready. Keep ZIP for portable use and TUI. See [Microsoft manual packaging](https://learn.microsoft.com/windows/msix/desktop/desktop-to-uwp-manual-conversion) and [signing guidance](https://learn.microsoft.com/windows/msix/package/sign-msix-package-guide).
