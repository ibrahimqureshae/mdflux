from __future__ import annotations

import hashlib
from pathlib import Path

from .models import CheckResult


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_dependency_lock_checksum(
    root: Path,
    manifest: dict,
) -> CheckResult:
    lock_path = root / "resources" / "sidecar" / "requirements-full.lock"
    expected = manifest.get("dependency_lock_sha256")
    if not lock_path.is_file():
        return CheckResult(
            "dependency-lock-present",
            False,
            "Missing resources/sidecar/requirements-full.lock",
        )

    actual = sha256_file(lock_path)
    if expected != actual:
        return CheckResult(
            "dependency-lock-checksum",
            False,
            f"Checksum mismatch: manifest={expected}, actual={actual}",
        )
    return CheckResult(
        "dependency-lock-checksum",
        True,
        actual,
    )
