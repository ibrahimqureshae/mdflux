use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use tauri::{AppHandle, Manager};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct AppConfig {
    #[serde(default = "default_llm_mode")]
    pub llm_mode: String, // "off" | "local" | "api"
    #[serde(default = "default_local_base_url")]
    pub local_base_url: String,
    #[serde(default = "default_api_type")]
    pub api_type: String, // "openai_compat" | "anthropic"
    #[serde(default = "default_api_base_url")]
    pub api_base_url: String,
    #[serde(default)]
    pub api_key: String,
    /// Stage 5: model used for the optional LLM cleanup pass (empty = auto-pick first).
    #[serde(default)]
    pub cleanup_model: String,
    /// Stage 5: set once the user has seen the first-run cleanup highlight.
    #[serde(default)]
    pub cleanup_seen: bool,
    /// Stage 6: model used for LLM-powered conversion (image description, empty = auto).
    #[serde(default)]
    pub conversion_model: String,
    /// Stage 6: enable LLM image description during conversion (default false).
    #[serde(default)]
    pub llm_conversion: bool,
    /// Stage 6: extract embedded images to a {stem}_assets/ folder (default true).
    #[serde(default = "default_extract_images")]
    pub extract_images: bool,
    /// Stage 6: faster-whisper model size (default "base").
    #[serde(default = "default_audio_model")]
    pub audio_model: String,
    /// Stage 7: where batch output is written —
    /// "next_to_source" | "fixed_folder" | "mirror_tree".
    #[serde(default = "default_output_rule")]
    pub output_rule: String,
    /// Stage 7: the default output folder for "fixed_folder"/"mirror_tree"
    /// (empty = none chosen yet). Used to seed the per-run picker.
    #[serde(default)]
    pub output_folder: String,
    /// Stage 7: output filename template. Tokens: {stem} {ext} {date}. The ".md"
    /// extension is always appended. Default "{stem}" reproduces the old behavior.
    #[serde(default = "default_naming_template")]
    pub naming_template: String,
    /// Stage 7: case transform applied to the templated name —
    /// "keep" | "lower" | "slug".
    #[serde(default = "default_naming_case")]
    pub naming_case: String,
    /// Stage 7: reveal the output folder in the OS file manager after a batch.
    #[serde(default)]
    pub open_after_convert: bool,
}

fn default_llm_mode() -> String {
    "off".into()
}
fn default_local_base_url() -> String {
    "http://localhost:11434".into()
}
fn default_api_type() -> String {
    "openai_compat".into()
}
fn default_api_base_url() -> String {
    "https://api.openai.com/v1".into()
}
fn default_extract_images() -> bool {
    true
}
fn default_audio_model() -> String {
    "base".into()
}
fn default_output_rule() -> String {
    "next_to_source".into()
}
fn default_naming_template() -> String {
    "{stem}".into()
}
fn default_naming_case() -> String {
    "keep".into()
}

impl Default for AppConfig {
    fn default() -> Self {
        AppConfig {
            llm_mode: default_llm_mode(),
            local_base_url: default_local_base_url(),
            api_type: default_api_type(),
            api_base_url: default_api_base_url(),
            api_key: String::new(),
            cleanup_model: String::new(),
            cleanup_seen: false,
            conversion_model: String::new(),
            llm_conversion: false,
            extract_images: true,
            audio_model: default_audio_model(),
            output_rule: default_output_rule(),
            output_folder: String::new(),
            naming_template: default_naming_template(),
            naming_case: default_naming_case(),
            open_after_convert: false,
        }
    }
}

fn config_path(app: &AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| PathBuf::from("."))
        .join("config.json")
}

pub fn load(app: &AppHandle) -> AppConfig {
    let path = config_path(app);
    match std::fs::read_to_string(&path) {
        Ok(content) => serde_json::from_str(&content).unwrap_or_default(),
        Err(_) => AppConfig::default(),
    }
}

pub fn save(app: &AppHandle, config: &AppConfig) -> Result<(), String> {
    let path = config_path(app);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Cannot create config directory: {e}"))?;
    }
    let json = serde_json::to_string_pretty(config)
        .map_err(|e| format!("Config serialisation error: {e}"))?;
    // Atomic write: write to .tmp then rename. A crash mid-write won't corrupt
    // the config and silently reset the user's settings to defaults.
    let tmp = path.with_extension("json.tmp");
    std::fs::write(&tmp, json.as_bytes())
        .map_err(|e| format!("Cannot write config: {e}"))?;
    std::fs::rename(&tmp, &path)
        .map_err(|e| format!("Cannot finalise config: {e}"))
}
