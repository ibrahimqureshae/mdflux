# Ordinary Ubuntu / Linux setup

This is the **standard, non-Nix** path for building and running MDFlux on Linux x64 (glibc).
An optional [devenv](setup-devenv.md) path adds pinned tooling.

## Supported host

- **Ubuntu 22.04+** or similar glibc x64 distribution (Lubuntu 24.04 tested in development)
- **Not supported in this release cycle:** ARM64, musl-only systems, macOS (see
  [platforms-and-support.md](platforms-and-support.md))

## Runtime packages (to run the GUI)

```bash
sudo apt update
sudo apt install -y \
  libwebkit2gtk-4.1-0 \
  libgtk-3-0 \
  xdg-utils \
  libgl1 \
  libgomp1
```

`libwebkit2gtk-4.1-0` is the Linux equivalent of Windows WebView2. **Full edition archives still
require these system libraries**; they are not bundled inside the tarball.

## Build prerequisites

```bash
sudo apt install -y \
  libwebkit2gtk-4.1-dev \
  libgtk-3-dev \
  libayatana-appindicator3-dev \
  librsvg2-dev \
  libssl-dev \
  libxdo-dev \
  libjavascriptcoregtk-4.1-dev \
  patchelf \
  pkg-config \
  build-essential \
  curl
```

## Node.js 20+

Ubuntu's default `apt install nodejs` is **too old** (18.x). Install Node **20+**:

- [nodejs.org](https://nodejs.org/) binary tarball, or
- [NodeSource setup_20.x](https://github.com/nodesource/distributions), or
- `nvm` / `fnm`

Verify:

```bash
node --version   # v20.x or newer
```

## Rust (stable)

```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
rustup default stable
```

## uv (Python test and Full-package tooling)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

The sidecar test runner uses uv to create an isolated, hash-locked test environment. The Full
portable builder also uses a uv-managed Python 3.12 runtime.

## Clone and run in development

```bash
git clone https://github.com/ibrahimqureshae/mdflux.git
cd mdflux/app
npm ci
npm run tauri dev
```

The app provisions its own Python 3.12 environment on first launch (Lite-style dev workflow).
You do **not** need system Python to **run** the shipped app.

## Build a portable archive (developer)

Current baseline script (legacy output name):

```bash
bash scripts/make-portable-linux.sh
# -> dist/MDFlux_<version>_linux_x64.tar.gz
```

Portable Lite/Full packaging scripts and archive names:

- `scripts/make-portable-linux.sh` ? Lite (`MDFlux_<version>_linux_x64_glibc_lite.tar.gz`)
- `scripts/make-portable-linux-full.sh` ? Full (`MDFlux_<version>_linux_x64_glibc_full.tar.gz`)

> Use the commands available in your checkout; package names may vary by release.

## WSL2 notes

On Windows 11 + Ubuntu 24.04 under WSL2:

- Install Node 20+ as above (not `apt nodejs`).
- Install the runtime and build packages in the Linux distro.
- GUI apps use WSLg; `echo $DISPLAY` should print `:0`.

## Validation commands (frozen)

From the repository root, after changes:

```bash
cd app && npm run check
cd app/src-tauri && cargo check --locked && cargo test --locked
cd app/src-tauri/resources/sidecar && python -m unittest discover -s tests -p "test_*.py"
```

Artifact verification:

```bash
python -m tools.release --archive dist/MDFlux_<version>_linux_x64_glibc_lite.tar.gz \
  --platform linux-x64-glibc --edition lite
```

See [CONTRIBUTING.md](../../CONTRIBUTING.md) for pull-request expectations.
