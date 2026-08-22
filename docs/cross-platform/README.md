# MDFlux cross-platform documentation

MDFlux is one product built from a shared codebase for Windows x64 and Linux x64 (glibc). Platform
differences stay in a small adapter layer and release packaging.

## Documents

| Topic | Document |
| --- | --- |
| Lite vs Full editions | [editions.md](editions.md) |
| Supported platforms and dependencies | [platforms-and-support.md](platforms-and-support.md) |
| Release names, checksums, and verification | [releases-and-verification.md](releases-and-verification.md) |
| Ubuntu / Linux contributor setup | [setup-ubuntu.md](setup-ubuntu.md) |
| Optional devenv contributor setup | [setup-devenv.md](setup-devenv.md) |

## Release availability

Release availability varies by version and platform. Check the [GitHub Releases page](https://github.com/ibrahimqureshae/mdflux/releases)
and its notes for the archives currently available.

| Artifact | Archive name |
| --- | --- |
| Windows Lite | `MDFlux_<version>_windows_x64_lite.zip` |
| Windows Full | `MDFlux_<version>_windows_x64_full.zip` |
| Linux Lite | `MDFlux_<version>_linux_x64_glibc_lite.tar.gz` |
| Linux Full | `MDFlux_<version>_linux_x64_glibc_full.tar.gz` |

The earlier Windows portable archive (`MDFlux_<version>_portable.zip`) is a Lite-class build.

## Quick reference

Platform identifiers are `windows-x64` and `linux-x64-glibc`. Edition identifiers are `lite` and
`full`. Speech model weights are on demand in every edition and are never bundled in release archives.
