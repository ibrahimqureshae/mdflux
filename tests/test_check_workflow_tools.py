from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "release"))
import check_workflow_tools as checker


class WorkflowUvVersionTests(unittest.TestCase):
    def test_reads_platform_version_constant(self) -> None:
        source = 'pub const UV_VERSION: &str = "0.12.3";'
        self.assertEqual(checker.pinned_uv_version(source), "0.12.3")

    def test_accepts_matching_setup_uv_version(self) -> None:
        text = """jobs:
  build:
    steps:
      - uses: astral-sh/setup-uv@deadbeef
        with:
          version: "0.12.3"
          enable-cache: true
      - run: uv --version
"""
        self.assertEqual(checker.workflow_errors(Path("ci.yml"), text, "0.12.3"), [])

    def test_rejects_missing_or_mismatched_setup_uv_version(self) -> None:
        for setup in (
            "      - uses: astral-sh/setup-uv@deadbeef\n",
            '      - uses: astral-sh/setup-uv@deadbeef\n        with:\n          version: "0.5.11"\n',
        ):
            with self.subTest(setup=setup):
                errors = checker.workflow_errors(Path("ci.yml"), setup, "0.12.3")
                self.assertEqual(len(errors), 1)
                self.assertIn("does not match platform UV_VERSION", errors[0])


if __name__ == "__main__":
    unittest.main()
