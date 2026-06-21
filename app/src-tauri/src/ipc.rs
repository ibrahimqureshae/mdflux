use serde::{Deserialize, Serialize};
use std::collections::HashMap;

// ── Stage 0 types (unchanged) ──────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct HealthReport {
    pub python_version: String,
    pub markitdown_version: Option<String>,
    pub extras: HashMap<String, bool>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ProvisionStatus {
    pub state: String, // "not_provisioned" | "ready"
}

#[derive(Debug, Serialize, Clone)]
pub struct ProgressPayload {
    pub step: String,
    pub message: String,
    pub pct: f32,
    /// Live download metrics for the current step (bytes + speed). Present only
    /// while something is actively transferring; `None` for non-download work.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<DownloadDetail>,
}

/// What is being downloaded right now, and how fast.
#[derive(Debug, Serialize, Clone)]
pub struct DownloadDetail {
    /// Human label for the artefact, e.g. "uv 0.5.11 (Windows x64)".
    pub label: String,
    /// Bytes received so far.
    pub received: u64,
    /// Total bytes, if the server reported a content-length.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub total: Option<u64>,
    /// Instantaneous transfer rate in bytes per second.
    pub speed: f64,
}

// ── IPC v1 wire types ──────────────────────────────────────────────────────

/// Typed error envelope — same shape for every failure class.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct IpcError {
    pub code: String,
    pub title: String,
    pub detail: String,
    pub suggested_action: String,
    /// Set on MISSING_EXTRA so the UI can link to the matching Diagnostics row.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub diagnostics_key: Option<String>,
}

/// Metadata returned alongside the converted Markdown.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ConvertMeta {
    pub detected_format: String,
    pub converter_path: String,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
    /// Stage 6: populated when embedded images were extracted to a folder.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub assets_folder: Option<String>,
}

/// Successful conversion payload.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ConvertResult {
    pub markdown: String,
    pub meta: ConvertMeta,
}

/// Union response returned to the frontend by `convert_file`.
/// Always Ok(ConvertResponse) — never Err — so the typed error reaches the UI.
#[derive(Debug, Serialize, Clone)]
pub struct ConvertResponse {
    pub ok: bool,
    pub result: Option<ConvertResult>,
    pub error: Option<IpcError>,
}

// ── Stage 3: Capabilities types ────────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct RuntimeInfo {
    pub python_version: String,
    pub sidecar_version: String,
    pub markitdown_version: String,
    pub venv_path: String,
}

/// One row in the format-support table.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct FormatEntry {
    pub key: String,
    pub label: String,
    pub extensions: Vec<String>,
    pub module: Option<String>,
    pub module_version: Option<String>,
    pub converter: Option<String>,
    /// "available" | "missing" | "broken" | "coming_later"
    pub status: String,
    pub error: Option<String>,
    pub note: Option<String>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct OptionalCapability {
    pub status: String,     // "not_installed" | "installed" | "missing" (broken)
    pub engine: String,
    pub size_hint: String,
    pub note: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct OptionalCapabilities {
    pub ocr: OptionalCapability,
    pub audio: OptionalCapability,
}

/// Emitted as "engine:install-progress" during optional engine installation.
#[derive(Debug, Serialize, Clone)]
pub struct EngineInstallProgress {
    pub engine: String,
    pub step: String,
    pub message: String,
    pub pct: f32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CapabilitiesReport {
    pub runtime: RuntimeInfo,
    pub formats: Vec<FormatEntry>,
    pub optional: OptionalCapabilities,
}

// ── Stage 3: Provider check result ─────────────────────────────────────────

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ProviderCheckResult {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub server: Option<String>,
    pub reachable: bool,
    pub detail: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub models: Option<Vec<String>>,
    pub usable: bool,
}

// ── Stage 4: Batch types ────────────────────────────────────────────────────

/// One file in the batch queue.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BatchItem {
    pub id: String,
    pub path: String,
    pub filename: String,
    /// "pending" | "running" | "done" | "failed" | "cancelled"
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<IpcError>,
    /// Non-fatal notices from the conversion (e.g. "No text could be extracted").
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
}

/// Returned immediately by start_batch / retry_failed.
#[derive(Debug, Serialize, Clone)]
pub struct BatchStartResult {
    pub items: Vec<BatchItem>,
}

/// Emitted as "batch:file-status" whenever a file's state changes.
#[derive(Debug, Serialize, Clone)]
pub struct BatchFileStatusEvent {
    pub id: String,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub frac: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<IpcError>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_path: Option<String>,
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
}

/// Emitted as "batch:done" when the last worker finishes.
#[derive(Debug, Serialize, Clone)]
pub struct BatchDoneEvent {
    pub done: u32,
    pub failed: u32,
    pub cancelled: u32,
    pub items: Vec<BatchItem>,
    /// Stage 5: whether cleanup ran for this batch, and aggregate change counts.
    pub cleanup_applied: bool,
    pub cleanup_changes: u32,
}

// ── Stage 5: Cleanup types ──────────────────────────────────────────────────

/// Cleanup options carried on `start_batch` / `retry_failed`. Mirrors the sidecar
/// `cleanup` params. `method` is "none" | "rules" | "ai":
///   - "none": no cleanup
///   - "rules": deterministic rules only
///   - "ai": LLM cleans the raw extraction directly (rules ignored)
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CleanupOptions {
    pub method: String,
    /// Per-rule toggles for the "rules" method, keyed by rule id.
    #[serde(default)]
    pub rules: HashMap<String, bool>,
}

/// One rule's contribution to the change summary.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CleanupRuleSummary {
    pub key: String,
    pub label: String,
    pub applied: bool,
    pub changes: u32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CleanupSummary {
    pub rules: Vec<CleanupRuleSummary>,
    pub char_delta: i64,
    pub line_delta: i64,
}

/// Result of a `cleanup_markdown` call.
#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CleanupResult {
    pub markdown: String,
    pub summary: CleanupSummary,
    pub llm_applied: bool,
    pub llm_notice: Option<String>,
}
