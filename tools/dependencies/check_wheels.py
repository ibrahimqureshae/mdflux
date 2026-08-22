#!/usr/bin/env python3
"""Verify PyPI wheel availability for native packages in the canonical Full lock."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path


LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")


def locked_packages(path: Path) -> dict[str, str]:
    packages: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCK_LINE.match(line)
        if match:
            packages[match.group(1)] = match.group(2)
    if not packages:
        raise ValueError(f"no packages found in {path}")
    return packages


def is_native(filename: str) -> bool:
    return filename.endswith(".whl") and not filename.endswith("-none-any.whl")


def supports_windows(filename: str) -> bool:
    return filename.endswith(".whl") and "win_amd64" in filename and (
        "cp312" in filename or "abi3" in filename or "-none-win_amd64" in filename
    )


def supports_manylinux(filename: str) -> bool:
    return filename.endswith(".whl") and "manylinux" in filename and "x86_64" in filename and (
        "cp312" in filename or "abi3" in filename or "-none-manylinux" in filename
    )


def release_files(name: str, version: str) -> list[str]:
    url = f"https://pypi.org/pypi/{name}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = json.load(response)
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{name}=={version}: could not read PyPI metadata: {exc}") from exc
    urls = payload.get("urls")
    if not isinstance(urls, list):
        raise RuntimeError(f"{name}=={version}: PyPI metadata has no release files")
    return [item.get("filename", "") for item in urls if isinstance(item, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "app/src-tauri/resources/sidecar/requirements-full.lock",
    )
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    try:
        packages = locked_packages(args.lock)
        native: list[dict[str, object]] = []
        unsupported: list[dict[str, object]] = []
        for name, version in sorted(packages.items(), key=lambda item: item[0].lower()):
            files = release_files(name, version)
            native_files = [filename for filename in files if is_native(filename)]
            if not native_files:
                continue
            windows = [filename for filename in native_files if supports_windows(filename)]
            manylinux = [filename for filename in native_files if supports_manylinux(filename)]
            record: dict[str, object] = {
                "name": name,
                "version": version,
                "windows_x64": windows,
                "manylinux_x64": manylinux,
            }
            native.append(record)
            if not windows or not manylinux:
                unsupported.append(record)
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"wheel check failed: {exc}", file=sys.stderr)
        return 1

    report = {
        "schema": 1,
        "lock_sha256": hashlib.sha256(args.lock.read_bytes()).hexdigest(),
        "targets": ["windows-x64", "linux-x64-glibc"],
        "native_packages": native,
        "unsupported": unsupported,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if unsupported:
        print(f"wheel check found {len(unsupported)} unsupported native package(s)", file=sys.stderr)
        return 1
    print(f"wheel check OK; {len(native)} native packages support Windows x64 and manylinux x64")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
