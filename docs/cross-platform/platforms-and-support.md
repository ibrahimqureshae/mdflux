# Platforms and support policy

## Supported matrix

| Platform ID | Architecture | C library | Editions | Status |
| --- | --- | --- | --- | --- |
| `windows-x64` | x64 | N/A (Windows) | Lite, Full | Supported in v0.3.0. The v0.2.0 portable archive remains available under its legacy Lite-style name. |
| `linux-x64-glibc` | x64 | glibc | Lite, Full | Supported in v0.3.0 on the Ubuntu 22.04-or-newer baseline described below. |

## Linux baseline

The initial Linux baseline is **Ubuntu 22.04 or newer** (and equivalent glibc-based x64
distributions such as Lubuntu 24.04) on **x86-64**.

MDFlux does **not** target:

- Linux ARM64 (`aarch64`)
- musl-based distributions (Alpine, etc.) as first-class releases
- AppImage, Flatpak, or native `.deb` installers in this release cycle
- macOS (planned separately; see [ROADMAP.md](../../ROADMAP.md))

## System GUI dependencies

MDFlux is a Tauri desktop application. The webview stack is **not** bundled inside release
archives.

### Windows

- Windows 10 or 11 (x64)
- **WebView2** runtime (present on current Windows 10/11)

### Linux

- **WebKitGTK 4.1** at runtime; package name on Ubuntu/Debian: `libwebkit2gtk-4.1-0`
- **GTK 3**: `libgtk-3-0`
- **`xdg-utils`** for sensible default handlers

**Linux Full still requires compatible WebKitGTK system libraries.** Full bundles Python and
Python-side dependencies only; it does not bundle the desktop webview stack.

Build hosts additionally need development packages (WebKitGTK/GTK/OpenSSL headers, `patchelf`,
`pkg-config`, etc.). See [setup-ubuntu.md](setup-ubuntu.md) and [CONTRIBUTING.md](../../CONTRIBUTING.md).

OCR on Linux may also require `libgl1` and `libgomp1` at runtime.

## Support policy

1. **Supported for bug reports and release verification:** `windows-x64` and `linux-x64-glibc`,
   **Lite** and **Full**, **x64 only**.
2. Check the release notes for the versions and platforms currently available for download.
3. **Out-of-scope platforms** may compile opportunistically but are unsupported; please do not
   file release-blocking bugs for ARM, musl, or macOS until listed in the support matrix above.
4. **Security issues:** follow [SECURITY.md](../../SECURITY.md); do not use public issues.

## Runtime status (for bug reports)

When reporting bugs, copy the runtime/edition summary from **Diagnostics** if available. Expected
`status` values: `missing`, `installing`, `ready`, `invalid`, `repairable`. Component states:
`not_installed`, `installing`, `installed`, `failed`.

See the [bug report template](../../.github/ISSUE_TEMPLATE/bug_report.md) for required fields.
