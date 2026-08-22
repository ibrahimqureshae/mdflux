from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_ROOT = Path(__file__).resolve().parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(FIXTURES_ROOT) not in sys.path:
    sys.path.insert(0, str(FIXTURES_ROOT))

from archive_builder import (  # noqa: E402
    build_tar_gz,
    build_traversal_zip,
    build_zip,
)
from tools.release.cleanup import safe_remove_tree  # noqa: E402
from tools.release.extract import extract_archive  # noqa: E402
from tools.release.manifest import validate_edition_manifest  # noqa: E402
from tools.release.models import CONVERSION_FIXTURES, CheckResult  # noqa: E402
from tools.release.paths import UnsafePathError  # noqa: E402
from tools.release.runtime_checks import _sidecar_request  # noqa: E402
from tools.release.verify import verify_archive  # noqa: E402


SAMPLES_DIR = FIXTURES_ROOT / "samples"
ARCHIVES_DIR = FIXTURES_ROOT / "archives"


def setUpModule() -> None:
    # Approved samples are committed inputs. Tests must never regenerate them.
    missing = [
        name for name, _ in CONVERSION_FIXTURES if not (SAMPLES_DIR / name).is_file()
    ]
    if missing:
        raise AssertionError(f"Missing committed verifier fixtures: {', '.join(missing)}")
    ARCHIVES_DIR.mkdir(parents=True, exist_ok=True)


class ApprovedFixtureTests(unittest.TestCase):
    def test_pdf_startxref_points_to_xref_table(self) -> None:
        data = (SAMPLES_DIR / "sample.pdf").read_bytes()
        marker = b"startxref\n"
        start = data.rindex(marker) + len(marker)
        offset = int(data[start : data.index(b"\n", start)])
        self.assertTrue(data[offset:].startswith(b"xref\n"))

    def test_xlsx_contains_workbook_relationship_graph(self) -> None:
        with zipfile.ZipFile(SAMPLES_DIR / "sample.xlsx") as archive:
            self.assertTrue(
                {
                    "xl/workbook.xml",
                    "xl/_rels/workbook.xml.rels",
                    "xl/worksheets/sheet1.xml",
                }.issubset(archive.namelist())
            )


class ArchiveBuilderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lite_windows = build_zip(
            ARCHIVES_DIR / "lite-windows-good.zip",
            platform="windows-x64",
            edition="lite",
        )
        cls.full_windows = build_zip(
            ARCHIVES_DIR / "full-windows-good.zip",
            platform="windows-x64",
            edition="full",
        )
        cls.lite_linux = build_tar_gz(
            ARCHIVES_DIR / "lite-linux-good.tar.gz",
            platform="linux-x64-glibc",
            edition="lite",
        )
        cls.full_linux = build_tar_gz(
            ARCHIVES_DIR / "full-linux-good.tar.gz",
            platform="linux-x64-glibc",
            edition="full",
        )
        cls.bad_checksum = build_zip(
            ARCHIVES_DIR / "lite-windows-bad-checksum.zip",
            platform="windows-x64",
            edition="lite",
            bad_checksum=True,
        )
        cls.missing_sidecar = build_zip(
            ARCHIVES_DIR / "lite-windows-missing-sidecar.zip",
            platform="windows-x64",
            edition="lite",
            include_main=False,
        )
        cls.lite_with_runtime = build_zip(
            ARCHIVES_DIR / "lite-windows-with-runtime.zip",
            platform="windows-x64",
            edition="lite",
            include_runtime=True,
        )
        cls.full_missing_python = build_zip(
            ARCHIVES_DIR / "full-windows-missing-python.zip",
            platform="windows-x64",
            edition="full",
            include_runtime=False,
        )
        cls.traversal = build_traversal_zip(
            ARCHIVES_DIR / "traversal.zip",
        )

    def setUp(self) -> None:
        # Archive fixtures exercise extraction, layout, manifest, checksum,
        # reporting, and cleanup. Native sidecar conversions are release-host
        # integration checks and must not make this deterministic unit suite
        # depend on the developer machine's Python environment.
        runtime_checks = patch.multiple(
            "tools.release.verify",
            snapshot_provisioning=lambda _platform: {},
            verify_bundled_python_version=lambda *_args, **_kwargs: CheckResult(
                "bundled-python-version", True, "test runtime"
            ),
            verify_full_imports=lambda *_args, **_kwargs: CheckResult(
                "full-runtime-imports", True, "test imports"
            ),
            verify_sidecar_health=lambda *_args, **_kwargs: CheckResult(
                "sidecar-health", True, "test sidecar"
            ),
            verify_conversions=lambda *_args, **_kwargs: [
                CheckResult(f"conversion-{ext}", True, f"{name}: test conversion")
                for name, ext in CONVERSION_FIXTURES
            ],
            verify_no_full_provisioning=lambda *_args, **_kwargs: CheckResult(
                "full-no-provisioning", True, "test provisioning snapshot"
            ),
        )
        runtime_checks.start()
        self.addCleanup(runtime_checks.stop)


