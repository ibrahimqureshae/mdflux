use std::fs;
use std::path::{Path, PathBuf};
use tauri::{AppHandle, Emitter, Manager};

use crate::ipc::{DownloadDetail, ProgressPayload};

// ── Platform constants ─────────────────────────────────────────────────────

#[cfg(target_os = "windows")]
mod platform {
    pub const UV_URL: &str = "https://github.com/astral-sh/uv/releases/download/0.5.11/uv-x86_64-pc-windows-msvc.zip";
    pub const UV_SHA256: &str = "3e8203e6434b45427f20824419f8d8d53f970a76d94ccdcad07f8498fa01a9d0";
    pub const UV_ARCHIVE: &str = "uv.zip";
    pub const UV_BIN: &str = "uv.exe";
    pub const PYTHON_BIN: &str = "Scripts/python.exe";
    pub const UV_LABEL: &str = "uv 0.5.11 — Python package manager (Windows x64)";
}

#[cfg(all(target_os = "macos", target_arch = "aarch64"))]
mod platform {
    pub const UV_URL: &str = "https://github.com/astral-sh/uv/releases/download/0.5.11/uv-aarch64-apple-darwin.tar.gz";
    pub const UV_SHA256: &str = "695f3640d5b1a4e28de7e36e3a2e14072852dcc6c70bf9e4deec6ada00d516b4";
    pub const UV_ARCHIVE: &str = "uv.tar.gz";
    pub const UV_BIN: &str = "uv";
    pub const PYTHON_BIN: &str = "bin/python";
    pub const UV_LABEL: &str = "uv 0.5.11 — Python package manager (macOS arm64)";
}

#[cfg(all(target_os = "macos", target_arch = "x86_64"))]
mod platform {
    pub const UV_URL: &str = "https://github.com/astral-sh/uv/releases/download/0.5.11/uv-x86_64-apple-darwin.tar.gz";
    pub const UV_SHA256: &str = "7e23d1d892c23f9e74245c4fd3d3e246438ce9b34460f85eee61f784de137b0b";
    pub const UV_ARCHIVE: &str = "uv.tar.gz";
    pub const UV_BIN: &str = "uv";
    pub const PYTHON_BIN: &str = "bin/python";
    pub const UV_LABEL: &str = "uv 0.5.11 — Python package manager (macOS x64)";
}

// ── State helpers ──────────────────────────────────────────────────────────

#[derive(serde::Serialize, serde::Deserialize, Clone, Default)]
pub struct OptionalEngineState {
    #[serde(default)]
    pub status: String, // "not_installed" | "installed" | "failed"
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(serde::Serialize, serde::Deserialize, Default)]
struct OptionalEnginesState {
    #[serde(default)]
    ocr: OptionalEngineState,
    #[serde(default)]
    audio: OptionalEngineState,
}

#[derive(serde::Serialize, serde::Deserialize)]
struct ProvisionState {
    status: String,
    version: String,
    #[serde(default)]
    optional: OptionalEnginesState,
}

fn emit(app: &AppHandle, step: &str, message: &str, pct: f32) {
    let _ = app.emit(
        "provision:progress",
        ProgressPayload {
            step: step.to_string(),
            message: message.to_string(),
            pct,
            detail: None,
        },
    );
}

/// Emit a progress event carrying live download metrics (label + bytes + speed).
fn emit_detail(
    app: &AppHandle,
    step: &str,
    message: &str,
    pct: f32,
    detail: DownloadDetail,
) {
    let _ = app.emit(
        "provision:progress",
        ProgressPayload {
            step: step.to_string(),
            message: message.to_string(),
            pct,
            detail: Some(detail),
        },
    );
}

pub fn app_data_dir(app: &AppHandle) -> PathBuf {
    app.path().app_data_dir().expect("app data dir unavailable")
}

pub fn is_provisioned(app: &AppHandle) -> bool {
    let path = app_data_dir(app).join(".provision-state.json");
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str::<ProvisionState>(&s).ok())
        .map(|s| s.status == "ready")
        .unwrap_or(false)
}

