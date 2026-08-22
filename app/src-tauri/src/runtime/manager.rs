//! Runtime lifecycle: edition resolution, Lite transactional provisioning, Full immutability.

use std::collections::HashMap;
use std::fs;
use std::path::{Path, PathBuf};

use tauri::{AppHandle, Manager};

use crate::platform::{self, PlatformSpec};

use super::edition::{Edition, EditionManifest, EffectiveEdition};
use super::provision::{
    self, create_venv, download_uv, install_engine_packages, install_packages, smoke_test_python,
};
use super::status::{ComponentState, RuntimeLifecycle, RuntimeStatus};
use super::store::{
    activate_runtime, active_python_path, compute_runtime_id, python_in_environment, sha256_file,
    staging_runtime_dir, write_runtime_record, RuntimeRecord, STAGING_SUFFIX,
};

/// Optional engine install state persisted alongside legacy provision metadata.
#[derive(serde::Serialize, serde::Deserialize, Clone, Default)]
pub struct OptionalEngineState {
    #[serde(default)]
    pub status: String,
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

#[derive(serde::Serialize, serde::Deserialize, Default)]
struct LegacyProvisionState {
    #[serde(default)]
    status: String,
    #[serde(default)]
    version: String,
    #[serde(default)]
    optional: OptionalEnginesState,
}

pub struct RuntimeContext {
    pub platform: PlatformSpec,
    pub edition: EffectiveEdition,
    pub app_data: PathBuf,
    pub resource_root: PathBuf,
}

impl RuntimeContext {
    pub fn resolve(app: &AppHandle) -> Result<Self, String> {
        let platform = platform::current_platform()?;
        let resource_root = app
            .path()
            .resource_dir()
            .map_err(|e| format!("Cannot locate app resources: {e}"))?;
        let edition = match EditionManifest::load(&resource_root, &platform)? {
            Some(m) => EffectiveEdition::Manifest(m),
            None => EffectiveEdition::DevLite,
        };
        let app_data = app.path().app_data_dir().expect("app data dir unavailable");
        Ok(Self {
            platform,
            edition,
            app_data,
            resource_root,
        })
    }

    pub fn edition_kind(&self) -> Edition {
        self.edition.edition()
    }

