from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


PLATFORMS = frozenset({"windows-x64", "linux-x64-glibc"})
EDITIONS = frozenset({"lite", "full"})
FULL_COMPONENTS = ["core", "ocr", "audio-runtime"]
LITE_COMPONENTS = ["core"]
FULL_IMPORT_MODULES = (
    "markitdown",
    "openai",
    "httpx",
    "rapidocr",
    "onnxruntime",
    "pypdfium2",
    "faster_whisper",
    "ctranslate2",
)
CONVERSION_FIXTURES = (
    ("sample.pdf", ".pdf"),
    ("sample.docx", ".docx"),
    ("sample.pptx", ".pptx"),
    ("sample.xlsx", ".xlsx"),
    ("sample.html", ".html"),
    ("sample.txt", ".txt"),
)


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
            "severity": self.severity,
        }


@dataclass
class VerificationReport:
    archive: str
    platform: str
    edition: str
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    extract_dir: str | None = None
    manifest: dict[str, Any] | None = None

    def add(self, check: CheckResult) -> None:
        self.checks.append(check)
        if not check.passed and check.severity == "error":
            self.passed = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "archive": self.archive,
            "platform": self.platform,
            "edition": self.edition,
            "passed": self.passed,
            "extract_dir": self.extract_dir,
            "manifest": self.manifest,
            "checks": [check.to_dict() for check in self.checks],
        }