fn read_state(app: &AppHandle) -> ProvisionState {
    let path = app_data_dir(app).join(".provision-state.json");
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str::<ProvisionState>(&s).ok())
        .unwrap_or_else(|| ProvisionState {
            status: "not_provisioned".into(),
            version: env!("CARGO_PKG_VERSION").to_string(),
            optional: OptionalEnginesState::default(),
        })
}

fn write_state(app: &AppHandle, state: &ProvisionState) -> Result<(), String> {
    let dir = app_data_dir(app);
    fs::create_dir_all(&dir).map_err(|e| {
        format!(
            "Cannot create app data folder at {}.\n\nCheck that you have write permission.\n\nDetail: {e}",
            dir.display()
        )
    })?;
    // Atomic write: write to .tmp then rename. A crash mid-write won't leave a
    // truncated state file that forces a full re-provision.
    let final_path = dir.join(".provision-state.json");
    let tmp_path = dir.join(".provision-state.json.tmp");
    let json = serde_json::to_string(state)
        .map_err(|e| format!("State serialise error: {e}"))?;
    fs::write(&tmp_path, json.as_bytes())
        .map_err(|e| format!("Cannot write setup state: {e}"))?;
    fs::rename(&tmp_path, &final_path)
        .map_err(|e| format!("Cannot finalise setup state: {e}"))
}

fn set_state(app: &AppHandle, status: &str) -> Result<(), String> {
    let mut state = read_state(app);
    state.status = status.to_string();
    state.version = env!("CARGO_PKG_VERSION").to_string();
    write_state(app, &state)
}

fn emit_engine(app: &AppHandle, engine: &str, step: &str, message: &str, pct: f32) {
    use crate::ipc::EngineInstallProgress;
    let _ = app.emit("engine:install-progress", EngineInstallProgress {
        engine: engine.to_string(),
        step: step.to_string(),
        message: message.to_string(),
        pct,
    });
}

// ── Public API ─────────────────────────────────────────────────────────────

pub fn optional_engine_status(app: &AppHandle, engine: &str) -> OptionalEngineState {
    let state = read_state(app);
    match engine {
        "ocr"   => state.optional.ocr,
        "audio" => state.optional.audio,
        _       => OptionalEngineState::default(),
    }
}

pub async fn install_optional_engine(
    app: AppHandle,
    engine: String,
) -> Result<(), String> {
    let lock_name = match engine.as_str() {
        "ocr"   => "requirements-ocr.lock",
        "audio" => "requirements-audio.lock",
        other   => return Err(format!("Unknown engine: {other}")),
    };

    let data_dir = app_data_dir(&app);
    let bin_dir  = data_dir.join("bin");
    let venv_dir = data_dir.join("venv");
    let uv_path  = bin_dir.join(platform::UV_BIN);

    if !uv_path.exists() {
        return Err("Setup tools not found. Restart the app to re-provision.".to_string());
    }

    // Hash-pinned engine lock (same supply-chain posture as the core install).
    let lock_path = get_sidecar_resource(&app, lock_name)?;

    // Mark as in-progress in provision state.
    {
        let mut state = read_state(&app);
        let slot = match engine.as_str() {
            "ocr"   => &mut state.optional.ocr,
            "audio" => &mut state.optional.audio,
            _       => unreachable!(),
        };
        *slot = OptionalEngineState { status: "installing".into(), error: None };
        write_state(&app, &state)?;
    }

    let label = match engine.as_str() {
        "ocr"   => "OCR engine (RapidOCR + pypdfium2)",
        "audio" => "audio engine (faster-whisper)",
        _       => "engine",
    };
    emit_engine(&app, &engine, "installing", &format!("Installing {label}…"), 0.1);

    let python = venv_dir.join(platform::PYTHON_BIN);
    let uv2    = uv_path.clone();
    let lock   = lock_path.clone();
    let result = tokio::task::spawn_blocking(move || {
        let mut cmd = std::process::Command::new(&uv2);
        cmd.args([
            "pip", "install", "--python", &python.to_string_lossy(),
            "--require-hashes", "-r", &lock.to_string_lossy(),
        ]);
        crate::hide_console(&mut cmd);
        cmd.output()
            .map_err(|e| format!("Could not run package installer: {e}"))
    })
    .await
    .map_err(|e| format!("Internal error: {e}"))??;

    if result.status.success() {
        let mut state = read_state(&app);
        let slot = match engine.as_str() {
            "ocr"   => &mut state.optional.ocr,
            "audio" => &mut state.optional.audio,
            _       => unreachable!(),
        };
        *slot = OptionalEngineState { status: "installed".into(), error: None };
        write_state(&app, &state)?;
        emit_engine(&app, &engine, "installed", &format!("{label} installed."), 1.0);
        Ok(())
    } else {
        let stderr = String::from_utf8_lossy(&result.stderr).to_string();
        let low = stderr.to_lowercase();
        let msg = if low.contains("network") || low.contains("timeout")
            || low.contains("connection") || low.contains("resolve")
        {
            format!("Could not download packages — check your internet connection.\n\nDetail: {stderr}")
        } else {
            format!("Installation failed.\n\nDetail: {stderr}")
        };
        let mut state = read_state(&app);
        let slot = match engine.as_str() {
            "ocr"   => &mut state.optional.ocr,
            "audio" => &mut state.optional.audio,
            _       => unreachable!(),
        };
        *slot = OptionalEngineState { status: "failed".into(), error: Some(msg.clone()) };
        write_state(&app, &state)?;
        Err(msg)
    }
}

