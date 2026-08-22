//! Versioned Lite runtime directory layout and atomic activation.

use std::collections::BTreeSet;
use std::fs;
use std::path::{Path, PathBuf};

use sha2::{Digest, Sha256};

use crate::platform::PlatformSpec;

#[cfg(test)]
use super::edition::Edition;

pub const ACTIVE_POINTER_FILE: &str = "active-runtime.json";
pub const RUNTIME_JSON: &str = "runtime.json";
pub const ENV_DIR: &str = "environment";
pub const STAGING_SUFFIX: &str = ".staging";

/// Pointer written atomically when a runtime becomes active.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq, Eq)]
pub struct ActiveRuntimePointer {
    pub runtime_id: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub previous_runtime_id: Option<String>,
}

/// Metadata stored inside each versioned runtime directory.
#[derive(Debug, Clone, serde::Serialize, serde::Deserialize, PartialEq, Eq)]
pub struct RuntimeRecord {
    pub runtime_id: String,
    pub edition: String,
    pub platform: String,
    pub python_version: String,
    pub dependency_lock_sha256: String,
    pub components: Vec<String>,
    pub created_at_utc: String,
}

pub fn runtimes_root(app_data: &Path) -> PathBuf {
    app_data.join("runtimes")
}

pub fn active_pointer_path(app_data: &Path) -> PathBuf {
    app_data.join(ACTIVE_POINTER_FILE)
}

pub fn runtime_dir(app_data: &Path, runtime_id: &str) -> PathBuf {
    runtimes_root(app_data).join(runtime_id)
}

pub fn staging_runtime_dir(app_data: &Path, runtime_id: &str) -> PathBuf {
    runtimes_root(app_data).join(format!("{runtime_id}{STAGING_SUFFIX}"))
}

pub fn environment_dir(app_data: &Path, runtime_id: &str) -> PathBuf {
    runtime_dir(app_data, runtime_id).join(ENV_DIR)
}

pub fn python_in_environment(env_dir: &Path, platform: &PlatformSpec) -> PathBuf {
    env_dir.join(platform.venv_python_bin)
}

/// Derive a stable runtime id from version, platform, lock checksum, and components.
pub fn compute_runtime_id(
    app_version: &str,
    platform: &PlatformSpec,
    python_version: &str,
    dependency_lock_sha256: &str,
    components: &[String],
) -> String {
    let mut parts = components.to_vec();
    parts.sort();
    let payload = format!(
        "{}|{}|{}|{}|{}",
        app_version,
        platform.id.as_str(),
        python_version,
        dependency_lock_sha256,
        parts.join(",")
    );
    let digest = Sha256::digest(payload.as_bytes());
    let short: String = digest[..8].iter().map(|b| format!("{b:02x}")).collect();
    format!("rt-{short}")
}

pub fn sha256_file(path: &Path) -> Result<String, String> {
    let bytes = fs::read(path).map_err(|e| format!("Cannot read {}: {e}", path.display()))?;
    Ok(format!("{:x}", Sha256::digest(bytes)))
}

pub fn read_active_pointer(app_data: &Path) -> Result<Option<ActiveRuntimePointer>, String> {
    let path = active_pointer_path(app_data);
    if !path.is_file() {
        return Ok(None);
    }
    let text = fs::read_to_string(&path)
        .map_err(|e| format!("Cannot read active runtime pointer: {e}"))?;
    serde_json::from_str(&text).map_err(|e| format!("Active runtime pointer is invalid JSON: {e}"))
}

pub fn write_active_pointer(app_data: &Path, pointer: &ActiveRuntimePointer) -> Result<(), String> {
    fs::create_dir_all(app_data).map_err(|e| format!("Cannot create app data dir: {e}"))?;
    let final_path = active_pointer_path(app_data);
    let tmp_path = app_data.join(format!("{ACTIVE_POINTER_FILE}.tmp"));
    let json =
        serde_json::to_string(pointer).map_err(|e| format!("Pointer serialise error: {e}"))?;
    fs::write(&tmp_path, json.as_bytes()).map_err(|e| format!("Cannot write pointer temp: {e}"))?;
    fs::rename(&tmp_path, &final_path).map_err(|e| format!("Cannot activate runtime pointer: {e}"))
}

