# Contributing to MDFlux

Thanks for your interest — contributions are very welcome.

## Project layout

- `app/` — the Tauri 2 desktop app: a Svelte 5 (SvelteKit) front end (`app/src`) and a Rust
  shell (`app/src-tauri/src`).
- `app/src-tauri/resources/sidecar/` — the Python conversion sidecar (wraps Microsoft's
  MarkItDown, plus cleanup / OCR / audio). Dependencies are hash-pinned in `requirements*.lock`.
- `scripts/make-portable.ps1` — builds the portable, extract-and-run distributable.

The shell never contains conversion logic; the sidecar never contains UI. The IPC contract is the
only coupling.

## Prerequisites

- [Node.js](https://nodejs.org/) 18+
- [Rust](https://www.rust-lang.org/tools/install) (stable) + the Tauri prerequisites for your OS
- Windows + WebView2 runtime (present on current Windows 10/11)

The app downloads its own Python 3.12 environment on first launch — you don't need Python installed
to run it.

## Run it locally

```bash
cd app
npm install
npm run tauri dev
```

## Build the distributable

```powershell
pwsh -File scripts/make-portable.ps1
# -> dist/MDFlux_<version>_portable.zip   (portable, no installer)
```

MDFlux ships as a portable zip, not an installer (`bundle.active: false` in `tauri.conf.json`).

## Checks before a PR

```bash
cd app && npm run check          # svelte-check (0 errors expected)
cd app/src-tauri && cargo check  # Rust
```

## Pull requests

- Branch from `main`, keep PRs focused, and describe what changed and why.
- Match the surrounding code's style.
- By submitting a PR you certify you wrote the change (or have the right to contribute it) under
  the project's **MIT** license. No CLA — a [DCO](https://developercertificate.org/) sign-off
  (`git commit -s`) is appreciated for provenance.

## Reporting issues

Use the issue templates. For security issues, **do not** open a public issue — see
[`SECURITY.md`](SECURITY.md).
