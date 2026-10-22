from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "release"))
import check_packaged_app as checker


class PackagedAppReportTests(unittest.TestCase):
    def test_accepts_passed_report_with_expected_root(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "payload"
            report_path = Path(temp) / "report.json"
            report_path.write_text(
                json.dumps({"passed": True, "resource_root": str(root)}), encoding="utf-8"
            )
            self.assertTrue(checker.validate_report(report_path, root)["passed"])

    def test_rejects_failed_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            report_path.write_text(
                json.dumps({"passed": False, "error": "fixture failed"}), encoding="utf-8"
            )
            with self.assertRaisesRegex(checker.VerificationError, "fixture failed"):
                checker.validate_report(report_path, Path(temp))

    def test_rejects_resource_root_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            report_path = Path(temp) / "report.json"
            report_path.write_text(
                json.dumps({"passed": True, "resource_root": str(Path(temp) / "wrong")}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(checker.VerificationError, "resource_root mismatch"):
                checker.validate_report(report_path, Path(temp) / "expected")

    def test_lite_uv_version_requires_exact_first_two_tokens(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            test_dir = Path(temp)
            executable = test_dir / "MDFlux"
            executable.touch()
            uv_name = "uv.exe" if checker.os.name == "nt" else "uv"
            uv = test_dir / "app-data" / "bin" / "uv-0.12.3" / uv_name
            uv.parent.mkdir(parents=True)
            uv.touch()
            with patch(
                "check_packaged_app.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="uv 0.12.3", stderr=""),
            ):
                checker.verify_lite_uv(test_dir, executable)
            with patch(
                "check_packaged_app.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="not-uv 0.12.3", stderr=""),
            ):
                with self.assertRaisesRegex(checker.VerificationError, "does not report"):
                    checker.verify_lite_uv(test_dir, executable)

    def test_subprocess_failure_rejects_and_removes_stale_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "MDFlux"
            executable.touch()
            test_dir = root / "test-data"
            test_dir.mkdir()
            stale_report = test_dir / "report.json"
            stale_report.write_text(
                json.dumps({"passed": True, "resource_root": str(executable.parent)}),
                encoding="utf-8",
            )
            with patch(
                "check_packaged_app.subprocess.run",
                return_value=SimpleNamespace(returncode=1, stdout="", stderr="launch failed"),
            ):
                with self.assertRaisesRegex(checker.VerificationError, "exited 1"):
                    checker.run_verification(executable, test_dir, root)
            self.assertFalse(stale_report.exists())

    def test_success_exit_without_fresh_report_rejects_stale_result(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            executable = root / "MDFlux"
            executable.touch()
            test_dir = root / "test-data"
            test_dir.mkdir()
            stale_report = test_dir / "report.json"
            stale_report.write_text(
                json.dumps({"passed": True, "resource_root": str(executable.parent)}),
                encoding="utf-8",
            )
            with patch(
                "check_packaged_app.subprocess.run",
                return_value=SimpleNamespace(returncode=0, stdout="", stderr=""),
            ):
                with self.assertRaisesRegex(checker.VerificationError, "Cannot read verification report"):
                    checker.run_verification(executable, test_dir, root)
            self.assertFalse(stale_report.exists())


if __name__ == "__main__":
    unittest.main()
