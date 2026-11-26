# Verify the resource-map content produced by the SDK before GUI startup.
param([Parameter(Mandatory)][string]$Directory)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$root = (Resolve-Path $Directory).Path
$kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
$makepri = Get-ChildItem $kits -Directory | Where-Object { $_.Name -match '^10\.\d+\.\d+\.\d+$' } |
    Sort-Object { [version]$_.Name } -Descending |
    ForEach-Object { Join-Path $_.FullName "x64\makepri.exe" } |
    Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
if (!$makepri) { throw "Windows SDK MakePRI not found." }
$dump = Join-Path ([IO.Path]::GetTempPath()) ("GridAgent-pri-" + [guid]::NewGuid().ToString("N") + ".xml")
try {
    $pri = Join-Path $root "resources.pri"
    if (!(Test-Path $pri -PathType Leaf)) {
        $pri = Join-Path $root "GridAgent.pri"
        if (!(Test-Path $pri -PathType Leaf)) { throw "No application PRI in portable publish." }
    }
    & $makepri dump /if $pri /of $dump /o
    if ($LASTEXITCODE -ne 0) { throw "MakePRI dump failed ($LASTEXITCODE)." }
    [xml]$xml = Get-Content $dump -Raw
    $maps = @($xml.SelectNodes("/*[local-name()='PriInfo']/*[local-name()='ResourceMap']") | ForEach-Object { $_.GetAttribute("name") })
    Write-Host "Portable PRI $([IO.Path]::GetFileName($pri)); maps: $($maps -join ', ')"
    if ($maps -notcontains "Application") { throw "Unpackaged PRI must include the Application root resource map." }
    # MRT Core can use the root resources.pri in unpackaged applications. Publish the
    # verified index under that name, not a blindly renamed framework or package PRI.
    if (!(Test-Path (Join-Path $root "resources.pri") -PathType Leaf)) {
        Copy-Item $pri (Join-Path $root "resources.pri")
    }
    foreach ($name in @("App.xbf", "MainWindow.xbf", "Microsoft.UI.Xaml.dll")) {
        if (!(Test-Path (Join-Path $root $name) -PathType Leaf)) { throw "Missing WinUI payload: $name" }
    }
} finally {
    if (Test-Path $dump) { Remove-Item $dump -Force }
}
