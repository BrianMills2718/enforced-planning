#!/usr/bin/env python3
"""Render a compact truth-surface status summary.

This tool can render from validator output JSON or by running the validator from
config. It can also merge an optional semantic-review payload so advisory
findings appear beside deterministic findings without collapsing certainty.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.check_truth_surface_drift import Issue, run_checks  # noqa: E402
from scripts.review_truth_surface_semantic import load_semantic_review_payload  # noqa: E402
from scripts.truth_surface_semantic_models import SemanticReviewReport  # noqa: E402


def _load_issue_payload(path: Path) -> list[Issue]:
    """Load issues from a validator JSON payload."""
    payload = json.loads(path.read_text())
    issues_raw = payload.get("issues", [])
    issues: list[Issue] = []
    for item in issues_raw:
        issues.append(
            Issue(
                code=item["code"],
                severity=item["severity"],
                message=item["message"],
                evidence=item.get("evidence", {}),
            )
        )
    return issues


def _render_semantic_section(report: SemanticReviewReport) -> list[str]:
    """Render the advisory semantic section without changing deterministic status."""
    findings = report.findings
    if not findings:
        return [
            "- Semantic Review: clean",
            "- Semantic Findings: 0",
        ]

    counts = Counter(finding.severity for finding in findings)
    overall = "warn" if counts.get("warn") else "info"
    promotion_count = sum(1 for finding in findings if finding.promotion_candidate)
    lines = [
        f"- Semantic Review: {overall}",
        f"- Semantic Findings: {len(findings)}",
        f"- Semantic Warn: {counts.get('warn', 0)}",
        f"- Semantic Info: {counts.get('info', 0)}",
        f"- Semantic Promotion Candidates: {promotion_count}",
        f"- Semantic Overview: {report.overview}",
        "- Semantic Advisory Findings:",
    ]
    for finding in findings:
        evidence = ", ".join(finding.evidence_refs) if finding.evidence_refs else "none provided"
        promotion = "yes" if finding.promotion_candidate else "no"
        lines.append(
            f"  - [{finding.severity.upper()}] {finding.category}: {finding.summary}"
        )
        lines.append(f"    evidence: {evidence}")
        lines.append(f"    promotion_candidate: {promotion}")
        if finding.promotion_rule_hint:
            lines.append(f"    promotion_rule_hint: {finding.promotion_rule_hint}")
    return lines


def render_status(issues: list[Issue], semantic_report: SemanticReviewReport | None = None) -> str:
    """Render a deterministic human-readable truth-surface summary."""
    if not issues:
        lines = ["Truth Surface Status", "- Overall: clean", "- Issues: 0"]
        if semantic_report is not None:
            lines.extend(_render_semantic_section(semantic_report))
        return "\n".join(lines) + "\n"

    counts = Counter(issue.severity for issue in issues)
    if counts.get("fail"):
        overall = "fail"
    elif counts.get("warn"):
        overall = "warn"
    else:
        overall = "info"

    lines = [
        "Truth Surface Status",
        f"- Overall: {overall}",
        f"- Issues: {len(issues)}",
        f"- Fail: {counts.get('fail', 0)}",
        f"- Warn: {counts.get('warn', 0)}",
        f"- Info: {counts.get('info', 0)}",
        "- Findings:",
    ]
    for issue in issues:
        lines.append(f"  - [{issue.severity.upper()}] {issue.code}: {issue.message}")
    if semantic_report is not None:
        lines.extend(_render_semantic_section(semantic_report))
    return "\n".join(lines) + "\n"


def main() -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--config", help="Run validator from config and render the result")
    source.add_argument("--input-json", help="Render a previously captured validator JSON payload")
    parser.add_argument(
        "--semantic-json",
        help="Optional semantic-review JSON payload to merge into the rendered status",
    )
    parser.add_argument("--output", help="Optional output file for rendered text")
    args = parser.parse_args()

    if args.config:
        issues = run_checks(Path(args.config).expanduser())
    else:
        issues = _load_issue_payload(Path(args.input_json).expanduser())

    semantic_report = None
    if args.semantic_json:
        semantic_report = load_semantic_review_payload(Path(args.semantic_json).expanduser())

    rendered = render_status(issues, semantic_report=semantic_report)
    if args.output:
        Path(args.output).expanduser().write_text(rendered)
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
