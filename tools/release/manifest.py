from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .models import CheckResult, FULL_COMPONENTS, LITE_COMPONENTS


_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)


def load_edition_manifest(path: Path) -> tuple[dict[str, Any] | None, CheckResult | None]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, CheckResult(
            "edition-manifest-parse",
            False,
            f"Could not parse edition.json: {exc}",
        )
    if not isinstance(data, dict):
        return None, CheckResult(
            "edition-manifest-parse",
            False,
            "edition.json must be a JSON object",
        )
    return data, CheckResult("edition-manifest-parse", True, "Valid JSON object")


def validate_edition_manifest(
    manifest: dict[str, Any],
    *,
    expected_platform: str,
    expected_edition: str,
) -> list[CheckResult]:
    results: list[CheckResult] = []
    required_fields = (
        "schema",
        "edition",
        "app_version",
        "commit",
        "platform",
        "python_version",
        "components",
        "dependency_lock_sha256",
        "built_at_utc",
    )
    missing = [field for field in required_fields if field not in manifest]
    if missing:
        results.append(
            CheckResult(
                "edition-manifest-schema",
                False,
                f"Missing required fields: {', '.join(missing)}",
            )
        )
        return results

    schema = manifest.get("schema")
    if schema != 1:
        results.append(
            CheckResult(
                "edition-manifest-schema",
                False,
                f"schema must be 1, got {schema!r}",
            )
        )
    else:
        results.append(CheckResult("edition-manifest-schema", True, "schema=1"))

    edition = manifest.get("edition")
    if edition != expected_edition:
        results.append(
            CheckResult(
                "edition-manifest-edition",
                False,
                f"edition is {edition!r}, expected {expected_edition!r}",
            )
        )
    else:
        results.append(
            CheckResult("edition-manifest-edition", True, f"edition={edition}")
        )

    platform = manifest.get("platform")
    if platform != expected_platform:
        results.append(
            CheckResult(
                "edition-manifest-platform",
                False,
                f"platform is {platform!r}, expected {expected_platform!r}",
            )
        )
    else:
        results.append(
            CheckResult("edition-manifest-platform", True, f"platform={platform}")
        )

    app_version = manifest.get("app_version")
    if not isinstance(app_version, str) or not app_version.strip():
        results.append(
            CheckResult(
                "edition-manifest-app-version",
                False,
                "app_version must be a non-empty string",
            )
        )
    else:
        results.append(
            CheckResult(
                "edition-manifest-app-version",
                True,
                f"app_version={app_version}",
            )
        )

    commit = manifest.get("commit")
    if not isinstance(commit, str) or len(commit) < 7:
        results.append(
            CheckResult(
                "edition-manifest-commit",
                False,
                "commit must be a git commit string",
            )
        )
    else:
        results.append(CheckResult("edition-manifest-commit", True, commit[:12]))

    components = manifest.get("components")
    expected_components = (
        FULL_COMPONENTS if expected_edition == "full" else LITE_COMPONENTS
    )
    if components != expected_components:
        results.append(
            CheckResult(
                "edition-manifest-components",
                False,
                f"components={components!r}, expected {expected_components}",
            )
        )
    else:
        results.append(
            CheckResult(
                "edition-manifest-components",
                True,
                ", ".join(components),
            )
        )

    python_version = manifest.get("python_version")
    if expected_edition == "lite":
        if python_version is not None:
            results.append(
                CheckResult(
                    "edition-manifest-python-version",
                    False,
                    "Lite edition must set python_version to null",
                )
            )
        else:
            results.append(
                CheckResult(
                    "edition-manifest-python-version",
                    True,
                    "python_version is null",
                )
            )
    else:
        if not isinstance(python_version, str) or not python_version.strip():
            results.append(
                CheckResult(
                    "edition-manifest-python-version",
                    False,
                    "Full edition requires a python_version string",
                )
            )
        else:
            results.append(
                CheckResult(
                    "edition-manifest-python-version",
                    True,
                    python_version,
                )
            )

    lock_sha = manifest.get("dependency_lock_sha256")
    if not isinstance(lock_sha, str) or len(lock_sha) != 64:
        results.append(
            CheckResult(
                "edition-manifest-lock-sha256",
                False,
                "dependency_lock_sha256 must be a 64-character hex SHA-256",
            )
        )
    else:
        try:
            int(lock_sha, 16)
        except ValueError:
            results.append(
                CheckResult(
                    "edition-manifest-lock-sha256",
                    False,
                    "dependency_lock_sha256 must be hexadecimal",
                )
            )
        else:
            results.append(
                CheckResult(
                    "edition-manifest-lock-sha256",
                    True,
                    lock_sha[:16] + "...",
                )
            )

    built_at = manifest.get("built_at_utc")
    if not isinstance(built_at, str) or not _ISO8601_RE.match(built_at):
        results.append(
            CheckResult(
                "edition-manifest-built-at",
                False,
                "built_at_utc must be ISO-8601 UTC",
            )
        )
    else:
        try:
            normalized = built_at.replace("Z", "+00:00")
            datetime.fromisoformat(normalized)
        except ValueError:
            results.append(
                CheckResult(
                    "edition-manifest-built-at",
                    False,
                    f"built_at_utc is not parseable: {built_at}",
                )
            )
        else:
            results.append(
                CheckResult(
                    "edition-manifest-built-at",
                    True,
                    built_at,
                )
            )

    return results