// ── Public API ─────────────────────────────────────────────────────────────

pub async fn provision(app: AppHandle, force: bool) -> Result<(), String> {
    let data_dir = app_data_dir(&app);
    let bin_dir = data_dir.join("bin");
    let venv_dir = data_dir.join("venv");

    if force {
        // Best-effort cleanup; on Windows some files may be locked by a running
        // sidecar. Surface the error so the user knows to close the app and retry
        // rather than silently rebuilding on top of a half-removed venv.
        if let Err(e) = fs::remove_dir_all(&venv_dir) {
            if venv_dir.exists() {
                return Err(format!(
                    "Could not remove the old Python environment (files may be in use).\n\nClose the app fully and try again.\n\nDetail: {e}"
                ));
            }
        }
        if let Err(e) = fs::remove_dir_all(&bin_dir) {
            if bin_dir.exists() {
                return Err(format!(
                    "Could not remove old setup tools.\n\nClose the app fully and try again.\n\nDetail: {e}"
                ));
            }
        }
    }

    set_state(&app, "provisioning")?;

    // Step 1 — download uv
    emit(&app, "downloading_uv", "Downloading setup tools…", 0.05);
    let uv_path = download_uv(&app, &bin_dir).await.map_err(|e| {
        format!("Could not download setup tools.\n\nCheck your internet connection and try again.\n\nDetail: {e}")
    })?;
    emit(&app, "downloading_uv", "Setup tools ready.", 0.2);

    // Step 2 — create Python 3.12 venv (uv downloads Python automatically)
    emit(&app, "creating_env", "Setting up Python 3.12…", 0.25);
    let uv = uv_path.clone();
    let venv = venv_dir.clone();
    let app_venv = app.clone();
    tokio::task::spawn_blocking(move || create_venv(&app_venv, &uv, &venv))
        .await
        .map_err(|e| format!("Internal error: {e}"))??;
    emit(&app, "creating_env", "Python environment ready.", 0.45);

    // Step 3 — install packages
    emit(
        &app,
        "installing_packages",
        "Installing packages — this takes about a minute…",
        0.5,
    );
    let requirements = get_requirements_path(&app)?;
    let uv2 = uv_path.clone();
    let venv2 = venv_dir.clone();
    let app_pkgs = app.clone();
    tokio::task::spawn_blocking(move || install_packages(&app_pkgs, &uv2, &venv2, &requirements))
        .await
        .map_err(|e| format!("Internal error: {e}"))??;
    emit(&app, "installing_packages", "Packages installed.", 0.9);

    set_state(&app, "ready")?;
    emit(&app, "done", "Ready.", 1.0);
    Ok(())
}

