#!/usr/bin/env python3
"""Validate that plans expose capability metadata at the planning layer.

Plans that create or modify callable functions used by other projects
MUST declare their capabilities (input/output schemas, producer, consumer).
Capability-bearing plans must also carry the goal-graph header fields
``phase_ref`` and ``goal_ref``. Internal-only plans may skip the section.

Detection heuristic: a plan is "cross-project" if it:
  1. Has Files Affected spanning multiple projects, OR
  2. References producer/consumer in its text, OR
  3. Has consumers listed in its Capabilities table

Usage:
    python check_plan_capabilities.py docs/plans/        # check all plans in dir
    python check_plan_capabilities.py plan.md            # check single plan
    python check_plan_capabilities.py --strict plan.md   # fail (not warn) on missing
    python check_plan_capabilities.py --json plan.md     # JSON output
"""

import argparse
import json
import re
import sys
from pathlib import Path


# Keywords that suggest cross-project boundaries
BOUNDARY_KEYWORDS = {
    "producer", "consumer", "boundary", "@boundary", "@tool",
    "cross-project", "downstream", "upstream", "import from",
    "export to", "Pydantic model", "schema", "contract",
}

REQUIRED_GOAL_GRAPH_FIELDS = ("phase_ref", "goal_ref")
PLACEHOLDER_HEADER_VALUES = {
    "phase_ref": {"Phase X.Y", "Phase X", "phase x.y"},
    "goal_ref": {"goal-id"},
}


def _extract_header_value(text: str, field_name: str) -> str | None:
    """Return one plan header value, or None when the field is missing/unset."""
    match = re.search(rf"^\*\*{re.escape(field_name)}:\*\*\s*(.+)$", text, re.MULTILINE)
    if not match:
        return None
    value = match.group(1).strip()
    if not value:
        return None
    normalized = value.strip().strip('"').strip("'")
    if normalized in PLACEHOLDER_HEADER_VALUES.get(field_name, set()):
        return None
    return normalized


def _missing_goal_graph_fields(text: str) -> list[str]:
    """Return required goal-graph header fields that are missing or still placeholders."""
    missing = []
    for field_name in REQUIRED_GOAL_GRAPH_FIELDS:
        if _extract_header_value(text, field_name) is None:
            missing.append(field_name)
    return missing


def check_plan(path: Path) -> dict:
    """Check a single plan file for Capabilities section compliance.

    Returns a dict with: file, has_capabilities, is_cross_project, status, message.
    """
    text = path.read_text(encoding="utf-8")

    # Skip non-plan files (CLAUDE.md, AGENTS.md, TEMPLATE.md, etc.)
    if not re.search(r"^# Plan #\d+", text, re.MULTILINE):
        return {
            "file": str(path),
            "has_capabilities": False,
            "is_cross_project": False,
            "signals": [],
            "status": "skip",
            "message": "Not a plan file",
        }

    # Skip completed plans — they predate the Capabilities requirement
    status_match = re.search(r"\*\*Status:\*\*\s*(.+)", text)
    if status_match and "complete" in status_match.group(1).lower():
        return {
            "file": str(path),
            "has_capabilities": False,
            "is_cross_project": False,
            "signals": [],
            "status": "skip",
            "message": "Completed plan (predates requirement)",
        }

    # Check for Capabilities section
    has_capabilities = bool(re.search(r"^## Capabilities", text, re.MULTILINE))
    missing_goal_graph_fields = _missing_goal_graph_fields(text) if has_capabilities else []

    # Check if plan mentions skip instruction
    # Explicit opt-out: plan says it's internal
    explicit_internal = bool(re.search(
        r"(does NOT cross project boundar|N/A.*internal|internal.only)",
        text, re.IGNORECASE,
    ))

    # Detect cross-project signals
    signals = []
    text_lower = text.lower()
    for kw in BOUNDARY_KEYWORDS:
        if kw.lower() in text_lower:
            signals.append(kw)

    # Check for explicit consumer references in capabilities table
    has_consumer_table = bool(re.search(r"\|\s*Consumer", text, re.IGNORECASE))

    is_cross_project = (len(signals) >= 2 or has_consumer_table) and not explicit_internal

    # Determine status
    if has_capabilities and missing_goal_graph_fields:
        status = "warning"
        message = (
            "Capabilities section present but missing goal-graph header fields: "
            + ", ".join(missing_goal_graph_fields)
        )
    elif has_capabilities:
        status = "ok"
        message = "Has Capabilities section and goal-graph headers"
    elif not is_cross_project:
        status = "ok"
        message = "Internal plan — no Capabilities required"
    else:
        status = "warning"
        message = f"Cross-project plan missing Capabilities section (signals: {', '.join(signals[:5])})"

    return {
        "file": str(path),
        "has_capabilities": has_capabilities,
        "is_cross_project": is_cross_project,
        "signals": signals,
        "missing_goal_graph_fields": missing_goal_graph_fields,
        "status": status,
        "message": message,
    }


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Check plan files for capability and goal-graph metadata compliance",
    )
    parser.add_argument("paths", nargs="+", help="Plan files or directories to check")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any warning")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    args = parser.parse_args()

    # Collect plan files
    plan_files = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            plan_files.extend(sorted(path.glob("*.md")))
        elif path.is_file():
            plan_files.append(path)

    results = [check_plan(f) for f in plan_files]

    warnings = [r for r in results if r["status"] == "warning"]
    ok_count = sum(1 for r in results if r["status"] == "ok")

    if args.json:
        print(json.dumps({
            "total": len(results),
            "ok": ok_count,
            "warnings": len(warnings),
            "results": results,
        }, indent=2))
    else:
        for r in results:
            if r["status"] == "warning":
                print(f"  WARN: {Path(r['file']).name}: {r['message']}")
        print(f"\nChecked {len(results)} plans: {ok_count} ok, {len(warnings)} warnings")

    if args.strict and warnings:
        sys.exit(1)


if __name__ == "__main__":
    main()