pub fn write_runtime_record(runtime_root: &Path, record: &RuntimeRecord) -> Result<(), String> {
    fs::create_dir_all(runtime_root).map_err(|e| format!("Cannot create runtime dir: {e}"))?;
    let path = runtime_root.join(RUNTIME_JSON);
    let json =
        serde_json::to_string_pretty(record).map_err(|e| format!("Record serialise error: {e}"))?;
    fs::write(&path, json.as_bytes()).map_err(|e| format!("Cannot write runtime record: {e}"))
}

pub fn read_runtime_record(runtime_root: &Path) -> Result<RuntimeRecord, String> {
    let path = runtime_root.join(RUNTIME_JSON);
    let text = fs::read_to_string(&path)
        .map_err(|e| format!("Cannot read runtime record at {}: {e}", path.display()))?;
    serde_json::from_str(&text).map_err(|e| format!("Runtime record invalid JSON: {e}"))
}

/// Promote a staged runtime directory to active, retaining the previous id for rollback.
pub fn activate_runtime(app_data: &Path, runtime_id: &str) -> Result<ActiveRuntimePointer, String> {
    let staging = staging_runtime_dir(app_data, runtime_id);
    let final_dir = runtime_dir(app_data, runtime_id);
    if !staging.is_dir() {
        return Err(format!("Staging runtime missing at {}.", staging.display()));
    }
    if final_dir.exists() {
        fs::remove_dir_all(&final_dir).map_err(|e| {
            format!(
                "Cannot replace existing runtime at {}: {e}",
                final_dir.display()
            )
        })?;
    }
    fs::rename(&staging, &final_dir).map_err(|e| {
        format!(
            "Failed to promote staging runtime {} -> {}: {e}",
            staging.display(),
            final_dir.display()
        )
    })?;

    let previous = read_active_pointer(app_data)?.map(|p| p.runtime_id);
    let pointer = ActiveRuntimePointer {
        runtime_id: runtime_id.to_string(),
        previous_runtime_id: previous,
    };
    write_active_pointer(app_data, &pointer)?;
    Ok(pointer)
}

/// Remove stale runtime directories, keeping the active and immediately previous ids.
pub fn prune_old_runtimes(app_data: &Path) -> Result<(), String> {
    let root = runtimes_root(app_data);
    if !root.is_dir() {
        return Ok(());
    }
    let keep = active_and_previous_ids(app_data)?;
    for entry in fs::read_dir(&root).map_err(|e| e.to_string())? {
        let entry = entry.map_err(|e| e.to_string())?;
        let name = entry.file_name().to_string_lossy().to_string();
        if name.ends_with(STAGING_SUFFIX) {
            let _ = fs::remove_dir_all(entry.path());
            continue;
        }
        if !keep.contains(&name) {
            let _ = fs::remove_dir_all(entry.path());
        }
    }
    Ok(())
}

fn active_and_previous_ids(app_data: &Path) -> Result<BTreeSet<String>, String> {
    let mut keep = BTreeSet::new();
    if let Some(p) = read_active_pointer(app_data)? {
        keep.insert(p.runtime_id);
        if let Some(prev) = p.previous_runtime_id {
            keep.insert(prev);
        }
    }
    Ok(keep)
}

