//! Small platform boundary for supported release targets.
//!
//! MDFlux v0.2.x supports `windows-x64` and `linux-x64-glibc` only. Other targets
//! receive an explicit error instead of failing inside unresolved cfg modules.

use std::path::Path;

/// Platform identifiers supported by the application.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PlatformId {
    WindowsX64,
    LinuxX64Glibc,
}

impl PlatformId {
    pub fn as_str(self) -> &'static str {
        match self {
            PlatformId::WindowsX64 => "windows-x64",
            PlatformId::LinuxX64Glibc => "linux-x64-glibc",
        }
    }

    pub fn from_str(s: &str) -> Result<Self, String> {
        match s {
            "windows-x64" => Ok(PlatformId::WindowsX64),
            "linux-x64-glibc" => Ok(PlatformId::LinuxX64Glibc),
            other => Err(format!(
                "Unsupported platform identifier '{other}'. MDFlux supports windows-x64 and linux-x64-glibc."
            )),
        }
    }
}

/// Platform-specific constants and paths for provisioning and bundled runtimes.
#[derive(Debug, Clone)]
pub struct PlatformSpec {
    pub id: PlatformId,
    pub uv_url: &'static str,
    pub uv_sha256: &'static str,
    pub uv_archive: &'static str,
    pub uv_bin: &'static str,
    pub venv_python_bin: &'static str,
    pub bundled_python_bin: &'static str,
    pub uv_label: &'static str,
}

#[cfg(all(target_os = "windows", target_arch = "x86_64"))]
pub fn current_platform() -> Result<PlatformSpec, String> {
    Ok(PlatformSpec {
        id: PlatformId::WindowsX64,
        uv_url:
            "https://github.com/astral-sh/uv/releases/download/0.5.11/uv-x86_64-pc-windows-msvc.zip",
        uv_sha256: "3e8203e6434b45427f20824419f8d8d53f970a76d94ccdcad07f8498fa01a9d0",
        uv_archive: "uv.zip",
        uv_bin: "uv.exe",
        venv_python_bin: "Scripts/python.exe",
        bundled_python_bin: "python.exe",
        uv_label: "uv 0.5.11 - Python package manager (Windows x64)",
    })
}

#[cfg(all(target_os = "linux", target_arch = "x86_64"))]
pub fn current_platform() -> Result<PlatformSpec, String> {
    Ok(PlatformSpec {
        id: PlatformId::LinuxX64Glibc,
        uv_url: "https://github.com/astral-sh/uv/releases/download/0.5.11/uv-x86_64-unknown-linux-gnu.tar.gz",
        uv_sha256: "14411de26cdea5f5139fafaf2b675b1c633e744dd49c6d6a9fc8817ec065158b",
        uv_archive: "uv.tar.gz",
        uv_bin: "uv",
        venv_python_bin: "bin/python",
        bundled_python_bin: "bin/python3",
        uv_label: "uv 0.5.11 - Python package manager (Linux x64)",
    })
}

#[cfg(not(any(
    all(target_os = "windows", target_arch = "x86_64"),
    all(target_os = "linux", target_arch = "x86_64")
)))]
pub fn current_platform() -> Result<PlatformSpec, String> {
    Err(format!(
        "MDFlux does not support this operating system/architecture ({}/{}). \
         Supported targets: windows-x64, linux-x64-glibc.",
        std::env::consts::OS,
        std::env::consts::ARCH
    ))
}

/// Available physical memory in MiB for batch worker sizing.
#[cfg(windows)]
pub fn available_ram_mb() -> Option<u64> {
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

#[cfg(target_os = "linux")]
pub fn available_ram_mb() -> Option<u64> {
    let text = std::fs::read_to_string("/proc/meminfo").ok()?;
    for line in text.lines() {
        let Some(rest) = line.strip_prefix("MemAvailable:") else {
            continue;
        };
        let kb: u64 = rest.split_whitespace().next()?.parse().ok()?;
        return Some(kb / 1024);
    }
    None
}

#[cfg(not(any(windows, target_os = "linux")))]
pub fn available_ram_mb() -> Option<u64> {
    None
}

#[cfg(unix)]
pub fn set_executable(path: &Path) -> Result<(), String> {
    use std::os::unix::fs::PermissionsExt;
    let mut perms = std::fs::metadata(path)
        .map_err(|e| e.to_string())?
        .permissions();
    perms.set_mode(0o755);
    std::fs::set_permissions(path, perms).map_err(|e| e.to_string())
}

#[cfg(not(unix))]
pub fn set_executable(_path: &Path) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn platform_id_roundtrip() {
        for id in [PlatformId::WindowsX64, PlatformId::LinuxX64Glibc] {
            assert_eq!(PlatformId::from_str(id.as_str()).unwrap(), id);
        }
    }

    #[test]
    fn unsupported_platform_identifier_is_explicit() {
        let err = PlatformId::from_str("macos-arm64").unwrap_err();
        assert!(err.contains("Unsupported platform identifier"));
    }

    #[test]
    fn current_platform_matches_compile_target() {
        let spec = current_platform().expect("test target must be supported");
        #[cfg(all(target_os = "windows", target_arch = "x86_64"))]
        assert_eq!(spec.id, PlatformId::WindowsX64);
        #[cfg(all(target_os = "linux", target_arch = "x86_64"))]
        assert_eq!(spec.id, PlatformId::LinuxX64Glibc);
    }

    #[test]
    fn python_paths_follow_platform_layout() {
        let spec = current_platform().unwrap();
        #[cfg(target_os = "windows")]
        {
            assert_eq!(spec.venv_python_bin, "Scripts/python.exe");
            assert_eq!(spec.bundled_python_bin, "python.exe");
        }
        #[cfg(target_os = "linux")]
        {
            assert_eq!(spec.venv_python_bin, "bin/python");
            assert_eq!(spec.bundled_python_bin, "bin/python3");
        }
    }
}
