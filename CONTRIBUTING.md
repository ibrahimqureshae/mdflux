# Contributing to MDFlux

Thanks for your interest—contributions are welcome.

MDFlux is one cross-platform codebase for Windows x64 and Linux x64 (glibc). Read the
[cross-platform documentation](docs/cross-platform/README.md) for editions, support boundaries,
release verification, and setup paths before opening a pull request.

## Project layout

- `app/` — Tauri 2 desktop app with a Svelte 5 front end and Rust shell.
- `app/src-tauri/resources/sidecar/` — Python conversion sidecar, including cleanup, OCR, and audio support.
- `scripts/make-portable.ps1` and `scripts/make-portable-full.ps1` — Windows portable archives.
- `scripts/make-portable-linux.sh` — Linux x64 portable archive.

The shell contains no conversion logic and the sidecar contains no UI. They communicate through the IPC contract.

## Prerequisites

- [Node.js](https://nodejs.org/) 20+
- [Rust](https://www.rust-lang.org/tools/install) stable and the Tauri prerequisites for your OS
- Windows with WebView2, or Linux x64 (glibc) with WebKitGTK 4.1 and GTK 3

See [the Ubuntu setup guide](docs/cross-platform/setup-ubuntu.md) for Linux packages. Lite
provisions Python 3.12 on first launch; Full includes Python in the archive.

## Run and build

```bash
cd app
npm install
npm run tauri dev
```

Use the portable build scripts above to create local archives. Published names are documented in
[releases-and-verification.md](docs/cross-platform/releases-and-verification.md).

## Checks before a pull request

```bash
cd app && npm run check
cd app/src-tauri && cargo check --locked && cargo test --locked
cd app/src-tauri/resources/sidecar && python -m unittest discover -s tests -p "test_*.py"
```

## Pull requests and issues

Keep pull requests focused, describe what changed and why, and use platform adapter and packaging
layers for cross-platform behavior. Contributions are licensed under MIT; a
[DCO](https://developercertificate.org/) sign-off is appreciated.

Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md) and include platform, edition,
architecture, and Diagnostics runtime status. For security issues, see [`SECURITY.md`](SECURITY.md)
instead of opening a public issue.
