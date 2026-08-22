from __future__ import annotations

import os
from pathlib import Path


class UnsafePathError(ValueError):
    """Raised when a path would escape an allowed directory."""


def resolve(path: str | Path) -> Path:
    return Path(path).expanduser().resolve()


def is_within(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def assert_within(child: Path, root: Path, label: str = "path") -> Path:
    resolved_child = child.resolve()
    resolved_root = root.resolve()
    if not is_within(resolved_child, resolved_root):
        raise UnsafePathError(
            f"{label} {resolved_child} escapes allowed root {resolved_root}"
        )
    return resolved_child


def assert_safe_cleanup_target(target: Path, allowed_roots: list[Path]) -> Path:
    resolved = target.resolve()
    if not resolved.exists():
        raise UnsafePathError(f"Cleanup target does not exist: {resolved}")
    for root in allowed_roots:
        if is_within(resolved, root.resolve()):
            return resolved
    raise UnsafePathError(
        f"Refusing to delete {resolved}; not under allowed cleanup roots"
    )


def app_data_root(platform: str) -> Path:
    if platform == "windows-x64":
        base = os.environ.get("APPDATA")
        if not base:
            raise RuntimeError("APPDATA is not set")
        return Path(base) / "com.projektvisyo.mdflux"
    if platform == "linux-x64-glibc":
        return Path.home() / ".local" / "share" / "com.projektvisyo.mdflux"
    raise ValueError(f"Unsupported platform: {platform}")
