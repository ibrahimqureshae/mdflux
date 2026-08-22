from __future__ import annotations

from pathlib import Path

from .models import CheckResult, EDITIONS, PLATFORMS


def executable_name(platform: str) -> str:
    if platform == "windows-x64":
        return "MDFlux.exe"
    if platform == "linux-x64-glibc":
        return "MDFlux"
    raise ValueError(f"Unsupported platform: {platform}")


def bundled_python_path(root: Path, platform: str) -> Path:
    if platform == "windows-x64":
        return root / "resources" / "runtime" / "python.exe"
    if platform == "linux-x64-glibc":
        return root / "resources" / "runtime" / "bin" / "python3"
    raise ValueError(f"Unsupported platform: {platform}")


def validate_layout(
    root: Path,
    *,
    platform: str,
    edition: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []

    if platform not in PLATFORMS:
        results.append(
            CheckResult(
                "platform-identifier",
                False,
                f"Unknown platform {platform!r}; expected one of {sorted(PLATFORMS)}",
            )
        )
        return results

    if edition not in EDITIONS:
        results.append(
            CheckResult(
                "edition-identifier",
                False,
                f"Unknown edition {edition!r}; expected one of {sorted(EDITIONS)}",
            )
        )
        return results

    exe = root / executable_name(platform)
    if not exe.is_file():
        results.append(
            CheckResult(
                "executable-present",
                False,
                f"Missing executable: {executable_name(platform)}",
            )
        )
    else:
        results.append(
            CheckResult(
                "executable-present",
                True,
                str(exe.relative_to(root)),
            )
        )
        if platform == "linux-x64-glibc" and not exe.stat().st_mode & 0o111:
            results.append(
                CheckResult(
                    "executable-permissions",
                    False,
                    f"{exe.name} is not executable",
                )
            )
        elif platform == "linux-x64-glibc":
            results.append(
                CheckResult(
                    "executable-permissions",
                    True,
                    f"{exe.name} is executable",
                )
            )

    edition_json = root / "resources" / "edition.json"
    if not edition_json.is_file():
        results.append(
            CheckResult(
                "edition-manifest-present",
                False,
                "Missing resources/edition.json",
            )
        )
    else:
        results.append(
            CheckResult(
                "edition-manifest-present",
                True,
                "resources/edition.json",
            )
        )

    sidecar_main = root / "resources" / "sidecar" / "main.py"
    if not sidecar_main.is_file():
        results.append(
            CheckResult(
                "sidecar-present",
                False,
                "Missing resources/sidecar/main.py",
            )
        )
    else:
        results.append(
            CheckResult(
                "sidecar-present",
                True,
                "resources/sidecar/main.py",
            )
        )

    runtime_dir = root / "resources" / "runtime"
    bundled_python = bundled_python_path(root, platform)
    if edition == "lite":
        if runtime_dir.exists():
            results.append(
                CheckResult(
                    "lite-no-bundled-runtime",
                    False,
                    "Lite archive must not contain resources/runtime/",
                )
            )
        else:
            results.append(
                CheckResult(
                    "lite-no-bundled-runtime",
                    True,
                    "No bundled runtime directory",
                )
            )
    else:
        if not bundled_python.is_file():
            results.append(
                CheckResult(
                    "full-bundled-python",
                    False,
                    f"Missing bundled interpreter: {bundled_python.relative_to(root)}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "full-bundled-python",
                    True,
                    str(bundled_python.relative_to(root)),
                )
            )

    return results