/// Resolve the Python interpreter for the active Lite runtime, if any.
pub fn active_python_path(
    app_data: &Path,
    platform: &PlatformSpec,
) -> Result<Option<PathBuf>, String> {
    let Some(pointer) = read_active_pointer(app_data)? else {
        return Ok(None);
    };
    let env = environment_dir(app_data, &pointer.runtime_id);
    let python = python_in_environment(&env, platform);
    if python.is_file() {
        Ok(Some(python))
    } else {
        Ok(None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::platform::current_platform;

    fn temp_app_data(label: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("mdflux_rt_{label}_{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn runtime_id_is_stable_for_same_inputs() {
        let platform = current_platform().unwrap();
        let components = vec!["core".to_string()];
        let a = compute_runtime_id("0.2.0", &platform, "3.12.11", "abc", &components);
        let b = compute_runtime_id("0.2.0", &platform, "3.12.11", "abc", &components);
        assert_eq!(a, b);
        assert!(a.starts_with("rt-"));
    }

    #[test]
    fn failed_staging_leaves_active_unchanged() {
        let app_data = temp_app_data("fail_staging");
        let runtime_id = "rt-test1234";

        write_active_pointer(
            &app_data,
            &ActiveRuntimePointer {
                runtime_id: "rt-existing".into(),
                previous_runtime_id: None,
            },
        )
        .unwrap();

        // No staging directory present - activation must fail.
        assert!(activate_runtime(&app_data, runtime_id).is_err());
        let active = read_active_pointer(&app_data).unwrap().unwrap();
        assert_eq!(active.runtime_id, "rt-existing");

        let _ = fs::remove_dir_all(&app_data);
    }

    #[test]
    fn successful_activation_switches_pointer_and_keeps_previous() {
        let app_data = temp_app_data("activate");
        let platform = current_platform().unwrap();
        let old_id = "rt-old1234";
        let new_id = "rt-new5678";

        let old_env = environment_dir(&app_data, old_id);
        let old_python = python_in_environment(&old_env, &platform);
        fs::create_dir_all(old_python.parent().unwrap()).unwrap();
        fs::write(&old_python, b"").unwrap();
        write_active_pointer(
            &app_data,
            &ActiveRuntimePointer {
                runtime_id: old_id.into(),
                previous_runtime_id: None,
            },
        )
        .unwrap();

        let staging = staging_runtime_dir(&app_data, new_id);
        let staging_env = staging.join(ENV_DIR);
        let staging_python = python_in_environment(&staging_env, &platform);
        fs::create_dir_all(staging_python.parent().unwrap()).unwrap();
        fs::write(&staging_python, b"").unwrap();
        write_runtime_record(
            &staging,
            &RuntimeRecord {
                runtime_id: new_id.into(),
                edition: Edition::Lite.as_str().into(),
                platform: platform.id.as_str().into(),
                python_version: "3.12.11".into(),
                dependency_lock_sha256: "abc".into(),
                components: vec!["core".into()],
                created_at_utc: "2026-08-22T12:00:00Z".into(),
            },
        )
        .unwrap();

        let pointer = activate_runtime(&app_data, new_id).unwrap();
        assert_eq!(pointer.runtime_id, new_id);
        assert_eq!(pointer.previous_runtime_id.as_deref(), Some(old_id));
        assert!(runtime_dir(&app_data, new_id).is_dir());
        assert!(!staging.is_dir());

        let _ = fs::remove_dir_all(&app_data);
    }

    #[test]
    fn active_python_path_resolves_environment() {
        let app_data = temp_app_data("python_path");
        let platform = current_platform().unwrap();
        let runtime_id = "rt-path123";

        let env = environment_dir(&app_data, runtime_id);
        fs::create_dir_all(&env).unwrap();
        let python = python_in_environment(&env, &platform);
        fs::create_dir_all(python.parent().unwrap()).unwrap();
        fs::write(&python, b"").unwrap();
        write_active_pointer(
            &app_data,
            &ActiveRuntimePointer {
                runtime_id: runtime_id.into(),
                previous_runtime_id: None,
            },
        )
        .unwrap();

        let resolved = active_python_path(&app_data, &platform).unwrap().unwrap();
        assert_eq!(resolved, python);

        let _ = fs::remove_dir_all(&app_data);
    }
}
