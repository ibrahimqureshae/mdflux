//! Runtime status contract exposed to the UI.

use std::collections::HashMap;

use serde::{Deserialize, Serialize};

use super::edition::Edition;

/// Component install state values exposed to the UI.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ComponentState {
    NotInstalled,
    Installing,
    Installed,
    Failed,
}

impl ComponentState {
    pub fn as_str(self) -> &'static str {
        match self {
            ComponentState::NotInstalled => "not_installed",
            ComponentState::Installing => "installing",
            ComponentState::Installed => "installed",
            ComponentState::Failed => "failed",
        }
    }
}

/// Runtime lifecycle status values exposed to the UI.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeLifecycle {
    Missing,
    Installing,
    Ready,
    Invalid,
    Repairable,
}

impl RuntimeLifecycle {
    pub fn as_str(self) -> &'static str {
        match self {
            RuntimeLifecycle::Missing => "missing",
            RuntimeLifecycle::Installing => "installing",
            RuntimeLifecycle::Ready => "ready",
            RuntimeLifecycle::Invalid => "invalid",
            RuntimeLifecycle::Repairable => "repairable",
        }
    }
}

/// JSON shape returned by `get_runtime_status`.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RuntimeStatus {
    pub edition: String,
    pub platform: String,
    pub status: String,
    pub mutable: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub python_version: Option<String>,
    pub components: HashMap<String, String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub repair_action: Option<String>,
}

impl RuntimeStatus {
    pub fn new(
        edition: Edition,
        platform: &str,
        lifecycle: RuntimeLifecycle,
        python_version: Option<String>,
        components: HashMap<String, String>,
        repair_action: Option<String>,
    ) -> Self {
        Self {
            edition: edition.as_str().to_string(),
            platform: platform.to_string(),
            status: lifecycle.as_str().to_string(),
            mutable: edition.is_mutable(),
            python_version,
            components,
            repair_action,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serializes_frozen_contract_shape() {
        let mut components = HashMap::new();
        components.insert("core".into(), "installed".into());
        components.insert("ocr".into(), "not_installed".into());
        components.insert("audio".into(), "not_installed".into());
        let status = RuntimeStatus::new(
            Edition::Lite,
            "windows-x64",
            RuntimeLifecycle::Ready,
            Some("3.12.11".into()),
            components,
            None,
        );
        let json = serde_json::to_value(&status).unwrap();
        assert_eq!(json["edition"], "lite");
        assert_eq!(json["platform"], "windows-x64");
        assert_eq!(json["status"], "ready");
        assert_eq!(json["mutable"], true);
        assert_eq!(json["python_version"], "3.12.11");
        assert_eq!(json["components"]["core"], "installed");
        assert!(json.get("repair_action").is_none());
    }
}
