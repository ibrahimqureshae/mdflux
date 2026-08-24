from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from .checksum import verify_dependency_lock_checksum
from .cleanup import safe_remove_tree
from .extract import extract_archive
from .layout import validate_layout
from .manifest import load_edition_manifest, validate_edition_manifest
from .models import CheckResult, EDITIONS, PLATFORMS, VerificationReport
from .paths import UnsafePathError, resolve
from .report import format_human_report, format_json_report
from .runtime_checks import (
    snapshot_provisioning,
    verify_bundled_python_version,
    verify_conversions,
    verify_full_imports,
    verify_no_full_provisioning,
    verify_ocr_conversions,
    verify_sidecar_health,
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_fixtures_dir() -> Path:
    return _repo_root() / "tests" / "release-fixtures" / "samples"


def verify_archive(
    archive: str | Path,
    *,
    platform: str,
    edition: str,
    fixtures_dir: Path | None = None,
    keep_temp: bool = False,
) -> VerificationReport:
    archive_path = resolve(archive)
    fixtures = fixtures_dir or _default_fixtures_dir()
    report = VerificationReport(
        archive=archive_path.name,
        platform=platform,
        edition=edition,
        passed=True,
    )

    if platform not in PLATFORMS:
        report.add(
            CheckResult("platform", False, f"Unsupported platform {platform!r}")
        )
        return report
    if edition not in EDITIONS:
        report.add(
            CheckResult("edition", False, f"Unsupported edition {edition!r}")
        )
        return report

    temp_root = Path(tempfile.mkdtemp(prefix="mdflux-verify-"))
    extract_dir = temp_root / "extract"
    allowed_cleanup_roots = [temp_root.resolve()]
    provisioning_before = (
        snapshot_provisioning(platform) if edition == "full" else None
    )

    try:
        try:
            extract_archive(archive_path, extract_dir)
            report.add(
                CheckResult("archive-extract", True, "Extracted safely")
            )
        except (UnsafePathError, ValueError, OSError) as exc:
            report.add(CheckResult("archive-extract", False, str(exc)))
            return report

        for check in validate_layout(extract_dir, platform=platform, edition=edition):
            report.add(check)

        edition_json = extract_dir / "resources" / "edition.json"
        manifest = None
        if edition_json.is_file():
            manifest, parse_check = load_edition_manifest(edition_json)
            report.add(parse_check)
            if manifest is not None:
                report.manifest = manifest
                for check in validate_edition_manifest(
                    manifest,
                    expected_platform=platform,
                    expected_edition=edition,
                ):
                    report.add(check)
                report.add(
                    verify_dependency_lock_checksum(extract_dir, manifest),
                )

        if edition == "full" and manifest is not None:
            report.add(
                verify_bundled_python_version(
                    extract_dir,
                    platform=platform,
                    manifest=manifest,
                )
            )
            report.add(verify_full_imports(extract_dir, platform=platform))

        report.add(
            verify_sidecar_health(
                extract_dir,
                platform=platform,
                edition=edition,
            )
        )

        if not fixtures.is_dir():
            report.add(
                CheckResult(
                    "conversion-fixtures-dir",
                    False,
                    f"Missing fixtures directory: {fixtures.name}",
                )
            )
        else:
            report.add(
                CheckResult(
                    "conversion-fixtures-dir",
                    True,
                    "Approved conversion samples available",
                )
            )
            for check in verify_conversions(
                extract_dir,
                platform=platform,
                edition=edition,
                fixtures_dir=fixtures,
            ):
                report.add(check)

        if edition == "full":
            for check in verify_ocr_conversions(extract_dir, platform=platform):
                report.add(check)

        if edition == "full" and provisioning_before is not None:
            report.add(
                verify_no_full_provisioning(
                    provisioning_before,
                    platform=platform,
                )
            )

        return report
    finally:
        if keep_temp:
            report.extract_dir = str(extract_dir)
        else:
            try:
                safe_remove_tree(temp_root, allowed_cleanup_roots)
            except (UnsafePathError, OSError) as exc:
                report.add(
                    CheckResult(
                        "cleanup",
                        False,
                        str(exc),
                        severity="error",
                    )
                )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify an MDFlux Lite or Full release archive.",
    )
    parser.add_argument(
        "--archive",
        required=True,
        help="Path to a .zip or .tar.gz release archive",
    )
    parser.add_argument(
        "--platform",
        required=True,
        choices=sorted(PLATFORMS),
        help="Expected platform identifier",
    )
    parser.add_argument(
        "--edition",
        required=True,
        choices=sorted(EDITIONS),
        help="Expected edition identifier",
    )
    parser.add_argument(
        "--fixtures-dir",
        default=str(_default_fixtures_dir()),
        help="Directory containing conversion sample files",
    )
    parser.add_argument(
        "--json-out",
        help="Optional path to write the machine-readable JSON report",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the extracted archive directory for debugging",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    report = verify_archive(
        args.archive,
        platform=args.platform,
        edition=args.edition,
        fixtures_dir=Path(args.fixtures_dir),
        keep_temp=args.keep_temp,
    )
    human = format_human_report(report)
    print(human)
    payload = format_json_report(report)
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2) + "\n",
            encoding="utf-8",
        )
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
