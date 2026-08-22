# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] - 2026-08-23

### Added

- Cross-platform Windows x64 and Linux x64 (glibc) release packaging with Lite and Full editions.
- Linux platform support, including Ubuntu/glibc baseline guidance and WebKitGTK requirements.
- Cross-platform documentation covering editions, supported platforms, Ubuntu contributor setup,
  release archive names, checksums, and artifact verification.
- Bug report fields for platform, edition, architecture, and runtime status.

### Changed

- Lite now uses transactional, recoverable runtime provisioning; Full bundles an immutable
  offline-ready runtime and never installs Python packages at runtime.
- Runtime health, repair, and edition diagnostics now make provisioning state and failures clearer.
- AI cleanup handling and provider/runtime diagnostics were cleaned up for more predictable runs.
- README and contributor guidance now describe one shared Windows and Linux product codebase.

### Fixed

- Addressed AI cleanup timeout resilience reported in #25, Linux support reported in #28,
  and OCR dependency/provisioning failures reported in #30 through the bundled Full runtime
  and recoverable Lite provisioning.

## [0.2.0] - 2026-08-19

### Added

- Changes tab after cleanup, with added and removed lines.
- Provider picker in Diagnostics (DeepSeek, OpenAI, Groq, OpenRouter, or a compatible endpoint). Test the key first. OpenAI and DeepSeek keys both start with `sk-`, so pick those yourself; other prefixes switch automatically.
- Drop `.txt` and `.md` like any other file.
- Banner when a file converted to nothing usable.
- Type chip when dragging a file over the window.
- Ctrl+C with nothing selected copies the full Markdown.
- Clearer errors for damaged PDFs, unsupported types, and empty extracts.

### Changed

- Better conversion for PowerPoint charts, SVG, and Word equations.
- Better on-device OCR for scans. Models still ship in the install.
- JSON and XML show as fenced code in Preview.

If you already had OCR from 0.1.0, reinstall it from Diagnostics.

## [0.1.0] - 2026-06-19

First public release. Windows, portable (extract-and-run; no installer).

### Added

- Convert PDF, DOCX, PPTX, XLSX, EPUB, HTML, CSV, JSON, and XML to clean Markdown, built on
  Microsoft's MarkItDown.
- **Cleanup modes:** Off, deterministic rule-based, and an optional AI pass (local Ollama or
  bring-your-own-key OpenAI-compatible / Anthropic).
- **OCR** for scanned PDFs and images (RapidOCR) and **audio transcription** (faster-whisper),
  installed on demand as optional engines.
- **Batch conversion** with adaptive concurrency, cancel, timeouts, and per-file progress.
- **Output control:** folder rules, naming templates, before/after preview.
- Self-provisioning Python 3.12 runtime on first launch; fully offline thereafter.
- First-run setup shown as a multi-step stepper with live download size/speed.

### Security

- Dependencies are integrity-verified during the one-time setup, so first run is trustworthy. See
  [`SECURITY.md`](SECURITY.md).

[0.3.0]: https://github.com/ibrahimqureshae/mdflux/releases/tag/v0.3.0
[0.2.0]: https://github.com/ibrahimqureshae/mdflux/releases/tag/v0.2.0
[0.1.0]: https://github.com/ibrahimqureshae/mdflux/releases/tag/v0.1.0
