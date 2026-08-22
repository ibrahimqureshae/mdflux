from __future__ import annotations

import tarfile
import zipfile
from pathlib import Path

from .paths import UnsafePathError, assert_within, resolve


def _safe_extract_zip(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            member_path = Path(info.filename)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise UnsafePathError(
                    f"Archive entry escapes destination: {info.filename}"
                )
            target = destination / member_path
            assert_within(target, destination, label="Archive entry")
            if info.is_dir() or info.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, target.open("wb") as dst:
                dst.write(src.read())


def _safe_extract_tar(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, "r:*") as tf:
        for member in tf.getmembers():
            member_path = Path(member.name)
            if member_path.is_absolute() or ".." in member_path.parts:
                raise UnsafePathError(
                    f"Archive entry escapes destination: {member.name}"
                )
            target = destination / member_path
            assert_within(target, destination, label="Archive entry")
        tf.extractall(destination, filter="data")


def extract_archive(archive: str | Path, destination: str | Path) -> Path:
    archive_path = resolve(archive)
    dest_path = resolve(destination)
    if not archive_path.is_file():
        raise FileNotFoundError(f"Archive not found: {archive_path}")

    suffixes = archive_path.suffixes
    lower_name = archive_path.name.lower()
    if lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
        _safe_extract_tar(archive_path, dest_path)
    elif suffixes and suffixes[-1].lower() == ".zip":
        _safe_extract_zip(archive_path, dest_path)
    else:
        raise ValueError(
            f"Unsupported archive format: {archive_path.name}. Expected .zip or .tar.gz"
        )
    return dest_path
