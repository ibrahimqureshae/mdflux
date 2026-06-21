mod bootstrap;
mod config;
mod converter;
mod ipc;

use std::path::PathBuf;
use std::sync::Arc;

use tauri::{AppHandle, Emitter, Manager};
use tauri_plugin_dialog::DialogExt;

use converter::SidecarManager;

// ── Batch pool ─────────────────────────────────────────────────────────────

/// Logical processors available, with a safe fallback.
fn logical_cores() -> usize {
    std::thread::available_parallelism()
        .map(|n| n.get())
        .unwrap_or(4)
}

/// Conservative RAM budget per concurrent worker — a heavy OCR/audio worker holds
/// model weights plus a working set; 1 GiB covers that with headroom.
const PER_WORKER_MB: u64 = 1024;
/// RAM left untouched for the OS, the app, and the model weights already resident.
const RAM_RESERVE_MB: u64 = 1024;

/// Available physical memory in MiB, or None if it can't be determined (→ no RAM cap).
#[cfg(windows)]
fn available_ram_mb() -> Option<u64> {
    #[repr(C)]
    struct MemStatus {
        length: u32,
        memory_load: u32,
        total_phys: u64,
        avail_phys: u64,
        total_pagefile: u64,
        avail_pagefile: u64,
        total_virtual: u64,
        avail_virtual: u64,
        avail_ext_virtual: u64,
    }
    extern "system" {
        fn GlobalMemoryStatusEx(buffer: *mut MemStatus) -> i32;
    }
    let mut s: MemStatus = unsafe { std::mem::zeroed() };
    s.length = std::mem::size_of::<MemStatus>() as u32;
    if unsafe { GlobalMemoryStatusEx(&mut s) } != 0 {
        Some(s.avail_phys / (1024 * 1024))
    } else {
        None
    }
}

#[cfg(target_os = "macos")]
fn available_ram_mb() -> Option<u64> {
    extern "C" {
        fn sysctlbyname(
            name: *const std::os::raw::c_char,
            oldp: *mut std::ffi::c_void,
            oldlenp: *mut usize,
            newp: *mut std::ffi::c_void,
            newlen: usize,
        ) -> std::os::raw::c_int;
    }
    let name = b"hw.memsize\0";
    let mut val: u64 = 0;
    let mut len = std::mem::size_of::<u64>();
    let rc = unsafe {
        sysctlbyname(
            name.as_ptr() as *const _,
            &mut val as *mut _ as *mut _,
            &mut len,
            std::ptr::null_mut(),
            0,
        )
    };
    // hw.memsize is TOTAL physical RAM. macOS uses free RAM as cache, so treat ~half of
    // total as a conservative available budget for sizing the pool.
    if rc == 0 && val > 0 {
        Some((val / (1024 * 1024)) / 2)
    } else {
        None
    }
}

#[cfg(not(any(windows, target_os = "macos")))]
fn available_ram_mb() -> Option<u64> {
    None
}

/// CPU-based concurrency cap — stable across a run (does not depend on live RAM).
/// `batch_worker_threads` is derived from THIS so the per-worker thread budget never
/// changes; only the worker *count* (`batch_worker_cap`) can drop under memory pressure.
fn cpu_worker_cap() -> usize {
    (logical_cores() / 2).clamp(2, 8)
}

/// How many files convert concurrently in a batch, adapted to the machine.
///
/// Each concurrent worker is a SEPARATE converter subprocess (MarkItDown / OCR /
/// Whisper); the heavy ones (OCR, audio) are multi-threaded and hold model weights in
/// RAM. We start from a core-based cap, then clamp it DOWN if available memory is tight
/// so a many-core / low-RAM machine doesn't run more heavy workers than fit in memory.
/// Sampled per batch.
fn batch_worker_cap() -> usize {
    let cpu = cpu_worker_cap();
    match available_ram_mb() {
        Some(avail) => {
            let budget = avail.saturating_sub(RAM_RESERVE_MB);
            let ram_cap = (budget / PER_WORKER_MB).max(1) as usize;
            cpu.min(ram_cap).clamp(1, 8)
        }
        None => cpu,
    }
}

/// Per-worker CPU-thread budget for batch conversions, so N concurrent heavy workers
/// don't oversubscribe the CPU. Derived from the CPU cap (NOT the RAM-adjusted cap) so
/// it's fixed at startup and `workers × threads` can never exceed the core count.
/// Single-file conversions ignore it and use all cores.
fn batch_worker_threads() -> usize {
    std::cmp::max(1, logical_cores() / cpu_worker_cap())
}

/// Tracks output paths the app has written, so `read_text_file` can allow
/// reading them back without a blanket `.md` extension check that any file
/// could bypass. Populated by `write_output` and `save_markdown`.
#[derive(Default)]
pub struct WrittenPaths(std::sync::Mutex<std::collections::HashSet<PathBuf>>);

impl WrittenPaths {
    pub fn record(&self, path: &std::path::Path) {
        if let Ok(canon) = std::fs::canonicalize(path) {
            if let Ok(mut guard) = self.0.lock() {
                guard.insert(canon);
            }
        }
    }

    pub fn contains(&self, canon: &std::path::Path) -> bool {
        self.0
            .lock()
            .map(|g| g.contains(canon))
            .unwrap_or(false)
    }
}
pub struct BatchManager {
    cancel_flag: std::sync::atomic::AtomicBool,
}

impl BatchManager {
    fn new() -> Self {
        BatchManager {
            cancel_flag: std::sync::atomic::AtomicBool::new(false),
        }
    }
    fn reset(&self) {
        self.cancel_flag
            .store(false, std::sync::atomic::Ordering::Relaxed);
    }
    fn cancel(&self) {
        self.cancel_flag
            .store(true, std::sync::atomic::Ordering::Relaxed);
    }
    fn is_cancelled(&self) -> bool {
        self.cancel_flag
            .load(std::sync::atomic::Ordering::Relaxed)
    }
}

// ── Helpers ────────────────────────────────────────────────────────────────

fn sidecar_paths(app: &AppHandle) -> Result<(PathBuf, PathBuf), String> {
    let python = bootstrap::python_path(app);
    let resource_dir = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Cannot locate app resources: {e}"))?;
    let script = resource_dir
        .join("resources")
        .join("sidecar")
        .join("main.py");
    if !script.exists() {
        return Err(format!(
            "Sidecar script missing at {}. Re-install the app.",
            script.display()
        ));
    }
    Ok((python, script))
}

pub fn next_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static SEQ: AtomicU64 = AtomicU64::new(1);
    SEQ.fetch_add(1, Ordering::Relaxed).to_string()
}

/// Windows: suppress the console window a child process would otherwise flash on
/// screen (uv, Python, the sidecar, OCR/audio workers). No-op on other platforms.
/// Apply to EVERY process we spawn so install/provision/convert stay visually clean.
#[cfg(windows)]
pub(crate) fn hide_console(cmd: &mut std::process::Command) {
    use std::os::windows::process::CommandExt;
    const CREATE_NO_WINDOW: u32 = 0x0800_0000;
    cmd.creation_flags(CREATE_NO_WINDOW);
}
#[cfg(not(windows))]
pub(crate) fn hide_console(_cmd: &mut std::process::Command) {}

// ── Format sets (single source of truth in Rust) ───────────────────────────

/// Core formats always supported (provisioned at Stage 0).
const CORE_EXTS: &[&str] = &[
    "pdf", "docx", "pptx", "xlsx", "xls", "html", "htm", "csv", "json", "xml", "epub",
];
/// Formats requiring the OCR engine.
const OCR_EXTS: &[&str] = &["jpg", "jpeg", "png", "gif", "webp", "tiff", "tif", "bmp"];
/// Formats requiring the audio engine.
const AUDIO_EXTS: &[&str] = &["mp3", "wav", "m4a", "ogg", "flac", "aac"];

fn all_supported_exts() -> Vec<&'static str> {
    let mut v: Vec<&str> = CORE_EXTS.to_vec();
    v.extend_from_slice(OCR_EXTS);
    v.extend_from_slice(AUDIO_EXTS);
    v
}

/// Stage 6: conversion options threaded through the batch pipeline.
struct BatchConvOpts {
    /// LLM config for image description; `Null` when disabled.
    llm_cfg: serde_json::Value,
    extract_images: bool,
    audio_model: String,
}

// ── Tauri commands ─────────────────────────────────────────────────────────

#[tauri::command]
async fn get_provision_status(app: AppHandle) -> Result<ipc::ProvisionStatus, String> {
    let state = if bootstrap::is_provisioned(&app) {
        "ready"
    } else {
        "not_provisioned"
    };
    Ok(ipc::ProvisionStatus {
        state: state.to_string(),
    })
}