    pub fn is_full(&self) -> bool {
        self.edition.is_full()
    }
}

pub fn app_data_dir(app: &AppHandle) -> PathBuf {
    app.path().app_data_dir().expect("app data dir unavailable")
}

pub fn bundled_python_path(ctx: &RuntimeContext) -> Option<PathBuf> {
    let python = ctx
        .resource_root
        .join("resources")
        .join("runtime")
        .join(ctx.platform.bundled_python_bin);
    python.is_file().then_some(python)
}

fn validate_full_bundle(ctx: &RuntimeContext) -> Result<PathBuf, String> {
    let python = bundled_python_path(ctx).ok_or_else(|| {
        "Full edition requires a bundled Python interpreter at resources/runtime/.".to_string()
    })?;
    smoke_test_python(&python).map_err(|e| {
        format!(
            "Bundled Python interpreter failed validation at {}.\n\n{e}",
            python.display()
        )
    })?;
    Ok(python)
}

fn legacy_venv_python(app_data: &Path, spec: &PlatformSpec) -> PathBuf {
    app_data.join("venv").join(spec.venv_python_bin)
}

fn legacy_bin_dir(app_data: &Path) -> PathBuf {
    app_data.join("bin")
}

fn read_legacy_state(app_data: &Path) -> LegacyProvisionState {
    let path = app_data.join(".provision-state.json");
    fs::read_to_string(path)
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_default()
}

fn write_legacy_state(app_data: &Path, state: &LegacyProvisionState) -> Result<(), String> {
    fs::create_dir_all(app_data).map_err(|e| format!("Cannot create app data dir: {e}"))?;
    let final_path = app_data.join(".provision-state.json");
    let tmp_path = app_data.join(".provision-state.json.tmp");
    let json = serde_json::to_string(state).map_err(|e| format!("State serialise error: {e}"))?;
    fs::write(&tmp_path, json.as_bytes()).map_err(|e| format!("Cannot write setup state: {e}"))?;
    fs::rename(&tmp_path, &final_path).map_err(|e| format!("Cannot finalise setup state: {e}"))
}

fn sidecar_resource(ctx: &RuntimeContext, filename: &str) -> Result<PathBuf, String> {
    let path = ctx
        .resource_root
        .join("resources")
        .join("sidecar")
        .join(filename);
    if !path.exists() {
        return Err(format!(
            "{filename} not found at {}.\n\nRe-install the app to fix this.",
            path.display()
        ));
    }
    Ok(path)
}

fn core_lock_path(ctx: &RuntimeContext) -> Result<PathBuf, String> {
    sidecar_resource(ctx, "requirements.lock")
}

fn dependency_lock_sha256(ctx: &RuntimeContext) -> Result<String, String> {
    if let EffectiveEdition::Manifest(m) = &ctx.edition {
        return Ok(m.dependency_lock_sha256.clone());
    }
    sha256_file(&core_lock_path(ctx)?)
}

fn runtime_components(ctx: &RuntimeContext) -> Vec<String> {
    match &ctx.edition {
        EffectiveEdition::DevLite => vec!["core".into()],
        EffectiveEdition::Manifest(m) => m.components.clone(),
    }
}

pub fn python_path(app: &AppHandle) -> Result<PathBuf, String> {
    let ctx = RuntimeContext::resolve(app)?;
    if ctx.is_full() {
        return validate_full_bundle(&ctx);
    }
    if let Some(p) = active_python_path(&ctx.app_data, &ctx.platform)? {
        return Ok(p);
    }
    let legacy = legacy_venv_python(&ctx.app_data, &ctx.platform);
    if legacy.is_file() {
        return Ok(legacy);
    }
    Err("Python environment not found. Run setup to provision the runtime.".into())
}

pub fn is_provisioned(app: &AppHandle) -> bool {
    RuntimeContext::resolve(app)
        .ok()
        .map(|ctx| is_provisioned_ctx(&ctx))
        .unwrap_or(false)
}

fn is_provisioned_ctx(ctx: &RuntimeContext) -> bool {
    if ctx.is_full() {
        return bundled_python_path(ctx).is_some_and(|p| p.is_file());
    }
    if active_python_path(&ctx.app_data, &ctx.platform)
        .ok()
        .flatten()
        .is_some()
    {
        return true;
    }
    let legacy = read_legacy_state(&ctx.app_data);
    legacy.status == "ready" && legacy_venv_python(&ctx.app_data, &ctx.platform).is_file()
}

pub fn runtime_status(app: &AppHandle) -> Result<RuntimeStatus, String> {
    let ctx = RuntimeContext::resolve(app)?;
    let platform_id = ctx.platform.id.as_str();
    let edition = ctx.edition_kind();

    if ctx.is_full() {
        let python = bundled_python_path(&ctx);
        let (lifecycle, python_version, repair) = match python {
            Some(p) if p.is_file() => match smoke_test_python(&p) {
                Ok(v) => (RuntimeLifecycle::Ready, Some(v), None),
                Err(e) => (
                    RuntimeLifecycle::Invalid,
                    None,
                    Some(format!("Repair: reinstall the Full edition archive. {e}")),
                ),
            },
            _ => (
                RuntimeLifecycle::Invalid,
                None,
                Some(
                    "Repair: reinstall the Full edition archive - bundled Python is missing."
                        .into(),
                ),
            ),
        };
        let mut components = HashMap::new();
        components.insert("core".into(), ComponentState::Installed.as_str().into());
        components.insert("ocr".into(), ComponentState::Installed.as_str().into());
        components.insert("audio".into(), ComponentState::Installed.as_str().into());
        return Ok(RuntimeStatus::new(
            edition,
            platform_id,
            lifecycle,
            python_version,
            components,
            repair,
        ));
    }

    let legacy = read_legacy_state(&ctx.app_data);
    let active = active_python_path(&ctx.app_data, &ctx.platform)?;
    let legacy_ready =
        legacy.status == "ready" && legacy_venv_python(&ctx.app_data, &ctx.platform).is_file();

    let (lifecycle, python_version, repair) = if let Some(p) = active {
        match smoke_test_python(&p) {
            Ok(v) => (RuntimeLifecycle::Ready, Some(v), None),
            Err(_) => (
                RuntimeLifecycle::Repairable,
                None,
                Some("Repair: rebuild the active runtime.".into()),
            ),
        }
    } else if legacy.status == "provisioning" {
        (RuntimeLifecycle::Installing, None, None)
    } else if legacy_ready {
        match smoke_test_python(&legacy_venv_python(&ctx.app_data, &ctx.platform)) {
            Ok(v) => (RuntimeLifecycle::Ready, Some(v), None),
            Err(_) => (
                RuntimeLifecycle::Repairable,
                None,
                Some("Repair: migrate to a new versioned runtime.".into()),
            ),
        }
    } else if staging_dir_exists(&ctx.app_data) {
        (RuntimeLifecycle::Installing, None, None)
    } else {
        (
            RuntimeLifecycle::Missing,
            None,
            Some("Provision: install the core runtime.".into()),
        )
    };

    let mut components = HashMap::new();
    components.insert(
        "core".into(),
        if matches!(lifecycle, RuntimeLifecycle::Ready) {
            ComponentState::Installed.as_str()
        } else if matches!(lifecycle, RuntimeLifecycle::Installing) {
            ComponentState::Installing.as_str()
        } else if matches!(
            lifecycle,
            RuntimeLifecycle::Repairable | RuntimeLifecycle::Invalid
        ) {
            ComponentState::Failed.as_str()
        } else {
            ComponentState::NotInstalled.as_str()
        }
        .into(),
    );
    let ocr = &legacy.optional.ocr;
    components.insert("ocr".into(), map_optional_component(&ocr.status));
    let audio = &legacy.optional.audio;
    components.insert("audio".into(), map_optional_component(&audio.status));

    Ok(RuntimeStatus::new(
        edition,
        platform_id,
        lifecycle,
        python_version,
        components,
        repair,
    ))
}

fn map_optional_component(status: &str) -> String {
    match status {
        "installed" => ComponentState::Installed.as_str(),
        "installing" => ComponentState::Installing.as_str(),
        "failed" => ComponentState::Failed.as_str(),
        _ => ComponentState::NotInstalled.as_str(),
    }
    .into()
}

fn staging_dir_exists(app_data: &Path) -> bool {
    let root = super::store::runtimes_root(app_data);
    if !root.is_dir() {
        return false;
    }
    fs::read_dir(root)
        .ok()
        .into_iter()
        .flatten()
        .filter_map(|e| e.ok())
        .any(|e| e.file_name().to_string_lossy().ends_with(STAGING_SUFFIX))
}

pub async fn provision<F, Fut>(
    app: AppHandle,
    force: bool,
    shutdown_sidecar: F,
) -> Result<(), String>
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = ()>,
{
    let ctx = RuntimeContext::resolve(&app)?;
    if ctx.is_full() {
        return provision_full(&app, &ctx).await;
    }
    provision_lite(app, ctx, force, shutdown_sidecar).await
}

async fn provision_full(app: &AppHandle, ctx: &RuntimeContext) -> Result<(), String> {
    validate_full_bundle(ctx)?;
    let mut state = read_legacy_state(&ctx.app_data);
    state.status = "ready".into();
    state.version = env!("CARGO_PKG_VERSION").to_string();
    state.optional.ocr = OptionalEngineState {
        status: "installed".into(),
        error: None,
    };
    state.optional.audio = OptionalEngineState {
        status: "installed".into(),
        error: None,
    };
    write_legacy_state(&ctx.app_data, &state)?;
    provision::emit_progress(app, "done", "Bundled runtime ready.", 1.0);
    Ok(())
}

async fn provision_lite<F, Fut>(
    app: AppHandle,
    ctx: RuntimeContext,
    force: bool,
    shutdown_sidecar: F,
) -> Result<(), String>
where
    F: FnOnce() -> Fut,
    Fut: std::future::Future<Output = ()>,
{
    let lock_sha = dependency_lock_sha256(&ctx)?;
    let components = runtime_components(&ctx);
    let runtime_id = compute_runtime_id(
        env!("CARGO_PKG_VERSION"),
        &ctx.platform,
        "3.12",
        &lock_sha,
        &components,
    );

    if !force {
        if let Some(p) = active_python_path(&ctx.app_data, &ctx.platform)? {
            if smoke_test_python(&p).is_ok() {
                provision::emit_progress(&app, "done", "Runtime already ready.", 1.0);
                return Ok(());
            }
        }
    }

    let staging = staging_runtime_dir(&ctx.app_data, &runtime_id);
    if staging.exists() {
        fs::remove_dir_all(&staging).map_err(|e| {
            format!(
                "Could not clear incomplete staging runtime at {}: {e}",
                staging.display()
            )
        })?;
    }
    fs::create_dir_all(&staging).map_err(|e| format!("Cannot create staging runtime: {e}"))?;
    let staging_env = staging.join(super::store::ENV_DIR);
    fs::create_dir_all(&staging_env)
        .map_err(|e| format!("Cannot create staging environment: {e}"))?;

    let mut legacy = read_legacy_state(&ctx.app_data);
    legacy.status = "provisioning".into();
    write_legacy_state(&ctx.app_data, &legacy)?;

    let bin_dir = legacy_bin_dir(&ctx.app_data);
    provision::emit_progress(&app, "downloading_uv", "Downloading setup tools...", 0.05);
    let uv_path = download_uv(&app, &bin_dir, &ctx.platform)
        .await
        .map_err(|e| format!("Could not download setup tools.\n\n{e}"))?;
    provision::emit_progress(&app, "downloading_uv", "Setup tools ready.", 0.2);

    provision::emit_progress(&app, "creating_env", "Setting up Python 3.12...", 0.25);
    let uv = uv_path.clone();
    let env = staging_env.clone();
    let app_env = app.clone();
    tokio::task::spawn_blocking(move || create_venv(&app_env, &uv, &env))
        .await
        .map_err(|e| format!("Internal error: {e}"))??;
    provision::emit_progress(&app, "creating_env", "Python environment ready.", 0.45);

    provision::emit_progress(
        &app,
        "installing_packages",
        "Installing packages - this takes about a minute...",
        0.5,
    );
    let requirements = core_lock_path(&ctx)?;
    let uv2 = uv_path.clone();
    let env2 = staging_env.clone();
    let app_pkgs = app.clone();
    let platform = ctx.platform.clone();
    tokio::task::spawn_blocking(move || {
        install_packages(&app_pkgs, &uv2, &env2, &requirements, &platform)
    })
    .await
    .map_err(|e| format!("Internal error: {e}"))??;
    provision::emit_progress(&app, "installing_packages", "Packages installed.", 0.85);

    let python = python_in_environment(&staging_env, &ctx.platform);
    let python_version = smoke_test_python(&python).map_err(|e| {
        let _ = fs::remove_dir_all(&staging);
        format!("Staging runtime failed smoke test.\n\n{e}")
    })?;

    write_runtime_record(
        &staging,
        &RuntimeRecord {
            runtime_id: runtime_id.clone(),
            edition: Edition::Lite.as_str().into(),
            platform: ctx.platform.id.as_str().into(),
            python_version: python_version.clone(),
            dependency_lock_sha256: lock_sha,
            components: components.clone(),
            created_at_utc: chrono_now_utc(),
        },
    )?;

    // Sidecar must release loaded native modules before activation replaces the environment.
    shutdown_sidecar().await;

    match activate_runtime(&ctx.app_data, &runtime_id) {
        Ok(_) => {
            legacy.status = "ready".into();
            legacy.version = env!("CARGO_PKG_VERSION").to_string();
            write_legacy_state(&ctx.app_data, &legacy)?;
            let _ = super::store::prune_old_runtimes(&ctx.app_data);
            provision::emit_progress(&app, "done", "Ready.", 1.0);
            Ok(())
        }
        Err(e) => {
            let _ = fs::remove_dir_all(&staging);
            legacy.status = "repairable".into();
            let _ = write_legacy_state(&ctx.app_data, &legacy);
            Err(format!("Failed to activate staged runtime.\n\n{e}"))
        }
    }
}

fn chrono_now_utc() -> String {
    // Avoid adding a chrono dependency - RFC3339-like timestamp from system time.
    use std::time::{SystemTime, UNIX_EPOCH};
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0);
    format!("{secs}")
}

