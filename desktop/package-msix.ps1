# Package the verified, self-contained WinUI portable layout without rebuilding the engine.
[CmdletBinding(DefaultParameterSetName="Development")]
param(
    [Parameter(Mandatory)][string]$PortableDirectory,
    [string]$OutputDirectory = "desktop-msix",
    [string]$Version = "1.0.0.0",
    [Parameter(Mandatory, ParameterSetName="Development")][switch]$Development,
    [Parameter(Mandatory, ParameterSetName="Production")][string]$CertificateThumbprint,
    [Parameter(Mandatory, ParameterSetName="Production")][string]$IdentityName,
    [string]$Python = "python",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
function Invoke-Checked([string]$Executable, [string[]]$Arguments) {
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$([IO.Path]::GetFileName($Executable)) failed ($LASTEXITCODE)" }
}
function Find-SdkTool([string]$Name) {
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $candidate = Get-ChildItem $kits -Directory | Where-Object { $_.Name -match '^10\.\d+\.\d+\.\d+$' } |
        Sort-Object { [version]$_.Name } -Descending |
        ForEach-Object { Join-Path $_.FullName "x64\$Name" } | Where-Object { Test-Path $_ -PathType Leaf } | Select-Object -First 1
    if (!$candidate) { throw "Windows SDK tool missing: $Name" }
    return $candidate
}
$parts = $Version.Split(".")
if ($parts.Count -ne 4 -or @($parts | Where-Object { $_ -notmatch '^\d{1,5}$' -or [int]$_ -gt 65535 }).Count -ne 0 -or [int]$parts[0] -eq 0) {
    throw "MSIX version must have four 16-bit components and a nonzero major version."
}
$source = (Resolve-Path $PortableDirectory).Path
$out = [IO.Path]::GetFullPath($OutputDirectory)
if (Test-Path $out) { throw "Output directory already exists: $out" }
if ($out.StartsWith($source.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Output must be outside the portable layout." }
foreach ($file in @("GridAgent.exe", "runtime\python.exe", "runtime\python311._pth", "runtime-manifest.json", "Microsoft.UI.Xaml.dll")) {
    if (!(Test-Path (Join-Path $source $file) -PathType Leaf)) { throw "Verified WinUI portable layout missing $file" }
}
# A manually wrapped MSIX uses the package-root resources.pri as the default resource map.
# Never substitute the SDK framework's PRI for the application's own resources.
$appPri = @("resources.pri", "GridAgent.pri") | Where-Object { Test-Path (Join-Path $source $_) -PathType Leaf } | Select-Object -First 1
if (!$appPri) { throw "Portable WinUI application PRI missing; refusing MSIX packaging." }
$makeappx = Find-SdkTool "makeappx.exe"
$signtool = Find-SdkTool "signtool.exe"
New-Item -ItemType Directory $out | Out-Null
$stage = Join-Path ([IO.Path]::GetTempPath()) ("GridAgent-msix-" + [guid]::NewGuid().ToString("N"))
$cert = $null
try {
    New-Item -ItemType Directory $stage | Out-Null
    & robocopy $source $stage /E /XD __pycache__ /XF "*.pyc" /NFL /NDL /NJH /NJS /NP
    if ($LASTEXITCODE -ge 8) { throw "Staging failed ($LASTEXITCODE)" }
    if (!(Test-Path (Join-Path $stage "resources.pri") -PathType Leaf)) {
        Copy-Item (Join-Path $stage $appPri) (Join-Path $stage "resources.pri")
    }
    # Do not ship the portable-only command launcher as an app entry point.
    Remove-Item (Join-Path $stage "gridagent-tui.cmd") -ErrorAction SilentlyContinue
    if ($Development) {
        $IdentityName = "GridAgent.Development"
        $cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject "CN=TopoDrive Development" -CertStoreLocation "Cert:\CurrentUser\My" -KeyAlgorithm RSA -KeyLength 2048 -HashAlgorithm SHA256 -NotAfter (Get-Date).AddDays(30)
        Export-Certificate -Cert $cert -FilePath (Join-Path $out "GridAgent-Development.cer") | Out-Null
    } else {
        if ($IdentityName -eq "GridAgent.Development") { throw "Use a separate production package identity." }
        $cert = Get-Item ("Cert:\CurrentUser\My\" + $CertificateThumbprint)
        if (!$cert.HasPrivateKey) { throw "Signing certificate has no accessible private key." }
    }
    [xml]$manifest = Get-Content (Join-Path $PSScriptRoot "msix\AppxManifest.xml") -Raw
    $manifest.Package.Identity.Name = $IdentityName
    $manifest.Package.Identity.Publisher = $cert.Subject
    $manifest.Package.Identity.Version = $Version
    if (!$Development) {
        $manifest.Package.Properties.DisplayName = "GridAgent"
        $manifest.Package.Applications.Application.VisualElements.DisplayName = "GridAgent"
    }
    $manifest.Save((Join-Path $stage "AppxManifest.xml"))
    $brand = Join-Path $stage "BrandAssets"
    $msixAssets = Join-Path $stage "MsixAssets"
    New-Item -ItemType Directory -Force $msixAssets | Out-Null
    foreach ($name in @("StoreLogo.png", "Square44x44Logo.png", "Square150x150Logo.png")) {
        Copy-Item (Join-Path $brand $name) $msixAssets
    }
    Copy-Item (Join-Path $brand "GridAgent-logo.png") (Join-Path $out "GridAgent-logo.png")
    $suffix = if ($Development) { "-Development" } else { "" }
    $package = Join-Path $out "GridAgent-$Version-x64$suffix.msix"
    Invoke-Checked $makeappx @("pack", "/d", $stage, "/p", $package, "/o", "/h", "SHA256")
    $sign = @("sign", "/fd", "SHA256", "/s", "My", "/sha1", $cert.Thumbprint)
    if (!$Development) { $sign += @("/tr", $TimestampUrl, "/td", "SHA256") }
    Invoke-Checked $signtool ($sign + @($package))
    # Development certificate is intentionally not installed into a trust store here.
    $hash = (Get-FileHash $package -Algorithm SHA256).Hash
    "$hash  $([IO.Path]::GetFileName($package))" | Set-Content -Encoding ascii (Join-Path $out "SHA256SUMS.txt")
    $meta = @{ identity = $IdentityName; developer = "TopoDrive"; lead_developer = "Adex Hu"; publisher = $cert.Subject; version = $Version; architecture = "x64"; development = [bool]$Development; certificate_thumbprint = $cert.Thumbprint; bytes = (Get-Item $package).Length }
    $meta | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $out "package-info.json")
    Invoke-Checked $Python @((Join-Path $PSScriptRoot "msix\make-install-guide.py"), $out)
    Write-Host "MSIX built and signed: $package ($($meta.bytes) bytes)"
} finally {
    if ($Development -and $null -ne $cert) { Remove-Item ("Cert:\CurrentUser\My\" + $cert.Thumbprint) -ErrorAction SilentlyContinue }
    if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
}