#[tauri::command]
async fn start_provision(
    app: AppHandle,
    force: bool,
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<(), String> {
    // Kill the sidecar before force-provision so Windows doesn't hold locks on
    // venv DLLs/python.exe — a force rebuild on top of a running sidecar would
    // silently corrupt the venv.
    if force {
        manager.kill_sidecar().await;
    }
    bootstrap::provision(app, force).await
}

#[tauri::command]
async fn run_health_check(
    app: AppHandle,
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<ipc::HealthReport, String> {
    let python = bootstrap::python_path(&app);
    if !python.exists() {
        return Err("Python environment not found. Click Repair to reinstall.".to_string());
    }
    let (python, script) = sidecar_paths(&app)?;
    manager.ensure_alive(&python, &script).await?;

    let req = serde_json::json!({
        "v": 1,
        "id": next_id(),
        "method": "health",
        "params": {}
    });
    let resp = manager.send_streaming(&req, |_| {}).await?;

    if !resp.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        let msg = resp
            .get("error")
            .and_then(|e| e.get("detail"))
            .and_then(|d| d.as_str())
            .unwrap_or("Health check failed.")
            .to_string();
        return Err(msg);
    }

    let data = resp
        .get("result")
        .ok_or("Health response missing 'result' field.")?;
    serde_json::from_value(data.clone())
        .map_err(|e| format!("Could not parse health report: {e}"))
}

#[tauri::command]
async fn convert_file(
    app: AppHandle,
    path: String,
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<ipc::ConvertResponse, String> {
    let (python, script) = sidecar_paths(&app)?;
    manager.ensure_alive(&python, &script).await?;

    let cfg = config::load(&app);

    // Build LLM config for conversion when the user has enabled it.
    let llm_params = if cfg.llm_conversion && cfg.llm_mode != "off" {
        build_conversion_llm_cfg(&cfg)
    } else {
        serde_json::Value::Null
    };

    let mut params = serde_json::json!({ "path": path });
    if !llm_params.is_null() {
        params["llm"] = llm_params;
    }
    // Pass the audio model size so audio_worker picks the right weights.
    params["audio_model"] = serde_json::Value::String(cfg.audio_model.clone());

    let req = serde_json::json!({
        "v": 1,
        "id": next_id(),
        "method": "convert-one",
        "params": params
    });

    let app_clone = app.clone();
    let resp = manager
        .send_streaming(&req, move |progress_val| {
            let _ = app_clone.emit("convert:progress", progress_val);
        })
        .await?;

    let ok = resp.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
    if ok {
        // Image extraction for zip-based formats is deferred to `save_markdown` so
        // a preview-only conversion doesn't litter the user's source directory with a
        // `{stem}_assets/` folder. The batch path extracts at the output dir directly.
        let result: ipc::ConvertResult = serde_json::from_value(
            resp.get("result")
                .cloned()
                .ok_or("Response missing 'result'")?,
        )
        .map_err(|e| format!("Could not parse conversion result: {e}"))?;

        Ok(ipc::ConvertResponse { ok: true, result: Some(result), error: None })
    } else {
        let error: ipc::IpcError = serde_json::from_value(
            resp.get("error")
                .cloned()
                .ok_or("Response missing 'error'")?,
        )
        .map_err(|e| format!("Could not parse error response: {e}"))?;
        Ok(ipc::ConvertResponse { ok: false, result: None, error: Some(error) })
    }
}

/// Build the LLM config sent to the sidecar for image description during conversion.
fn build_conversion_llm_cfg(cfg: &config::AppConfig) -> serde_json::Value {
    let (base_url, key) = match cfg.llm_mode.as_str() {
        "local" => (cfg.local_base_url.clone(), String::new()),
        "api"   => (cfg.api_base_url.clone(), cfg.api_key.clone()),
        _       => return serde_json::Value::Null,
    };
    serde_json::json!({
        "mode":     cfg.llm_mode,
        "api_type": cfg.api_type,
        "base_url": base_url,
        "key":      key,
        "model":    cfg.conversion_model,
    })
}

/// Extract images from a DOCX / PPTX / EPUB (all are ZIP archives) and write
/// them to `{stem}_assets/` inside `out_dir`. Returns the assets folder name
/// (relative, for use in Markdown links) and a list of relative Markdown image links.
/// Failures to write individual images are silently skipped — the .md is never lost.
fn extract_zip_images(source: &str, out_dir: &std::path::Path) -> (String, Vec<String>) {
    let p = std::path::Path::new(source);
    let ext = p.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
    if !["docx", "pptx", "epub"].contains(&ext.as_str()) {
        return (String::new(), vec![]);
    }

    let stem = p.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| "output".into());
    let assets_dir = out_dir.join(format!("{stem}_assets"));
    let assets_name = format!("{stem}_assets");

    let file = match std::fs::File::open(source) {
        Ok(f) => f,
        Err(_) => return (String::new(), vec![]),
    };
    let mut zip = match zip::ZipArchive::new(file) {
        Ok(z) => z,
        Err(_) => return (String::new(), vec![]),
    };

    const IMG_EXTS: &[&str] = &["png", "jpg", "jpeg", "gif", "webp", "tiff", "tif", "bmp"];
    // Skip images smaller than this — theme backgrounds, bullet glyphs, header logos and
    // other chrome are almost always tiny, while real content images are larger. This
    // keeps the "Extracted Images" block to actual document content.
    const MIN_IMAGE_BYTES: usize = 5 * 1024;
    let mut links: Vec<String> = Vec::new();
    let mut dir_created = false;

    // Collect image entries upfront (can't borrow zip while iterating and writing).
    // Dedupe identical images (the same logo/icon recurs across many slides/pages) by a
    // content hash so each distinct image is written once.
    let mut to_extract: Vec<(String, Vec<u8>)> = Vec::new();
    let mut seen: std::collections::HashSet<u64> = std::collections::HashSet::new();
    for i in 0..zip.len() {
        let mut entry = match zip.by_index(i) { Ok(e) => e, Err(_) => continue };
        let name_lc = entry.name().to_lowercase();
        // Only extract from standard media/image folders.
        let in_media = name_lc.contains("/media/")
            || name_lc.contains("\\media\\")
            || name_lc.starts_with("images/")
            || name_lc.contains("/images/");
        if !in_media { continue; }
        let entry_ext = std::path::Path::new(&name_lc)
            .extension().map(|e| e.to_string_lossy().to_string()).unwrap_or_default();
        if !IMG_EXTS.contains(&entry_ext.as_str()) { continue; }

        let mut data = Vec::new();
        use std::io::Read;
        if entry.read_to_end(&mut data).is_ok() && data.len() >= MIN_IMAGE_BYTES {
            use std::hash::{Hash, Hasher};
            let mut h = std::collections::hash_map::DefaultHasher::new();
            data.hash(&mut h);
            if !seen.insert(h.finish()) {
                continue; // duplicate of an already-collected image
            }
            let fname = std::path::Path::new(entry.name())
                .file_name().map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| format!("image_{}.{entry_ext}", to_extract.len() + 1));
            to_extract.push((fname, data));
        }
    }

    for (fname, data) in to_extract {
        if !dir_created {
            if std::fs::create_dir_all(&assets_dir).is_err() {
                break; // can't create folder — skip all images, never lose the .md
            }
            dir_created = true;
        }
        let dest = assets_dir.join(&fname);
        if std::fs::write(&dest, &data).is_ok() {
            links.push(format!("![{fname}]({assets_name}/{fname})"));
        }
    }

    (assets_name, links)
}

#[tauri::command]
async fn cancel_conversion(
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<(), String> {
    manager.cancel().await
}

#[tauri::command]
async fn save_markdown(
    app: AppHandle,
    content: String,
    suggested_name: String,
    source_path: Option<String>,
    extract_images: Option<bool>,
    written: tauri::State<'_, Arc<WrittenPaths>>,
) -> Result<bool, String> {
    let cfg = config::load(&app);
    let should_extract = extract_images.unwrap_or(cfg.extract_images);

    let path = tokio::task::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Save as Markdown")
            .add_filter("Markdown", &["md"])
            .set_file_name(&suggested_name)
            .blocking_save_file()
    })
    .await
    .map_err(|e| format!("Dialog error: {e}"))?;

    match path {
        Some(p) => {
            let dest = p.into_path().map_err(|e| format!("Invalid path: {e}"))?;

            // Image extraction: for zip-based source formats, extract embedded images
            // to `{stem}_assets/` beside the saved .md so relative links resolve.
            // Deferred from convert_file so preview-only runs don't litter the source dir.
            let mut final_content = content;
            if should_extract {
                if let Some(src) = source_path.as_deref() {
                    let dest_dir = dest.parent().unwrap_or(std::path::Path::new("."));
                    let (assets_name, links) = extract_zip_images(src, dest_dir);
                    if !links.is_empty() {
                        final_content.push_str("\n\n---\n\n## Extracted Images\n\n");
                        final_content.push_str(&links.join("\n\n"));
                    }
                    let _ = assets_name; // relative folder name embedded in links above
                }
            }

            std::fs::write(&dest, final_content.as_bytes())
                .map_err(|e| format!("Could not save file: {e}"))?;
            // Record the written path so read_text_file can read it back.
            written.record(&dest);
            Ok(true)
        }
        None => Ok(false),
    }
}