pub fn python_path(app: &AppHandle) -> PathBuf {
    app_data_dir(app)
        .join("venv")
        .join(platform::PYTHON_BIN)
}

// ── Download ───────────────────────────────────────────────────────────────

async fn download_uv(app: &AppHandle, bin_dir: &Path) -> Result<PathBuf, String> {
    fs::create_dir_all(bin_dir).map_err(|e| e.to_string())?;

    let uv_path = bin_dir.join(platform::UV_BIN);
    if uv_path.exists() {
        // Validate the cached binary isn't a zero-byte/corrupt leftover from an
        // interrupted download. If validation fails, re-download.
        let valid = std::fs::metadata(&uv_path)
            .map(|m| m.len() > 1024)
            .unwrap_or(false);
        if valid {
            return Ok(uv_path);
        }
    }

    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(120))
        .build()
        .map_err(|e| e.to_string())?;

    let mut resp = client
        .get(platform::UV_URL)
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;

    let total = resp.content_length();
    let mut bytes: Vec<u8> = Vec::with_capacity(total.unwrap_or(0) as usize);

    // Stream the body chunk-by-chunk so we can report live bytes + speed. We map
    // download progress onto the 0.05–0.20 slice of the overall provisioning bar.
    use std::time::Instant;
    let started = Instant::now();
    let mut last_emit = Instant::now();
    // Rolling-window speed: bytes received since the previous sample.
    let mut window_start = Instant::now();
    let mut window_bytes: u64 = 0;
    let mut speed: f64 = 0.0;

    while let Some(chunk) = resp.chunk().await.map_err(|e| e.to_string())? {
        bytes.extend_from_slice(&chunk);
        window_bytes += chunk.len() as u64;

        // Recompute speed over a ~0.4s window so the number is responsive but not jumpy.
        let win = window_start.elapsed().as_secs_f64();
        if win >= 0.4 {
            speed = window_bytes as f64 / win;
            window_start = Instant::now();
            window_bytes = 0;
        }

        // Throttle UI events to ~10/sec.
        if last_emit.elapsed().as_millis() >= 100 {
            let received = bytes.len() as u64;
            let frac = total
                .map(|t| if t > 0 { received as f32 / t as f32 } else { 0.0 })
                .unwrap_or(0.0)
                .clamp(0.0, 1.0);
            emit_detail(
                app,
                "downloading_uv",
                "Downloading setup tools…",
                0.05 + frac * 0.15,
                DownloadDetail {
                    label: platform::UV_LABEL.to_string(),
                    received,
                    total,
                    // Fall back to the running average before the first window closes.
                    speed: if speed > 0.0 {
                        speed
                    } else {
                        received as f64 / started.elapsed().as_secs_f64().max(0.001)
                    },
                },
            );
            last_emit = Instant::now();
        }
    }

    // Integrity check: verify SHA256 against the pinned hash. An empty constant
    // means the hash hasn't been filled in yet (verification skipped). Pinning the
    // version URL is the primary defense against supply-chain attacks.
    if !platform::UV_SHA256.is_empty() {
        use sha2::{Digest, Sha256};
        let mut hasher = Sha256::new();
        hasher.update(&bytes);
        let actual = format!("{:x}", hasher.finalize());
        if actual != platform::UV_SHA256 {
            return Err(format!(
                "Setup tools failed integrity check (SHA256 mismatch).\n\nExpected: {}\nGot:    {}\n\nThis may indicate a corrupted download or a compromised package. Try again, and if it persists, report this issue.",
                platform::UV_SHA256, actual
            ));
        }
    }

    let archive_path = bin_dir.join(platform::UV_ARCHIVE);
    fs::write(&archive_path, &bytes).map_err(|e| e.to_string())?;

    let dest = bin_dir.to_path_buf();
    let archive_clone = archive_path.clone();
    tokio::task::spawn_blocking(move || extract_uv(&archive_clone, &dest))
        .await
        .map_err(|e| e.to_string())??;

    let _ = fs::remove_file(&archive_path);

    #[cfg(unix)]
    set_executable(&uv_path)?;

    Ok(uv_path)
}

