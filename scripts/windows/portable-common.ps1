Set-StrictMode -Version Latest

function Assert-SafeStagePath {
    param([Parameter(Mandatory = $true)][string]$DistDirectory, [Parameter(Mandatory = $true)][string]$StageDirectory)
    $distFull = [IO.Path]::GetFullPath($DistDirectory).TrimEnd('\')
    $stageFull = [IO.Path]::GetFullPath($StageDirectory).TrimEnd('\')
    if (-not $stageFull.StartsWith($distFull + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "Unsafe staging path: $stageFull is not beneath $distFull" }
    if ([IO.Path]::GetDirectoryName($stageFull) -ne $distFull) { throw "Unsafe staging path: $stageFull must be a direct child of $distFull" }
    return $stageFull
}

function Remove-SafeStageDirectory {
    param([Parameter(Mandatory = $true)][string]$DistDirectory, [Parameter(Mandatory = $true)][string]$StageDirectory)
    $safeStage = Assert-SafeStagePath -DistDirectory $DistDirectory -StageDirectory $StageDirectory
    if (Test-Path -LiteralPath $safeStage) { Remove-Item -LiteralPath $safeStage -Recurse -Force }
}

function Get-MDFluxBuildMetadata {
    param([Parameter(Mandatory = $true)][string]$RepositoryRoot, [Parameter(Mandatory = $true)][string]$TauriDirectory, [Parameter(Mandatory = $true)][string]$FullLock)
    if (-not (Test-Path -LiteralPath $FullLock)) { throw "Canonical dependency lock is missing: $FullLock" }
    $config = Get-Content -LiteralPath (Join-Path $TauriDirectory "tauri.conf.json") -Raw | ConvertFrom-Json
    $commit = (& git -C $RepositoryRoot rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') { throw "Could not determine the source commit for edition.json." }
    return [ordered]@{ Version = $config.version; Commit = $commit; LockSha256 = (Get-FileHash -LiteralPath $FullLock -Algorithm SHA256).Hash.ToLowerInvariant() }
}

function Write-EditionManifest {
    param([Parameter(Mandatory = $true)][string]$ResourcesDirectory, [Parameter(Mandatory = $true)][ValidateSet("lite", "full")][string]$Edition, [Parameter(Mandatory = $true)][System.Collections.IDictionary]$Metadata, [AllowNull()][string]$PythonVersion)
    $components = @("core")
    if ($Edition -eq "full") { $components = @("core", "ocr", "audio-runtime") }
    $manifest = [ordered]@{ schema = 1; edition = $Edition; app_version = $Metadata.Version; commit = $Metadata.Commit; platform = "windows-x64"; python_version = $PythonVersion; components = $components; dependency_lock_sha256 = $Metadata.LockSha256; built_at_utc = [DateTime]::UtcNow.ToString("o") }
    if ($Edition -eq "lite") { $manifest.python_version = $null }
    $json = $manifest | ConvertTo-Json -Depth 3
    [IO.File]::WriteAllText((Join-Path $ResourcesDirectory "edition.json"), $json + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}

function Test-WindowsPortableArchive {
    param([Parameter(Mandatory = $true)][string]$Zip, [Parameter(Mandatory = $true)][string]$DistDirectory, [Parameter(Mandatory = $true)][ValidateSet("lite", "full")][string]$Edition)
    $inspection = Join-Path $DistDirectory ("_portable_{0}_inspection" -f $Edition)
    Remove-SafeStageDirectory -DistDirectory $DistDirectory -StageDirectory $inspection
    try {
        Expand-Archive -LiteralPath $Zip -DestinationPath $inspection -Force
        if (-not (Test-Path -LiteralPath (Join-Path $inspection "MDFlux.exe"))) { throw "Archive is missing MDFlux.exe" }
        $resources = Join-Path $inspection "resources"
        $manifestPath = Join-Path $resources "edition.json"
        if (-not (Test-Path -LiteralPath $manifestPath)) { throw "Archive is missing resources\\edition.json" }
        $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
        if ($manifest.schema -ne 1 -or $manifest.edition -ne $Edition -or $manifest.platform -ne "windows-x64") { throw "Archive manifest does not match the defined Windows $Edition contract." }
        $runtime = Join-Path $resources "runtime"
        if ($Edition -eq "lite") {
            if (Test-Path -LiteralPath $runtime) { throw "Lite archive unexpectedly contains resources\\runtime" }
        } else {
            $python = Join-Path $runtime "python.exe"
            if (-not (Test-Path -LiteralPath $python)) { throw "Full archive is missing resources\\runtime\\python.exe" }
            Invoke-PackagedSidecarHealth -Python $python -SidecarDirectory (Join-Path $resources "sidecar")
        }
    } finally {
        Remove-SafeStageDirectory -DistDirectory $DistDirectory -StageDirectory $inspection
    }
}

function Invoke-PackagedSidecarHealth {
    param([Parameter(Mandatory = $true)][string]$Python, [Parameter(Mandatory = $true)][string]$SidecarDirectory)
    $main = Join-Path $SidecarDirectory "main.py"
    if (-not (Test-Path -LiteralPath $main)) { throw "Packaged sidecar entry point is missing: $main" }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $Python
    # Match the application launch path: execute the sidecar entry point directly so
    # its directory is available for sibling imports such as capabilities.py.
    $start.Arguments = "`"$main`""
    $start.WorkingDirectory = $SidecarDirectory
    $start.UseShellExecute = $false
    $start.RedirectStandardInput = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $start
    [void]$process.Start()
    $process.StandardInput.WriteLine('{"v":1,"id":"packaging-health","method":"health","params":{}}')
    $process.StandardInput.Close()
    $stdout = $process.StandardOutput.ReadToEnd()
    $stderr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    if ($process.ExitCode -ne 0) { throw "Packaged sidecar health process failed ($($process.ExitCode)): $stderr" }
    $response = $stdout.Trim() | ConvertFrom-Json
    if (-not $response.ok -or $response.id -ne "packaging-health") { throw "Packaged sidecar health check returned an invalid response: $stdout" }
}
