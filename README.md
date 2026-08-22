<div align="center">

<img src="docs/media/logo/logo-256.png" width="120" alt="MDFlux"/>

# MDFlux

**Turn any document into clean, AI-ready Markdown.**
Local-first · reads scanned PDFs · up to 6× fewer tokens than vision models

**Works with** PDF · DOCX · PPTX · XLSX · EPUB · HTML · CSV · JSON · XML · TXT · MD · images · audio

[![License: MIT](https://img.shields.io/badge/License-MIT-3b82f6.svg)](LICENSE)
[![Download v0.3.0](https://img.shields.io/badge/download-v0.3.0-3b82f6)](https://github.com/ibrahimqureshae/mdflux/releases/latest)
[![Up to 6x fewer tokens](https://img.shields.io/badge/vs%20vision-up%20to%206%C3%97%20fewer%20tokens-3b82f6)](#the-proof-fewer-tokens-lower-cost)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20Linux%20(x64)-3b82f6.svg)](https://github.com/ibrahimqureshae/mdflux/releases)
[![Works offline](https://img.shields.io/badge/works-offline-3fb950)](#)
[![GitHub stars](https://img.shields.io/github/stars/ibrahimqureshae/mdflux?style=flat&label=stars&color=3b82f6)](https://github.com/ibrahimqureshae/mdflux/stargazers)

[![Download for Windows](https://img.shields.io/badge/Download_for_Windows-Lite_x64-2563EB?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/ibrahimqureshae/mdflux/releases/latest/download/MDFlux_0.3.0_windows_x64_lite.zip)
&nbsp;&nbsp;
[![Download for Linux](https://img.shields.io/badge/Download_for_Linux-Lite_x64-F59E0B?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/ibrahimqureshae/mdflux/releases/latest/download/MDFlux_0.3.0_linux_x64_glibc_lite.tar.gz)

[Full / offline-ready downloads](https://github.com/ibrahimqureshae/mdflux/releases/latest)
&nbsp;&nbsp;·&nbsp;&nbsp;
[**Cross-platform docs**](docs/cross-platform/README.md)
&nbsp;&nbsp;·&nbsp;&nbsp;
[Website](https://ibrahimqureshae.github.io/mdflux/)
&nbsp;&nbsp;·&nbsp;&nbsp;
[The proof](#the-proof-fewer-tokens-lower-cost)
&nbsp;&nbsp;·&nbsp;&nbsp;
[How it compares](#how-it-compares-to-microsoft-markitdown)
&nbsp;&nbsp;·&nbsp;&nbsp;
[Report a bug](https://github.com/ibrahimqureshae/mdflux/issues)
&nbsp;&nbsp;·&nbsp;&nbsp;
[❤️ Sponsor](https://github.com/sponsors/ibrahimqureshae)

<img src="docs/media/demo-hero.gif" width="780" alt="Drop a document, get clean Markdown in seconds"/>

</div>

---

## Why MDFlux?

Getting a document into a shape an LLM can use is more annoying than it should be. You either dump the raw text and lose every heading, table, and list, or you ship your pages to a cloud vision model as images, which means your documents leave your machine and you pay by the page to read your own files. And scanned PDFs? Plain text extractors just hand you back nothing. The text is right there, and the tool acts like the page is blank.

MDFlux is what I wanted instead. Drop in a file or a folder and get back clean, structured Markdown, with OCR for those "blank" scanned pages, batch processing for a whole directory, and an optional cleanup pass to tidy up messy extraction. It runs entirely on your machine. It's built on Microsoft's [MarkItDown](https://github.com/microsoft/markitdown), with everything around it that makes the engine actually usable day to day.

---

## The proof: fewer tokens, lower cost

Every time a document gets read by an LLM, you pay for it in tokens. The common way to feed a document to a model is to send its pages as images to a vision model, and images are an expensive way to spend tokens. MDFlux hands the model clean Markdown instead, which is far cheaper to read and reuse.

**Why clean Markdown costs fewer tokens than feeding documents to AI:**

- **You pay for pixels, not words.** A page sent to a vision model as an image costs a fixed chunk of tokens (often well over a thousand) no matter how little text is on it. The same page as Markdown is usually a few hundred.
- **Plain text tokenizes efficiently.** Markdown is just text, with no image data, no markup bloat, no base64 blobs.
- **Clean beats raw.** MDFlux strips the broken layout, repeated whitespace, and junk characters that pad out messy extractions, so you don't spend tokens on noise.
- **Structure stays compact.** Headings, tables, and lists carry the document's meaning in very few tokens, so the model understands more for less.
- **It compounds.** The saving lands on every single call that reads the document, so it multiplies across a pipeline or a batch instead of happening once.

**About 2 to 6 times fewer tokens than vision.** For ordinary documents, MDFlux Markdown runs around 4 times lighter than sending the pages as images, and up to 5.7 times lighter on scanned pages. That saving lands on every single call that reads the document, so it compounds quickly across a pipeline or a large batch.

<div align="center">
<img src="docs/media/poster-2-vs-vision-1080x1350.png" width="380" alt="Two to six times fewer tokens than a vision model"/>
</div>

**And it reads what other tools return empty.** Point a plain extractor at a scanned, image-only PDF and you get zero usable text. MDFlux's OCR recovers it, and even then it stays lighter than the vision route:

| Scanned, image-only PDF | Usable tokens of text |
|---|---:|
| Plain text extractor | 0 |
| Vision model (page as an image) | 10,731 |
| MDFlux (OCR to Markdown) | 1,893 |

That's the full text recovered in about 5.7 times fewer tokens than the vision model, which still has to OCR the image on its end anyway.

<div align="center">

[![Download for Windows](https://img.shields.io/badge/Download_for_Windows-Lite_x64-2563EB?style=for-the-badge&logo=windows11&logoColor=white)](https://github.com/ibrahimqureshae/mdflux/releases/latest/download/MDFlux_0.3.0_windows_x64_lite.zip)
&nbsp;
[![Download for Linux](https://img.shields.io/badge/Download_for_Linux-Lite_x64-F59E0B?style=for-the-badge&logo=linux&logoColor=white)](https://github.com/ibrahimqureshae/mdflux/releases/latest/download/MDFlux_0.3.0_linux_x64_glibc_lite.tar.gz)

[**Full / offline-ready downloads**](https://github.com/ibrahimqureshae/mdflux/releases/latest)
&nbsp;·&nbsp;
[**Editions &amp; platforms**](docs/cross-platform/README.md)
&nbsp;·&nbsp; Free &amp; MIT-licensed &nbsp;·&nbsp; No account, no cloud

</div>

---

## Key features

| | |
|---|---|
| 💸 **Fewer tokens, lower cost** | Clean Markdown costs about 2 to 6 times fewer tokens than sending pages to a vision model, so every LLM call that reads the document is cheaper. |
| 🔒 **Local and private** | Your documents never leave your machine. No cloud, no API key, no account. |
| 🔍 **Reads scanned PDFs** | Built-in OCR recovers text from scans that other tools treat as blank. |
| 🧱 **Real structure** | Proper Markdown with headings, tables, and lists intact. Readable, greppable, diff-able. |
| 🖥️ **No terminal needed** | Portable app. Unzip, run, click through a one-time setup. Done. |
| 📦 **Many formats** | PDF, DOCX, PPTX, XLSX, EPUB, HTML, CSV, JSON, XML, TXT, Markdown, images, and audio. |
| 🔁 **Batch a whole folder** | Convert everything at once, with progress, cancellation, and per-file diagnostics. |
| 🧹 **Optional cleanup** | Off, rule-based, or an AI pass (local or API). The **Changes** tab shows what cleanup added or removed. |

---

## What's new in 0.3.0

- **Cross-platform release matrix:** Windows and Linux x64 (glibc) Lite and Full archives.
- **Lite and Full editions:** Lite provisions dependencies transactionally on first launch;
  Full bundles an immutable runtime and never installs packages at runtime.
- **Runtime reliability:** recoverable provisioning, offline-ready Full operation, and clearer
  runtime health and repair diagnostics.
- **AI cleanup:** more predictable cleanup behavior and clearer provider/runtime diagnostics.
- **Issue fixes:** AI cleanup timeout resilience (#25), Linux support (#28), and OCR
  dependency/provisioning reliability through Lite recovery and the bundled Full runtime (#30).

## What's new in 0.2.0

- **Changes tab:** added and removed lines after cleanup.
- **OCR:** newer on-device engine for scans.
- **AI cleanup:** pick DeepSeek, OpenAI, Groq, or another provider in Diagnostics, then Test the key.
- Drop `.txt` and `.md` like any other file.

If you already had OCR from 0.1.0, reinstall it from Diagnostics.

---

## Who it's for

🤖 **AI and RAG builders**: feed clean, structured source documents to any model instead of raw text or pricey vision tokens

🔬 **Researchers**: batch-convert papers, reports, and scanned archives into searchable Markdown

🧑‍💻 **Developers**: get diff-able, version-controllable text out of binary document formats

📝 **Writers and analysts**: pull clean copy out of PDFs and Office files without the formatting mess

🔒 **Privacy-conscious users**: convert sensitive contracts, records, and decks with nothing ever uploaded

---

## How it works

```
1. Drop a file or folder   →   PDF, Office, EPUB, scans, audio, and more
2. Pick a cleanup mode      →   Off, rule-based, or AI (local or API)
3. Get clean Markdown       →   Preview, Source, Split, or Changes. Copy or save as .md.
```

The first launch sets up a private, self-contained Python environment (one time, needs internet). Every conversion after that runs fully offline.

<div align="center">
<img src="docs/media/screenshot-cleanup-modes.png" width="560" alt="MDFlux cleanup mode selector: Off, Rule-based, Local AI, and API"/>
<br/>
<sub>Cleanup modes: Off, rule-based, or an AI pass, chosen per run.</sub>
</div>

<div align="center">
<img src="docs/media/screenshot-changes.png" width="560" alt="Changes tab after cleanup, showing added and removed lines"/>
<br/>
<sub>The Changes tab after cleanup: what was added or removed, line by line.</sub>
</div>

---

## See it in action

**01 · Select.** Grab a folder of mixed files: Word, PowerPoint, Excel, PDFs, scans, web pages, anything. No conversion settings to pick.

<div align="center">
<img src="docs/media/fetching-files.gif" width="300" alt="Selecting a folder of mixed files"/>
</div>

**02 · Convert.** One drop turns the whole batch into AI-ready Markdown, locally. OCR recovers text from scans that other tools read as empty.

<div align="center">
<img src="docs/media/converting-to-markdown.gif" width="720" alt="Converting documents to clean Markdown"/>
</div>

**03 · Stays healthy.** Dependency health and diagnostics run on-device, so you can see exactly what's installed and working.

<div align="center">
<img src="docs/media/diagnostics.gif" width="720" alt="Dependency health and diagnostics"/>
</div>

---

## How it compares to Microsoft MarkItDown

MDFlux is built on Microsoft's [MarkItDown](https://github.com/microsoft/markitdown), which is a genuinely great conversion library. What MDFlux adds is everything around it: the OCR for scans, the desktop app, the batching, the reliability, and the privacy-by-default packaging that lets anyone run it against a folder of files without touching a command line.

<div align="center">
<img src="docs/media/poster-3-vs-markitdown-1080x1350.png" width="380" alt="MDFlux next to MarkItDown"/>
</div>

| | Microsoft MarkItDown | MDFlux |
|---|:---:|:---:|
| Core conversion engine | yes | yes (uses MarkItDown) |
| Scanned / image-only PDFs | returns roughly 0 characters | built-in OCR recovers the text |
| Install and run | `pip install` plus a terminal | portable app, no terminal |
| Dependency setup | manual (pip, ffmpeg, OCR extras) | sets itself up on first launch |
| Batch a whole folder | write your own script | built in, runs concurrently with progress |
| Timeouts and cancel | can hang with no feedback | every job streams progress and can be cancelled |
| Cleanup modes | raw output | Off, rule-based, or AI cleanup (local or API) |
| Preview and diagnostics | none | rendered preview plus a health panel |
| Audio transcription | plugin or Azure | local, built in |
| Privacy | local if you wire it up | local by default |

On already-clean files the output is close to identical, because under the hood it is MarkItDown. The point isn't to beat the engine. It's to make that engine genuinely usable.

<div align="center">
<sub>If MDFlux sounds useful, consider ⭐ starring the repo. It helps others find it.</sub>
</div>

---

## Editions and platforms

MDFlux is **one cross-platform product** with two editions on each supported platform:

| Edition | Download size | Python setup | Best for |
| --- | --- | --- | --- |
| **Lite** | Smaller archive | One-time transactional provisioning (internet on first launch) | Most users; smaller download |
| **Full** | Larger archive | Immutable bundled runtime — no package installs at runtime | Offline / air-gapped use |

Supported platform identifiers: `windows-x64` and `linux-x64-glibc` (x64 only). Speech model
weights are on demand in **both** editions.

> **Release status:** v0.3.0 introduces verified Windows and Linux x64 Lite and Full archives.
> Windows v0.2.0 remains available under the legacy Lite-style name
> `MDFlux_<version>_portable.zip`. Each v0.3.0 archive is verified before the release is
> published; see [docs/cross-platform/README.md](docs/cross-platform/README.md).

Full details: [editions](docs/cross-platform/editions.md) ·
[platforms & support](docs/cross-platform/platforms-and-support.md) ·
[releases & verification](docs/cross-platform/releases-and-verification.md)

---

## Getting started

**Requirements:** Windows 10 or 11 (x64) with WebView2 (ships with current Windows). Linux x64
(glibc, Ubuntu 22.04+) needs WebKitGTK 4.1 (`libwebkit2gtk-4.1-0`) — including **Full** edition
builds. macOS is on the [roadmap](#roadmap).

**1. Download and run.** Get the portable archive from [Releases](https://github.com/ibrahimqureshae/mdflux/releases/latest). On Windows, extract the zip and double-click `MDFlux.exe`. No installer, no admin rights. Linux Lite/Full tarballs with frozen names are **pending** the cross-platform release — see [setup guide](docs/cross-platform/setup-ubuntu.md) for contributor builds.

> **SmartScreen warning?** The build is open source and unsigned. Click "More info" then "Run anyway". You'll need the WebView2 runtime, already on current Windows 10/11.

**2. First launch (one-time, internet required).** MDFlux sets up a private, self-contained Python environment. This happens once. After that, it runs fully offline.

<div align="center">
<img src="docs/media/screenshot-setup.png" width="560" alt="MDFlux first-run setup screen">
</div>

**3. Convert.** Drop a document onto the window, pick a cleanup mode, and click "Convert to AI-Ready Markdown". Preview it, then copy straight from the preview or save as `.md`. For a whole folder, you pick an output folder up front and every converted file lands there.

<div align="center">
<img src="docs/media/converting-to-markdown.gif" width="720" alt="Converting a document to clean Markdown"/>
</div>

To verify your download, check the SHA-256 posted on the [release page](https://github.com/ibrahimqureshae/mdflux/releases/latest). After cross-platform integration, use the [artifact verifier](docs/cross-platform/releases-and-verification.md) for Lite and Full archives.

---

## Supported formats

| Documents | Office | Web and data | Other |
|---|---|---|---|
| PDF (including scanned, via OCR) | DOCX | HTML | Audio to transcript (MP3, WAV, M4A, OGG, FLAC, AAC) |
| EPUB | PPTX | CSV, JSON, XML | Images via OCR (PNG, JPG, GIF, WEBP, TIFF, BMP) |
| TXT, Markdown | XLSX, XLS | | OCR on images embedded in documents |

---

## Troubleshooting

**"Windows protected your PC"**: That's SmartScreen reacting to an unsigned build. Click "More info" then "Run anyway". The build is open source; code signing is on the roadmap.

**Linux says a WebKit library is missing**: Install the runtime WebKitGTK package (on Ubuntu/Lubuntu 24.04: `sudo apt install libwebkit2gtk-4.1-0 libgtk-3-0 xdg-utils`). That is the Linux equivalent of WebView2.

**The first launch is downloading for a while**: That's the one-time setup of the local Python environment. It only happens once, and every launch after is instant and offline.

**AI cleanup says the key was rejected (401)**: The key is valid for a *provider*, not for "any API". In Diagnostics, set **Provider** to match the key (DeepSeek, Groq, OpenRouter, …) then Test. A DeepSeek key sent to OpenAI will always 401. Unambiguous prefixes (`sk-ant-`, `gsk_`, `sk-or-`, `AIza`, `xai-`, `pplx-`) switch the provider automatically; OpenAI and DeepSeek both start with `sk-`, so those you pick yourself.

**A conversion finished with a warning or looks empty**: Open the diagnostics panel. It tells you what's installed and healthy and what went wrong, so you get a clear next step instead of a silent empty file.

<div align="center">
<img src="docs/media/screenshot-diagnostics.png" width="560" alt="MDFlux diagnostics panel: dependency health and per-file status"/>
</div>

**Where are my converted files?** In the output folder shown in the app. For batch jobs you pick the folder up front.

**Anything else**: [Open an issue](https://github.com/ibrahimqureshae/mdflux/issues). Bug reports genuinely help.

---

## Roadmap

- [ ] MCP server, so Claude Code and other agents can convert documents through MDFlux directly
- [ ] CLI for scripted, headless conversion in pipelines and CI
- [ ] macOS build (arm64 and Intel)
- [ ] Code signing, to remove the SmartScreen warning
- [ ] More OCR languages and tuning presets

The full list lives in [ROADMAP.md](ROADMAP.md). Open an issue if you want to shape it.

---

## For developers

MDFlux is a Tauri 2 (Rust) shell around a Python sidecar (MarkItDown + OCR + audio), with a Svelte 5 front end. You'll need Node 20+, Rust (stable), and the Tauri prerequisites for your OS; then clone it, run `npm install`, and `npm run tauri dev`. See [CONTRIBUTING.md](CONTRIBUTING.md) for build steps and [docs/cross-platform/setup-ubuntu.md](docs/cross-platform/setup-ubuntu.md) for Linux. Optional [devenv](docs/cross-platform/setup-devenv.md) setup is planned for contributors who want a pinned shell.

---

## Contributing

Contributions are genuinely welcome. Honestly, it's the main reason I'm open-sourcing this. Bug reports, ideas, code, and testing on different hardware all help.

Start with a [good first issue](https://github.com/ibrahimqureshae/mdflux/labels/good%20first%20issue), and see [CONTRIBUTING.md](CONTRIBUTING.md) to get a dev build running. Commits use a [DCO](CONTRIBUTING.md) sign-off (`git commit -s`). Be kind; we follow a [Code of Conduct](CODE_OF_CONDUCT.md).

---

## Support the project

MDFlux is free and MIT-licensed. If it saves you time, supporting it goes straight into the roadmap above: the macOS build, code signing, and the MCP server and CLI.

<p align="center">
  <a href="https://github.com/sponsors/ibrahimqureshae">
    <img src="https://img.shields.io/badge/Sponsor%20on%20GitHub-%E2%99%A5-ea4aaa?style=for-the-badge&logo=githubsponsors&logoColor=white" alt="Sponsor on GitHub"/>
  </a>
  &nbsp;&nbsp;
  <a href="https://buymeacoffee.com/mibrahim99">
    <img src="https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?style=for-the-badge&logo=buymeacoffee&logoColor=black" alt="Buy Me a Coffee"/>
  </a>
  &nbsp;&nbsp;
  <a href="https://www.paypal.me/mibrahimqr">
    <img src="https://img.shields.io/badge/Donate%20via%20PayPal-0070ba?style=for-the-badge&logo=paypal&logoColor=white" alt="Donate via PayPal"/>
  </a>
</p>

And starring the repo is free, which helps more than you'd think.

---

## License

MIT, copyright 2026 ibrahimqureshae. Free to use, modify, and distribute. See [LICENSE](LICENSE).

---

<div align="center">
Built on open-source foundations: <a href="https://github.com/microsoft/markitdown">MarkItDown</a> · <a href="https://tauri.app/">Tauri</a> · <a href="https://github.com/RapidAI/RapidOCR">RapidOCR</a> · <a href="https://github.com/pypdfium2-team/pypdfium2">pypdfium2</a>

<br/>

<a href="https://claude.com/claude-code"><img src="https://img.shields.io/badge/Built%20with-Claude%20Code-D97757?logo=claude&logoColor=white" height="20" alt="Built with Claude Code"/></a>
</div>