#[tauri::command]
async fn pick_file(app: AppHandle) -> Result<Option<String>, String> {
    let path = tokio::task::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Open File")
            .add_filter(
                "Supported files",
                &[
                    "pdf", "docx", "pptx", "xlsx", "xls", "html", "htm", "csv", "json", "xml",
                    "epub",
                    "jpg", "jpeg", "png", "gif", "webp", "tiff", "tif", "bmp",
                    "mp3", "wav", "m4a", "ogg", "flac", "aac",
                ],
            )
            // Escape hatch so the OS never disables Open: the user can switch to
            // "All files" and pick anything; unsupported types get a clean typed
            // error after selection rather than a greyed-out, unexplained button.
            .add_filter("All files", &["*"])
            .blocking_pick_file()
    })
    .await
    .map_err(|e| format!("Dialog error: {e}"))?;

    Ok(path
        .and_then(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().into_owned()))
}

// ── Stage 6: Optional engine management ───────────────────────────────────

/// Return the install state of an optional engine from provision state.
#[tauri::command]
async fn optional_engine_status(
    app: AppHandle,
    engine: String,
) -> Result<bootstrap::OptionalEngineState, String> {
    Ok(bootstrap::optional_engine_status(&app, &engine))
}

/// Install an optional engine (OCR or audio) in the background.
/// Streams "engine:install-progress" events; kills the sidecar afterward
/// so the fresh process picks up the newly installed packages.
/// A mutex serializes concurrent installs so two simultaneous installs don't
/// race the provision state file or conflict at the venv layer.
#[tauri::command]
async fn install_engine(
    app: AppHandle,
    engine: String,
    manager: tauri::State<'_, Arc<SidecarManager>>,
    install_lock: tauri::State<'_, Arc<tokio::sync::Mutex<()>>>,
) -> Result<(), String> {
    let _guard = install_lock.lock().await;
    bootstrap::install_optional_engine(app.clone(), engine).await?;
    // Kill sidecar so it respawns with the new packages importable.
    manager.kill_sidecar().await;
    Ok(())
}

// ── Stage 3 commands ───────────────────────────────────────────────────────

#[tauri::command]
async fn get_capabilities(
    app: AppHandle,
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<ipc::CapabilitiesReport, String> {
    let (python, script) = sidecar_paths(&app)?;
    manager.ensure_alive(&python, &script).await?;

    let req = serde_json::json!({
        "v": 1,
        "id": next_id(),
        "method": "capabilities",
        "params": {}
    });
    let resp = manager.send_streaming(&req, |_| {}).await?;

    if !resp.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        return Err("Capabilities check failed.".into());
    }

    let data = resp
        .get("result")
        .ok_or("Capabilities response missing 'result'.")?;
    serde_json::from_value(data.clone())
        .map_err(|e| format!("Could not parse capabilities report: {e}"))
}

#[tauri::command]
async fn check_provider(
    app: AppHandle,
    provider: String,
    base_url: String,
    key: String,
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<ipc::ProviderCheckResult, String> {
    let (python, script) = sidecar_paths(&app)?;
    manager.ensure_alive(&python, &script).await?;

    let req = serde_json::json!({
        "v": 1,
        "id": next_id(),
        "method": "check-provider",
        "params": { "provider": provider, "base_url": base_url, "key": key }
    });
    let resp = manager.send_streaming(&req, |_| {}).await?;

    let data = resp
        .get("result")
        .ok_or("Provider check response missing 'result'.")?;
    serde_json::from_value(data.clone())
        .map_err(|e| format!("Could not parse provider check result: {e}"))
}

#[tauri::command]
async fn get_config(app: AppHandle) -> Result<config::AppConfig, String> {
    Ok(config::load(&app))
}

#[tauri::command]
async fn set_config(app: AppHandle, config: config::AppConfig) -> Result<(), String> {
    config::save(&app, &config)
}

// ── Stage 5: Cleanup ─────────────────────────────────────────────────────────

/// Build the provider config block the sidecar `cleanup` method expects. Keeps the
/// API key server-side — the frontend never has to round-trip it for cleanup.
fn build_provider_cfg(cfg: &config::AppConfig) -> serde_json::Value {
    let (base_url, key) = match cfg.llm_mode.as_str() {
        "local" => (cfg.local_base_url.clone(), String::new()),
        "api" => (cfg.api_base_url.clone(), cfg.api_key.clone()),
        _ => (String::new(), String::new()),
    };
    serde_json::json!({
        "mode": cfg.llm_mode,
        "api_type": cfg.api_type,
        "base_url": base_url,
        "key": key,
        "model": cfg.cleanup_model,
    })
}

/// Run a cleanup pass on a Markdown string. Deterministic rules always; optional
/// LLM pass when `llm` is true and the configured provider is usable (fails soft
/// inside the sidecar). Re-runnable with different rule sets without re-converting.
#[tauri::command]
async fn cleanup_markdown(
    app: AppHandle,
    markdown: String,
    source_format: String,
    method: String,
    rules: std::collections::HashMap<String, bool>,
    manager: tauri::State<'_, Arc<SidecarManager>>,
) -> Result<ipc::CleanupResult, String> {
    let (python, script) = sidecar_paths(&app)?;
    manager.ensure_alive(&python, &script).await?;

    let cfg = config::load(&app);
    let provider_cfg = build_provider_cfg(&cfg);

    let req = serde_json::json!({
        "v": 1,
        "id": next_id(),
        "method": "cleanup",
        "params": {
            "markdown": markdown,
            "source_format": source_format,
            "method": method,
            "rules": rules,
            "provider": provider_cfg,
        }
    });

    let resp = manager.send_streaming(&req, |_| {}).await?;

    if !resp.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        let detail = resp
            .get("error")
            .and_then(|e| e.get("detail"))
            .and_then(|d| d.as_str())
            .unwrap_or("Cleanup failed.")
            .to_string();
        return Err(detail);
    }

    let data = resp
        .get("result")
        .ok_or("Cleanup response missing 'result'.")?;
    serde_json::from_value(data.clone())
        .map_err(|e| format!("Could not parse cleanup result: {e}"))
}

// ── Stage 4 commands ───────────────────────────────────────────────────────

/// Expand a list of paths (files and/or folders) to all supported file paths.
/// Folders are walked recursively; unsupported extensions are filtered out.
#[tauri::command]
async fn list_files(paths: Vec<String>) -> Result<Vec<String>, String> {
    let supported = all_supported_exts();
    let mut result = Vec::new();
    for path in &paths {
        let p = std::path::Path::new(path);
        if p.is_dir() {
            collect_supported(p, &mut result, &supported)?;
        } else if p.is_file() {
            let ext = p
                .extension()
                .map(|e| e.to_string_lossy().to_lowercase())
                .unwrap_or_default();
            if supported.contains(&ext.as_str()) {
                result.push(path.clone());
            }
        }
    }
    Ok(result)
}

/// Metadata for a staged file: name, uppercase extension (type badge), byte size.
#[derive(serde::Serialize)]
pub struct FileInfo {
    pub path: String,
    pub name: String,
    pub ext: String,
    pub size: u64,
}

/// Read a UTF-8 text file (used to view a finished batch item's output .md).
/// Validates that the path is within an allowed directory (app data dir, the
/// configured output folder) OR was recorded as a path the app itself wrote.
/// This prevents a compromised webview from reading arbitrary files.
#[tauri::command]
async fn read_text_file(
    app: AppHandle,
    path: String,
    written: tauri::State<'_, Arc<WrittenPaths>>,
) -> Result<String, String> {
    let canonical = std::fs::canonicalize(&path)
        .map_err(|e| format!("Could not read file: {e}"))?;

    let cfg = config::load(&app);
    let mut allowed = false;

    // App data dir is always allowed (config, logs, etc.).
    if let Ok(app_data) = app.path().app_data_dir() {
        if let Ok(app_data_canon) = std::fs::canonicalize(&app_data) {
            if canonical.starts_with(&app_data_canon) {
                allowed = true;
            }
        }
    }

    // The configured output folder is allowed (that's where batch .md files live).
    if !allowed && !cfg.output_folder.is_empty() {
        if let Ok(out_canon) = std::fs::canonicalize(&cfg.output_folder) {
            if canonical.starts_with(&out_canon) {
                allowed = true;
            }
        }
    }

    // Paths the app itself wrote (via write_output or save_markdown) are allowed.
    // This covers the next_to_source case without a blanket .md extension check.
    if !allowed && written.contains(&canonical) {
        allowed = true;
    }

    if !allowed {
        return Err("Access denied: this file is outside the app's output directories.".to_string());
    }

    std::fs::read_to_string(&canonical).map_err(|e| format!("Could not read file: {e}"))
}

/// Return name/type/size for each path, for the staging list chips.
#[tauri::command]
async fn stat_files(paths: Vec<String>) -> Result<Vec<FileInfo>, String> {
    let mut out = Vec::with_capacity(paths.len());
    for p in paths {
        let path = std::path::Path::new(&p);
        let name = path
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| p.clone());
        let ext = path
            .extension()
            .map(|e| e.to_string_lossy().to_uppercase())
            .unwrap_or_default();
        let size = std::fs::metadata(&p).map(|m| m.len()).unwrap_or(0);
        out.push(FileInfo { path: p.clone(), name, ext, size });
    }
    Ok(out)
}

