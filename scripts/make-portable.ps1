# Build the Windows Lite portable archive (first-run runtime provisioning).
param([switch]$NoBuild)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows\portable-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$tauriDir = Join-Path $root "app\src-tauri"
$releaseDir = Join-Path $tauriDir "target\release"
$dist = Join-Path $root "dist"
$fullLock = Join-Path $tauriDir "resources\sidecar\requirements-full.lock"

if (-not $NoBuild) {
    Push-Location (Join-Path $root "app")
    try { npm run tauri build -- --no-bundle; if ($LASTEXITCODE -ne 0) { throw "Application build failed." } } finally { Pop-Location }
}

$exe = Join-Path $releaseDir "app.exe"
$resources = Join-Path $releaseDir "resources"
if (-not (Test-Path -LiteralPath $exe)) { throw "Release build not found at $exe. Run without -NoBuild first." }
if (-not (Test-Path -LiteralPath $resources)) { throw "Release resources not found at $resources." }
$metadata = Get-MDFluxBuildMetadata -RepositoryRoot $root -TauriDirectory $tauriDir -FullLock $fullLock

New-Item -ItemType Directory -Force -Path $dist | Out-Null
$stage = Assert-SafeStagePath -DistDirectory $dist -StageDirectory (Join-Path $dist "_portable_lite_stage")
$zip = Join-Path $dist "MDFlux_$($metadata.Version)_windows_x64_lite.zip"
Remove-SafeStageDirectory -DistDirectory $dist -StageDirectory $stage
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
try {
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Copy-Item -LiteralPath $exe -Destination (Join-Path $stage "MDFlux.exe")
    Copy-Item -LiteralPath $resources -Destination $stage -Recurse
    $runtime = Join-Path $stage "resources\runtime"
    if (Test-Path -LiteralPath $runtime) { Remove-Item -LiteralPath $runtime -Recurse -Force }
    Write-EditionManifest -ResourcesDirectory (Join-Path $stage "resources") -Edition "lite" -Metadata $metadata -PythonVersion $null
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
    Test-WindowsPortableArchive -Zip $zip -DistDirectory $dist -Edition "lite"
} finally {
    Remove-SafeStageDirectory -DistDirectory $dist -StageDirectory $stage
}
$mb = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 2)
Write-Host "Lite portable build: $zip ($mb MB)"
