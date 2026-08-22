from __future__ import annotations

from typing import Any

from .models import VerificationReport


def format_human_report(report: VerificationReport) -> str:
    lines = [
        "MDFlux release archive verification",
        f"Archive:  {report.archive}",
        f"Platform: {report.platform}",
        f"Edition:  {report.edition}",
        f"Result:   {'PASS' if report.passed else 'FAIL'}",
        "",
        "Checks:",
    ]
    for check in report.checks:
        status = "PASS" if check.passed else "FAIL"
        detail = f" - {check.detail}" if check.detail else ""
        lines.append(f"  [{status}] {check.name}{detail}")
    if report.extract_dir:
        lines.extend(["", f"Extracted to: {report.extract_dir}"])
    return "\n".join(lines)


def format_json_report(report: VerificationReport) -> dict[str, Any]:
    return report.to_dict()
