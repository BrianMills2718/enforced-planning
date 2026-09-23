#!/usr/bin/env python3
"""Build a cross-repo plan registry from all governed repos.

Scans a projects directory for repos containing docs/plans/AGENTS.md or legacy CLAUDE.md and
produces a JSON registry of all plans: their numbers, titles, statuses,
and dependency references.

Output: plan_registry.json — a flat, consumable registry used by:
  - check_plan_deps.py for cross-repo reference validation
  - Agents making decisions about what to work on next
  - Dashboard for cross-repo roadmap views

Usage:
    python build_plan_registry.py
    python build_plan_registry.py --scan-dir ~/projects --output plan_registry.json
    python build_plan_registry.py --summary
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


# Pattern for plan table rows in AGENTS.md or legacy CLAUDE.md plan indexes
# Matches: | N | Title | Priority | Status | Blocks |
# or:      | N | Title (path) | Priority | Status | Blocks |
PLAN_ROW_RE = re.compile(
    r"^\|\s*(\d+)\s*\|([^|]+)\|([^|]*)\|([^|]*)\|([^|]*)\|?\s*$"
)

# Detect governed repos by presence of meta-process.yaml
META_PROCESS_MARKER = "meta-process.yaml"

# Files where plan tables live
PLAN_INDEX_NAMES = ["AGENTS.md", "CLAUDE.md"]


def _extract_plan_title(raw_cell: str) -> str:
    """Clean a plan title cell: strip links, markdown, excess whitespace."""
    # Strip markdown links [text](path) → text
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw_cell)
    # Strip backticks and bold
    cleaned = re.sub(r"[`*]+", "", cleaned)
    return cleaned.strip()


def _extract_status(raw_cell: str) -> str:
    """Normalize a status cell to a canonical string."""
    cell = raw_cell.strip()
    # Map emoji + text to canonical strings
    if "✅" in cell or "Complete" in cell:
        return "complete"
    if "🚧" in cell or "In Progress" in cell:
        return "in_progress"
    if "📋" in cell or "Planned" in cell:
        return "planned"
    if "⏸" in cell or "Blocked" in cell:
        return "blocked"
    if "❌" in cell or "Cancelled" in cell:
        return "cancelled"
    return cell.lower().strip()


def parse_plan_index(plan_index_path: Path, project: str) -> list[dict[str, Any]]:
    """Parse a docs/plans/AGENTS.md or legacy CLAUDE.md file and return a list of plan entries.

    Each entry has: {project, plan_num, title, status, priority, blocks}.
    """
    entries: list[dict[str, Any]] = []
    try:
        text = plan_index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return entries

    for line in text.splitlines():
        m = PLAN_ROW_RE.match(line.strip())
        if not m:
            continue
        num_str, title_cell, priority_cell, status_cell, blocks_cell = [
            m.group(i) for i in range(1, 6)
        ]
        try:
            plan_num = int(num_str)
        except ValueError:
            continue

        entries.append({
            "project": project,
            "plan_num": plan_num,
            "title": _extract_plan_title(title_cell),
            "priority": priority_cell.strip().lower(),
            "status": _extract_status(status_cell),
            "blocks": blocks_cell.strip(),
        })

    return entries


def discover_governed_repos(scan_dir: Path) -> list[Path]:
    """Find all repos with a meta-process.yaml in scan_dir."""
    repos: list[Path] = []
    for candidate in sorted(scan_dir.iterdir()):
        if not candidate.is_dir():
            continue
        if candidate.name.startswith(".") or candidate.name.startswith("_"):
            continue
        if (candidate / META_PROCESS_MARKER).exists():
            repos.append(candidate)
    return repos


def find_plan_index(repo_root: Path) -> Path | None:
    """Find the plan index file in a governed repo."""
    plan_dir = repo_root / "docs" / "plans"
    if not plan_dir.exists():
        return None
    for name in PLAN_INDEX_NAMES:
        candidate = plan_dir / name
        if candidate.exists():
            return candidate
    return None


def build_registry(scan_dir: Path) -> dict[str, Any]:
    """Build the full cross-repo plan registry.

    Returns {
        "projects": {project_name: {repo_path, plan_count, plans: [...]}},
        "total_plans": int,
        "complete": int,
        "in_progress": int,
        "planned": int,
    }
    """
    projects: dict[str, Any] = {}
    all_plans: list[dict[str, Any]] = []

    for repo in discover_governed_repos(scan_dir):
        plan_index = find_plan_index(repo)
        if plan_index is None:
            continue
        project = repo.name
        plans = parse_plan_index(plan_index, project)
        if not plans:
            continue
        projects[project] = {
            "repo_path": str(repo),
            "plan_count": len(plans),
            "plans": plans,
        }
        all_plans.extend(plans)

    status_counts = {"complete": 0, "in_progress": 0, "planned": 0, "blocked": 0}
    for p in all_plans:
        s = p["status"]
        if s in status_counts:
            status_counts[s] += 1

    return {
        "projects": projects,
        "total_plans": len(all_plans),
        **status_counts,
    }


def format_summary(registry: dict[str, Any]) -> str:
    """Format a human-readable summary of the plan registry."""
    lines = ["# Cross-Repo Plan Registry\n"]
    lines.append(f"Total plans: {registry['total_plans']}")
    lines.append(f"  complete: {registry['complete']}")
    lines.append(f"  in_progress: {registry['in_progress']}")
    lines.append(f"  planned: {registry['planned']}")
    lines.append(f"  blocked: {registry['blocked']}")
    lines.append(f"\nProjects ({len(registry['projects'])}):")
    for proj, info in sorted(registry["projects"].items()):
        lines.append(f"  {proj}: {info['plan_count']} plans")
        for plan in info["plans"]:
            status_icon = {
                "complete": "✅",
                "in_progress": "🚧",
                "planned": "📋",
                "blocked": "⏸",
            }.get(plan["status"], "?")
            lines.append(f"    #{plan['plan_num']:3d} {status_icon} {plan['title']}")
    return "\n".join(lines)


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Build cross-repo plan registry")
    parser.add_argument(
        "--scan-dir",
        type=Path,
        default=Path("~/projects").expanduser(),
        help="Directory to scan for governed repos (default: ~/projects)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Output JSON file (default: stdout or generated/plan_registry.json)",
    )
    parser.add_argument("--summary", action="store_true", help="Print human-readable summary")
    args = parser.parse_args()

    scan_dir = args.scan_dir.expanduser().resolve()
    if not scan_dir.is_dir():
        print(f"Error: {scan_dir} is not a directory", file=sys.stderr)
        return 1

    registry = build_registry(scan_dir)

    if args.summary or not args.output:
        print(format_summary(registry))
        if not args.output:
            return 0

    output = args.output or Path("generated/plan_registry.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    with open(output, "w") as f:
        json.dump(registry, f, indent=2)
    print(f"Wrote registry to {output} ({registry['total_plans']} plans from {len(registry['projects'])} projects)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
