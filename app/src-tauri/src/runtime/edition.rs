//! Edition manifest (`resources/edition.json`) parsing and validation.

use std::path::Path;

use crate::platform::{PlatformId, PlatformSpec};

/// Edition identifiers supported by the runtime.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Edition {
    Lite,
    Full,
}

impl Edition {
    pub fn as_str(self) -> &'static str {
        match self {
            Edition::Lite => "lite",
            Edition::Full => "full",
        }
    }

    pub fn from_str(s: &str) -> Result<Self, String> {
        match s {
            "lite" => Ok(Edition::Lite),
            "full" => Ok(Edition::Full),
            other => Err(format!(
                "Invalid edition '{other}'. Expected 'lite' or 'full'."
            )),
        }
    }

    pub fn is_mutable(self) -> bool {
        matches!(self, Edition::Lite)
    }
}

/// Parsed and validated edition manifest.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EditionManifest {
    pub schema: u32,
    pub edition: Edition,
    pub app_version: String,
    pub commit: String,
    pub platform: PlatformId,
    pub python_version: Option<String>,
    pub components: Vec<String>,
    pub dependency_lock_sha256: String,
    pub built_at_utc: String,
}

#[derive(serde::Deserialize)]
struct RawEditionManifest {
    schema: u32,
    edition: String,
    app_version: String,
    commit: String,
    platform: String,
    python_version: Option<String>,
    components: Vec<String>,
    dependency_lock_sha256: String,
    built_at_utc: String,
}

impl EditionManifest {
    fn validate(raw: RawEditionManifest, host: &PlatformSpec) -> Result<Self, String> {
        if raw.schema != 1 {
            return Err(format!(
                "Unsupported edition manifest schema {} (expected 1).",
                raw.schema
            ));
        }
        let edition = Edition::from_str(&raw.edition)?;
        let platform = PlatformId::from_str(&raw.platform)?;
        if platform != host.id {
            return Err(format!(
                "Edition manifest targets {} but this build runs on {}.",
                platform.as_str(),
                host.id.as_str()
            ));
        }
        match edition {
            Edition::Lite => {
                if raw.python_version.is_some() {
                    return Err("Lite edition manifest must set python_version to null.".into());
                }
                if raw.components != ["core"] {
                    return Err(format!(
                        "Lite edition manifest components must be [\"core\"], got {:?}.",
                        raw.components
                    ));
                }
            }
            Edition::Full => {
                let py = raw.python_version.as_deref().ok_or_else(|| {
                    "Full edition manifest must include python_version.".to_string()
                })?;
                if py.trim().is_empty() {
                    return Err("Full edition manifest python_version cannot be empty.".into());
                }
                let expected = ["core", "ocr", "audio-runtime"];
                if raw.components != expected {
                    return Err(format!(
                        "Full edition manifest components must be {expected:?}, got {:?}.",
                        raw.components
                    ));
                }
            }
        }
        if raw.dependency_lock_sha256.trim().is_empty() {
            return Err("Edition manifest dependency_lock_sha256 is missing.".into());
        }
        Ok(EditionManifest {
            schema: raw.schema,
            edition,
            app_version: raw.app_version,
            commit: raw.commit,
            platform,
            python_version: raw.python_version,
            components: raw.components,
            dependency_lock_sha256: raw.dependency_lock_sha256,
            built_at_utc: raw.built_at_utc,
        })
    }

    /// Load and validate `resources/edition.json` when present.
    pub fn load(resource_root: &Path, host: &PlatformSpec) -> Result<Option<Self>, String> {
        let path = resource_root.join("resources").join("edition.json");
        if !path.is_file() {
            return Ok(None);
        }
        let text = std::fs::read_to_string(&path)
            .map_err(|e| format!("Cannot read edition manifest at {}: {e}", path.display()))?;
        let raw: RawEditionManifest = serde_json::from_str(&text).map_err(|e| {
            format!(
                "Edition manifest at {} is invalid JSON: {e}",
                path.display()
            )
        })?;
        Self::validate(raw, host).map(Some)
    }
}

/// Effective edition for this process: manifest when packaged, Lite in dev trees.
#[derive(Debug, Clone)]
pub enum EffectiveEdition {
    DevLite,
    Manifest(EditionManifest),
}

impl EffectiveEdition {
    pub fn edition(&self) -> Edition {
        match self {
            EffectiveEdition::DevLite => Edition::Lite,
            EffectiveEdition::Manifest(m) => m.edition,
        }
    }

    pub fn is_full(&self) -> bool {
        matches!(self.edition(), Edition::Full)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::platform::current_platform;

    fn host() -> PlatformSpec {
        current_platform().expect("supported test target")
    }

    fn lite_raw(platform: &str) -> RawEditionManifest {
        RawEditionManifest {
            schema: 1,
            edition: "lite".to_string(),
            app_version: "0.2.1".to_string(),
            commit: "abc123".to_string(),
            platform: platform.to_string(),
            python_version: None,
            components: vec!["core".to_string()],
            dependency_lock_sha256: "deadbeef".to_string(),
            built_at_utc: "2026-08-22T12:00:00Z".to_string(),
        }
    }

    fn full_raw(platform: &str) -> RawEditionManifest {
        RawEditionManifest {
            schema: 1,
            edition: "full".to_string(),
            app_version: "0.2.1".to_string(),
            commit: "abc123".to_string(),
            platform: platform.to_string(),
            python_version: Some("3.12.11".to_string()),
            components: vec![
                "core".to_string(),
                "ocr".to_string(),
                "audio-runtime".to_string(),
            ],
            dependency_lock_sha256: "deadbeef".to_string(),
            built_at_utc: "2026-08-22T12:00:00Z".to_string(),
        }
    }

    #[test]
    fn parses_valid_lite_manifest() {
        let h = host();
        let m = EditionManifest::validate(lite_raw(h.id.as_str()), &h).unwrap();
        assert_eq!(m.edition, Edition::Lite);
        assert!(m.python_version.is_none());
    }

    #[test]
    fn parses_valid_full_manifest() {
        let h = host();
        let m = EditionManifest::validate(full_raw(h.id.as_str()), &h).unwrap();
        assert_eq!(m.edition, Edition::Full);
        assert_eq!(m.python_version.as_deref(), Some("3.12.11"));
    }

    #[test]
    fn rejects_invalid_schema() {
        let h = host();
        let mut raw = lite_raw(h.id.as_str());
        raw.schema = 2;
        assert!(EditionManifest::validate(raw, &h)
            .unwrap_err()
            .contains("schema"));
    }

    #[test]
    fn rejects_missing_full_python_version() {
        let h = host();
        let mut raw = full_raw(h.id.as_str());
        raw.python_version = None;
        assert!(EditionManifest::validate(raw, &h)
            .unwrap_err()
            .contains("python_version"));
    }

    #[test]
    fn rejects_platform_mismatch() {
        let h = host();
        let other = if h.id == PlatformId::WindowsX64 {
            "linux-x64-glibc"
        } else {
            "windows-x64"
        };
        assert!(EditionManifest::validate(lite_raw(other), &h)
            .unwrap_err()
            .contains("targets"));
    }

    #[test]
    fn rejects_unknown_edition() {
        let h = host();
        let mut raw = lite_raw(h.id.as_str());
        raw.edition = "enterprise".into();
        assert!(EditionManifest::validate(raw, &h)
            .unwrap_err()
            .contains("edition"));
    }
}
