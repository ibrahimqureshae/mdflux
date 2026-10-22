# Releases, checksums, and artifact verification

## Frozen archive names

After cross-platform integration, published archives use these deterministic names (replace
`<version>` with the semver tag, for example `0.2.1`):

| Platform | Edition | Archive name |
| --- | --- | --- |
| Windows x64 | Lite | `MDFlux_<version>_windows_x64_lite.zip` |
| Windows x64 | Full | `MDFlux_<version>_windows_x64_full.zip` |
| Linux x64 glibc | Lite | `MDFlux_<version>_linux_x64_glibc_lite.tar.gz` |
| Linux x64 glibc | Full | `MDFlux_<version>_linux_x64_glibc_full.tar.gz` |

> **Legacy v0.2.0 Windows build:** `MDFlux_<version>_portable.zip` (Lite-style provisioning,
> pre-frozen naming). Treat it as a Windows Lite-class build.

## Archive layout (frozen)

**Windows**

```text
MDFlux.exe
resources/
  edition.json
  sidecar/
  runtime/                 # Full only
    python.exe
```

**Linux**

```text
MDFlux
resources/
  edition.json
  sidecar/
  runtime/                 # Full only
    bin/python3
```

## Download checksums

Each GitHub Release publishes **SHA-256** checksums for attached archives.

1. Download the archive from [Releases](https://github.com/ibrahimqureshae/mdflux/releases).
2. Open the release notes for the matching `SHA256SUMS` or per-file hash entry.
3. Verify locally:

   **Windows (PowerShell)**

   ```powershell
   Get-FileHash -Algorithm SHA256 .\MDFlux_<version>_windows_x64_lite.zip
   ```

   **Linux**

   ```bash
   sha256sum MDFlux_<version>_linux_x64_glibc_lite.tar.gz
   ```

4. Compare the output to the published hash **before extracting**.

Each published release includes checksums for its attached archives. Verify the hash posted on the matching release entry.

## Expected sizes

Archive sizes **vary by version** (dependency updates, bundled Full runtime, compression). **Do
not rely on hard-coded size promises in documentation.**

After a release is published, use the byte size shown on the GitHub Release asset list. Sizes for
the four-edition matrix are **pending** first publication.

## Artifact verifier

Developers and release CI validate **extracted** archives with the artifact verifier:

```bash
python -m tools.release \
  --archive /path/to/MDFlux_<version>_windows_x64_lite.zip \
  --platform windows-x64 \
  --edition lite
```

```bash
python -m tools.release \
  --archive /path/to/MDFlux_<version>_linux_x64_glibc_full.tar.gz \
  --platform linux-x64-glibc \
  --edition full
```

Optional flags:

- `--json-out report.json`: machine-readable JSON report
- `--fixtures-dir tests/release-fixtures/samples`: conversion sample fixtures
- `--keep-temp`: retain the extraction directory for debugging
- `--app-smoke`: launch the extracted executable in isolated package-verification mode,
  repeat against the same test data to exercise restart behavior, then copy and launch the
  payload from a relocated directory to confirm resource lookup follows the executable.

Release and release-candidate CI enable `--app-smoke` for all four platform/edition archives.
Linux jobs install `xvfb` and invoke the verifier under `xvfb-run -a` so the packaged app can
initialize its Tauri runtime and event loop in a headless runner. Package-verification mode
clears the configured windows, so it does not initialize a webview. This smoke gate checks
startup, runtime provisioning, conversion, restart state, and resource relocation; it does
**not** test visible GUI behavior or human interaction.

The executable's `--verify-package ABSOLUTE_TEST_DIRECTORY` mode uses only that directory for
verification data and application data. It creates a `.mdflux-verification` marker and writes
`report.json`; an existing directory is accepted only when the marker is present. The Python
standalone runner uses fresh directories beneath a new `--work-dir` and preserves that work
directory and reports for inspection. When `--app-smoke` is run through `tools.release`, the
enclosing verifier removes its temporary directory at completion unless `--keep-temp` is set.
Choose an absolute work path outside the extracted payload; existing work directories are
refused and never removed.

The Lite smoke verifies that the versioned `app-data/bin/uv-0.12.3/uv[.exe]` exists and that
the first two output tokens are exactly `uv 0.12.3` on first launch and restart. To exercise
replacement of a legacy unversioned
installer, supply an older uv executable with the packaged-app runner:

```bash
python tools/release/check_packaged_app.py \
  --executable /path/to/extracted/MDFlux \
  --work-dir /absolute/path/to/new-app-smoke \
  --legacy-uv /path/to/legacy/uv
```

Use `uv.exe` for the legacy executable on Windows. This regression seeds it into the marked,
isolated app-data directory before the first launch, then checks that Lite installs and uses the
versioned uv path. It never uses the developer's normal application data.

The verifier checks layout, `resources/edition.json`, dependency lock checksum, bundled Python
(Full), core/OCR/audio imports (Full), sidecar health, sample conversions, real image and
scanned-PDF OCR (Full), and confirms Full does not write a provisioned runtime into application
data. CI also installs the locked OCR dependency set separately on Windows and Linux and runs
the same two OCR paths, protecting Lite's optional OCR installation.

> Use the verifier version available in your checkout for CI and local checks.

## Release procedure

Archives reach GitHub only through the Release workflow. v0.3.0 was published from a local build
after the workflow failed at "Build Windows Lite", which meant the archives users downloaded had
never passed the gate written for them. The rule from v0.3.1 on:

1. Open the PR and apply the `integration` label (or dispatch "Release candidate" with the exact
   commit SHA). All four RC archives must verify, including `--app-smoke`.
2. Run the manual clean-machine checks on the RC archives: Lite first-run provisioning on a host
   with no uv cache (`%LOCALAPPDATA%\uv` on Windows), Linux Lite extracted outside any `target/`
   directory, a scanned-PDF OCR conversion on Full, and an AI cleanup "Test" against one hosted
   provider. Record pass/fail with evidence before tagging.
3. Merge, then push the `vX.Y.Z` tag that matches `app/src-tauri/tauri.conf.json`.
4. Wait for the Release workflow. If any job fails, fix the cause and re-run the workflow for the
   same tag with `workflow_dispatch`. Never build locally and upload by hand.
5. Publish the draft the workflow created as a **pre-release**. Point open issue reporters at it.
6. Promote to a full release after reporters confirm, or after seven days without a regression.

## Portable archive layout inside `edition.json`

Every archive includes `resources/edition.json` (schema version 1) with `edition`, `platform`,
`app_version`, `commit`, `python_version`, `components`, `dependency_lock_sha256`, and
`built_at_utc`. Full editions list `components: ["core", "ocr", "audio-runtime"]`; Lite lists
`["core"]` at build time (OCR/audio install later via provisioning).

## What verification proves

| Check | Lite | Full |
| --- | --- | --- |
| Archive extracts safely | Yes | Yes |
| `edition.json` matches platform/edition | Yes | Yes |
| Bundled interpreter present | No | Yes |
| Sidecar health request | Yes | Yes |
| Sample conversions | Yes | Yes |
| Image and scanned-PDF OCR | Locked-runtime CI | Yes |
| No runtime provisioning into app data | N/A | Yes |
| Packaged launch, restart, and relocation (`--app-smoke`) | Release CI | Release CI |

**Pending:** end-to-end verification reports for all four archives on clean Windows and Ubuntu
hosts.
