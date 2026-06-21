# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-06-19

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

[0.1.0]: https://github.com/ibrahimqureshae/mdflux/releases/tag/v0.1.0
