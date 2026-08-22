---
name: Bug report
about: Something isn't working
title: "[Bug] "
labels: bug
---

**What happened**
A clear description of the bug.

**Steps to reproduce**
1.
2.
3.

**Expected behavior**
What you expected instead.

**File / format involved**
e.g. a scanned PDF, a DOCX, audio — and the cleanup mode (Off / Rule-based / AI).

**Platform**
<!-- Use frozen identifiers: windows-x64 or linux-x64-glibc -->
- Platform ID:
- Architecture: x64

**Edition**
<!-- lite = first-run provisioning; full = immutable bundled runtime; dev build = local npm run tauri dev -->
- Edition: lite / full / dev build
- MDFlux version (or commit for dev builds):

**Runtime status** *(from Diagnostics, if available)*
- Overall status: missing / installing / ready / invalid / repairable
- Components (core / ocr / audio): not_installed / installing / installed / failed
- Python version shown in Diagnostics:

**Environment**
- OS and version: e.g. Windows 11 23H2, Ubuntu 24.04
- WebView2 (Windows) or WebKitGTK 4.1 (Linux) installed: yes / no / unknown

**Logs / screenshots**
Anything from the Diagnostics panel that helps. Do not paste API keys.

**Release artifact** *(if reporting against a downloaded build)*
- Archive file name: e.g. `MDFlux_0.2.0_portable.zip` or frozen Lite/Full name from [releases docs](../../docs/cross-platform/releases-and-verification.md)
- SHA-256 verified against release page: yes / no / n/a
