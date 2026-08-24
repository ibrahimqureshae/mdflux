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

The verifier checks layout, `resources/edition.json`, dependency lock checksum, bundled Python
(Full), core/OCR/audio imports (Full), sidecar health, sample conversions, real image and
scanned-PDF OCR (Full), and confirms Full does not write a provisioned runtime into application
data. CI also installs the locked OCR dependency set separately on Windows and Linux and runs
the same two OCR paths, protecting Lite's optional OCR installation.

> Use the verifier version available in your checkout for CI and local checks.

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

**Pending:** end-to-end verification reports for all four archives on clean Windows and Ubuntu
hosts.
