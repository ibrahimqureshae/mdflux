from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


UV_VERSION = "0.12.3"
VERIFICATION_MARKER = ".mdflux-verification"
TIMEOUT_SECONDS = 600


class VerificationError(RuntimeError):
    pass


def canonical_path(path: str | Path) -> str:
    value = os.path.normpath(str(Path(path).resolve()))
    if os.name == "nt":
        if value.startswith("\\\\?\\UNC\\"):
            value = "\\\\" + value[8:]
        elif value.startswith("\\\\?\\"):
            value = value[4:]
        value = os.path.normcase(value)
    return value


def validate_report(report_path: Path, expected_root: Path) -> dict[str, Any]:
    try:
        report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VerificationError(f"Cannot read verification report {report_path}: {error}") from error
    if not isinstance(report, dict) or report.get("passed") is not True:
        detail = report.get("error", "report did not pass") if isinstance(report, dict) else "invalid report"
        raise VerificationError(f"Packaged verification failed: {detail}")
    actual_root = report.get("resource_root")
    if not isinstance(actual_root, str) or canonical_path(actual_root) != canonical_path(expected_root):
        raise VerificationError(
            f"Packaged resource_root mismatch: expected {expected_root}, got {actual_root!r}"
        )
    return report


def run_verification(executable: Path, test_dir: Path, cwd: Path) -> dict[str, Any]:
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / VERIFICATION_MARKER).write_text(
        "MDFlux isolated package verification\n", encoding="utf-8"
    )
    report_path = test_dir / "report.json"
    report_path.unlink(missing_ok=True)
    try:
        env = os.environ.copy()
        env["UV_NO_CACHE"] = "1"
        result = subprocess.run(
            [str(executable), "--verify-package", str(test_dir)],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
            env=env,
            **(
                {"creationflags": subprocess.CREATE_NO_WINDOW}
                if os.name == "nt"
                else {}
            ),
        )
    except subprocess.TimeoutExpired as error:
        raise VerificationError(f"Packaged verification timed out after {TIMEOUT_SECONDS}s") from error
    if result.returncode != 0:
        output = (result.stderr or result.stdout).strip()
        raise VerificationError(
            f"Packaged executable exited {result.returncode}: {output or 'no diagnostic output'}"
        )
    return validate_report(report_path, executable.parent)


def verify_lite_uv(test_dir: Path, executable: Path) -> None:
    if os.name == "nt":
        uv_name = "uv.exe"
    else:
        uv_name = "uv"
    installed_uv = test_dir / "app-data" / "bin" / f"uv-{UV_VERSION}" / uv_name
    if not installed_uv.is_file():
        raise VerificationError(f"Versioned Lite uv was not installed: {installed_uv}")
    try:
        result = subprocess.run(
            [str(installed_uv), "--version"],
            cwd=executable.parent,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise VerificationError(f"Cannot query installed uv at {installed_uv}: {error}") from error
    version_tokens = (result.stdout + result.stderr).strip().split()
    if result.returncode != 0 or version_tokens[:2] != ["uv", UV_VERSION]:
        raise VerificationError(
            f"Installed uv does not report {UV_VERSION}: {(result.stdout + result.stderr).strip()}"
        )


def seed_legacy_uv(source: Path, test_dir: Path) -> None:
    test_dir.mkdir(parents=True, exist_ok=True)
    (test_dir / VERIFICATION_MARKER).write_text(
        "MDFlux isolated package verification\n", encoding="utf-8"
    )
    destination = test_dir / "app-data" / "bin" / ("uv.exe" if os.name == "nt" else "uv")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if os.name != "nt":
        destination.chmod(destination.stat().st_mode | 0o111)


def run(executable: Path, work_dir: Path, legacy_uv: Path | None = None) -> None:
    if not work_dir.is_absolute():
        raise VerificationError("--work-dir must be an absolute path")
    executable = executable.resolve(strict=True)
    work_dir = work_dir.resolve(strict=False)
    if not executable.is_file():
        raise VerificationError(f"Executable is not a file: {executable}")
    if work_dir.exists():
        raise VerificationError(f"Refusing to use existing work directory: {work_dir}")
    source_payload = executable.parent
    try:
        work_dir.relative_to(source_payload)
    except ValueError:
        pass
    else:
        raise VerificationError("Work directory cannot be inside the source payload")
    if legacy_uv is not None:
        legacy_uv = legacy_uv.resolve(strict=True)
        if not legacy_uv.is_file():
            raise VerificationError(f"Legacy uv is not a file: {legacy_uv}")

    work_dir.mkdir(parents=True)
    first = work_dir / "first-run"
    if legacy_uv is not None:
        seed_legacy_uv(legacy_uv, first)
    report = run_verification(executable, first, work_dir)
    if report.get("edition", "").lower() == "lite":
        verify_lite_uv(first, executable)
    elif legacy_uv is not None:
        raise VerificationError("--legacy-uv requires a Lite package")

    # A second launch against the same marked directory exercises persisted state.
    restarted = run_verification(executable, first, work_dir)
    if restarted.get("edition", "").lower() == "lite":
        verify_lite_uv(first, executable)
    elif legacy_uv is not None:
        raise VerificationError("--legacy-uv requires a Lite package")

    relocated = work_dir / "relocated-payload"
    shutil.copytree(source_payload, relocated)
    relocated_executable = relocated / executable.name
    relocated_test_dir = work_dir / "relocated-run"
    moved_report = run_verification(relocated_executable, relocated_test_dir, work_dir)
    if canonical_path(moved_report["resource_root"]) != canonical_path(relocated):
        raise VerificationError("Relocated executable did not resolve resources from moved payload")
    print("Packaged app verification: first run, restart, and relocation passed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify an extracted MDFlux app payload.")
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument("--work-dir", required=True, type=Path)
    parser.add_argument("--legacy-uv", type=Path)
    args = parser.parse_args(argv)
    try:
        run(args.executable, args.work_dir, args.legacy_uv)
    except (OSError, VerificationError, shutil.Error) as error:
        print(f"Packaged app verification failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
