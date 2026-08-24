# Build the Windows Full portable archive with an immutable bundled Python runtime.
param([switch]$NoBuild, [string]$UvPath = "")

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows\portable-common.ps1")
$root = Split-Path -Parent $PSScriptRoot
$appDir = Join-Path $root "app"
$tauriDir = Join-Path $appDir "src-tauri"
$sidecarDir = Join-Path $tauriDir "resources\sidecar"
$releaseDir = Join-Path $tauriDir "target\release"
$distDir = Join-Path $root "dist"
$fullLock = Join-Path $sidecarDir "requirements-full.lock"

if (-not $NoBuild) {
    Push-Location $appDir
    try { npm run tauri build -- --no-bundle; if ($LASTEXITCODE -ne 0) { throw "Application build failed." } } finally { Pop-Location }
}

$exe = Join-Path $releaseDir "app.exe"
$resources = Join-Path $releaseDir "resources"
if (-not (Test-Path -LiteralPath $exe)) { throw "Release executable not found at $exe" }
if (-not (Test-Path -LiteralPath $resources)) { throw "Release resources not found at $resources" }
if (-not $UvPath) { $uvCommand = Get-Command uv -ErrorAction SilentlyContinue; if ($uvCommand) { $UvPath = $uvCommand.Source } }
if (-not $UvPath -or -not (Test-Path -LiteralPath $UvPath)) { throw "uv was not found. Install uv or pass -UvPath C:\\path\\to\\uv.exe" }

$managedPython = (& $UvPath python find --managed-python 3.12).Trim()
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $managedPython)) {
    & $UvPath python install 3.12
    if ($LASTEXITCODE -ne 0) { throw "Python 3.12 installation for the Full runtime failed." }
    $managedPython = (& $UvPath python find --managed-python 3.12).Trim()
}
if (-not (Test-Path -LiteralPath $managedPython)) { throw "A managed Python 3.12 runtime could not be located after installation." }
$pythonRoot = Split-Path -Parent $managedPython
$metadata = Get-MDFluxBuildMetadata -RepositoryRoot $root -TauriDirectory $tauriDir -FullLock $fullLock

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
$stage = Assert-SafeStagePath -DistDirectory $distDir -StageDirectory (Join-Path $distDir "_portable_full_stage")
$zip = Join-Path $distDir "MDFlux_$($metadata.Version)_windows_x64_full.zip"
Remove-SafeStageDirectory -DistDirectory $distDir -StageDirectory $stage
if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
try {
    New-Item -ItemType Directory -Force -Path $stage | Out-Null
    Copy-Item -LiteralPath $exe -Destination (Join-Path $stage "MDFlux.exe")
    Copy-Item -LiteralPath $resources -Destination $stage -Recurse
    $stagedSidecar = Join-Path $stage "resources\sidecar"
    if (Test-Path -LiteralPath $stagedSidecar) {
        Remove-Item -LiteralPath $stagedSidecar -Recurse -Force
    }
    Copy-Item -LiteralPath $sidecarDir -Destination (Join-Path $stage "resources") -Recurse
    $runtime = Join-Path $stage "resources\runtime"
    New-Item -ItemType Directory -Force -Path $runtime | Out-Null
    Copy-Item -Path (Join-Path $pythonRoot '*') -Destination $runtime -Recurse -Force
    $runtimePython = Join-Path $runtime "python.exe"
    if (-not (Test-Path -LiteralPath $runtimePython)) { throw "Bundled Python executable was not created." }
    $oldLinkMode = $env:UV_LINK_MODE
    $env:UV_LINK_MODE = "copy"
    try {
        & $UvPath pip install --python $runtimePython --system --break-system-packages --require-hashes -r $fullLock
        if ($LASTEXITCODE -ne 0) { throw "Bundled dependency installation failed." }
    } finally { $env:UV_LINK_MODE = $oldLinkMode }
    & $runtimePython -I -c "import markitdown, openai, httpx, rapidocr, onnxruntime, pypdfium2, faster_whisper, ctranslate2; print('bundled runtime imports: OK')"
    if ($LASTEXITCODE -ne 0) { throw "Bundled runtime smoke test failed." }
    $pythonVersion = (& $runtimePython -I -c "import platform; print(platform.python_version())").Trim()
    if ($pythonVersion -notmatch '^3\.12\.') { throw "Bundled runtime must be Python 3.12; found $pythonVersion" }
    Write-EditionManifest -ResourcesDirectory (Join-Path $stage "resources") -Edition "full" -Metadata $metadata -PythonVersion $pythonVersion
    Compress-Archive -Path (Join-Path $stage '*') -DestinationPath $zip -CompressionLevel Optimal
    Test-WindowsPortableArchive -Zip $zip -DistDirectory $distDir -Edition "full"
} finally {
    Remove-SafeStageDirectory -DistDirectory $distDir -StageDirectory $stage
}
$size = [math]::Round((Get-Item -LiteralPath $zip).Length / 1MB, 1)
Write-Host "Full portable build: $zip ($size MB)"
