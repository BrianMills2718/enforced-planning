#!/usr/bin/env python3
"""Validate plan dependency references in blocked_by and blocks fields.

Checks that plan references resolve to real plans and that the dependency
format follows the standard:
  - #N              same-project plan reference
  - project#N       cross-project plan reference
  - #N — condition  plan ref with human-readable condition
  - [future] desc   conceptual/aspirational, not validated

Usage:
    python check_plan_deps.py docs/plans/           # check all plans in dir
    python check_plan_deps.py plan.md               # check single file
    python check_plan_deps.py --scan-dir ~/projects  # resolve cross-project refs
    python check_plan_deps.py --strict plan.md      # exit 1 on any error
    python check_plan_deps.py --json plan.md        # JSON output
"""

import argparse
import json
import re
import sys
from pathlib import Path


# Patterns for dependency references (ordered by specificity)
# Canonical: #N, project#N, [future]
# Legacy (also accepted): Plan #N, bare N, Plan #N description
SAME_PROJECT_REF = re.compile(
    r"^(?:Plan\s+)?#(\d+)(?:\s+.*)?$|"  # #N or Plan #N, optional trailing text
    r"^(\d+)(?:\s*[—–-]\s*.*)?$",        # bare number, optional condition
    re.IGNORECASE,
)
CROSS_PROJECT_REF = re.compile(r"^([\w_-]+)#(\d+)(?:\s*[—–-]\s*.*)?$")
FUTURE_REF = re.compile(r"^\[future\]\s+", re.IGNORECASE)
NONE_REF = re.compile(r"^(?:none|n/a|—|-)\s*$", re.IGNORECASE)


def _find_plans_in_dir(plan_dir: Path) -> dict[int, Path]:
    """Build a map of plan number → file path for a plans directory."""
    plans: dict[int, Path] = {}
    for f in plan_dir.glob("*.md"):
        m = re.match(r"^(\d+)[_-]", f.name)
        if m:
            plans[int(m.group(1))] = f
    return plans


def _find_cross_project_plans(scan_dir: Path) -> dict[str, dict[int, Path]]:
    """Build project → {plan_number: path} map by scanning ~/projects/."""
    projects: dict[str, dict[int, Path]] = {}
    if not scan_dir.exists():
        return projects
    for project_dir in scan_dir.iterdir():
        if not project_dir.is_dir():
            continue
        plans_dir = project_dir / "docs" / "plans"
        if plans_dir.exists():
            local_plans = _find_plans_in_dir(plans_dir)
            if local_plans:
                projects[project_dir.name] = local_plans
    return projects


def _parse_dep_refs(text: str) -> list[str]:
    """Extract individual dependency references from a blocked_by/blocks field value."""
    # Split on commas and newlines, strip bullets and whitespace
    refs = []
    for line in re.split(r"[,\n]", text):
        line = line.strip().lstrip("-*• ").strip()
        if line and not NONE_REF.match(line):
            refs.append(line)
    return refs


