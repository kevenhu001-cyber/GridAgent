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
    $deadline = (Get-Date).AddSeconds($(if ($UiOnly) { 100 } else { 45 }))
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
            if ($stages -match 'application.unhandled|application.initialize.failed|launch.failed|ui.smoke.failed') { throw "Managed UI exception recorded." }
            if ($UiOnly) {
                if (!$stages.Contains("ui.smoke.complete")) { continue }
                foreach ($page in @("chat", "tasks", "models", "runs", "studies", "tools", "plugins", "knowledge", "settings")) {
                    if (!$stages.Contains("ui.page.$page")) { throw "Missing native page smoke milestone: $page" }
                }
                foreach ($view in @("chart", "heatmap", "surface", "topology", "table")) {
                    if (!$stages.Contains("ui.viewer.$view")) { throw "Missing scientific viewer milestone: $view" }
                }
                $snapshots = @(Get-ChildItem (Join-Path $root "ui-snapshots") -Filter "*.png" -File -ErrorAction SilentlyContinue | Where-Object Length -gt 0)
                Write-Host "Native page and scientific viewer smoke passed; captured $($snapshots.Count) XAML snapshots."
                if ($snapshots.Count -eq 0) { Write-Warning "Snapshot readback unavailable; visual review remains pending." }
            }
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