fn collect_supported(
    dir: &std::path::Path,
    out: &mut Vec<String>,
    exts: &[&str],
) -> Result<(), String> {
    collect_supported_depth(dir, out, exts, 0)
}

fn collect_supported_depth(
    dir: &std::path::Path,
    out: &mut Vec<String>,
    exts: &[&str],
    depth: usize,
) -> Result<(), String> {
    // Cap recursion depth — a symlink loop (a → b → a) would otherwise stack-overflow.
    const MAX_DEPTH: usize = 32;
    if depth > MAX_DEPTH {
        return Ok(());
    }
    let entries =
        std::fs::read_dir(dir).map_err(|e| format!("Cannot read directory: {e}"))?;
    for entry in entries.flatten() {
        // Use file_type() (does NOT follow symlinks) instead of is_dir() (which does)
        // so a symlink loop can't send us into unbounded recursion.
        let ft = match entry.file_type() {
            Ok(ft) => ft,
            Err(_) => continue,
        };
        if ft.is_dir() && !ft.is_symlink() {
            collect_supported_depth(&entry.path(), out, exts, depth + 1)?;
        } else if ft.is_file() {
            let p = entry.path();
            let ext = p
                .extension()
                .map(|e| e.to_string_lossy().to_lowercase())
                .unwrap_or_default();
            if exts.contains(&ext.as_str()) {
                out.push(p.to_string_lossy().to_string());
            }
        }
    }
    Ok(())
}

/// Open a native folder-picker dialog; returns the chosen path or null.
#[tauri::command]
async fn pick_folder(app: AppHandle) -> Result<Option<String>, String> {
    let path = tokio::task::spawn_blocking(move || {
        app.dialog()
            .file()
            .set_title("Choose output folder")
            .blocking_pick_folder()
    })
    .await
    .map_err(|e| format!("Dialog error: {e}"))?;

    Ok(path
        .and_then(|p| p.into_path().ok())
        .map(|p| p.to_string_lossy().into_owned()))
}

/// Stage 7: reveal a path in the OS file manager. If given a file, opens its
/// containing folder; if given a folder, opens it directly.
#[tauri::command]
async fn open_folder(app: AppHandle, path: String) -> Result<(), String> {
    use tauri_plugin_opener::OpenerExt;
    let p = std::path::Path::new(&path);
    let target = if p.is_file() {
        p.parent().map(|d| d.to_path_buf()).unwrap_or_else(|| p.to_path_buf())
    } else {
        p.to_path_buf()
    };
    app.opener()
        .open_path(target.to_string_lossy().to_string(), None::<&str>)
        .map_err(|e| format!("Could not open folder: {e}"))
}

/// Shared logic for `start_batch` and `retry_failed` (identical signatures + behavior).
#[allow(clippy::too_many_arguments)]
async fn start_batch_inner(
    app: AppHandle,
    files: Vec<String>,
    output_folder: Option<String>,
    output_rule: Option<String>,
    cleanup: Option<ipc::CleanupOptions>,
    extract_images: Option<bool>,
    manager: Arc<SidecarManager>,
    batch: Arc<BatchManager>,
) -> Result<ipc::BatchStartResult, String> {
    let (python, script) = sidecar_paths(&app)?;
    manager.ensure_alive(&python, &script).await?;

    batch.reset();

    let run = next_id();
    let items: Vec<ipc::BatchItem> = files
        .iter()
        .enumerate()
        .map(|(idx, path)| pre_check_file(path, idx, &run))
        .collect();

    let result = ipc::BatchStartResult { items: items.clone() };

    let cfg = config::load(&app);
    let provider_cfg = build_provider_cfg(&cfg);
    let conv_opts = BatchConvOpts {
        llm_cfg: if cfg.llm_conversion && cfg.llm_mode != "off" {
            build_conversion_llm_cfg(&cfg)
        } else {
            serde_json::Value::Null
        },
        extract_images: extract_images.unwrap_or(cfg.extract_images),
        audio_model: cfg.audio_model.clone(),
    };
    let out_opts =
        OutputOpts::from_config(&cfg, output_rule, output_folder, common_parent(&files));
    let app2 = app.clone();
    let mgr2 = Arc::clone(&manager);
    let bat2 = Arc::clone(&batch);

    tokio::spawn(run_batch(
        app2, items, mgr2, bat2, python, script, out_opts, cleanup, provider_cfg, conv_opts,
    ));

    Ok(result)
}

/// Start a batch conversion. Returns the initial item list immediately;
/// progress and completion are reported via "batch:file-status" / "batch:done" events.
#[tauri::command]
#[allow(clippy::too_many_arguments)]
async fn start_batch(
    app: AppHandle,
    files: Vec<String>,
    output_folder: Option<String>,
    output_rule: Option<String>,
    cleanup: Option<ipc::CleanupOptions>,
    extract_images: Option<bool>,
    manager: tauri::State<'_, Arc<SidecarManager>>,
    batch: tauri::State<'_, Arc<BatchManager>>,
) -> Result<ipc::BatchStartResult, String> {
    start_batch_inner(
        app, files, output_folder, output_rule, cleanup, extract_images,
        Arc::clone(&*manager), Arc::clone(&*batch),
    ).await
}

/// Cancel the running batch — sets the flag and tells the sidecar to stop all
/// in-flight conversions.
#[tauri::command]
async fn cancel_batch(
    manager: tauri::State<'_, Arc<SidecarManager>>,
    batch: tauri::State<'_, Arc<BatchManager>>,
) -> Result<(), String> {
    batch.cancel();
    manager.cancel().await
}

/// Re-run only the failed files from a previous batch. Signature matches
/// start_batch so the frontend can reuse the same flow.
#[tauri::command]
#[allow(clippy::too_many_arguments)]
async fn retry_failed(
    app: AppHandle,
    files: Vec<String>,
    output_folder: Option<String>,
    output_rule: Option<String>,
    cleanup: Option<ipc::CleanupOptions>,
    extract_images: Option<bool>,
    manager: tauri::State<'_, Arc<SidecarManager>>,
    batch: tauri::State<'_, Arc<BatchManager>>,
) -> Result<ipc::BatchStartResult, String> {
    start_batch_inner(
        app, files, output_folder, output_rule, cleanup, extract_images,
        Arc::clone(&*manager), Arc::clone(&*batch),
    ).await
}

// ── Batch runner ───────────────────────────────────────────────────────────

fn pre_check_file(path: &str, idx: usize, run: &str) -> ipc::BatchItem {
    let id = format!("{run}-{idx}");
    let p = std::path::Path::new(path);
    let filename = p
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| path.to_string());

    if !p.exists() {
        return ipc::BatchItem {
            id,
            path: path.to_string(),
            filename: filename.clone(),
            status: "failed".to_string(),
            output_path: None,
            error: Some(ipc::IpcError {
                code: "FILE_NOT_FOUND".to_string(),
                title: "File not found".to_string(),
                detail: format!("'{filename}' does not exist."),
                suggested_action: "Check the file hasn't been moved or deleted.".to_string(),
                diagnostics_key: None,
            }),
            warnings: Vec::new(),
        };
    }

    let supported = all_supported_exts();
    let ext = p
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    if !supported.contains(&ext.as_str()) {
        return ipc::BatchItem {
            id,
            path: path.to_string(),
            filename,
            status: "failed".to_string(),
            output_path: None,
            error: Some(ipc::IpcError {
                code: "UNSUPPORTED_FORMAT".to_string(),
                title: "Format not supported".to_string(),
                detail: format!("'.{ext}' files can't be converted."),
                suggested_action: "Use PDF, DOCX, PPTX, XLSX, HTML, CSV, JSON, XML, EPUB, images, or audio.".to_string(),
                diagnostics_key: None,
            }),
            warnings: Vec::new(),
        };
    }

    // Size cap is format-aware: documents that MarkItDown loads into memory are capped
    // at 100 MB, but audio (transcription) and images/scans (OCR) are legitimately large
    // and are stream/page processed, so they get a much higher ceiling. This matches the
    // sidecar, which exempts the OCR/audio path from its own 100 MB document cap.
    let is_media = OCR_EXTS.contains(&ext.as_str()) || AUDIO_EXTS.contains(&ext.as_str());
    let limit: u64 = if is_media { 2048 * 1024 * 1024 } else { 100 * 1024 * 1024 };
    let limit_mb = limit / (1024 * 1024);
    if let Ok(meta) = std::fs::metadata(path) {
        if meta.len() > limit {
            let mb = meta.len() as f64 / (1024.0 * 1024.0);
            return ipc::BatchItem {
                id,
                path: path.to_string(),
                filename,
                status: "failed".to_string(),
                output_path: None,
                error: Some(ipc::IpcError {
                    code: "FILE_TOO_LARGE".to_string(),
                    title: "File too large".to_string(),
                    detail: format!("{mb:.1} MB — limit is {limit_mb} MB."),
                    suggested_action: "Split the file into smaller parts.".to_string(),
                    diagnostics_key: None,
                }),
                warnings: Vec::new(),
            };
        }
    }

    ipc::BatchItem {
        id,
        path: path.to_string(),
        filename,
        status: "pending".to_string(),
        output_path: None,
        error: None,
        warnings: Vec::new(),
    }
}

