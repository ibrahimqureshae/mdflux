from __future__ import annotations

import re
import sys
from pathlib import Path


WORKFLOWS = (
    Path(".github/workflows/release-candidate.yml"),
    Path(".github/workflows/release.yml"),
)
JOB_HEADER = re.compile(r"^  ([a-zA-Z0-9_-]+):\s*$", re.MULTILINE)
UV_COMMAND = re.compile(
    r"^\s+(?:uv(?:\.exe)?|&\s+uv(?:\.exe)?|python(?:\.exe)?\s+-m\s+uv)\s+",
    re.IGNORECASE | re.MULTILINE,
)
UV_SETUP = "uses: astral-sh/setup-uv@"


def job_blocks(text: str) -> list[tuple[str, str]]:
    matches = list(JOB_HEADER.finditer(text))
    blocks: list[tuple[str, str]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        blocks.append((match.group(1), text[match.start() : end]))
    return blocks


def main() -> int:
    errors: list[str] = []
    for workflow in WORKFLOWS:
        text = workflow.read_text(encoding="utf-8")
        for job, block in job_blocks(text):
            command = UV_COMMAND.search(block)
            setup = block.find(UV_SETUP)
            if command and (setup < 0 or setup > command.start()):
                errors.append(
                    f"{workflow}: job {job!r} runs uv before pinned setup-uv"
                )

    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("Release workflow tool setup: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
