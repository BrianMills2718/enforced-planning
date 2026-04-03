#!/usr/bin/env python3
"""Log governance friction observations to FRICTION.md.

Agents call this when the governance framework creates friction during
autonomous work. Each entry becomes actionable feedback for improving
the framework.

Usage:
    python scripts/log_friction.py \
        --friction "Plan validator blocked a status-only change" \
        --impact "Had to use ack file workaround, 5 min lost" \
        --suggestion "Skip validation when only Status field changes" \
        --severity medium \
        --agent claude-code \
        --phase implementation

    python scripts/log_friction.py --list
    python scripts/log_friction.py --summary
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRICTION_FILE = REPO_ROOT / "FRICTION.md"
TEMPLATE = REPO_ROOT / "templates" / "FRICTION.md"


def ensure_friction_file() -> Path:
    """Create FRICTION.md from the canonical template when missing."""
    if not FRICTION_FILE.exists():
        if TEMPLATE.exists():
            FRICTION_FILE.write_text(
                TEMPLATE.read_text(encoding="utf-8"), encoding="utf-8"
            )
        else:
            FRICTION_FILE.write_text(
                "# Governance Friction Log\n\n## Entries\n\n"
                "<!-- Append new entries below this line -->\n",
                encoding="utf-8",
            )
    return FRICTION_FILE


def append_entry(
    friction: str,
    impact: str,
    suggestion: str,
    severity: str = "medium",
    agent: str = "claude-code",
    phase: str = "unknown",
) -> None:
    """Append one structured friction entry to FRICTION.md."""
    path = ensure_friction_file()
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    entry = (
        f"\n### {date} — {agent} — {phase}\n"
        f"**Friction:** {friction}\n"
        f"**Impact:** {impact}\n"
        f"**Suggestion:** {suggestion}\n"
        f"**Severity:** {severity}\n"
    )
    path.write_text(path.read_text(encoding="utf-8") + entry, encoding="utf-8")
    print(f"Logged friction entry ({severity}) to {path}")


def list_entries() -> None:
    """Print all recorded friction entries."""
    path = ensure_friction_file()
    content = path.read_text(encoding="utf-8")
    entries = re.findall(
        r"### (\d{4}-\d{2}-\d{2}) — (.+?) — (.+?)\n"
        r"\*\*Friction:\*\* (.+?)\n"
        r"\*\*Impact:\*\* (.+?)\n"
        r"\*\*Suggestion:\*\* (.+?)\n"
        r"\*\*Severity:\*\* (.+?)(?:\n|$)",
        content,
    )
    if not entries:
        print("No friction entries found.")
        return
    for date, agent, phase, friction, impact, suggestion, severity in entries:
        print(f"[{severity}] {date} ({agent}, {phase}): {friction}")


def summary() -> None:
    """Print friction counts by severity."""
    path = ensure_friction_file()
    content = path.read_text(encoding="utf-8")
    severities = re.findall(r"\*\*Severity:\*\* (\w+)", content)
    if not severities:
        print("No friction entries found.")
        return

    counts: dict[str, int] = {}
    for severity in severities:
        counts[severity] = counts.get(severity, 0) + 1

    print(f"Friction entries: {sum(counts.values())}")
    for severity in ("high", "medium", "low"):
        if severity in counts:
            print(f"  {severity}: {counts[severity]}")


def main() -> int:
    """CLI entry point for friction logging and summary operations."""
    parser = argparse.ArgumentParser(description="Log governance friction")
    parser.add_argument("--friction", help="What happened")
    parser.add_argument("--impact", help="How it slowed you down")
    parser.add_argument("--suggestion", help="What would have been better")
    parser.add_argument(
        "--severity",
        choices=["low", "medium", "high"],
        default="medium",
    )
    parser.add_argument("--agent", default="claude-code")
    parser.add_argument("--phase", default="unknown")
    parser.add_argument("--list", action="store_true", help="List all entries")
    parser.add_argument("--summary", action="store_true", help="Count by severity")
    args = parser.parse_args()

    if args.list:
        list_entries()
        return 0
    if args.summary:
        summary()
        return 0

    if not args.friction:
        parser.error("--friction is required when logging an entry")
    if not args.impact:
        parser.error("--impact is required when logging an entry")
    if not args.suggestion:
        parser.error("--suggestion is required when logging an entry")

    append_entry(
        friction=args.friction,
        impact=args.impact,
        suggestion=args.suggestion,
        severity=args.severity,
        agent=args.agent,
        phase=args.phase,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