class StructuralVerificationTests(ArchiveBuilderTests):
    def test_lite_windows_passes_layout(self) -> None:
        report = verify_archive(
            self.lite_windows,
            platform="windows-x64",
            edition="lite",
            fixtures_dir=SAMPLES_DIR,
        )
        layout_checks = {
            check.name: check.passed
            for check in report.checks
            if check.name
            in {
                "executable-present",
                "edition-manifest-present",
                "sidecar-present",
                "lite-no-bundled-runtime",
                "dependency-lock-checksum",
            }
        }
        self.assertTrue(layout_checks["executable-present"])
        self.assertTrue(layout_checks["edition-manifest-present"])
        self.assertTrue(layout_checks["sidecar-present"])
        self.assertTrue(layout_checks["lite-no-bundled-runtime"])
        self.assertTrue(layout_checks["dependency-lock-checksum"])

    def test_full_windows_requires_bundled_python(self) -> None:
        report = verify_archive(
            self.full_windows,
            platform="windows-x64",
            edition="full",
            fixtures_dir=SAMPLES_DIR,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertTrue(by_name["full-bundled-python"].passed)
        self.assertEqual(
            by_name["edition-manifest-edition"].detail,
            "edition=full",
        )

    def test_lite_linux_tarball_layout(self) -> None:
        report = verify_archive(
            self.lite_linux,
            platform="linux-x64-glibc",
            edition="lite",
            fixtures_dir=SAMPLES_DIR,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertTrue(by_name["archive-extract"].passed)
        self.assertTrue(by_name["executable-present"].passed)
        self.assertTrue(by_name["lite-no-bundled-runtime"].passed)

    def test_bad_checksum_fails(self) -> None:
        report = verify_archive(
            self.bad_checksum,
            platform="windows-x64",
            edition="lite",
            fixtures_dir=SAMPLES_DIR,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertFalse(by_name["dependency-lock-checksum"].passed)
        self.assertFalse(report.passed)

    def test_missing_sidecar_fails(self) -> None:
        report = verify_archive(
            self.missing_sidecar,
            platform="windows-x64",
            edition="lite",
            fixtures_dir=SAMPLES_DIR,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertFalse(by_name["sidecar-present"].passed)
        self.assertFalse(report.passed)

    def test_lite_with_runtime_fails(self) -> None:
        report = verify_archive(
            self.lite_with_runtime,
            platform="windows-x64",
            edition="lite",
            fixtures_dir=SAMPLES_DIR,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertFalse(by_name["lite-no-bundled-runtime"].passed)

    def test_full_missing_interpreter_fails(self) -> None:
        report = verify_archive(
            self.full_missing_python,
            platform="windows-x64",
            edition="full",
            fixtures_dir=SAMPLES_DIR,
        )
        by_name = {check.name: check for check in report.checks}
        self.assertFalse(by_name["full-bundled-python"].passed)


class ExtractionSafetyTests(ArchiveBuilderTests):
    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsafePathError):
                extract_archive(self.traversal, Path(tmp) / "extract")

    def test_cleanup_refuses_outside_allowed_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            allowed_root = Path(tmp) / "allowed"
            outside = Path(tmp) / "outside"
            allowed_root.mkdir()
            outside.mkdir()
            marker = outside / "do-not-delete"
            marker.write_text("stay", encoding="utf-8")
            with self.assertRaises(UnsafePathError):
                safe_remove_tree(outside, [allowed_root.resolve()])
            self.assertTrue(marker.exists())

    def test_cleanup_retries_transient_windows_file_lock(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            allowed_root = Path(tmp)
            target = allowed_root / "extract"
            target.mkdir()
            transient_lock = PermissionError(5, "Access is denied", "libcrypto.dll")
            with (
                patch(
                    "tools.release.cleanup.shutil.rmtree",
                    side_effect=[transient_lock, transient_lock, None],
                ) as remove_tree,
                patch("tools.release.cleanup.time.sleep") as sleep,
            ):
                safe_remove_tree(
                    target,
                    [allowed_root.resolve()],
                    attempts=3,
                    initial_delay=0.25,
                )

            self.assertEqual(remove_tree.call_count, 3)
            self.assertEqual(
                [entry.args[0] for entry in sleep.call_args_list],
                [0.25, 0.5],
            )


class ManifestTests(unittest.TestCase):
    def test_invalid_platform_in_manifest(self) -> None:
        manifest = {
            "schema": 1,
            "edition": "lite",
            "app_version": "0.2.0",
            "commit": "abc1234",
            "platform": "windows-x64",
            "python_version": None,
            "components": ["core"],
            "dependency_lock_sha256": "a" * 64,
            "built_at_utc": "2026-08-22T12:00:00Z",
        }
        checks = validate_edition_manifest(
            manifest,
            expected_platform="linux-x64-glibc",
            expected_edition="lite",
        )
        self.assertFalse(any(check.name == "edition-manifest-platform" and check.passed for check in checks))


class SidecarIpcTests(unittest.TestCase):
    def test_request_keeps_stdin_open_for_async_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar_dir = Path(tmp)
            (sidecar_dir / "main.py").write_text(
                "import asyncio, json, sys\n"
                "async def main():\n"
                "    loop = asyncio.get_running_loop()\n"
                "    request = json.loads(await loop.run_in_executor(None, sys.stdin.readline))\n"
                "    async def respond():\n"
                "        await asyncio.sleep(0.1)\n"
                "        print(json.dumps({'id': request['id'], 'ok': True, 'result': {}}), flush=True)\n"
                "    asyncio.create_task(respond())\n"
                "    await loop.run_in_executor(None, sys.stdin.readline)\n"
                "asyncio.run(main())\n",
                encoding="utf-8",
            )
            response, error = _sidecar_request(
                Path(sys.executable),
                sidecar_dir,
                {"id": "async-ipc", "method": "convert-one", "params": {}},
                timeout=5,
            )
            self.assertEqual(error, "")
            self.assertTrue(response and response.get("ok"))

    def test_request_skips_logs_and_stops_persistent_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar_dir = Path(tmp)
            (sidecar_dir / "main.py").write_text(
                "import json, sys, time\n"
                "request = json.loads(sys.stdin.readline())\n"
                "print('sidecar startup log', flush=True)\n"
                "print(json.dumps({'id': request['id'], 'ok': True, 'result': {}}), flush=True)\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            started = time.monotonic()
            response, error = _sidecar_request(
                Path(sys.executable),
                sidecar_dir,
                {"id": "bounded-ipc", "method": "health", "params": {}},
                timeout=5,
            )
            self.assertEqual(error, "")
            self.assertTrue(response and response.get("ok"))
            self.assertLess(time.monotonic() - started, 5)

    def test_request_stops_sidecar_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sidecar_dir = Path(tmp)
            (sidecar_dir / "main.py").write_text(
                "import json, pathlib, subprocess, sys\n"
                "request = json.loads(sys.stdin.readline())\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "pathlib.Path('child.pid').write_text(str(child.pid), encoding='ascii')\n"
                "print(json.dumps({'id': request['id'], 'ok': True, 'result': {}}), flush=True)\n"
                "sys.stdin.readline()\n",
                encoding="utf-8",
            )
            response, error = _sidecar_request(
                Path(sys.executable),
                sidecar_dir,
                {"id": "tree-ipc", "method": "convert-one", "params": {}},
                timeout=5,
            )
            self.assertEqual(error, "")
            self.assertTrue(response and response.get("ok"))
            child_pid = int((sidecar_dir / "child.pid").read_text(encoding="ascii"))
            for _ in range(20):
                try:
                    os.kill(child_pid, 0)
                except OSError:
                    break
                time.sleep(0.05)
            else:
                self.fail(f"Sidecar descendant {child_pid} was left running")


class ReportTests(ArchiveBuilderTests):
    def test_json_report_shape(self) -> None:
        report = verify_archive(
            self.lite_windows,
            platform="windows-x64",
            edition="lite",
            fixtures_dir=SAMPLES_DIR,
        )
        payload = report.to_dict()
        self.assertEqual(payload["platform"], "windows-x64")
        self.assertEqual(payload["edition"], "lite")
        self.assertEqual(payload["archive"], self.lite_windows.name)
        self.assertIsNone(payload["extract_dir"])
        self.assertIn("checks", payload)
        self.assertTrue(isinstance(payload["checks"], list))
        serialized = json.dumps(payload)
        self.assertNotIn(str(self.lite_windows.parent), serialized)
        self.assertNotIn(str(SAMPLES_DIR), serialized)

    def test_cli_json_out(self) -> None:
        import io
        from contextlib import redirect_stdout

        from tools.release.verify import main

        with tempfile.TemporaryDirectory() as tmp:
            json_out = Path(tmp) / "report.json"
            with redirect_stdout(io.StringIO()):
                code = main(
                    [
                        "--archive",
                        str(self.lite_windows),
                        "--platform",
                        "windows-x64",
                        "--edition",
                        "lite",
                        "--fixtures-dir",
                        str(SAMPLES_DIR),
                        "--json-out",
                        str(json_out),
                    ]
                )
            self.assertIn(code, (0, 1))
            data = json.loads(json_out.read_text(encoding="utf-8"))
            self.assertEqual(data["archive"], self.lite_windows.name)
            self.assertIsNone(data["extract_dir"])


if __name__ == "__main__":
    unittest.main()
