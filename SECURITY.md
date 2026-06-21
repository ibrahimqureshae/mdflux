# Security Policy

MDFlux is a local-first desktop app: the user owns the machine, the files, the API key, and the
clicks. The webview renders only the app's own UI and Markdown the user converted from their own
documents (sanitised through `marked` + DOMPurify). Our threat model therefore focuses on
**upstream/integrity** issues a user cannot protect themselves against, not on local-access
scenarios that are inherent to any desktop tool.

## Reporting a vulnerability

Please report suspected vulnerabilities privately to **muhammadibrahim.ger@gmail.com** rather than
opening a public issue. Include steps to reproduce and the affected version. We aim to acknowledge
within a few days.

## Supply-chain integrity

Python dependencies are **version-pinned and integrity-verified** during the one-time setup on first
launch. If a downloaded package doesn't match its expected hash, setup stops rather than running
unverified code.

## Model weights (OCR / audio)

- **OCR:** models ship inside the pinned, integrity-verified OCR package — no separate download.
- **Audio (faster-whisper):** model weights download from the official Systran HuggingFace
  repositories on first use of the opt-in audio engine. These are trusted at download time and not
  yet revision-pinned; pinned verification is planned. If you require a fully verified supply chain,
  avoid the audio engine for now.

## What is intentionally out of scope (local-desktop threat model)

These are standard for a local app where the user controls the environment, and are **not** treated
as vulnerabilities (they would be reopened for any hosted/cloud variant):

- The user's own API key stored in the app's `config.json` on the user's own disk.
- The app reading/writing files the user themselves selected or that the app wrote.
- Document content reaching the optional, opt-in AI cleanup (no tool/function calling, so no
  exfiltration channel; a data-loss guardrail flags content mangling).