#[cfg(target_os = "windows")]
fn extract_uv(archive: &Path, dest: &Path) -> Result<(), String> {
    let file = fs::File::open(archive).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|e| e.to_string())?;
        let name = entry.name().to_string();
        if name == platform::UV_BIN || name.ends_with(&format!("/{}", platform::UV_BIN)) {
            let mut out =
                fs::File::create(dest.join(platform::UV_BIN)).map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut out).map_err(|e| e.to_string())?;
            return Ok(());
        }
    }
    Err(format!("{} not found in archive", platform::UV_BIN))
}

#[cfg(target_os = "macos")]
fn extract_uv(archive: &Path, dest: &Path) -> Result<(), String> {
    let file = fs::File::open(archive).map_err(|e| e.to_string())?;
    let gz = flate2::read::GzDecoder::new(file);
    let mut tar = tar::Archive::new(gz);
    for entry in tar.entries().map_err(|e| e.to_string())? {
        let mut entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path().map_err(|e| e.to_string())?;
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if name == platform::UV_BIN {
            entry
                .unpack(dest.join(platform::UV_BIN))
                .map_err(|e| e.to_string())?;
            return Ok(());
        }
    }
    Err(format!("{} not found in archive", platform::UV_BIN))
}

#[cfg(not(any(target_os = "windows", target_os = "macos")))]
fn extract_uv(_archive: &Path, _dest: &Path) -> Result<(), String> {
    Err("Unsupported platform. Rebuild for win-x64, darwin-arm64, or darwin-x64.".to_string())
}

#[cfg(unix)]
fn set_executable(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let mut perms = fs::metadata(path)
        .map_err(|e| e.to_string())?
        .permissions();
    perms.set_mode(0o755);
    fs::set_permissions(path, perms).map_err(|e| e.to_string())
}

// ── Venv + packages ────────────────────────────────────────────────────────

/// Run a `uv` command, streaming its stderr line-by-line to `on_line` as it
/// arrives (uv logs everything to stderr). Returns the exit status plus the full
/// captured stderr for error reporting. stdout is discarded — uv writes nothing
/// meaningful there, and null-ing it avoids any pipe-buffer deadlock.
fn run_uv_streamed(
    mut cmd: std::process::Command,
    mut on_line: impl FnMut(&str),
) -> Result<(std::process::ExitStatus, String), String> {
    use std::io::{BufRead, BufReader};
    cmd.stdout(std::process::Stdio::null());
    cmd.stderr(std::process::Stdio::piped());
    crate::hide_console(&mut cmd);

    let mut child = cmd
        .spawn()
        .map_err(|e| format!("Could not run setup tool: {e}"))?;
    let stderr = child.stderr.take().expect("stderr was piped");

    let mut collected = String::new();
    for line in BufReader::new(stderr).lines() {
        let Ok(line) = line else { break };
        collected.push_str(&line);
        collected.push('\n');
        let trimmed = line.trim();
        if !trimmed.is_empty() {
            on_line(trimmed);
        }
    }

    let status = child
        .wait()
        .map_err(|e| format!("Setup tool error: {e}"))?;
    Ok((status, collected))
}

