# Run on Windows x64 with a full CPython 3.11 installation and .NET 10 SDK.
# Produces a portable app directory. No Python installation is needed on the target PC.
param([string]$Output = "desktop-publish", [string]$Python = "python")
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

function Invoke-Checked {
    param([string]$Executable, [string[]]$Arguments)
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Executable failed ($LASTEXITCODE)" }
}

$Repo = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Output = [IO.Path]::GetFullPath($Output)
if (Test-Path $Output) { throw "Output directory already exists: $Output" }
$Source = (& $Python -c "import sys; print(sys.base_prefix)").Trim()
if ($LASTEXITCODE -ne 0) { throw "Cannot locate CPython" }
$Version = (& $Python -c "import sys,struct; assert sys.version_info[:2] == (3,11) and struct.calcsize('P') == 8; print(sys.version.split()[0])").Trim()
if ($LASTEXITCODE -ne 0) { throw "Build requires x64 CPython 3.11" }

Invoke-Checked dotnet @("publish", (Join-Path $Repo "desktop/GridAgent.Windows"), "-c", "Release", "-r", "win-x64", "--self-contained", "true", "-o", $Output)
$Runtime = Join-Path $Output "runtime"
# Copy the complete installed CPython layout, not a non-relocatable virtualenv.
# Exclude build-machine site packages and console entry-point wrappers.
& robocopy $Source $Runtime /E /XD site-packages Scripts __pycache__ /XF "*.pyc" /NFL /NDL /NJH /NJS /NP
if ($LASTEXITCODE -ge 8) { throw "CPython copy failed ($LASTEXITCODE)" }
$Bundled = Join-Path $Runtime "python.exe"
if (!(Test-Path $Bundled)) { throw "Missing private CPython executable" }
$Packages = Join-Path $Runtime "Lib/site-packages"
New-Item -ItemType Directory -Force $Packages | Out-Null
# A normal wheel installation preserves ANDES packaged cases and native DLLs.
Push-Location $Repo
try {
    Invoke-Checked $Python @("-m", "pip", "install", "--disable-pip-version-check", "--target", $Packages, ".[core]", "pip>=25,<27")
} finally { Pop-Location }
# A private path file isolates imports from system Python, registry and user site.
@(".", "DLLs", "Lib", "Lib/site-packages", "import site") | Set-Content -Encoding ascii (Join-Path $Runtime "python311._pth")
$Freeze = & $Python -m pip freeze --all --path $Packages
if ($LASTEXITCODE -ne 0) { throw "Cannot record package versions" }
$Freeze | Set-Content -Encoding utf8 (Join-Path $Output "runtime-requirements.txt")
@{ python = $Version; architecture = "win-x64"; runtime = "private-cpython"; project = "GridAgent" } |
    ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Output "runtime-manifest.json")
Copy-Item (Join-Path $Repo "LICENSE"), (Join-Path $Repo "docs/windows.md"), (Join-Path $Repo "desktop/gridagent-tui.cmd") $Output
Copy-Item (Join-Path $Repo "examples") (Join-Path $Output "examples") -Recurse
Invoke-Checked $Python @((Join-Path $Repo "scripts/sync_benchmark.py"), (Join-Path $Output "benchmark-assets"))
# A moved install path with spaces verifies that no build-machine prefix is required.
$Relocated = "$Output relocated"
if (Test-Path $Relocated) { throw "Relocation test directory already exists" }
Move-Item $Output $Relocated
$OldPath = $env:PATH
$OldHome = $env:PYTHONHOME
$OldPythonPath = $env:PYTHONPATH
try {
    $env:PATH = "$env:SystemRoot\System32;$env:SystemRoot"
    Remove-Item Env:PYTHONHOME, Env:PYTHONPATH -ErrorAction SilentlyContinue
    Invoke-Checked (Join-Path $Relocated "runtime/python.exe") @("-X", "utf8", (Join-Path $Repo "desktop/smoke_runtime.py"))
} finally {
    $env:PATH = $OldPath
    $env:PYTHONHOME = $OldHome
    $env:PYTHONPATH = $OldPythonPath
    Move-Item $Relocated $Output
}
$Bytes = (Get-ChildItem $Output -Recurse -File | Measure-Object Length -Sum).Sum
Write-Host "Portable application verified: $Output ($Bytes bytes uncompressed)"
