//! Resolve portable and installed resources once for every runtime consumer.
use std::path::{Path, PathBuf};

pub fn resolve(
    executable: &Path,
    framework_root: &Path,
    development: bool,
) -> Result<PathBuf, String> {
    let adjacent = executable
        .parent()
        .ok_or("Executable has no parent directory")?;
    // A portable payload takes precedence over an unrelated system installation.
    let root = if adjacent.join("resources").exists() {
        adjacent
    } else {
        framework_root
    };
    let resources = root.join("resources");
    for file in ["sidecar/main.py", "sidecar/requirements.lock"] {
        if !resources.join(file).is_file() {
            return Err(format!("Packaged resource {file} is missing under {}. Extract the complete archive before starting MDFlux.", resources.display()));
        }
    }
    if !development && !resources.join("edition.json").is_file() {
        return Err(format!("Packaged edition manifest is missing under {}. Extract the complete archive before starting MDFlux.", resources.display()));
    }
    Ok(root.to_path_buf())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        fs,
        sync::atomic::{AtomicU64, Ordering},
    };
    static NEXT: AtomicU64 = AtomicU64::new(0);
    struct Fixture(PathBuf);
    impl Fixture {
        fn new() -> Self {
            let root = std::env::temp_dir().join(format!(
                "mdflux-resources-{}-{}",
                std::process::id(),
                NEXT.fetch_add(1, Ordering::Relaxed)
            ));
            fs::create_dir_all(&root).unwrap();
            Self(root)
        }
        fn payload(&self, name: &str, manifest: bool) -> PathBuf {
            let root = self.0.join(name);
            fs::create_dir_all(root.join("resources/sidecar")).unwrap();
            for file in ["main.py", "requirements.lock"] {
                fs::write(root.join("resources/sidecar").join(file), "fixture").unwrap();
            }
            if manifest {
                fs::write(root.join("resources/edition.json"), "{}").unwrap();
            }
            root
        }
    }
    impl Drop for Fixture {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }
    #[test]
    fn portable_wins_over_system_and_survives_relocation() {
        let f = Fixture::new();
        let portable = f.payload("portable with spaces", true);
        let installed = f.payload("system", true);
        assert_eq!(
            resolve(&portable.join("MDFlux"), &installed, false).unwrap(),
            portable
        );
        let moved = f.0.join("relocated");
        fs::rename(&portable, &moved).unwrap();
        assert_eq!(
            resolve(&moved.join("MDFlux"), &installed, false).unwrap(),
            moved
        );
    }
    #[test]
    fn installed_layout_uses_framework_root() {
        let f = Fixture::new();
        let installed = f.payload("usr/lib/MDFlux", true);
        assert_eq!(
            resolve(&f.0.join("usr/bin/MDFlux"), &installed, false).unwrap(),
            installed
        );
    }
    #[test]
    fn incomplete_portable_does_not_fall_back_to_system_or_development() {
        let f = Fixture::new();
        let portable = f.payload("portable", false);
        let installed = f.payload("system", true);
        assert!(resolve(&portable.join("MDFlux"), &installed, false)
            .unwrap_err()
            .contains("manifest"));
        assert!(resolve(&portable.join("MDFlux"), &installed, true).is_ok());
        fs::remove_file(portable.join("resources/sidecar/requirements.lock")).unwrap();
        assert!(resolve(&portable.join("MDFlux"), &installed, false)
            .unwrap_err()
            .contains("requirements.lock"));
    }
}