fn create_venv(app: &AppHandle, uv: &Path, venv_dir: &Path) -> Result<(), String> {
    let mut cmd = std::process::Command::new(uv);
    cmd.args(["venv", "--python", "3.12", &venv_dir.to_string_lossy()]);

    let (status, stderr) = run_uv_streamed(cmd, |line| {
        // Surface what uv is doing: fetching the CPython 3.12 runtime, then
        // building the environment. Keep messages short and human.
        let low = line.to_lowercase();
        let (msg, pct) = if low.contains("download") || low.contains("fetching") {
            ("Downloading Python 3.12 runtime…", 0.30)
        } else if low.contains("creating") || low.contains("created") || low.contains("environment") {
            ("Creating the Python environment…", 0.42)
        } else {
            ("Setting up Python 3.12…", 0.28)
        };
        emit_detail(
            app,
            "creating_env",
            msg,
            pct,
            DownloadDetail {
                label: "CPython 3.12 runtime (~25 MB)".to_string(),
                received: 0,
                total: None,
                speed: 0.0,
            },
        );
    })?;

    if !status.success() {
        let msg = if stderr.contains("No interpreter found") || stderr.contains("download") {
            "Python 3.12 could not be downloaded. Check your internet connection and try again."
        } else {
            "Could not create Python environment."
        };
        return Err(format!("{msg}\n\nDetail: {stderr}"));
    }
    Ok(())
}

fn install_packages(
    app: &AppHandle,
    uv: &Path,
    venv_dir: &Path,
    requirements: &Path,
) -> Result<(), String> {
    let python = venv_dir.join(platform::PYTHON_BIN);
    let mut cmd = std::process::Command::new(uv);
    cmd.args([
        "pip",
        "install",
        "--python",
        &python.to_string_lossy(),
        // Supply-chain integrity: install only the exact, hash-verified versions in
        // the bundled lock file. uv aborts if any artifact's hash doesn't match.
        "--require-hashes",
        "-r",
        &requirements.to_string_lossy(),
    ]);

    let (status, stderr) = run_uv_streamed(cmd, |line| {
        // uv prints milestone lines like "Resolved N packages", "Prepared N
        // packages", "Installed N packages". Map them onto the 0.50–0.90 slice.
        let low = line.to_lowercase();
        let (msg, pct): (String, f32) = if low.starts_with("resolved") {
            ("Resolving package versions…".to_string(), 0.58)
        } else if low.starts_with("downloading") || low.starts_with("downloaded") {
            (truncate(line, 90), 0.72)
        } else if low.starts_with("prepared") || low.starts_with("preparing") {
            ("Unpacking packages…".to_string(), 0.80)
        } else if low.starts_with("installed") {
            ("Finalising installation…".to_string(), 0.88)
        } else {
            ("Installing packages…".to_string(), 0.62)
        };
        emit_detail(
            app,
            "installing_packages",
            &msg,
            pct,
            DownloadDetail {
                label: "markitdown + format support, openai client".to_string(),
                received: 0,
                total: None,
                speed: 0.0,
            },
        );
    })?;

    if !status.success() {
        let low = stderr.to_lowercase();
        let msg = if low.contains("network")
            || low.contains("timeout")
            || low.contains("connection")
            || low.contains("resolve")
            || low.contains("refused")
        {
            "Packages could not be downloaded. Check your internet connection and try again."
        } else {
            "Package installation failed."
        };
        return Err(format!("{msg}\n\nDetail: {stderr}"));
    }
    Ok(())
}

/// Truncate a status line to keep UI messages tidy.
fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(max.saturating_sub(1)).collect();
        out.push('…');
        out
    }
}

/// Resolve a bundled sidecar resource file (e.g. a requirements lock) by name.
fn get_sidecar_resource(app: &AppHandle, filename: &str) -> Result<PathBuf, String> {
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Cannot locate app resources: {e}"))?;
    let path = resource_dir.join("resources").join("sidecar").join(filename);
    if !path.exists() {
        return Err(format!(
            "{filename} not found at {}.\n\nRe-install the app to fix this.",
            path.display()
        ));
    }
    Ok(path)
}

fn get_requirements_path(app: &AppHandle) -> Result<PathBuf, String> {
    // The hash-pinned lock is the install source of truth (requirements.txt is the
    // human-readable spec it was compiled from).
    get_sidecar_resource(app, "requirements.lock")
}