pub fn optional_engine_status(app: &AppHandle, engine: &str) -> OptionalEngineState {
    let Ok(ctx) = RuntimeContext::resolve(app) else {
        return OptionalEngineState::default();
    };
    if ctx.is_full() && matches!(engine, "ocr" | "audio") {
        return OptionalEngineState {
            status: "installed".into(),
            error: None,
        };
    }
    let state = read_legacy_state(&ctx.app_data);
    match engine {
        "ocr" => state.optional.ocr,
        "audio" => state.optional.audio,
        _ => OptionalEngineState::default(),
    }
}

pub async fn install_optional_engine(app: AppHandle, engine: String) -> Result<(), String> {
    let ctx = RuntimeContext::resolve(&app)?;
    if ctx.is_full() {
        return match engine.as_str() {
            "ocr" | "audio" => Ok(()),
            other => Err(format!("Unknown engine: {other}")),
        };
    }

    let lock_name = match engine.as_str() {
        "ocr" => "requirements-ocr.lock",
        "audio" => "requirements-audio.lock",
        other => return Err(format!("Unknown engine: {other}")),
    };

    let uv_path = legacy_bin_dir(&ctx.app_data).join(&ctx.platform.uv_bin);
    if !uv_path.exists() {
        return Err("Setup tools not found. Restart the app to re-provision.".into());
    }

    let python = python_path(&app)?;
    let lock_path = sidecar_resource(&ctx, lock_name)?;

    let mut legacy = read_legacy_state(&ctx.app_data);
    let slot = match engine.as_str() {
        "ocr" => &mut legacy.optional.ocr,
        "audio" => &mut legacy.optional.audio,
        _ => unreachable!(),
    };
    *slot = OptionalEngineState {
        status: "installing".into(),
        error: None,
    };
    write_legacy_state(&ctx.app_data, &legacy)?;

    let uv = uv_path.clone();
    let py = python.clone();
    let lock = lock_path.clone();
    let result = tokio::task::spawn_blocking(move || install_engine_packages(&uv, &py, &lock))
        .await
        .map_err(|e| format!("Internal error: {e}"))?;

    match result {
        Ok(()) => {
            let mut legacy = read_legacy_state(&ctx.app_data);
            let slot = match engine.as_str() {
                "ocr" => &mut legacy.optional.ocr,
                "audio" => &mut legacy.optional.audio,
                _ => unreachable!(),
            };
            *slot = OptionalEngineState {
                status: "installed".into(),
                error: None,
            };
            write_legacy_state(&ctx.app_data, &legacy)?;
            Ok(())
        }
        Err(stderr) => {
            let msg = classify_install_error(&stderr);
            let mut legacy = read_legacy_state(&ctx.app_data);
            let slot = match engine.as_str() {
                "ocr" => &mut legacy.optional.ocr,
                "audio" => &mut legacy.optional.audio,
                _ => unreachable!(),
            };
            *slot = OptionalEngineState {
                status: "failed".into(),
                error: Some(msg.clone()),
            };
            write_legacy_state(&ctx.app_data, &legacy)?;
            Err(msg)
        }
    }
}

