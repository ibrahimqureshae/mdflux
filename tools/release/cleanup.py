from __future__ import annotations

import os
import shutil
import stat
import time
from pathlib import Path

from .paths import UnsafePathError, assert_safe_cleanup_target, resolve


def _remove_readonly(func, path, exc_info) -> None:  # noqa: ANN001
    exc = exc_info[1]
    if isinstance(exc, PermissionError):
        os.chmod(path, stat.S_IWUSR | stat.S_IREAD)
        func(path)
        return
    raise exc


def safe_remove_tree(
    target: Path,
    allowed_roots: list[Path],
    *,
    attempts: int = 8,
    initial_delay: float = 0.25,
) -> None:
    resolved = assert_safe_cleanup_target(target, allowed_roots)
    if attempts < 1:
        raise ValueError("Cleanup attempts must be at least 1")

    delay = initial_delay
    for attempt in range(attempts):
        if not resolved.exists():
            return
        try:
            if resolved.is_dir():
                shutil.rmtree(resolved, onerror=_remove_readonly)
            else:
                try:
                    resolved.unlink()
                except PermissionError:
                    os.chmod(resolved, stat.S_IWUSR | stat.S_IREAD)
                    resolved.unlink()
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 2.0)
