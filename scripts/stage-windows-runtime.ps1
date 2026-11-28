# Stage a relocatable CPython 3.11 + locked Pi SDK from the CI toolchain.
param([Parameter(Mandatory=$true)][string]$Destination)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Destination = [IO.Path]::GetFullPath($Destination)
if (Test-Path $Destination) { Remove-Item $Destination -Recurse -Force }
$python = Join-Path $Destination 'python'
$node = Join-Path $Destination 'node'
$pi = Join-Path $Destination 'pi'
New-Item -ItemType Directory -Force $python,$node,$pi | Out-Null
$base = (& python -c "import sys; assert sys.version_info[:2]==(3,11); print(sys.base_prefix)").Trim()
# Only runtime files: no host registry, venv, installed packages or absolute scripts.
Get-ChildItem $base -File | Where-Object { $_.Extension -in '.exe','.dll','.txt' } | Copy-Item -Destination $python
Copy-Item (Join-Path $base 'DLLs') $python -Recurse
New-Item -ItemType Directory -Force (Join-Path $python 'Lib') | Out-Null
Get-ChildItem (Join-Path $base 'Lib') -Force | Where-Object { $_.Name -notin 'site-packages','test','__pycache__' } | Copy-Item -Destination (Join-Path $python 'Lib') -Recurse
$site = Join-Path $python 'Lib/site-packages'
New-Item -ItemType Directory -Force $site | Out-Null
# A relative ._pth is required by the existing Windows Sandbox runtime check.
@('.', 'DLLs', 'Lib', 'Lib/site-packages', 'import site') | Set-Content (Join-Path $python 'python311._pth') -Encoding ascii
Push-Location $repo
try {
    python -m pip install --disable-pip-version-check --no-compile --target $site '.[core]'
} finally { Pop-Location }
Copy-Item (Get-Command node.exe -CommandType Application).Source (Join-Path $node 'node.exe')
$source = Join-Path $repo 'integration/pi-runtime'
Get-ChildItem $source -File | Where-Object { $_.Name -in 'package.json','package-lock.json','smoke_install.py' -or ($_.Extension -eq '.mjs' -and $_.Name -notmatch '\.test\.mjs$') } | Copy-Item -Destination $pi
Push-Location $pi
try { npm ci --omit=dev --ignore-scripts --no-audit --no-fund } finally { Pop-Location }
# Prove both runtimes resolve from a relocated copy with no developer PATH.
$relocated = Join-Path $env:RUNNER_TEMP 'GridAgent runtime relocation smoke'
if (Test-Path $relocated) { Remove-Item $relocated -Recurse -Force }
Copy-Item $Destination $relocated -Recurse
$originalPath = $env:PATH
try {
    $env:PATH = "$(Join-Path $relocated 'node');$env:SystemRoot\System32;$env:SystemRoot"
    $embedded = Join-Path $relocated 'python/python.exe'
    & $embedded -I -B -c "import gridagent.native_service,numpy,scipy,pandas,andes,pandapower,highspy,control,sympy; import sys; print(sys.executable)"
    & $embedded -I -B (Join-Path $relocated 'pi/smoke_install.py')
} finally {
    $env:PATH = $originalPath
    Remove-Item $relocated -Recurse -Force
}
