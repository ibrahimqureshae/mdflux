//! Lite runtime provisioning helpers (uv download, venv, hash-pinned packages).

use std::fs;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::time::Instant;

use sha2::{Digest, Sha256};
use tauri::{AppHandle, Emitter};

use crate::ipc::{DownloadDetail, ProgressPayload};
use crate::platform::{self, PlatformSpec};

pub fn emit_progress(app: &AppHandle, step: &str, message: &str, pct: f32) {
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

fn emit_detail(app: &AppHandle, step: &str, message: &str, pct: f32, detail: DownloadDetail) {
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

pub async fn download_uv(
    app: &AppHandle,
    bin_dir: &Path,
    spec: &PlatformSpec,
) -> Result<PathBuf, String> {
    fs::create_dir_all(bin_dir).map_err(|e| e.to_string())?;

    let uv_path = bin_dir.join(spec.uv_bin);
    if uv_path.exists() {
        let valid = fs::metadata(&uv_path)
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
        .get(spec.uv_url)
        .send()
        .await
        .map_err(|e| e.to_string())?
        .error_for_status()
        .map_err(|e| e.to_string())?;

    let total = resp.content_length();
    let mut bytes: Vec<u8> = Vec::with_capacity(total.unwrap_or(0) as usize);
    let started = Instant::now();
    let mut last_emit = Instant::now();
    let mut window_start = Instant::now();
    let mut window_bytes: u64 = 0;
    let mut speed: f64 = 0.0;

    while let Some(chunk) = resp.chunk().await.map_err(|e| e.to_string())? {
        bytes.extend_from_slice(&chunk);
        window_bytes += chunk.len() as u64;
        let win = window_start.elapsed().as_secs_f64();
        if win >= 0.4 {
            speed = window_bytes as f64 / win;
            window_start = Instant::now();
            window_bytes = 0;
        }
        if last_emit.elapsed().as_millis() >= 100 {
            let received = bytes.len() as u64;
            let frac = total
                .map(|t| {
                    if t > 0 {
                        received as f32 / t as f32
                    } else {
                        0.0
                    }
                })
                .unwrap_or(0.0)
                .clamp(0.0, 1.0);
            emit_detail(
                app,
                "downloading_uv",
                "Downloading setup tools...",
                0.05 + frac * 0.15,
                DownloadDetail {
                    label: spec.uv_label.to_string(),
                    received,
                    total,
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

    if !spec.uv_sha256.is_empty() {
        let actual = format!("{:x}", Sha256::digest(&bytes));
        if actual != spec.uv_sha256 {
            return Err(format!(
                "Setup tools failed integrity check (SHA256 mismatch).\n\nExpected: {}\nGot:    {}",
                spec.uv_sha256, actual
            ));
        }
    }

    let archive_path = bin_dir.join(spec.uv_archive);
    fs::write(&archive_path, &bytes).map_err(|e| e.to_string())?;
    let dest = bin_dir.to_path_buf();
    let archive_clone = archive_path.clone();
    let spec_uv_bin = spec.uv_bin.to_string();
    tokio::task::spawn_blocking(move || extract_uv(&archive_clone, &dest, &spec_uv_bin))
        .await
        .map_err(|e| e.to_string())??;
    let _ = fs::remove_file(&archive_path);
    platform::set_executable(&uv_path)?;
    Ok(uv_path)
}

#[cfg(target_os = "windows")]
fn extract_uv(archive: &Path, dest: &Path, uv_bin: &str) -> Result<(), String> {
    let file = fs::File::open(archive).map_err(|e| e.to_string())?;
    let mut zip = zip::ZipArchive::new(file).map_err(|e| e.to_string())?;
    for i in 0..zip.len() {
        let mut entry = zip.by_index(i).map_err(|e| e.to_string())?;
        let name = entry.name().to_string();
        if name == uv_bin || name.ends_with(&format!("/{uv_bin}")) {
            let mut out = fs::File::create(dest.join(uv_bin)).map_err(|e| e.to_string())?;
            std::io::copy(&mut entry, &mut out).map_err(|e| e.to_string())?;
            return Ok(());
        }
    }
    Err(format!("{uv_bin} not found in archive"))
}

#[cfg(unix)]
fn extract_uv(archive: &Path, dest: &Path, uv_bin: &str) -> Result<(), String> {
    let file = fs::File::open(archive).map_err(|e| e.to_string())?;
    let gz = flate2::read::GzDecoder::new(file);
    let mut tar = tar::Archive::new(gz);
    for entry in tar.entries().map_err(|e| e.to_string())? {
        let mut entry = entry.map_err(|e| e.to_string())?;
        let path = entry.path().map_err(|e| e.to_string())?;
        let name = path.file_name().and_then(|n| n.to_str()).unwrap_or("");
        if name == uv_bin {
            entry.unpack(dest.join(uv_bin)).map_err(|e| e.to_string())?;
            return Ok(());
        }
    }
    Err(format!("{uv_bin} not found in archive"))
}

fn run_uv_streamed(
    mut cmd: std::process::Command,
    mut on_line: impl FnMut(&str),
) -> Result<(std::process::ExitStatus, String), String> {
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
    let status = child.wait().map_err(|e| format!("Setup tool error: {e}"))?;
    Ok((status, collected))
}

pub fn create_venv(app: &AppHandle, uv: &Path, venv_dir: &Path) -> Result<(), String> {
    let mut cmd = std::process::Command::new(uv);
    cmd.args(["venv", "--python", "3.12", &venv_dir.to_string_lossy()]);
    let (status, stderr) = run_uv_streamed(cmd, |line| {
        let low = line.to_lowercase();
        let (msg, pct) = if low.contains("download") || low.contains("fetching") {
            ("Downloading Python 3.12 runtime...", 0.30)
        } else if low.contains("creating") || low.contains("created") || low.contains("environment")
        {
            ("Creating the Python environment...", 0.42)
        } else {
            ("Setting up Python 3.12...", 0.28)
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

pub fn install_packages(
    app: &AppHandle,
    uv: &Path,
    venv_dir: &Path,
    requirements: &Path,
    spec: &PlatformSpec,
) -> Result<(), String> {
    let python = venv_dir.join(spec.venv_python_bin);
    let mut cmd = std::process::Command::new(uv);
    cmd.args([
        "pip",
        "install",
        "--python",
        &python.to_string_lossy(),
        "--require-hashes",
        "-r",
        &requirements.to_string_lossy(),
    ]);
    let (status, stderr) = run_uv_streamed(cmd, |line| {
        let low = line.to_lowercase();
        let (msg, pct): (String, f32) = if low.starts_with("resolved") {
            ("Resolving package versions...".to_string(), 0.58)
        } else if low.starts_with("downloading") || low.starts_with("downloaded") {
            (truncate(line, 90), 0.72)
        } else if low.starts_with("prepared") || low.starts_with("preparing") {
            ("Unpacking packages...".to_string(), 0.80)
        } else if low.starts_with("installed") {
            ("Finalising installation...".to_string(), 0.88)
        } else {
            ("Installing packages...".to_string(), 0.62)
        };
        emit_detail(
            app,
            "installing_packages",
            &msg,
            pct,
            DownloadDetail {
                label: "markitdown + format support".to_string(),
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

pub fn install_engine_packages(uv: &Path, python: &Path, lock_path: &Path) -> Result<(), String> {
    let mut cmd = std::process::Command::new(uv);
    cmd.args([
        "pip",
        "install",
        "--python",
        &python.to_string_lossy(),
        "--require-hashes",
        "-r",
        &lock_path.to_string_lossy(),
    ]);
    crate::hide_console(&mut cmd);
    let output = cmd
        .output()
        .map_err(|e| format!("Could not run package installer: {e}"))?;
    if output.status.success() {
        Ok(())
    } else {
        Err(String::from_utf8_lossy(&output.stderr).to_string())
    }
}

pub fn smoke_test_python(python: &Path) -> Result<String, String> {
    let mut cmd = std::process::Command::new(python);
    cmd.args([
        "-c",
        "import markitdown; import sys; print(sys.version.split()[0])",
    ]);
    crate::hide_console(&mut cmd);
    let output = cmd.output().map_err(|e| {
        format!(
            "Smoke test could not run Python at {}: {e}",
            python.display()
        )
    })?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Runtime smoke test failed.\n\nDetail: {stderr}"));
    }
    let version = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(version)
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let mut out: String = s.chars().take(max.saturating_sub(1)).collect();
        out.push_str("...");
        out
    }
}
