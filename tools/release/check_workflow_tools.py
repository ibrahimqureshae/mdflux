from __future__ import annotations

import re
import sys
from pathlib import Path


WORKFLOWS = (
    Path(".github/workflows/ci.yml"),
    Path(".github/workflows/release-candidate.yml"),
    Path(".github/workflows/release.yml"),
)
PLATFORM_MODULE = Path("app/src-tauri/src/platform/mod.rs")
JOB_HEADER = re.compile(r"^  ([a-zA-Z0-9_-]+):\s*$", re.MULTILINE)
UV_COMMAND = re.compile(
    r"^\s+(?:uv(?:\.exe)?|&\s+uv(?:\.exe)?|python(?:\.exe)?\s+-m\s+uv)\s+",
    re.IGNORECASE | re.MULTILINE,
)
UV_SETUP = "uses: astral-sh/setup-uv@"
UV_VERSION = re.compile(r'^pub const UV_VERSION: &str = "([^\"]+)";', re.MULTILINE)
SETUP_STEP = re.compile(
    r"^\s*- uses: astral-sh/setup-uv@[^\r\n]*\r?\n(?P<body>(?:(?!^\s*- ).*(?:\r?\n|$))*)",
    re.MULTILINE,
)
STEP_VERSION = re.compile(r'^\s+version:\s*["\']?([^\s"\']+)', re.MULTILINE)


def pinned_uv_version(platform_source: str) -> str | None:
    match = UV_VERSION.search(platform_source)
    return match.group(1) if match else None


def workflow_errors(workflow: Path, text: str, expected_version: str) -> list[str]:
    errors: list[str] = []
    for job, block in job_blocks(text):
        command = UV_COMMAND.search(block)
        setup = block.find(UV_SETUP)
        if command and (setup < 0 or setup > command.start()):
            errors.append(f"{workflow}: job {job!r} runs uv before pinned setup-uv")

    for match in SETUP_STEP.finditer(text):
        version = STEP_VERSION.search(match.group("body"))
        actual_version = version.group(1) if version else None
        if actual_version != expected_version:
            errors.append(
                f"{workflow}: setup-uv version {actual_version!r} does not match "
                f"platform UV_VERSION {expected_version!r}"
            )
    return errors


def job_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(JOB_HEADER.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1), text[match.start() : end]))
    return blocks


def main() -> int:
    errors: list[str] = []
    platform_source = PLATFORM_MODULE.read_text(encoding="utf-8")
    expected_version = pinned_uv_version(platform_source)
    if expected_version is None:
        print(f"{PLATFORM_MODULE}: missing UV_VERSION constant", file=sys.stderr)
        return 1
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        errors.extend(workflow_errors(workflow, text, expected_version))

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Release workflow tool setup: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