def check_plan(
    path: Path,
    local_plans: dict[int, Path],
    cross_project_plans: dict[str, dict[int, Path]] | None = None,
) -> list[dict]:
    """Check a single plan file for dependency format compliance.

    Returns a list of findings (empty = all good).
    """
    text = path.read_text(encoding="utf-8")
    findings: list[dict] = []

    # Skip non-plan files
    if not re.search(r"^# Plan #\d+", text, re.MULTILINE):
        return []

    # Extract blocked_by and blocks fields
    for field_name in ("Blocked By", "Blocks"):
        m = re.search(
            rf"\*\*{field_name}:\*\*\s*(.+?)(?:\n\n|\n\*\*|\n---|\n##|\Z)",
            text,
            re.DOTALL,
        )
        if not m:
            continue

        field_value = m.group(1).strip()
        if NONE_REF.match(field_value):
            continue

        refs = _parse_dep_refs(field_value)
        for ref in refs:
            # Check format
            if FUTURE_REF.match(ref):
                findings.append({
                    "file": str(path),
                    "field": field_name,
                    "ref": ref,
                    "status": "ok",
                    "type": "future",
                    "message": "Conceptual reference (not validated)",
                })
                continue

            same_match = SAME_PROJECT_REF.match(ref)
            if same_match:
                plan_num = int(same_match.group(1) or same_match.group(2))
                if plan_num in local_plans:
                    findings.append({
                        "file": str(path),
                        "field": field_name,
                        "ref": ref,
                        "status": "ok",
                        "type": "same_project",
                        "message": f"Resolves to {local_plans[plan_num].name}",
                    })
                else:
                    findings.append({
                        "file": str(path),
                        "field": field_name,
                        "ref": ref,
                        "status": "error",
                        "type": "same_project",
                        "message": f"Plan #{plan_num} not found in {path.parent}",
                    })
                continue

            cross_match = CROSS_PROJECT_REF.match(ref)
            if cross_match:
                project = cross_match.group(1)
                plan_num = int(cross_match.group(2))
                if cross_project_plans is None:
                    findings.append({
                        "file": str(path),
                        "field": field_name,
                        "ref": ref,
                        "status": "skip",
                        "type": "cross_project",
                        "message": "Cross-project ref (use --scan-dir to validate)",
                    })
                elif project in cross_project_plans:
                    if plan_num in cross_project_plans[project]:
                        findings.append({
                            "file": str(path),
                            "field": field_name,
                            "ref": ref,
                            "status": "ok",
                            "type": "cross_project",
                            "message": f"Resolves to {project}/docs/plans/{cross_project_plans[project][plan_num].name}",
                        })
                    else:
                        findings.append({
                            "file": str(path),
                            "field": field_name,
                            "ref": ref,
                            "status": "error",
                            "type": "cross_project",
                            "message": f"Plan #{plan_num} not found in {project}/docs/plans/",
                        })
                else:
                    findings.append({
                        "file": str(path),
                        "field": field_name,
                        "ref": ref,
                        "status": "error",
                        "type": "cross_project",
                        "message": f"Project '{project}' not found",
                    })
                continue

            # Unrecognized format
            findings.append({
                "file": str(path),
                "field": field_name,
                "ref": ref,
                "status": "warning",
                "type": "unrecognized",
                "message": "Does not match #N, project#N, or [future] format. Use structured format for new plans.",
            })

    return findings


def main():
    """Entry point."""
    parser = argparse.ArgumentParser(description="Validate plan dependency references")
    parser.add_argument("paths", nargs="+", help="Plan files or directories to check")
    parser.add_argument("--scan-dir", type=Path, help="Root dir to resolve cross-project refs (e.g., ~/projects)")
    parser.add_argument("--strict", action="store_true", help="Exit 1 on any error")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args()

    # Collect plan files
    plan_files = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            plan_files.extend(sorted(path.glob("*.md")))
        elif path.is_file():
            plan_files.append(path)

    # Build plan index for the first path's directory
    local_plans: dict[int, Path] = {}
    if plan_files:
        plans_dir = plan_files[0].parent
        local_plans = _find_plans_in_dir(plans_dir)

    # Build cross-project index if requested
    cross_project_plans = None
    if args.scan_dir:
        cross_project_plans = _find_cross_project_plans(args.scan_dir.expanduser())

    all_findings = []
    for f in plan_files:
        # Use per-file local plans if files span multiple directories
        file_local = _find_plans_in_dir(f.parent) if f.parent != plans_dir else local_plans
        all_findings.extend(check_plan(f, file_local, cross_project_plans))

    errors = [f for f in all_findings if f["status"] == "error"]
    warnings = [f for f in all_findings if f["status"] == "warning"]
    ok = [f for f in all_findings if f["status"] == "ok"]

    if args.json:
        print(json.dumps({
            "total_refs": len(all_findings),
            "errors": len(errors),
            "warnings": len(warnings),
            "ok": len(ok),
            "findings": all_findings,
        }, indent=2))
    else:
        for f in errors:
            print(f"  ERROR: {Path(f['file']).name} [{f['field']}] {f['ref']}: {f['message']}")
        for f in warnings:
            print(f"  WARN:  {Path(f['file']).name} [{f['field']}] {f['ref']}: {f['message']}")
        print(f"\nChecked {len(plan_files)} plans, {len(all_findings)} refs: {len(ok)} ok, {len(warnings)} warnings, {len(errors)} errors")

    if args.strict and errors:
        sys.exit(1)


if __name__ == "__main__":
    main()
