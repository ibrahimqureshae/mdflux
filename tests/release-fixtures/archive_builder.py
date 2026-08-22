"""Build synthetic MDFlux release archives for verifier tests."""

from __future__ import annotations

import io
import shutil
import sys
import tarfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SIDECAR_SRC = REPO_ROOT / "app" / "src-tauri" / "resources" / "sidecar"
FULL_LOCK = SIDECAR_SRC / "requirements-full.lock"


def lock_sha256() -> str:
    import hashlib

    digest = hashlib.sha256()
    with FULL_LOCK.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def edition_manifest(
    *,
    platform: str,
    edition: str,
    lock_checksum: str | None = None,
    bad_checksum: bool = False,
) -> dict:
    checksum = lock_checksum or lock_sha256()
    if bad_checksum:
        checksum = "0" * 64
    manifest = {
        "schema": 1,
        "edition": edition,
        "app_version": "0.2.0-test",
        "commit": "baseline000000",
        "platform": platform,
        "python_version": None,
        "components": ["core"] if edition == "lite" else ["core", "ocr", "audio-runtime"],
        "dependency_lock_sha256": checksum,
        "built_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        ),
    }
    if edition == "full":
        manifest["python_version"] = ".".join(map(str, sys.version_info[:3]))
    return manifest


def _copy_sidecar(dest: Path, *, include_main: bool = True) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for item in SIDECAR_SRC.iterdir():
        if item.name == "tests":
            continue
        if not include_main and item.name == "main.py":
            continue
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _stage_common(
    stage: Path,
    *,
    platform: str,
    edition: str,
    include_main: bool = True,
    bad_checksum: bool = False,
    include_runtime: bool | None = None,
) -> None:
    if include_runtime is None:
        include_runtime = edition == "full"

    resources = stage / "resources"
    sidecar = resources / "sidecar"
    _copy_sidecar(sidecar, include_main=include_main)

    manifest = edition_manifest(
        platform=platform,
        edition=edition,
        bad_checksum=bad_checksum,
    )
    (resources / "edition.json").write_text(
        __import__("json").dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )

    if include_runtime:
        if platform == "windows-x64":
            runtime_python = resources / "runtime" / "python.exe"
        else:
            runtime_python = resources / "runtime" / "bin" / "python3"
            runtime_python.parent.mkdir(parents=True, exist_ok=True)
        runtime_python.parent.mkdir(parents=True, exist_ok=True)
        if platform == "windows-x64":
            shutil.copy2(Path(sys.executable), runtime_python)
        else:
            shutil.copy2(Path(sys.executable), runtime_python)
            runtime_python.chmod(runtime_python.stat().st_mode | 0o111)

    if platform == "windows-x64":
        exe = stage / "MDFlux.exe"
        exe.write_bytes(b"MZ-stub")
    else:
        exe = stage / "MDFlux"
        exe.write_bytes(b"\x7fELF-stub")
        exe.chmod(exe.stat().st_mode | 0o111)


def build_zip(
    output: Path,
    *,
    platform: str,
    edition: str,
    include_main: bool = True,
    bad_checksum: bool = False,
    include_runtime: bool | None = None,
) -> Path:
    stage = output.parent / f"_stage_{output.stem}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    try:
        _stage_common(
            stage,
            platform=platform,
            edition=edition,
            include_main=include_main,
            bad_checksum=bad_checksum,
            include_runtime=include_runtime,
        )
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in stage.rglob("*"):
                if path.is_file():
                    zf.write(path, path.relative_to(stage).as_posix())
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return output


def build_tar_gz(
    output: Path,
    *,
    platform: str,
    edition: str,
    include_main: bool = True,
    bad_checksum: bool = False,
    include_runtime: bool | None = None,
) -> Path:
    stage = output.parent / f"_stage_{output.stem}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    try:
        _stage_common(
            stage,
            platform=platform,
            edition=edition,
            include_main=include_main,
            bad_checksum=bad_checksum,
            include_runtime=include_runtime,
        )
        with tarfile.open(output, "w:gz") as tf:
            for path in stage.rglob("*"):
                if path.is_file():
                    tf.add(path, arcname=path.relative_to(stage).as_posix())
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return output


def build_traversal_zip(output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w") as zf:
        zf.writestr("resources/edition.json", "{}")
        zf.writestr("../../escape.txt", "bad")
    return output