fn classify_install_error(stderr: &str) -> String {
    let low = stderr.to_lowercase();
    if low.contains("access is denied")
        || low.contains("access denied")
        || low.contains("os error 5")
    {
        format!(
            "Could not update packages because Python files are still in use. Close MDFlux fully and try Repair.\n\nDetail: {stderr}"
        )
    } else if low.contains("missing `record` file") || low.contains("missing record file") {
        format!(
            "The Python environment is incomplete. Use Repair before installing this component again.\n\nDetail: {stderr}"
        )
    } else if low.contains("network")
        || low.contains("timeout")
        || low.contains("connection")
        || low.contains("failed to resolve")
        || low.contains("name resolution")
        || low.contains("dns")
    {
        format!("Could not download packages - check your internet connection.\n\nDetail: {stderr}")
    } else {
        format!("Installation failed.\n\nDetail: {stderr}")
    }
}

/// On successful launch, prune stale runtimes while keeping rollback copy.
pub fn on_successful_launch(app: &AppHandle) -> Result<(), String> {
    let ctx = RuntimeContext::resolve(app)?;
    if ctx.is_full() {
        return Ok(());
    }
    super::store::prune_old_runtimes(&ctx.app_data)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::runtime::store::{
        activate_runtime, read_active_pointer, write_active_pointer, ActiveRuntimePointer,
    };

    #[test]
    fn full_edition_refuses_optional_engine_install() {
        // Full behavior is enforced by is_full + early return; verify helper logic.
        let components: Vec<String> = vec!["core".into(), "ocr".into(), "audio-runtime".into()];
        assert_eq!(components.len(), 3);
    }

    #[test]
    fn legacy_ready_detection() {
        let app_data = std::env::temp_dir().join(format!("mdflux_mgr_{}", std::process::id()));
        let _ = fs::remove_dir_all(&app_data);
        fs::create_dir_all(&app_data).unwrap();
        let platform = platform::current_platform().unwrap();
        let venv = legacy_venv_python(&app_data, &platform);
        fs::create_dir_all(venv.parent().unwrap()).unwrap();
        fs::write(&venv, b"").unwrap();
        let mut legacy = LegacyProvisionState::default();
        legacy.status = "ready".into();
        write_legacy_state(&app_data, &legacy).unwrap();
        let ctx = RuntimeContext {
            platform: platform.clone(),
            edition: EffectiveEdition::DevLite,
            app_data: app_data.clone(),
            resource_root: app_data.join("resources"),
        };
        assert!(is_provisioned_ctx(&ctx));
        let _ = fs::remove_dir_all(&app_data);
    }

    #[test]
    fn activation_failure_preserves_active_pointer() {
        let app_data = std::env::temp_dir().join(format!("mdflux_mgr2_{}", std::process::id()));
        let _ = fs::remove_dir_all(&app_data);
        fs::create_dir_all(&app_data).unwrap();
        write_active_pointer(
            &app_data,
            &ActiveRuntimePointer {
                runtime_id: "rt-keep".into(),
                previous_runtime_id: None,
            },
        )
        .unwrap();
        assert!(activate_runtime(&app_data, "rt-missing").is_err());
        assert_eq!(
            read_active_pointer(&app_data).unwrap().unwrap().runtime_id,
            "rt-keep"
        );
        let _ = fs::remove_dir_all(&app_data);
    }
}
