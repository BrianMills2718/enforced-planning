#!/usr/bin/env python3
"""Parse plan files for enforcement hooks.

Extracts structured data from plan markdown files:
- Files Affected section (what files the plan declares it will touch)
- References Reviewed section (what code/docs were reviewed before planning)
- Research Basis For This Slice section (what broader research informed the slice)
- research_citations header metadata (which prior agent-memory findings informed the plan)

Usage:
    # Get active plan's file scope
    python scripts/parse_plan.py --files-affected

    # Get active plan's references
    python scripts/parse_plan.py --references-reviewed

    # Get active plan's research basis
    python scripts/parse_plan.py --research-basis

    # Check if a file is in scope
    python scripts/parse_plan.py --check-file src/world/ledger.py

    # Parse a specific plan file
    python scripts/parse_plan.py --plan 15 --files-affected

    # JSON output for hooks
    python scripts/parse_plan.py --json --files-affected
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]


def get_main_repo_root() -> Path:
    """Get the main repo root (not worktree)."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_dir = Path(result.stdout.strip())
        return git_dir.parent
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


def get_current_branch() -> str:
    """Get current git branch name."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def get_plan_number_from_branch(branch: str) -> int | None:
    """Extract plan number from branch name like 'plan-15-feature'."""
    match = re.match(r"plan-(\d+)", branch)
    if match:
        return int(match.group(1))
    return None


def get_active_plan_number() -> int | None:
    """Get the plan number for the current work context.

    Tries in order:
    1. Branch name (plan-NN-xxx)
    2. Active claim from .claude/active-work.yaml
    """
    # Try branch name first
    branch = get_current_branch()
    plan_num = get_plan_number_from_branch(branch)
    if plan_num:
        return plan_num

    # Try active claims
    main_root = get_main_repo_root()
    claims_file = main_root / ".claude/active-work.yaml"

    if claims_file.exists():
        try:
            import yaml  # type: ignore[import-untyped]
            with open(claims_file) as f:
                data = yaml.safe_load(f) or {}

            claims = data.get("claims", [])
            for claim in claims:
                if claim.get("cc_id") == branch and claim.get("plan"):
                    return claim["plan"]
        except Exception:
            pass

    return None


def find_plan_file(plan_number: int) -> Path | None:
    """Find the plan file for a given plan number.

    Checks current worktree first, then main repo.
    This allows worktree-specific plan updates to be found before they're merged.
    """
    # Check locations in order of preference - worktree first
    locations = [
        Path.cwd() / "docs/plans",  # Current worktree (may have uncommitted changes)
        get_main_repo_root() / "docs/plans",  # Main repo (shared)
    ]

    # Dedupe while preserving order
    seen = set()
    unique_locations = []
    for loc in locations:
        resolved = loc.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique_locations.append(loc)

    # Try both formats: 01_name.md and 1_name.md
    for plans_dir in unique_locations:
        if not plans_dir.exists():
            continue
        for pattern in [f"{plan_number:02d}_*.md", f"{plan_number}_*.md"]:
            matches = list(plans_dir.glob(pattern))
            if matches:
                return matches[0]

    return None


def parse_files_affected(content: str) -> list[dict[str, Any]]:
    """Parse the Files Affected section from plan content.

    Expected format:
    ## Files Affected
    - src/world/executor.py (modify)
    - src/world/rate_limiter.py (create)
    - tests/test_rate_limiter.py (create)

    Returns list of dicts with 'path' and 'action' keys.
    """
    files: list[dict[str, Any]] = []

    # Find Files Affected section
    match = re.search(
        r"##\s*Files?\s*Affected\s*\n(.*?)(?=\n##|\n---|\Z)",
        content,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return files

    section = match.group(1)

    # Parse each line
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove leading bullet/dash
        line = re.sub(r"^[-*]\s*", "", line)

        # Extract path and action
        # Format: path (action) or just path
        path_match = re.match(r"([^\s(]+)\s*(?:\((\w+)\))?", line)
        if path_match:
            path = path_match.group(1).strip()
            action = path_match.group(2) or "modify"

            # Skip comments and empty paths
            if path and not path.startswith("#"):
                files.append({
                    "path": path,
                    "action": action.lower(),
                })

    return files


def parse_references_reviewed(content: str) -> list[dict[str, Any]]:
    """Parse the References Reviewed section from plan content.

    Expected format:
    ## References Reviewed
    - src/world/executor.py:45-89 - existing action handling
    - docs/architecture/current/actions.md - action design

    Returns list of dicts with 'path', 'lines', and 'description' keys.
    """
    refs: list[dict[str, Any]] = []

    # Find References Reviewed section
    match = re.search(
        r"##\s*References?\s*Reviewed\s*\n(.*?)(?=\n##|\n---|\Z)",
        content,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return refs

    section = match.group(1)

    # Parse each line
    for line in section.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Remove leading bullet/dash
        line = re.sub(r"^[-*]\s*", "", line)

        # Extract path, optional line range, and description
        # Format: path:start-end - description
        #     or: path - description
        #     or: path
        ref_match = re.match(
            r"([^\s:]+)(?::(\d+)(?:-(\d+))?)?(?:\s*[-–]\s*(.+))?",
            line
        )

        if ref_match:
            path = ref_match.group(1).strip().strip("`")
            start_line = ref_match.group(2)
            end_line = ref_match.group(3)
            description = ref_match.group(4) or ""

            if path and not path.startswith("#"):
                ref_entry: dict[str, Any] = {"path": path}

                if start_line:
                    ref_entry["lines"] = {
                        "start": int(start_line),
                        "end": int(end_line) if end_line else int(start_line),
                    }

                if description:
                    ref_entry["description"] = description.strip()

                refs.append(ref_entry)

    return refs


def parse_research_basis(content: str) -> list[dict[str, Any]]:
    """Parse the Research Basis For This Slice section from plan content.

    Expected format:
    ## Research Basis For This Slice
    - investigations/cross-project/2026-04-04-example.md - compared options
    - research/orchestration/SYNTHESIS.md - reusable recommendation

    Returns list of dicts with 'path', optional 'lines', and optional
    'description' keys. Literal skip statements are ignored.
    """
    refs: list[dict[str, Any]] = []

    match = re.search(
        r"##\s*Research\s*Basis\s*For\s*This\s*Slice\s*\n(.*?)(?=\n##|\n---|\Z)",
        content,
        re.IGNORECASE | re.DOTALL
    )

    if not match:
        return refs

    section = match.group(1)

    for line in section.strip().split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        line = re.sub(r"^[-*]\s*", "", line)

        if line.startswith("No additional research beyond References Reviewed"):
            continue
        if line.startswith("No external research"):
            continue

        ref_match = re.match(
            r"([^\s:]+)(?::(\d+)(?:-(\d+))?)?(?:\s*[-–]\s*(.+))?",
            line
        )

        if ref_match:
            path = ref_match.group(1).strip().strip("`")
            start_line = ref_match.group(2)
            end_line = ref_match.group(3)
            description = ref_match.group(4) or ""

            if path and not path.startswith("#"):
                ref_entry: dict[str, Any] = {"path": path}

                if start_line:
                    ref_entry["lines"] = {
                        "start": int(start_line),
                        "end": int(end_line) if end_line else int(start_line),
                    }

                if description:
                    ref_entry["description"] = description.strip()

                refs.append(ref_entry)

    return refs


def _extract_metadata_value(content: str, field_name: str) -> str | None:
    """Extract one bolded plan-header metadata field value."""
    match = re.search(
        rf"^\*\*{re.escape(field_name)}:\*\*\s*(.+?)\s*$",
        content,
        re.IGNORECASE | re.MULTILINE,
    )
    if not match:
        return None
    value = re.sub(r"<!--.*?-->", "", match.group(1)).strip()
    return value or None


def parse_research_citations(content: str) -> list[str]:
    """Parse the optional research_citations header field as a list of strings."""
    raw_value = _extract_metadata_value(content, "research_citations")
    if raw_value is None:
        return []

    try:
        loaded = yaml.safe_load(raw_value)
    except yaml.YAMLError:
        return []

    if loaded in (None, ""):
        return []
    if not isinstance(loaded, list):
        return []

    citations: list[str] = []
    for item in loaded:
        value = str(item).strip()
        if value:
            citations.append(value)
    return citations


def parse_steps(content: str) -> list[dict[str, Any]]:
    """Parse steps from a plan's Steps, Plan, or similar section.

    Handles multiple formats:
    - Pipe tables: | 1 | Do X | Done |
    - Numbered lists: 1. Do X
    - Bullet checkboxes: - [x] Do X
    - Heading-based steps: ### Step 1: Do X

    Returns list of dicts with 'number', 'description', and 'status' keys.
    """
    steps: list[dict[str, Any]] = []

    # Try multiple section headings
    section = ""
    for heading in ["Steps", "Plan", "Implementation Steps", "Task Pack"]:
        match = re.search(
            rf"##\s*{re.escape(heading)}\s*\n(.*?)(?=\n##\s[^#]|\Z)",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            section = match.group(1).strip()
            break

    if not section:
        # Fallback: look for any numbered list in the Plan section
        match = re.search(
            r"##\s*Plan\b.*?\n(.*?)(?=\n##\s[^#]|\Z)",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            section = match.group(1).strip()

    if not section:
        return steps

    step_num = 0

    for line in section.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        # Format 1: Pipe table row | N | Description | Status |
        table_match = re.match(
            r"\|\s*(\d+)\s*\|\s*(.+?)\s*\|\s*(.+?)\s*\|",
            line,
        )
        if table_match:
            steps.append({
                "number": int(table_match.group(1)),
                "description": table_match.group(2).strip(),
                "status": _normalize_status(table_match.group(3).strip()),
            })
            continue

        # Skip table headers/separators
        if re.match(r"^\|[-\s|:]+\|$", line):
            continue
        if re.match(r"^\|\s*(Step|#|Number)", line, re.IGNORECASE):
            continue

        # Format 2: Numbered list: 1. Do X or 1) Do X
        num_match = re.match(r"(\d+)[.)]\s+(.+)", line)
        if num_match:
            step_num = int(num_match.group(1))
            desc = num_match.group(2).strip()
            status = "not_started"
            # Check for inline status markers
            if re.search(r"\(done\)|\(complete\)|✅|✓", desc, re.IGNORECASE):
                status = "done"
            elif re.search(r"\(in.?progress\)|🚧", desc, re.IGNORECASE):
                status = "in_progress"
            steps.append({
                "number": step_num,
                "description": re.sub(r"\s*\((?:done|complete|in.?progress)\)\s*", "", desc, flags=re.IGNORECASE).strip(),
                "status": status,
            })
            continue

        # Format 3: Checkbox list: - [x] Do X or - [ ] Do X
        check_match = re.match(r"[-*]\s+\[([ xX])\]\s+(.+)", line)
        if check_match:
            step_num += 1
            checked = check_match.group(1).lower() == "x"
            steps.append({
                "number": step_num,
                "description": check_match.group(2).strip(),
                "status": "done" if checked else "not_started",
            })
            continue

        # Format 4: ### Step N: Description
        heading_match = re.match(r"###\s*Step\s+(\d+)\s*[:.]\s*(.+)", line, re.IGNORECASE)
        if heading_match:
            steps.append({
                "number": int(heading_match.group(1)),
                "description": heading_match.group(2).strip(),
                "status": "not_started",
            })
            continue

    return steps


def _normalize_status(raw: str) -> str:
    """Normalize status strings to canonical values."""
    lower = raw.lower().strip()
    if any(w in lower for w in ["done", "complete", "✅", "verified"]):
        return "done"
    if any(w in lower for w in ["progress", "started", "🚧", "wip"]):
        return "in_progress"
    if any(w in lower for w in ["blocked", "⏸"]):
        return "blocked"
    if any(w in lower for w in ["not started", "planned", "📋", "pending"]):
        return "not_started"
    return raw


def parse_acceptance_criteria(content: str) -> list[dict[str, Any]]:
    """Parse acceptance criteria from a plan.

    Looks for checkbox lists in Acceptance Criteria or Verification sections.
    Returns list of dicts with 'description' and 'met' keys.
    """
    criteria: list[dict[str, Any]] = []

    for heading in ["Acceptance Criteria", "Verification", "Success Criteria"]:
        match = re.search(
            rf"##\s*{re.escape(heading)}\s*\n(.*?)(?=\n##\s[^#]|\Z)",
            content,
            re.IGNORECASE | re.DOTALL,
        )
        if match:
            section = match.group(1).strip()
            for line in section.split("\n"):
                line = line.strip()
                check_match = re.match(r"[-*]\s+\[([ xX])\]\s+(.+)", line)
                if check_match:
                    criteria.append({
                        "description": check_match.group(2).strip(),
                        "met": check_match.group(1).lower() == "x",
                    })
            if criteria:
                break

    return criteria


def check_file_in_scope(file_path: str, files_affected: list[dict[str, Any]]) -> tuple[bool, str]:
    """Check if a file is in the plan's declared scope.

    Returns (in_scope, reason).
    """
    # Normalize the file path
    normalized = str(Path(file_path))

    for entry in files_affected:
        declared_path = str(Path(entry["path"]))

        # Exact match
        if normalized == declared_path:
            return True, f"Declared as ({entry['action']})"

        # Check if declared path is a directory prefix
        if normalized.startswith(declared_path + "/"):
            return True, f"Under declared directory {declared_path}"

    return False, "Not in Files Affected"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse plan files for enforcement hooks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--plan", "-p",
        type=int,
        help="Plan number (default: detect from branch/claims)"
    )
    parser.add_argument(
        "--files-affected", "-f",
        action="store_true",
        help="Output the Files Affected section"
    )
    parser.add_argument(
        "--references-reviewed", "-r",
        action="store_true",
        help="Output the References Reviewed section"
    )
    parser.add_argument(
        "--research-basis",
        action="store_true",
        help="Output the Research Basis For This Slice section"
    )
    parser.add_argument(
        "--research-citations",
        action="store_true",
        help="Output the research_citations header field"
    )
    parser.add_argument(
        "--steps", "-s",
        action="store_true",
        help="Output the Steps/Plan section (numbered, checkbox, or table)"
    )
    parser.add_argument(
        "--acceptance-criteria", "-a",
        action="store_true",
        help="Output acceptance criteria checkboxes"
    )
    parser.add_argument(
        "--check-file", "-c",
        type=str,
        help="Check if a file is in the plan's scope"
    )
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output as JSON (for hooks)"
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Suppress informational messages"
    )

    args = parser.parse_args()

    # Determine plan number
    plan_number = args.plan or get_active_plan_number()

    if not plan_number:
        if not args.quiet:
            print("Could not determine active plan.", file=sys.stderr)
            print("Use --plan N or work from a plan-NN-xxx branch.", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": "no_active_plan"}))
        return 1

    # Find plan file
    plan_file = find_plan_file(plan_number)

    if not plan_file or not plan_file.exists():
        if not args.quiet:
            print(f"Plan file not found for plan #{plan_number}", file=sys.stderr)
        if args.json:
            print(json.dumps({"error": "plan_not_found", "plan": plan_number}))
        return 1

    # Read plan content
    content = plan_file.read_text()

    # Handle --check-file
    if args.check_file:
        files_affected = parse_files_affected(content)
        in_scope, reason = check_file_in_scope(args.check_file, files_affected)

        if args.json:
            print(json.dumps({
                "file": args.check_file,
                "in_scope": in_scope,
                "reason": reason,
                "plan": plan_number,
            }))
        else:
            status = "✓ IN SCOPE" if in_scope else "✗ NOT IN SCOPE"
            print(f"{status}: {args.check_file}")
            print(f"  Reason: {reason}")
            print(f"  Plan: #{plan_number}")

        return 0 if in_scope else 2

    # Handle --steps
    if args.steps:
        steps = parse_steps(content)
        if args.json:
            print(json.dumps({"plan": plan_number, "steps": steps}, indent=2))
        else:
            if not steps:
                print(f"Plan #{plan_number}: No parseable steps found")
                return 1
            print(f"Plan #{plan_number} - Steps ({len(steps)} found):")
            for step in steps:
                status_marker = {"done": "✓", "in_progress": "→", "blocked": "⏸", "not_started": " "}.get(step["status"], "?")
                print(f"  [{status_marker}] {step['number']}. {step['description']}")
        return 0

    # Handle --acceptance-criteria
    if args.acceptance_criteria:
        criteria = parse_acceptance_criteria(content)
        if args.json:
            print(json.dumps({"plan": plan_number, "acceptance_criteria": criteria}, indent=2))
        else:
            if not criteria:
                print(f"Plan #{plan_number}: No acceptance criteria found")
                return 1
            met = sum(1 for c in criteria if c["met"])
            print(f"Plan #{plan_number} - Acceptance Criteria ({met}/{len(criteria)} met):")
            for c in criteria:
                marker = "x" if c["met"] else " "
                print(f"  [{marker}] {c['description']}")
        return 0

    # Handle --files-affected
    if args.files_affected:
        files_affected = parse_files_affected(content)

        if args.json:
            print(json.dumps({
                "plan": plan_number,
                "files_affected": files_affected,
            }))
        else:
            if not files_affected:
                print(f"Plan #{plan_number}: No Files Affected section found")
                return 1

            print(f"Plan #{plan_number} - Files Affected:")
            for entry in files_affected:
                print(f"  {entry['path']} ({entry['action']})")

        return 0

    # Handle --references-reviewed
    if args.references_reviewed:
        refs = parse_references_reviewed(content)

        if args.json:
            print(json.dumps({
                "plan": plan_number,
                "references_reviewed": refs,
            }))
        else:
            if not refs:
                print(f"Plan #{plan_number}: No References Reviewed section found")
                return 1

            print(f"Plan #{plan_number} - References Reviewed:")
            for ref in refs:
                lines = ref.get("lines", {})
                line_str = f":{lines['start']}-{lines['end']}" if lines else ""
                desc = f" - {ref['description']}" if ref.get("description") else ""
                print(f"  {ref['path']}{line_str}{desc}")

        return 0

    # Handle --research-basis
    if args.research_basis:
        refs = parse_research_basis(content)

        if args.json:
            print(json.dumps({
                "plan": plan_number,
                "research_basis": refs,
            }))
        else:
            if not refs:
                print(f"Plan #{plan_number}: No Research Basis For This Slice section found")
                return 1

            print(f"Plan #{plan_number} - Research Basis For This Slice:")
            for ref in refs:
                lines = ref.get("lines", {})
                line_str = f":{lines['start']}-{lines['end']}" if lines else ""
                desc = f" - {ref['description']}" if ref.get("description") else ""
                print(f"  {ref['path']}{line_str}{desc}")

        return 0

    # Handle --research-citations
    if args.research_citations:
        citations = parse_research_citations(content)

        if args.json:
            print(json.dumps({
                "plan": plan_number,
                "research_citations": citations,
            }))
        else:
            if not citations:
                print(f"Plan #{plan_number}: No research_citations declared")
                return 1

            print(f"Plan #{plan_number} - research_citations:")
            for citation in citations:
                print(f"  {citation}")

        return 0

    # Default: show both
    files_affected = parse_files_affected(content)
    refs = parse_references_reviewed(content)
    research = parse_research_basis(content)
    citations = parse_research_citations(content)

    if args.json:
        print(json.dumps({
            "plan": plan_number,
            "plan_file": str(plan_file),
            "files_affected": files_affected,
            "references_reviewed": refs,
            "research_basis": research,
            "research_citations": citations,
        }, indent=2))
    else:
        print(f"Plan #{plan_number}: {plan_file.name}")
        print()

        print("Files Affected:")
        if files_affected:
            for entry in files_affected:
                print(f"  {entry['path']} ({entry['action']})")
        else:
            print("  (none declared)")

        print()
        print("Research Basis For This Slice:")
        if research:
            for ref in research:
                lines = ref.get("lines", {})
                line_str = f":{lines['start']}-{lines['end']}" if lines else ""
                desc = f" - {ref['description']}" if ref.get("description") else ""
                print(f"  {ref['path']}{line_str}{desc}")
        else:
            print("  (none declared)")

        print()
        print("research_citations:")
        if citations:
            for citation in citations:
                print(f"  {citation}")
        else:
            print("  (none declared)")

        print()
        print("References Reviewed:")
        if refs:
            for ref in refs:
                lines = ref.get("lines", {})
                line_str = f":{lines['start']}-{lines['end']}" if lines else ""
                desc = f" - {ref['description']}" if ref.get("description") else ""
                print(f"  {ref['path']}{line_str}{desc}")
        else:
            print("  (none declared)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
