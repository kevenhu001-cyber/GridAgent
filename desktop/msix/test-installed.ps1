# Run only on a disposable Windows test machine, not a user's workstation.
param([Parameter(Mandatory)][string]$PackageDirectory, [Parameter(Mandatory)][switch]$DisposableTestMachine)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$directory = (Resolve-Path $PackageDirectory).Path
$info = Get-Content (Join-Path $directory "package-info.json") -Raw | ConvertFrom-Json
if (!$DisposableTestMachine -or !$info.development -or $info.identity -ne "GridAgent.Development") { throw "Development package and explicit disposable-test approval required." }
if (Get-AppxPackage -Name $info.identity) { throw "Existing development package found; refusing to overwrite it." }
$certFile = Join-Path $directory "GridAgent-Development.cer"
$certificate = [System.Security.Cryptography.X509Certificates.X509Certificate2]::new($certFile)
if ($certificate.Thumbprint -ne $info.certificate_thumbprint -or $certificate.Subject -ne $info.publisher) { throw "Certificate metadata mismatch." }
$package = @(Get-ChildItem $directory -Filter "*.msix" -File)
if ($package.Count -ne 1) { throw "Expected exactly one development MSIX." }
$trustPath = "Cert:\LocalMachine\TrustedPeople\" + $certificate.Thumbprint
if (Test-Path $trustPath) { throw "Test certificate already trusted; refusing to alter existing trust." }
$installed = $null
$appProcessId = 0
$appProcess = $null
$activationStarted = $null
try {
    Import-Certificate -FilePath $certFile -CertStoreLocation "Cert:\LocalMachine\TrustedPeople" | Out-Null
    Add-AppxPackage -Path $package[0].FullName -ErrorAction Stop
    $installed = Get-AppxPackage -Name $info.identity
    if (!$installed -or $installed.Publisher -ne $info.publisher -or $installed.Version.ToString() -ne $info.version) { throw "Installed package identity mismatch." }
    $marker = Join-Path $env:LOCALAPPDATA ("Packages\" + $installed.PackageFamilyName + "\LocalState\msix-smoke.json")
    if (Test-Path $marker) { throw "Unexpected existing smoke marker." }
    Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
[ComImport, Guid("2E941141-7F97-4756-BA1D-9DECDE894A3D"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
public interface IApplicationActivationManager
{
    [PreserveSig] int ActivateApplication([MarshalAs(UnmanagedType.LPWStr)] string appUserModelId,
        [MarshalAs(UnmanagedType.LPWStr)] string arguments, uint options, out uint processId);
    [PreserveSig] int ActivateForFile(IntPtr app, IntPtr items, IntPtr verb, out uint processId);
    [PreserveSig] int ActivateForProtocol(IntPtr app, IntPtr items, out uint processId);
}
public static class GridAgentActivation
{
    public static uint Launch(string id)
    {
        var clsid = new Guid("45BA127D-10A8-46EA-8AB7-56EA9078943C");
        var manager = (IApplicationActivationManager)Activator.CreateInstance(Type.GetTypeFromCLSID(clsid));
        uint pid;
        int hr = manager.ActivateApplication(id, "--msix-smoke", 0, out pid);
        Marshal.ThrowExceptionForHR(hr);
        return pid;
    }
}
'@
    $activationStarted = Get-Date
    $appProcessId = [GridAgentActivation]::Launch($installed.PackageFamilyName + "!GridAgent")
    Write-Host "Activated packaged GridAgent PID $appProcessId"
    $appProcess = Get-Process -Id $appProcessId -ErrorAction SilentlyContinue
    $deadline = (Get-Date).AddMinutes(8)
    while (!(Test-Path $marker) -and (Get-Date) -lt $deadline) {
        if (!$appProcess -or $appProcess.HasExited) {
            # The marker is published atomically by the app. Recheck after exit
            # to avoid misclassifying an app that just finished writing it.
            if (Test-Path $marker) { break }
            $exitCode = if ($appProcess) { $appProcess.ExitCode } else { "unavailable" }
            throw "Packaged GridAgent terminated before its smoke result (PID $appProcessId, exit code $exitCode)."
        }
        Start-Sleep -Seconds 2
    }
    if (!(Test-Path $marker)) { throw "Packaged application smoke timed out." }
    $result = Get-Content $marker -Raw | ConvertFrom-Json
    $result | ConvertTo-Json | Write-Host
    if (!$result.success) { throw "Packaged application smoke failed at $($result.stage): $($result.error)" }
    Write-Host "Installed MSIX activated; private Python, resident metadata, AC solver and plugin lifecycle passed."
} catch {
    if ($activationStarted) {
        # CI-only diagnostics: bounded recent crash/activation events, before uninstall.
        foreach ($log in @("Application", "Microsoft-Windows-AppModel-Runtime/Admin", "Microsoft-Windows-TWinUI/Operational")) {
            try {
                Get-WinEvent -FilterHashtable @{ LogName = $log; StartTime = $activationStarted } -MaxEvents 60 -ErrorAction Stop |
                    Where-Object { $_.Message -match "GridAgent|$appProcessId" } |
                    Select-Object -First 8 TimeCreated, Id, ProviderName, Message | Format-List | Out-String | Write-Host
            } catch { Write-Host "No matching diagnostic events available from $log." }
        }
    }
    throw
} finally {
    if ($appProcess) { $appProcess.Dispose() }
    if ($appProcessId -gt 0) { Stop-Process -Id $appProcessId -Force -ErrorAction SilentlyContinue }
    if ($installed) { Remove-AppxPackage -Package $installed.PackageFullName -ErrorAction Continue }
    if (Test-Path $trustPath) { Remove-Item $trustPath -ErrorAction Continue }
}
