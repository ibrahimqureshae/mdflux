#!/usr/bin/env python3
"""Validate that all feature exports are constrained by the canonical Full lock."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path


LOCK_LINE = re.compile(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)")
HASH_LINE = re.compile(r"^\s*--hash=sha256:([0-9a-f]{64})\s*\\?$")
INPUT_NAME = re.compile(r"^([A-Za-z0-9_.-]+)(?:\[[^]]+\])?(?:[<>=!~].*)?$")


@dataclass(frozen=True)
class LockedPackage:
    version: str
    hashes: frozenset[str]


def normalized(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def parse_lock(path: Path) -> dict[str, LockedPackage]:
    packages: dict[str, LockedPackage] = {}
    current_name: str | None = None
    current_version: str | None = None
    current_hashes: set[str] = set()

    def finish() -> None:
        if current_name is None or current_version is None:
            return
        if not current_hashes:
            raise ValueError(f"{path}: {current_name} has no hashes")
        key = normalized(current_name)
        if key in packages:
            raise ValueError(f"{path}: duplicate package {current_name}")
        packages[key] = LockedPackage(current_version, frozenset(current_hashes))

    for line in path.read_text(encoding="utf-8").splitlines():
        match = LOCK_LINE.match(line)
        if match:
            finish()
            current_name, current_version = match.groups()
            current_hashes = set()
            continue
        hash_match = HASH_LINE.match(line)
        if hash_match and current_name is not None:
            current_hashes.add(hash_match.group(1))
    finish()
    if not packages:
        raise ValueError(f"{path}: no locked packages found")
    return packages


def direct_requirements(path: Path) -> set[str]:
    result: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("-r "):
            continue
        match = INPUT_NAME.match(line)
        if not match:
            raise ValueError(f"{path}: unsupported input line {line!r}")
        result.add(normalized(match.group(1)))
    return result


def check(sidecar: Path) -> list[str]:
    errors: list[str] = []
    full_input = sidecar / "requirements-full.in"
    full_lock = sidecar / "requirements-full.lock"
    expected_refs = {"-r requirements.txt", "-r requirements-ocr.in", "-r requirements-audio.in"}
    actual_refs = {
        line.strip()
        for line in full_input.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("-r ")
    }
    if actual_refs != expected_refs:
        errors.append(
            f"{full_input}: expected only {sorted(expected_refs)}, found {sorted(actual_refs)}"
        )

    full_header = full_lock.read_text(encoding="utf-8").splitlines()[:2]
    header = "\n".join(full_header)
    for required in ("requirements-full.in", "--universal", "--python-version 3.12", "--generate-hashes", "--only-binary :all:"):
        if required not in header:
            errors.append(f"{full_lock}: missing regeneration option {required}")

    canonical = parse_lock(full_lock)
    exports = {
        "core": (sidecar / "requirements.txt", sidecar / "requirements.lock"),
        "ocr": (sidecar / "requirements-ocr.in", sidecar / "requirements-ocr.lock"),
        "audio": (sidecar / "requirements-audio.in", sidecar / "requirements-audio.lock"),
    }
    for feature, (input_path, export_path) in exports.items():
        export = parse_lock(export_path)
        missing_direct = direct_requirements(input_path) - set(export)
        if missing_direct:
            errors.append(f"{feature}: direct requirements absent from export: {sorted(missing_direct)}")
        for name, package in export.items():
            expected = canonical.get(name)
            if expected is None:
                errors.append(f"{feature}: {name} is absent from canonical Full lock")
                continue
            if package.version != expected.version:
                errors.append(
                    f"{feature}: {name}=={package.version} differs from canonical {expected.version}"
                )
            if not package.hashes <= expected.hashes:
                errors.append(f"{feature}: {name} contains a hash absent from canonical Full lock")

        export_header = "\n".join(export_path.read_text(encoding="utf-8").splitlines()[:2])
        if "--constraint requirements-full.lock" not in export_header:
            errors.append(f"{export_path}: must be generated with requirements-full.lock as a constraint")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sidecar-dir",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "app/src-tauri/resources/sidecar",
    )
    args = parser.parse_args()
    sidecar = args.sidecar_dir.resolve()
    try:
        errors = check(sidecar)
    except (OSError, ValueError) as exc:
        print(f"dependency graph check failed: {exc}", file=sys.stderr)
        return 1
    if errors:
        print("dependency graph drift detected:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    digest = hashlib.sha256((sidecar / "requirements-full.lock").read_bytes()).hexdigest()
    print(f"dependency graph OK; requirements-full.lock sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
