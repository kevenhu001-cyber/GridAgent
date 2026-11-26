# CI-only actual GUI startup check, separate from the private Python bridge smoke.
param([Parameter(Mandatory)][string]$PortableDirectory, [switch]$UiOnly)
$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$root = (Resolve-Path $PortableDirectory).Path
$exe = Join-Path $root "GridAgent.exe"
$started = Get-Date
$log = Join-Path $root "startup-diagnostics.log"
if (Test-Path $log) { Remove-Item $log -Force }
$oldDiagnostics = $env:GRIDAGENT_STARTUP_DIAGNOSTICS
$env:GRIDAGENT_STARTUP_DIAGNOSTICS = "1"
$process = $null
try {
    if ($UiOnly) {
        $process = Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList "--ui-smoke" -PassThru
    } else {
        $process = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
    }
    $null = $process.Handle
    $deadline = (Get-Date).AddSeconds(45)
    do {
        $process.Refresh()
        if ($process.HasExited) { throw "Portable GridAgent exited before its main window (exit $($process.ExitCode))." }
        if ($process.MainWindowHandle -ne [IntPtr]::Zero -and $process.Responding) {
            Start-Sleep -Seconds 3
            $process.Refresh()
            if ($process.HasExited -or $process.MainWindowHandle -eq [IntPtr]::Zero -or !$process.Responding) { throw "Portable GridAgent did not remain responsive." }
            if (!(Test-Path $log)) { throw "Missing managed startup diagnostics." }
            $stages = Get-Content $log -Raw
            foreach ($stage in @("application.initialize.complete", "window.xaml.complete", "window.construct.complete", "window.activate.complete", "window.loaded")) {
                if (!$stages.Contains($stage)) { throw "Missing startup milestone: $stage" }
            }
            if ($stages -match 'application.unhandled|application.initialize.failed|launch.failed') { throw "Managed startup exception recorded." }
            Write-Host "Portable GridAgent XAML loaded, window activated and remained responsive."
            return
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    throw "Portable GridAgent main window startup timed out."
} catch {
    if (Test-Path $log) {
        Write-Host "Portable WinUI startup stages:"
        Get-Content $log -Tail 80 | Write-Host
    } else { Write-Host "Process did not reach managed App diagnostics." }
    try {
        Get-WinEvent -FilterHashtable @{ LogName = "Application"; StartTime = $started } -MaxEvents 60 -ErrorAction Stop |
            Where-Object { $_.Message -match "GridAgent" } |
            Select-Object -First 8 TimeCreated, Id, ProviderName, Message | Format-List | Out-String | Write-Host
    } catch { Write-Host "No matching application events available." }
    throw
} finally {
    $env:GRIDAGENT_STARTUP_DIAGNOSTICS = $oldDiagnostics
    if ($process) {
        if (!$process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
        $process.Dispose()
    }
    if (Test-Path $log) { Remove-Item $log -Force }
}
