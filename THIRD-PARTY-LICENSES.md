# Third-Party Licenses

MDFlux itself is licensed under the **MIT License** (see [`LICENSE`](LICENSE)). It builds on the
open-source components listed below. This is a curated inventory of the direct and
otherwise-notable dependencies; each pulls in its own transitive tree under compatible terms.

To regenerate the full transitive list:

- **Rust:** `cargo tree` (or `cargo about generate` for a license report) in `app/src-tauri`
- **npm:** `npm ls --all` in `app`
- **Python:** the runtime venv is provisioned on first launch; inspect with
  `uv pip list` against `%APPDATA%\com.projektvisyo.mdflux\venv`

All components listed below are under licenses compatible with the MIT License under which MDFlux
is distributed.

---

## License compatibility summary

**The dependency tree is free of strong copyleft** — no AGPL, no GPL, no LGPL. Every dependency is
permissive (MIT / BSD / Apache-2.0 / MIT-CMU / PSF / OFL / 0BSD / Zlib), with two MPL-2.0
components (`certifi`, `tqdm`).

MPL-2.0 is file-level weak copyleft: it covers only the MPL-licensed files themselves and imposes
no obligation on the larger work. Both are used unmodified and combine freely with MDFlux's MIT
license.

---

## Python sidecar (provisioned at runtime, not bundled in the repo)

Declared in `app/src-tauri/resources/sidecar/requirements.txt`
(`markitdown[pdf,docx,pptx,xlsx,xls]`, `openai`) plus the install-on-choice OCR/audio
engines. Key packages:

| Package | Version | License |
|---------|---------|---------|
| markitdown | 0.1.6 | MIT |
| openai | 2.43.0 | Apache-2.0 |
| pdfminer.six | 20260107 | MIT |
| pdfplumber | 0.11.10 | MIT |
| mammoth | 1.11.0 | BSD-2-Clause |
| python-pptx | 1.0.2 | MIT |
| openpyxl | 3.1.5 | MIT |
| xlrd | 2.0.2 | BSD-3-Clause |
| lxml | 6.1.1 | BSD-3-Clause |
| defusedxml | 0.7.1 | PSF |
| beautifulsoup4 | 4.15.0 | MIT |
| markdownify | 1.2.2 | MIT |
| charset-normalizer | 3.4.7 | MIT |
| magika | 0.6.3 | Apache-2.0 |
| httpx | 0.28.1 | BSD-3-Clause |
| pydantic | 2.13.4 | MIT |
| requests | 2.34.2 | Apache-2.0 |
| certifi | 2026.6.17 | **MPL-2.0** (file-level; no effect on larger work) |

### Install-on-choice engines (OCR / audio — only installed if the user enables them)

| Package | Version | License |
|---------|---------|---------|
| pypdfium2 | 5.9.0 | BSD-3-Clause / Apache-2.0 |
| rapidocr-onnxruntime | 1.4.4 | Apache-2.0 |
| onnxruntime | 1.20.1 | MIT |
| faster-whisper | 1.2.1 | MIT |
| ctranslate2 | 4.8.0 | MIT |
| tokenizers | 0.23.1 | Apache-2.0 |
| huggingface-hub | 1.20.0 | Apache-2.0 |
| pillow | 12.2.0 | MIT-CMU (HPND) |
| numpy | 2.4.6 | BSD-3-Clause (+ 0BSD / MIT / Zlib components) |
| tqdm | 4.68.3 | **MPL-2.0** AND MIT (file-level; no effect on larger work) |

The OCR/audio model weights are downloaded from their respective upstreams on first use and are
not redistributed by this project.

---

## Rust shell (Tauri)

Declared in `app/src-tauri/Cargo.toml`:

| Crate | Version (req) | License |
|-------|---------------|---------|
| tauri | 2.x | MIT OR Apache-2.0 |
| tauri-plugin-opener | 2.x | MIT OR Apache-2.0 |
| tauri-plugin-dialog | 2.x | MIT OR Apache-2.0 |
| tauri-plugin-fs | 2.x | MIT OR Apache-2.0 |
| serde / serde_json | 1.x | MIT OR Apache-2.0 |
| tokio | 1.x | MIT |
| reqwest | 0.12 | MIT OR Apache-2.0 |
| zip | 2.x | MIT |
| flate2 | 1.x | MIT OR Apache-2.0 |
| tar | 0.4 | MIT OR Apache-2.0 |
| sha2 | 0.10 | MIT OR Apache-2.0 |

The Windows build also relies on the system **WebView2** runtime (Microsoft, distributed with
Windows) — it is not bundled.

---

## Frontend (SvelteKit)

Declared in `app/package.json`:

| Package | Version | License |
|---------|---------|---------|
| svelte | 5.56.3 | MIT |
| @sveltejs/kit | 2.64.0 | MIT |
| @sveltejs/adapter-static | 3.0.10 | MIT |
| @sveltejs/vite-plugin-svelte | 5.1.1 | MIT |
| vite | 6.4.3 | MIT |
| typescript | 5.6.3 | Apache-2.0 |
| svelte-check | 4.6.0 | MIT |
| @tauri-apps/api | 2.11.0 | MIT OR Apache-2.0 |
| @tauri-apps/cli | 2.11.2 | MIT OR Apache-2.0 |
| @tauri-apps/plugin-dialog | 2.7.1 | MIT OR Apache-2.0 |
| @tauri-apps/plugin-fs | 2.5.1 | MIT OR Apache-2.0 |
| @tauri-apps/plugin-opener | 2.5.4 | MIT OR Apache-2.0 |
| marked | 18.0.5 | MIT |
| dompurify | 3.4.10 | Apache-2.0 OR MPL-2.0 |
| @fontsource-variable/inter | 5.2.8 | OFL-1.1 (Inter font) |
| @fontsource/jetbrains-mono | 5.2.8 | OFL-1.1 (JetBrains Mono font) |

Bundled fonts (Inter, JetBrains Mono) are under the SIL Open Font License 1.1.

---

## uv (provisioning bootstrap)

The first-launch setup uses the **uv** binary (Astral), licensed **MIT OR Apache-2.0**. It is
fetched at runtime, not bundled.
