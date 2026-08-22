# Optional devenv contributor setup

MDFlux supports an optional [devenv](https://devenv.sh/) shell for reproducible Linux, WSL, and
macOS contributor environments. Nix/devenv is not required; the [ordinary Ubuntu setup](setup-ubuntu.md)
remains supported.

## Design goals

The environment pins Node 20, Rust, GTK/WebKitGTK, OpenSSL, `pkg-config`, `patchelf`, `uv`, and
`shellcheck`, while keeping secrets out of the Nix store and release binaries free of Nix Store
paths. It complements the ordinary commands documented in [CONTRIBUTING.md](../../CONTRIBUTING.md).

## Common commands

```bash
devenv shell
devenv test
```

Use the ordinary setup for a quick Ubuntu clone. Use devenv when the same toolchain versions must
be reproduced across Linux, WSL, or macOS contributors. CI and release builds follow the repository
workflows and do not require devenv.

macOS contributors may use devenv where packages permit, but macOS release binaries are not currently
listed in the supported platform matrix.
