# MDFlux Roadmap

This is a living document — directional, not a promise of dates. Issues and PRs are
welcome on any of these; open one to shape the priority.

## Now (v0.1.x)

- Windows portable build, hardened across 8 engineering stages. ✅ shipped in v0.1.0.
- Stability + diagnostics polish based on early-user reports.

## Next

- **🔌 MCP server** — expose MDFlux conversion as an MCP tool so Claude Code and other
  agents can turn documents into Markdown without leaving the chat.
- **⌨️ CLI** — a scriptable, headless `mdflux convert` for pipelines and CI.
- **🍎 macOS build** — separate arm64 and Intel sidecar builds.
- **🔏 Code signing** — sign the Windows build to remove the SmartScreen warning
  (and notarize the macOS build once it exists).

## Later / exploring

- More OCR languages and tuning presets.
- Optional structured outputs (front-matter, JSON sidecars) for downstream pipelines.
- Pluggable cleanup profiles.

## Out of scope (by design)

- Cloud-hosted conversion. MDFlux is local-first; cloud features will only ever be
  clearly-marked, opt-in seams — never a hardcoded dependency.

---

Have an idea? [Open an issue](https://github.com/ibrahimqureshae/mdflux/issues) or start a
discussion. See [CONTRIBUTING.md](CONTRIBUTING.md) to get a dev build running.
