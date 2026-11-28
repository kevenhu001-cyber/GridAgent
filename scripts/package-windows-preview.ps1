# Build the retained Tauri app with the production resource-bound Pi runtime.
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$vendor = Join-Path $root 'vendor/proliferate'
$tauri = Join-Path $vendor 'apps/desktop/src-tauri'
$target = 'x86_64-pc-windows-msvc'
$out = Join-Path $root 'dist/windows-preview'
$version = (& python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])").Trim()
if ($version -notmatch '^\d+\.\d+\.\d+$') { throw "Expected a numeric GridAgent version, got $version" }
if ($env:GITHUB_REF_TYPE -eq 'tag' -and $env:GITHUB_REF_NAME -ne "v$version") { throw 'Tag/version mismatch' }

# Keep the existing test build and UI untouched. Apply product packaging identity
# only to this disposable CI checkout. The upstream updater is intentionally disabled.
$configPath = Join-Path $tauri 'tauri.conf.json'
$config = Get-Content $configPath -Raw | ConvertFrom-Json -AsHashtable
$config.productName = 'GridAgent'
$config.identifier = 'com.topodrive.gridagent'
$config.version = $version
$config.app.windows[0].title = 'GridAgent'
$config.bundle.publisher = 'TopoDrive'
$config.bundle.targets = @('msi', 'nsis')
$config.bundle.createUpdaterArtifacts = $false
$config.bundle.resources += 'gridagent-runtime/'
$env:GRIDAGENT_PACKAGED_BUILD = '1'
$config.plugins.updater.endpoints = @()
# Avoid registering the upstream application's deep-link protocol.
$config.plugins['deep-link'].desktop.schemes = @('gridagent')
$originalConfig = Get-Content $configPath -Raw
try {
    & (Join-Path $PSScriptRoot 'stage-windows-runtime.ps1') -Destination (Join-Path $tauri 'gridagent-runtime')
    $config | ConvertTo-Json -Depth 100 | Set-Content -Path $configPath -Encoding utf8
    $env:CARGO_TARGET_DIR = Join-Path $vendor 'target'
    $release = Join-Path $env:CARGO_TARGET_DIR "$target/release"

    Push-Location $vendor
    try {
        pnpm install --frozen-lockfile
        cargo build --locked --release --target $target -p anyharness -p proliferate-worker -p proliferate-debug
        $sidecars = @{
            ANYHARNESS_BIN = 'anyharness.exe'
            PROLIFERATE_WORKER_BIN = 'proliferate-worker.exe'
            PROLIFERATE_DEBUG_BIN = 'proliferate-debug.exe'
        }
        foreach ($key in $sidecars.Keys) {
            $binary = Join-Path $release $sidecars[$key]
            if (!(Test-Path $binary -PathType Leaf) -or (Get-Item $binary).Length -lt 1024) { throw "Missing real sidecar: $binary" }
            [Environment]::SetEnvironmentVariable($key, $binary, 'Process')
        }
        # The upstream collector is explicitly unsupported on Windows; its
        # build script stages the supported placeholder. Supply the fourth
        # explicit input to force real staging of the other three binaries.
        $placeholder = Join-Path $release 'windows-unsupported-collector.txt'
        Set-Content -Path $placeholder -Value 'Windows diagnostics collector unavailable' -Encoding ascii
        $env:PROLIFERATE_DIAGNOSTICS_COLLECTOR_BIN = $placeholder
        New-Item -ItemType Directory -Force (Join-Path $tauri 'agent-seeds') | Out-Null
        pnpm --filter proliferate tauri build --target $target --bundles msi,nsis
        git diff --exit-code -- Cargo.lock pnpm-lock.yaml
    } finally { Pop-Location }

    $bundle = Join-Path $release 'bundle'
    $msi = @(Get-ChildItem (Join-Path $bundle 'msi') -Filter '*.msi' -File)
    $exe = @(Get-ChildItem (Join-Path $bundle 'nsis') -Filter '*.exe' -File)
    if ($msi.Count -ne 1 -or $exe.Count -ne 1) { throw 'Expected exactly one MSI and one NSIS installer' }
    if (($msi[0].Length -lt 1024) -or ($exe[0].Length -lt 1024)) { throw 'Empty or invalid installer output' }
    if (Test-Path $out) { Remove-Item $out -Recurse -Force }
    New-Item -ItemType Directory -Force $out | Out-Null
    Copy-Item $msi[0].FullName (Join-Path $out "GridAgent-$version-windows-x64-preview.msi")
    Copy-Item $exe[0].FullName (Join-Path $out "GridAgent-$version-windows-x64-preview-setup.exe")
    $checksums = Get-ChildItem $out -File | Sort-Object Name | ForEach-Object {
        "$((Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant())  $($_.Name)"
    }
    $checksums | Set-Content (Join-Path $out 'SHA256SUMS.txt') -Encoding ascii
    Write-Host 'Created unsigned installer preview with bundled Node, Pi and Python runtime.'
} finally {
    Set-Content -Path $configPath -Value $originalConfig -Encoding utf8 -NoNewline
}
