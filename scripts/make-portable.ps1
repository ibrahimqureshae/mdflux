# Build MDFlux and package it as a portable, extract-and-run zip (no installer).
# The zip contains app.exe + resources/ (the Python sidecar). On first launch the app
# downloads uv + Python + deps to %APPDATA% — same online-provisioning model as the installer.
#
# Usage:  pwsh -File scripts\make-portable.ps1            # build + zip
#         pwsh -File scripts\make-portable.ps1 -NoBuild   # zip the existing release build

param([switch]$NoBuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$rel  = Join-Path $root "app\src-tauri\target\release"
$dist = Join-Path $root "dist"

if (-not $NoBuild) {
    # --no-bundle: compile app.exe + stage resources, but DO NOT build an installer.
    # MDFlux ships as a portable, extract-and-run zip — no NSIS installer.
    Push-Location (Join-Path $root "app")
    try { npm run tauri build -- --no-bundle } finally { Pop-Location }
}

$exe = Join-Path $rel "app.exe"
$res = Join-Path $rel "resources"
if (-not (Test-Path $exe)) { throw "Release build not found at $exe. Run without -NoBuild first." }

# Read version from tauri.conf.json for the zip name.
$conf = Get-Content (Join-Path $root "app\src-tauri\tauri.conf.json") -Raw | ConvertFrom-Json
$version = $conf.version

New-Item -ItemType Directory -Force -Path $dist | Out-Null
$zip = Join-Path $dist "MDFlux_${version}_portable.zip"
if (Test-Path $zip) { Remove-Item $zip -Force }

# Stage the payload so the shipped executable is MDFlux.exe (the build output is app.exe
# because the Rust crate is named "app"; users are told to run MDFlux.exe).
$stage = Join-Path $dist "_portable_stage"
if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $stage | Out-Null
Copy-Item $exe (Join-Path $stage "MDFlux.exe")
Copy-Item $res -Destination $stage -Recurse

Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
Remove-Item $stage -Recurse -Force
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 2)
Write-Host "Portable build: $zip ($mb MB)  (executable: MDFlux.exe)"