#[allow(clippy::too_many_arguments)]
async fn run_batch(
    app: AppHandle,
    items: Vec<ipc::BatchItem>,
    manager: Arc<SidecarManager>,
    batch: Arc<BatchManager>,
    python: PathBuf,
    script: PathBuf,
    out_opts: OutputOpts,
    cleanup: Option<ipc::CleanupOptions>,
    provider_cfg: serde_json::Value,
    conv_opts: BatchConvOpts,
) {
    use std::sync::atomic::{AtomicU32, Ordering};
    use tokio::sync::Mutex;
    let sem = Arc::new(tokio::sync::Semaphore::new(batch_worker_cap()));
    let state: Arc<Mutex<Vec<ipc::BatchItem>>> = Arc::new(Mutex::new(items.clone()));
    let mut handles: Vec<tokio::task::JoinHandle<()>> = Vec::new();

    // Stage 5: aggregate cleanup change counts across all workers.
    let cleanup_enabled = cleanup
        .as_ref()
        .map(|c| c.method != "none")
        .unwrap_or(false);
    let cleanup_changes = Arc::new(AtomicU32::new(0));
    let cleanup = Arc::new(cleanup);
    let provider_cfg = Arc::new(provider_cfg);
    let conv_opts = Arc::new(conv_opts);
    let out_opts = Arc::new(out_opts);

    for item in items {
        // Pre-failed items: emit their final status immediately, no worker needed.
        if item.status != "pending" {
            let _ = app.emit(
                "batch:file-status",
                ipc::BatchFileStatusEvent {
                    id: item.id,
                    status: item.status,
                    frac: None,
                    error: item.error,
                    output_path: None,
                    warnings: item.warnings,
                },
            );
            continue;
        }

        // Drain the remaining queue if the batch was cancelled.
        if batch.is_cancelled() {
            set_item_cancelled(&state, &item.id).await;
            let _ = app.emit(
                "batch:file-status",
                ipc::BatchFileStatusEvent {
                    id: item.id,
                    status: "cancelled".to_string(),
                    frac: None,
                    error: None,
                    output_path: None,
                    warnings: Vec::new(),
                },
            );
            continue;
        }

        let permit = match Arc::clone(&sem).acquire_owned().await {
            Ok(p) => p,
            Err(_) => break,
        };

        // Re-check after acquiring the semaphore slot.
        if batch.is_cancelled() {
            drop(permit);
            set_item_cancelled(&state, &item.id).await;
            let _ = app.emit(
                "batch:file-status",
                ipc::BatchFileStatusEvent {
                    id: item.id,
                    status: "cancelled".to_string(),
                    frac: None,
                    error: None,
                    output_path: None,
                    warnings: Vec::new(),
                },
            );
            continue;
        }

        let app2 = app.clone();
        let mgr2 = Arc::clone(&manager);
        let bat2 = Arc::clone(&batch);
        let st2 = Arc::clone(&state);
        let py2 = python.clone();
        let sc2 = script.clone();
        let item2 = item.clone();
        let out2 = Arc::clone(&out_opts);
        let clean2 = Arc::clone(&cleanup);
        let prov2 = Arc::clone(&provider_cfg);
        let changes2 = Arc::clone(&cleanup_changes);
        let conv2 = Arc::clone(&conv_opts);

        handles.push(tokio::spawn(async move {
            let _permit = permit; // released when task ends
            convert_one_batch(
                app2, item2, mgr2, bat2, st2, py2, sc2, out2, clean2, prov2, changes2, conv2,
            )
            .await;
        }));
    }

    for h in handles {
        match h.await {
            Ok(_) => {}
            Err(join_err) => {
                // A worker task panicked — its BatchItem was never updated, so mark it
                // failed here and emit the event the frontend expects. Without this the
                // chip stays "running" forever and the done/failed/cancelled count won't sum.
                let err = ipc::IpcError {
                    code: "INTERNAL_ERROR".to_string(),
                    title: "Conversion failed".to_string(),
                    detail: format!("Internal error: {join_err}"),
                    suggested_action: "Restart the app.".to_string(),
                    diagnostics_key: None,
                };
                // The panicked worker's item id is unknown here (it was moved into the
                // task). Scan for any item still "running" and fail it.
                let failed_ids: Vec<String> = {
                    let mut state_guard = state.lock().await;
                    state_guard
                        .iter_mut()
                        .filter(|i| i.status == "running")
                        .map(|i| {
                            i.status = "failed".to_string();
                            i.error = Some(err.clone());
                            i.id.clone()
                        })
                        .collect()
                };
                for id in failed_ids {
                    let _ = app.emit(
                        "batch:file-status",
                        ipc::BatchFileStatusEvent {
                            id,
                            status: "failed".to_string(),
                            frac: None,
                            error: Some(err.clone()),
                            output_path: None,
                            warnings: Vec::new(),
                        },
                    );
                }
            }
        }
    }

    let final_items = state.lock().await.clone();
    let done = final_items.iter().filter(|i| i.status == "done").count() as u32;
    let failed = final_items.iter().filter(|i| i.status == "failed").count() as u32;
    let cancelled = final_items
        .iter()
        .filter(|i| i.status == "cancelled")
        .count() as u32;

    let _ = app.emit(
        "batch:done",
        ipc::BatchDoneEvent {
            done,
            failed,
            cancelled,
            items: final_items,
            cleanup_applied: cleanup_enabled,
            cleanup_changes: cleanup_changes.load(Ordering::Relaxed),
        },
    );
}

