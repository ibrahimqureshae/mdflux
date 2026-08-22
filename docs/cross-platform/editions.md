# Editions: Lite and Full

MDFlux ships in two editions on each supported platform. Both editions use the same Svelte UI,
Rust shell, and Python sidecar sources.

## Lite

**Identifier:** `lite`

Lite is the smaller download. It includes the application and sidecar sources but does not include
`resources/runtime/`. On first launch, it transactionally provisions a private Python 3.12
environment from the locked dependency graph. Smoke checks run before activation, and the previous
working environment remains available if an update fails.

Lite requires internet access during first setup and when OCR or audio is installed for the first
time. After provisioning, conversion runs offline.

## Full

**Identifier:** `full`

Full is the offline-ready edition. It includes an immutable `resources/runtime/` with a relocatable
Python 3.12 interpreter and core, OCR, and audio runtime dependencies pre-installed. Full does not
install packages at runtime or mutate its bundled environment. Optional speech model weights are
downloaded on demand and are not part of the archive.

## Component matrix

| Component | Lite | Full |
| --- | --- | --- |
| Core conversion | Provisioned on first launch | Pre-installed |
| OCR engine packages | Installed on demand | Pre-installed |
| Audio runtime packages | Installed on demand | Pre-installed |
| Speech model weights | On demand | On demand |
| `resources/runtime/` in archive | No | Yes |

## Choosing an edition

| You want | Choose |
| --- | --- |
| Smallest download and an online first launch is acceptable | **Lite** |
| Fully offline use after download | **Full** |
| To reproduce a support or CI result | Match the archive you downloaded |

## Edition manifest

Every release archive contains `resources/edition.json` describing the edition, platform, app
version, commit, Python version (Full only), component list, and dependency lock checksum. Release
checks use this metadata to confirm that an archive matches its published platform and edition.
