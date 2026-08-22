//! Public provisioning API — delegates to the runtime manager and platform layer.

use std::path::PathBuf;

use tauri::AppHandle;

pub use crate::runtime::{
    install_optional_engine, is_provisioned, on_successful_launch, optional_engine_status,
    provision, python_path, runtime_status, OptionalEngineState,
};

/// Legacy alias retained for callers that checked bundled runtime directly.
pub fn is_bundled_runtime(app: &AppHandle) -> bool {
    crate::runtime::RuntimeContext::resolve(app)
        .map(|ctx| ctx.is_full())
        .unwrap_or(false)
}

pub fn bundled_python_path(app: &AppHandle) -> Option<PathBuf> {
    let ctx = crate::runtime::RuntimeContext::resolve(app).ok()?;
    crate::runtime::manager::bundled_python_path(&ctx)
}