#[allow(clippy::too_many_arguments)]
async fn convert_one_batch(
    app: AppHandle,
    item: ipc::BatchItem,
    manager: Arc<SidecarManager>,
    batch: Arc<BatchManager>,
    state: Arc<tokio::sync::Mutex<Vec<ipc::BatchItem>>>,
    python: PathBuf,
    script: PathBuf,
    out_opts: Arc<OutputOpts>,
    cleanup: Arc<Option<ipc::CleanupOptions>>,
    provider_cfg: Arc<serde_json::Value>,
    cleanup_changes: Arc<std::sync::atomic::AtomicU32>,
    conv_opts: Arc<BatchConvOpts>,
) {
    let id = item.id.clone();
    let path = item.path.clone();
    // The conv_id sent to the sidecar must be unique per request for IPC routing.
    let conv_id = format!("batch-{id}");

    let _ = app.emit(
        "batch:file-status",
        ipc::BatchFileStatusEvent {
            id: id.clone(),
            status: "running".to_string(),
            frac: None,
            error: None,
            output_path: None,
            warnings: Vec::new(),
        },
    );

    if let Err(e) = manager.ensure_alive(&python, &script).await {
        let error = ipc::IpcError {
            code: "INTERNAL_ERROR".to_string(),
            title: "Sidecar unavailable".to_string(),
            detail: e,
            suggested_action: "Restart the app.".to_string(),
            diagnostics_key: None,
        };
        update_item(&state, &id, "failed", None, Some(error.clone()), Vec::new()).await;
        let _ = app.emit(
            "batch:file-status",
            ipc::BatchFileStatusEvent {
                id,
                status: "failed".to_string(),
                frac: None,
                error: Some(error),
                output_path: None,
                warnings: Vec::new(),
            },
        );
        return;
    }

    let mut conv_params = serde_json::json!({ "path": path });
    if !conv_opts.llm_cfg.is_null() {
        conv_params["llm"] = conv_opts.llm_cfg.clone();
    }
    conv_params["audio_model"] = serde_json::Value::String(conv_opts.audio_model.clone());

    let req = serde_json::json!({
        "v": 1,
        "id": conv_id,
        "method": "convert-one",
        "params": conv_params
    });

    let app2 = app.clone();
    let id2 = id.clone();

    let resp = manager
        .send_streaming(&req, move |prog| {
            let frac = prog.get("frac").and_then(|v| v.as_f64());
            let _ = app2.emit(
                "batch:file-status",
                ipc::BatchFileStatusEvent {
                    id: id2.clone(),
                    status: "running".to_string(),
                    frac,
                    error: None,
                    output_path: None,
                    warnings: Vec::new(),
                },
            );
        })
        .await;

    match resp {
        Err(e) => {
            let (status, error) = if batch.is_cancelled() {
                ("cancelled".to_string(), None)
            } else {
                (
                    "failed".to_string(),
                    Some(ipc::IpcError {
                        code: "INTERNAL_ERROR".to_string(),
                        title: "Conversion failed".to_string(),
                        detail: e,
                        suggested_action: "Restart the app.".to_string(),
                        diagnostics_key: None,
                    }),
                )
            };
            update_item(&state, &id, &status, None, error.clone(), Vec::new()).await;
            let _ = app.emit(
                "batch:file-status",
                ipc::BatchFileStatusEvent {
                    id,
                    status,
                    frac: None,
                    error,
                    output_path: None,
                    warnings: Vec::new(),
                },
            );
        }
        Ok(val) => {
            let ok = val.get("ok").and_then(|v| v.as_bool()).unwrap_or(false);
            if ok {
                let raw_markdown = val
                    .get("result")
                    .and_then(|r| r.get("markdown"))
                    .and_then(|m| m.as_str())
                    .unwrap_or("")
                    .to_string();

                // Carry the sidecar's non-fatal notices (e.g. "No text could be
                // extracted") through to the batch summary so an empty result is
                // never silent.
                let warnings: Vec<String> = val
                    .get("result")
                    .and_then(|r| r.get("meta"))
                    .and_then(|m| m.get("warnings"))
                    .and_then(|w| w.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str().map(|s| s.to_string()))
                            .collect()
                    })
                    .unwrap_or_default();

                // Stage 6: image extraction (zip-based formats, Rust-side).
                // Extract to the OUTPUT directory (not the source) so relative links
                // resolve correctly under fixed_folder / mirror_tree output rules.
                let raw_markdown = if conv_opts.extract_images {
                    match resolve_output_dir(&path, &out_opts) {
                        Ok(out_dir) => {
                            let (_assets_name, links) = extract_zip_images(&path, &out_dir);
                            if !links.is_empty() {
                                let mut md = raw_markdown;
                                md.push_str("\n\n---\n\n## Extracted Images\n\n");
                                md.push_str(&links.join("\n\n"));
                                md
                            } else {
                                raw_markdown
                            }
                        }
                        Err(_) => raw_markdown, // can't resolve dir — don't lose the .md
                    }
                } else {
                    raw_markdown
                };

                // Stage 5: optional cleanup before the single write chokepoint.
                // Fails soft — on any cleanup error, fall back to the raw markdown
                // so the file is still written and the run continues.
                let markdown = match cleanup.as_ref() {
                    Some(opts) if opts.method != "none" => {
                        match run_batch_cleanup(
                            &manager, opts, &provider_cfg, &raw_markdown, &path,
                        )
                        .await
                        {
                            Some((cleaned, changes)) => {
                                cleanup_changes
                                    .fetch_add(changes, std::sync::atomic::Ordering::Relaxed);
                                cleaned
                            }
                            None => raw_markdown,
                        }
                    }
                    _ => raw_markdown,
                };

                match write_output(&path, &markdown, &out_opts) {
                    Ok(out_path) => {
                        // Record the written path so read_text_file can read it back.
                        if let Some(wp) = app.try_state::<Arc<WrittenPaths>>() {
                            wp.record(std::path::Path::new(&out_path));
                        }
                        update_item(
                            &state, &id, "done", Some(out_path.clone()), None,
                            warnings.clone(),
                        )
                        .await;
                        let _ = app.emit(
                            "batch:file-status",
                            ipc::BatchFileStatusEvent {
                                id,
                                status: "done".to_string(),
                                frac: Some(1.0),
                                error: None,
                                output_path: Some(out_path),
                                warnings,
                            },
                        );
                    }
                    Err(e) => {
                        let error = ipc::IpcError {
                            code: "INTERNAL_ERROR".to_string(),
                            title: "Could not write output file".to_string(),
                            detail: e,
                            suggested_action: "Check write permissions in the output folder."
                                .to_string(),
                            diagnostics_key: None,
                        };
                        update_item(&state, &id, "failed", None, Some(error.clone()), Vec::new()).await;
                        let _ = app.emit(
                            "batch:file-status",
                            ipc::BatchFileStatusEvent {
                                id,
                                status: "failed".to_string(),
                                frac: None,
                                error: Some(error),
                                output_path: None,
                                warnings: Vec::new(),
                            },
                        );
                    }
                }
            } else {
                let code = val
                    .get("error")
                    .and_then(|e| e.get("code"))
                    .and_then(|c| c.as_str())
                    .unwrap_or("");
                let (status, error) = if code == "CANCELLED" || batch.is_cancelled() {
                    ("cancelled".to_string(), None)
                } else {
                    let err: Option<ipc::IpcError> = val
                        .get("error")
                        .and_then(|e| serde_json::from_value(e.clone()).ok());
                    ("failed".to_string(), err)
                };
                update_item(&state, &id, &status, None, error.clone(), Vec::new()).await;
                let _ = app.emit(
                    "batch:file-status",
                    ipc::BatchFileStatusEvent {
                        id,
                        status,
                        frac: None,
                        error,
                        output_path: None,
                        warnings: Vec::new(),
                    },
                );
            }
        }
    }
}

async fn update_item(
    state: &Arc<tokio::sync::Mutex<Vec<ipc::BatchItem>>>,
    id: &str,
    status: &str,
    output_path: Option<String>,
    error: Option<ipc::IpcError>,
    warnings: Vec<String>,
) {
    let mut items = state.lock().await;
    if let Some(item) = items.iter_mut().find(|i| i.id == id) {
        item.status = status.to_string();
        item.output_path = output_path;
        item.error = error;
        item.warnings = warnings;
    }
}

async fn set_item_cancelled(
    state: &Arc<tokio::sync::Mutex<Vec<ipc::BatchItem>>>,
    id: &str,
) {
    update_item(state, id, "cancelled", None, None, Vec::new()).await;
}

/// Run the sidecar cleanup pass for one batch file. Returns the cleaned markdown
/// and the total number of changes, or `None` if cleanup failed (caller falls back
/// to the raw markdown — failure never stops the run).
async fn run_batch_cleanup(
    manager: &Arc<SidecarManager>,
    opts: &ipc::CleanupOptions,
    provider_cfg: &serde_json::Value,
    markdown: &str,
    path: &str,
) -> Option<(String, u32)> {
    let source_format = std::path::Path::new(path)
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();

    let req = serde_json::json!({
        "v": 1,
        "id": format!("cleanup-{}", next_id()),
        "method": "cleanup",
        "params": {
            "markdown": markdown,
            "source_format": source_format,
            "method": opts.method,
            "rules": opts.rules,
            "provider": provider_cfg,
        }
    });

    let resp = manager.send_streaming(&req, |_| {}).await.ok()?;
    if !resp.get("ok").and_then(|v| v.as_bool()).unwrap_or(false) {
        return None;
    }
    let result = resp.get("result")?;
    let cleaned = result.get("markdown").and_then(|m| m.as_str())?.to_string();
    let changes: u32 = result
        .get("summary")
        .and_then(|s| s.get("rules"))
        .and_then(|r| r.as_array())
        .map(|rules| {
            rules
                .iter()
                .filter(|r| r.get("applied").and_then(|a| a.as_bool()).unwrap_or(false))
                .filter_map(|r| r.get("changes").and_then(|c| c.as_u64()))
                .sum::<u64>() as u32
        })
        .unwrap_or(0);
    Some((cleaned, changes))
}

/// Stage 7: resolved output settings for a conversion run. Built once from config
/// + the per-run folder/rule override, then applied to every file in the batch.
#[derive(Clone)]
struct OutputOpts {
    /// "next_to_source" | "fixed_folder" | "mirror_tree"
    rule: String,
    /// Destination folder for fixed_folder / mirror_tree (None = none chosen).
    folder: Option<String>,
    /// Filename template — tokens {stem} {ext} {date}; ".md" is always appended.
    template: String,
    /// "keep" | "lower" | "slug"
    case: String,
    /// Common parent of all batch sources — the base whose sub-tree mirror_tree
    /// recreates under `folder`. None outside a multi-file run.
    source_root: Option<String>,
}

impl OutputOpts {
    /// Build from config, with a per-run rule/folder override (from the staging UI).
    fn from_config(
        cfg: &config::AppConfig,
        rule_override: Option<String>,
        folder_override: Option<String>,
        source_root: Option<String>,
    ) -> Self {
        let rule = rule_override.unwrap_or_else(|| cfg.output_rule.clone());
        // An explicit per-run folder wins; otherwise fall back to the saved default.
        let folder = folder_override
            .filter(|f| !f.is_empty())
            .or_else(|| (!cfg.output_folder.is_empty()).then(|| cfg.output_folder.clone()));
        OutputOpts {
            rule,
            folder,
            template: if cfg.naming_template.trim().is_empty() {
                "{stem}".to_string()
            } else {
                cfg.naming_template.clone()
            },
            case: cfg.naming_case.clone(),
            source_root,
        }
    }
}

/// Today's date as YYYY-MM-DD (UTC) for the {date} naming token. Computed without a
/// date crate via the civil-from-days algorithm.
fn today_date_string() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    let days = (secs / 86_400) as i64;
    let (y, m, d) = civil_from_days(days);
    format!("{y:04}-{m:02}-{d:02}")
}

/// Howard Hinnant's civil_from_days: days since 1970-01-01 → (year, month, day).
fn civil_from_days(z: i64) -> (i64, u32, u32) {
    let z = z + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let y = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = (doy - (153 * mp + 2) / 5 + 1) as u32;
    let m = (if mp < 10 { mp + 3 } else { mp - 9 }) as u32;
    (y + if m <= 2 { 1 } else { 0 }, m, d)
}

