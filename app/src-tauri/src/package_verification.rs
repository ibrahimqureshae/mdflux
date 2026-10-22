//! Explicit packaged-backend smoke mode. Never uses the user's application data.
use std::{path::PathBuf, sync::Arc};
use tauri::Manager;

#[derive(Clone, Default)]
pub struct Verification(pub Option<PathBuf>);

impl Verification {
    pub fn from_args() -> Result<Self, String> {
        let args: Vec<_> = std::env::args_os().collect();
        if args.get(1).is_none_or(|arg| arg != "--verify-package") {
            return Ok(Self::default());
        }
        if args.len() != 3 {
            return Err("Usage: MDFlux --verify-package ABSOLUTE_TEST_DIRECTORY".into());
        }
        let path = PathBuf::from(&args[2]);
        if !path.is_absolute() {
            return Err("Verification directory must be absolute".into());
        }
        let marker = path.join(".mdflux-verification");
        if path.exists() && !marker.is_file() {
            return Err("Refusing an existing directory without a verification marker".into());
        }
        std::fs::create_dir_all(&path).map_err(|e| e.to_string())?;
        std::fs::write(marker, "MDFlux isolated package verification\n")
            .map_err(|e| e.to_string())?;
        Ok(Self(Some(path)))
    }
}

pub async fn run(
    app: &tauri::AppHandle,
    root: &std::path::Path,
) -> Result<serde_json::Value, String> {
    let ctx = crate::runtime::RuntimeContext::resolve(app)?;
    let manager = app.state::<Arc<crate::SidecarManager>>();
    let mgr = Arc::clone(&manager);
    // Full must work without provisioning; Lite exercises the real installer.
    if !ctx.is_full() {
        crate::runtime::provision(app.clone(), false, || async move {
            mgr.kill_sidecar().await;
        })
        .await?;
    }
    let health = crate::run_health_check(app.clone(), app.state()).await?;
    let (python, script) = crate::sidecar_paths(app)?;
    let fixture = root.join("smoke.txt");
    let expected = "MDFlux packaged runtime regression fixture";
    std::fs::write(&fixture, expected).map_err(|e| e.to_string())?;
    let response = manager
        .send_streaming(
            &serde_json::json!({
                "v": 1, "id": "package-smoke", "method": "convert-one", "params": {"path": fixture}
            }),
            |_| {},
        )
        .await?;
    if response.get("ok").and_then(|v| v.as_bool()) != Some(true)
        || !response["result"]["markdown"]
            .as_str()
            .unwrap_or("")
            .contains(expected)
    {
        return Err(format!("Packaged conversion failed: {response}"));
    }
    Ok(
        serde_json::json!({"passed": true, "edition": ctx.edition_kind().as_str(),
        "resource_root": ctx.resource_root, "app_data": ctx.app_data, "python": python,
        "sidecar": script, "health": health, "conversion": "text fixture passed",
        "uv_version": crate::platform::UV_VERSION}),
    )
}