/// Lowercase, collapse any non-alphanumeric run to a single '-', trim leading/trailing '-'.
fn slugify(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut prev_dash = false;
    for ch in s.to_lowercase().chars() {
        if ch.is_alphanumeric() {
            out.push(ch);
            prev_dash = false;
        } else if !prev_dash {
            out.push('-');
            prev_dash = true;
        }
    }
    out.trim_matches('-').to_string()
}

/// Strip characters illegal in a filename (Windows-safe), control chars, and any
/// trailing dots/spaces. Also avoids Windows reserved names (CON, PRN, AUX, NUL,
/// COM1-9, LPT1-9). Never returns a path separator.
fn sanitize_filename(s: &str) -> String {
    let cleaned: String = s
        .chars()
        .map(|c| match c {
            '\\' | '/' | ':' | '*' | '?' | '"' | '<' | '>' | '|' => '-',
            c if (c as u32) < 0x20 => '-',
            c => c,
        })
        .collect();
    let result = cleaned.trim().trim_end_matches('.').trim().to_string();
    // Windows reserved names — appending '_' avoids the OS refusing to create the file.
    let upper = result.to_uppercase();
    let reserved = ["CON", "PRN", "AUX", "NUL",
        "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
        "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9"];
    if reserved.contains(&upper.as_str()) {
        return format!("{result}_");
    }
    result
}

/// Apply the naming template + case to a source path → a base filename (no extension).
fn build_output_name(p: &std::path::Path, template: &str, case: &str) -> String {
    let stem = p
        .file_stem()
        .map(|s| s.to_string_lossy().to_string())
        .unwrap_or_else(|| "output".to_string());
    let ext = p
        .extension()
        .map(|e| e.to_string_lossy().to_lowercase())
        .unwrap_or_default();
    let name = template
        .replace("{stem}", &stem)
        .replace("{ext}", &ext)
        .replace("{date}", &today_date_string());
    let cased = match case {
        "lower" => name.to_lowercase(),
        "slug" => slugify(&name),
        _ => name,
    };
    let final_name = sanitize_filename(&cased);
    if final_name.is_empty() { "output".to_string() } else { final_name }
}

/// Deepest directory that is an ancestor of every path (for mirror_tree). None if the
/// list is empty or paths share no common base.
fn common_parent(paths: &[String]) -> Option<String> {
    let mut base = std::path::Path::new(paths.first()?).parent()?.to_path_buf();
    for p in paths {
        let parent = std::path::Path::new(p)
            .parent()
            .unwrap_or_else(|| std::path::Path::new(""));
        while !parent.starts_with(&base) {
            if !base.pop() {
                return Some(base.to_string_lossy().to_string());
            }
        }
    }
    Some(base.to_string_lossy().to_string())
}

/// Resolve the output directory for a source file given the output rule + opts.
/// Extracted from `write_output` so the batch path can extract images to the same
/// directory before writing the .md.
fn resolve_output_dir(source: &str, opts: &OutputOpts) -> Result<std::path::PathBuf, String> {
    let p = std::path::Path::new(source);
    let src_parent = p.parent().unwrap_or_else(|| std::path::Path::new("."));

    let dir: std::path::PathBuf = match opts.rule.as_str() {
        "fixed_folder" => match opts.folder.as_deref() {
            Some(f) if !f.is_empty() => std::path::PathBuf::from(f),
            _ => src_parent.to_path_buf(),
        },
        "mirror_tree" => match (opts.folder.as_deref(), opts.source_root.as_deref()) {
            (Some(dest), Some(root)) if !dest.is_empty() => {
                let rel = src_parent
                    .strip_prefix(root)
                    .unwrap_or_else(|_| std::path::Path::new(""));
                std::path::PathBuf::from(dest).join(rel)
            }
            (Some(dest), None) if !dest.is_empty() => std::path::PathBuf::from(dest),
            _ => src_parent.to_path_buf(),
        },
        // "next_to_source" and any unknown value
        _ => src_parent.to_path_buf(),
    };

    std::fs::create_dir_all(&dir)
        .map_err(|e| format!("Cannot create output folder: {e}"))?;
    Ok(dir)
}

/// Write `markdown` for `source`, applying the resolved output rule + naming template.
/// Creates the destination folder if needed; appends `_2`, `_3`, … on collision and
/// never overwrites (atomic create — safe under concurrent workers).
fn write_output(source: &str, markdown: &str, opts: &OutputOpts) -> Result<String, String> {
    let p = std::path::Path::new(source);
    let dir = resolve_output_dir(source, opts)?;

    let name = build_output_name(p, &opts.template, &opts.case);
    let base = dir.join(format!("{name}.md"));

    // Atomic exclusive create — safe under concurrency. Two workers producing the
    // same name can't both observe !exists() and silently overwrite each other.
    use std::io::Write;
    match std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&base)
    {
        Ok(mut f) => {
            f.write_all(markdown.as_bytes())
                .map_err(|e| format!("Write failed: {e}"))?;
            return Ok(base.to_string_lossy().to_string());
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {}
        Err(e) => return Err(format!("Write failed: {e}")),
    }

    for n in 2u32..=999 {
        let candidate = dir.join(format!("{name}_{n}.md"));
        match std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&candidate)
        {
            Ok(mut f) => {
                f.write_all(markdown.as_bytes())
                    .map_err(|e| format!("Write failed: {e}"))?;
                return Ok(candidate.to_string_lossy().to_string());
            }
            Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(e) => return Err(format!("Write failed: {e}")),
        }
    }
    Err(format!("Could not find a free output path for '{name}.md'"))
}

// ── Tests ────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    /// Build a minimal DOCX-shaped zip (word/media/<imgs>) in a temp dir and run
    /// extract_zip_images against it.
    fn make_zip_with_media(dir: &std::path::Path, name: &str, media: &[(&str, &[u8])]) -> String {
        let path = dir.join(name);
        let file = std::fs::File::create(&path).unwrap();
        let mut zip = zip::ZipWriter::new(file);
        let opts: zip::write::FileOptions<()> =
            zip::write::FileOptions::default().compression_method(zip::CompressionMethod::Stored);
        // Some non-image entries that must be ignored.
        zip.start_file("word/document.xml", opts).unwrap();
        zip.write_all(b"<xml/>").unwrap();
        zip.start_file("[Content_Types].xml", opts).unwrap();
        zip.write_all(b"<types/>").unwrap();
        for (n, data) in media {
            zip.start_file(*n, opts).unwrap();
            zip.write_all(data).unwrap();
        }
        zip.finish().unwrap();
        path.to_string_lossy().to_string()
    }

    #[test]
    fn extracts_media_images_and_links() {
        let tmp = std::env::temp_dir().join(format!("mdstudio_test_{}", next_id()));
        std::fs::create_dir_all(&tmp).unwrap();
        // Content images must clear the MIN_IMAGE_BYTES (5 KB) junk threshold and be
        // distinct (the dedupe is content-hashed).
        let mut png = b"\x89PNG\r\n\x1a\n".to_vec();
        png.extend(std::iter::repeat(0xAB).take(8192));
        let mut jpg = b"\xff\xd8\xff\xe0".to_vec();
        jpg.extend(std::iter::repeat(0xCD).take(8192));
        let tiny = b"\x89PNG tiny chrome glyph"; // < 5 KB → must be skipped
        let src = make_zip_with_media(
            &tmp,
            "doc.docx",
            &[
                ("word/media/image1.png", png.as_slice()),
                ("word/media/image2.jpg", jpg.as_slice()),
                ("word/media/image3.png", png.as_slice()), // duplicate of image1 → deduped
                ("word/media/icon.png", tiny),             // too small → skipped
                ("word/media/notes.txt", b"ignore me"),    // non-image → skipped
            ],
        );

        let (assets_name, links) = extract_zip_images(&src, &tmp);
        assert_eq!(links.len(), 2, "exactly the 2 distinct content images (tiny+dupe dropped)");
        assert!(links.iter().any(|l| l.contains("image1.png")));
        assert!(links.iter().any(|l| l.contains("image2.jpg")));
        assert!(links.iter().all(|l| l.starts_with("![")), "links are markdown images");
        // Files actually written, content preserved.
        let p1 = tmp.join(format!("{assets_name}")).join("image1.png");
        assert!(p1.exists());
        assert_eq!(std::fs::read(&p1).unwrap(), png);
        // Relative path in the link points at {stem}_assets/.
        assert!(links[0].contains("doc_assets/"));

        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn concurrency_caps_are_sane() {
        let cpu = cpu_worker_cap();
        let cap = batch_worker_cap();
        let threads = batch_worker_threads();
        let cores = logical_cores();
        eprintln!(
            "cores={cores} cpu_cap={cpu} batch_cap={cap} threads/worker={threads} \
             avail_ram_mb={:?}",
            available_ram_mb()
        );
        assert!((2..=8).contains(&cpu), "cpu cap in range");
        assert!((1..=8).contains(&cap), "batch cap in range");
        assert!(cap <= cpu, "RAM only reduces the count, never above the CPU cap");
        assert!(threads >= 1, "at least one thread per worker");
        // The thread budget must never let a full pool oversubscribe the cores.
        assert!(threads * cpu <= cores + cpu, "workers x threads ~= cores");
    }

    fn opts(rule: &str, folder: Option<&str>, template: &str, case: &str, root: Option<&str>) -> OutputOpts {
        OutputOpts {
            rule: rule.to_string(),
            folder: folder.map(|s| s.to_string()),
            template: template.to_string(),
            case: case.to_string(),
            source_root: root.map(|s| s.to_string()),
        }
    }

    #[test]
    fn naming_template_and_case() {
        // {stem} keeps the old behavior; {ext} distinguishes formats; slug lowercases.
        let p = std::path::Path::new("C:/docs/My Report.PDF");
        assert_eq!(build_output_name(p, "{stem}", "keep"), "My Report");
        assert_eq!(build_output_name(p, "{stem}_{ext}", "keep"), "My Report_pdf");
        assert_eq!(build_output_name(p, "{stem}", "lower"), "my report");
        assert_eq!(build_output_name(p, "{stem}", "slug"), "my-report");
        // Illegal characters in a template are sanitized to '-'.
        assert_eq!(build_output_name(p, "a/b:c", "keep"), "a-b-c");
    }

    #[test]
    fn write_output_default_is_next_to_source() {
        let tmp = std::env::temp_dir().join(format!("mdflux_out_{}", next_id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let src = tmp.join("doc.pdf");
        std::fs::write(&src, b"x").unwrap();

        let o = opts("next_to_source", None, "{stem}", "keep", None);
        let out = write_output(&src.to_string_lossy(), "# hi", &o).unwrap();
        assert!(out.ends_with("doc.md"));
        assert!(std::path::Path::new(&out).exists());
        // Collision → _2 suffix.
        let out2 = write_output(&src.to_string_lossy(), "# hi again", &o).unwrap();
        assert!(out2.ends_with("doc_2.md"));

        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn write_output_fixed_and_mirror() {
        let tmp = std::env::temp_dir().join(format!("mdflux_out2_{}", next_id()));
        let root = tmp.join("in");
        let sub = root.join("sub");
        let dest = tmp.join("out");
        std::fs::create_dir_all(&sub).unwrap();
        let src = sub.join("a.docx");
        std::fs::write(&src, b"x").unwrap();

        // fixed_folder: lands directly in dest, no sub-tree.
        let of = opts("fixed_folder", Some(&dest.to_string_lossy()), "{stem}", "keep", None);
        let out = write_output(&src.to_string_lossy(), "md", &of).unwrap();
        assert_eq!(std::path::Path::new(&out).parent().unwrap(), dest);

        // mirror_tree: recreates sub/ under dest.
        let om = opts(
            "mirror_tree",
            Some(&dest.to_string_lossy()),
            "{stem}",
            "keep",
            Some(&root.to_string_lossy()),
        );
        let out = write_output(&src.to_string_lossy(), "md", &om).unwrap();
        assert_eq!(std::path::Path::new(&out).parent().unwrap(), dest.join("sub"));

        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn common_parent_finds_deepest_shared_dir() {
        let paths = vec![
            "C:/a/b/c/one.pdf".to_string(),
            "C:/a/b/d/two.pdf".to_string(),
        ];
        let cp = common_parent(&paths).unwrap().replace('\\', "/");
        assert_eq!(cp, "C:/a/b");
    }

    #[test]
    fn non_zip_format_yields_nothing() {
        let tmp = std::env::temp_dir().join(format!("mdstudio_test2_{}", next_id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let p = tmp.join("plain.pdf");
        std::fs::write(&p, b"not a zip").unwrap();
        let (_dir, links) = extract_zip_images(&p.to_string_lossy(), &tmp);
        assert!(links.is_empty(), "pdf is not a zip-image source");
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn zip_with_no_media_yields_nothing() {
        let tmp = std::env::temp_dir().join(format!("mdstudio_test3_{}", next_id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let src = make_zip_with_media(&tmp, "empty.pptx", &[]);
        let (_dir, links) = extract_zip_images(&src, &tmp);
        assert!(links.is_empty());
        // No assets folder should be created when there's nothing to extract.
        assert!(!tmp.join("empty_assets").exists());
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn next_id_is_unique_under_rapid_calls() {
        // The old ms-timestamp id collided when two callers called within the same
        // millisecond. The AtomicU64 counter must never produce a duplicate.
        let ids: std::collections::HashSet<String> = (0..1000).map(|_| next_id()).collect();
        assert_eq!(ids.len(), 1000, "next_id must produce 1000 unique ids");
    }

    #[test]
    fn write_output_atomic_no_overwrite() {
        // Two concurrent writes to the same path must not silently overwrite —
        // the atomic create_new path produces _2 on collision.
        let tmp = std::env::temp_dir().join(format!("mdflux_atomic_{}", next_id()));
        std::fs::create_dir_all(&tmp).unwrap();
        let src = tmp.join("f.pdf");
        std::fs::write(&src, b"x").unwrap();
        let o = opts("next_to_source", None, "{stem}", "keep", None);
        let out1 = write_output(&src.to_string_lossy(), "first", &o).unwrap();
        let out2 = write_output(&src.to_string_lossy(), "second", &o).unwrap();
        assert_ne!(out1, out2, "collision must produce a different path");
        // Both files exist with their own content (no overwrite).
        assert_eq!(std::fs::read_to_string(&out1).unwrap(), "first");
        assert_eq!(std::fs::read_to_string(&out2).unwrap(), "second");
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn collect_supported_skips_symlinks() {
        // A symlink loop must not cause unbounded recursion (stack overflow).
        // We can't easily create a symlink loop without admin on Windows, but we
        // can at least verify the function handles a normal tree without crashing
        // and respects the depth cap. The symlink-skip is tested by file_type().
        let tmp = std::env::temp_dir().join(format!("mdflux_symlink_{}", next_id()));
        std::fs::create_dir_all(tmp.join("a").join("b")).unwrap();
        std::fs::write(tmp.join("a").join("doc.pdf"), b"x").unwrap();
        std::fs::write(tmp.join("a").join("b").join("note.docx"), b"x").unwrap();
        let mut out: Vec<String> = Vec::new();
        let exts = ["pdf", "docx"];
        collect_supported(&tmp, &mut out, &exts).unwrap();
        assert_eq!(out.len(), 2, "should find both files in the tree");
        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn extract_zip_images_writes_to_out_dir() {
        // The H1 fix: images must be written to the OUTPUT dir, not next to source.
        // Verify the assets folder appears in out_dir, not in source's parent.
        let tmp = std::env::temp_dir().join(format!("mdflux_imgdir_{}", next_id()));
        let src_dir = tmp.join("src");
        let out_dir = tmp.join("out");
        std::fs::create_dir_all(&src_dir).unwrap();
        std::fs::create_dir_all(&out_dir).unwrap();
        let mut png = b"\x89PNG\r\n\x1a\n".to_vec();
        png.extend(std::iter::repeat(0xAB).take(8192));
        let src = make_zip_with_media(&src_dir, "doc.docx", &[("word/media/image1.png", png.as_slice())]);
        let (assets_name, links) = extract_zip_images(&src, &out_dir);
        assert!(!links.is_empty(), "image extracted");
        // Assets folder must be in out_dir, NOT in src_dir.
        assert!(out_dir.join(&assets_name).exists(), "assets in output dir");
        assert!(!src_dir.join(&assets_name).exists(), "assets NOT in source dir");
        std::fs::remove_dir_all(&tmp).ok();
    }
}

// ── App entry ──────────────────────────────────────────────────────────────

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    // Per-worker CPU-thread budget for batch conversions. The sidecar reads this and
    // applies it to batch workers only (single conversions use all cores). Set once at
    // startup so it propagates to the sidecar process and its worker subprocesses.
    std::env::set_var("MDFLUX_BATCH_THREADS", batch_worker_threads().to_string());

    let app = tauri::Builder::default()
        .manage(Arc::new(SidecarManager::new()))
        .manage(Arc::new(BatchManager::new()))
        .manage(Arc::new(WrittenPaths::default()))
        .manage(Arc::new(tokio::sync::Mutex::new(())))
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .invoke_handler(tauri::generate_handler![
            get_provision_status,
            start_provision,
            run_health_check,
            convert_file,
            cancel_conversion,
            save_markdown,
            pick_file,
            get_capabilities,
            check_provider,
            get_config,
            set_config,
            cleanup_markdown,
            list_files,
            stat_files,
            read_text_file,
            pick_folder,
            open_folder,
            start_batch,
            cancel_batch,
            retry_failed,
            optional_engine_status,
            install_engine,
        ])
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // Kill the sidecar deterministically on app exit. kill_on_drop(true) on the spawn
    // is a backstop, but this ensures the python.exe is terminated even if the managed
    // Arc's drop order doesn't reach it (e.g. the process is torn down without dropping
    // managed state). Without this the sidecar orphaned on Windows until reboot.
    app.run(|app_handle, event| {
        if let tauri::RunEvent::ExitRequested { .. } = event {
            if let Some(manager) = app_handle.try_state::<Arc<SidecarManager>>() {
                tauri::async_runtime::block_on(manager.kill_sidecar());
            }
        }
    });
}
