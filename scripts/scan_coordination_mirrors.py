#!/usr/bin/env python3
"""Scan repos for copied worktree-coordination docs versus explicit mirror stubs.

This scanner is intentionally narrow. It only looks at the legacy repo-local
`docs/meta-patterns/worktree-coordination/` trees that historically drifted
from enforced-planning. The goal is to classify each repo as:

- canonical source (`enforced-planning`)
- explicit mirror stubs
- copied/custom local coordination docs
- no local coordination tree
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


PROJECTS_ROOT = Path.home() / "projects"
COORDINATION_DIR = Path("docs/meta-patterns/worktree-coordination")
MIRROR_DOCS: tuple[str, ...] = (
    "README.md",
    "18_claim-system.md",
    "19_worktree-enforcement.md",
    "20_rebase-workflow.md",
    "21_pr-coordination.md",
    "26_ownership-respect.md",
)
STUB_MARKER = "This repo-local file is an explicit mirror stub."
OPERATOR_GUIDE_MARKER = "WORKTREE_COORDINATION_OPERATOR_GUIDE.md"
CANONICAL_PATTERN_MARKER = "enforced-planning/patterns/worktree-coordination"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments for coordination mirror scanning."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-root",
        default=str(PROJECTS_ROOT),
        help="Workspace root containing repo directories (default: ~/projects)",
    )
    parser.add_argument(
        "--repo-root",
        action="append",
        default=[],
        help="Specific repo root(s) to scan. Repeat as needed.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human output.",
    )
    parser.add_argument(
        "--fail-on-copied",
        action="store_true",
        help="Exit non-zero when any repo still has copied/custom local coordination docs.",
    )
    return parser.parse_args()


def _is_repo_root(path: Path) -> bool:
    return (path / ".git").exists()


def _is_stub(text: str) -> bool:
    return (
        STUB_MARKER in text
        and OPERATOR_GUIDE_MARKER in text
        and CANONICAL_PATTERN_MARKER in text
    )


def _scan_repo(repo_root: Path) -> dict[str, Any]:
    coordination_root = repo_root / COORDINATION_DIR
    result: dict[str, Any] = {
        "repo_root": str(repo_root),
        "repo_name": repo_root.name,
        "coordination_dir": str(coordination_root),
        "status": "absent",
        "files": {},
    }

    if repo_root.name == "enforced-planning":
        result["status"] = "canonical-source"
        return result

    if not coordination_root.is_dir():
        return result

    stub_count = 0
    copied_count = 0
    present_count = 0
    for relpath in MIRROR_DOCS:
        path = coordination_root / relpath
        if not path.exists():
            result["files"][relpath] = {"present": False, "classification": "missing"}
            continue
        present_count += 1
        text = path.read_text(encoding="utf-8")
        classification = "mirror-stub" if _is_stub(text) else "copied-or-custom"
        if classification == "mirror-stub":
            stub_count += 1
        else:
            copied_count += 1
        result["files"][relpath] = {"present": True, "classification": classification}

    if present_count == 0:
        result["status"] = "empty-tree"
    elif copied_count == 0 and stub_count == present_count:
        result["status"] = "mirror-stub"
    else:
        result["status"] = "copied-or-custom"

    result["stub_count"] = stub_count
    result["copied_count"] = copied_count
    result["present_count"] = present_count
    return result


def _candidate_repos(workspace_root: Path, explicit_roots: list[str]) -> list[Path]:
    if explicit_roots:
        return [Path(item).expanduser().resolve() for item in explicit_roots]
    repos = [
        child.resolve()
        for child in sorted(workspace_root.iterdir())
        if child.is_dir() and _is_repo_root(child)
    ]
    return repos


def scan_workspace(workspace_root: Path, explicit_roots: list[str]) -> dict[str, Any]:
    """Return a deterministic workspace-level mirror scan report."""
    repos = _candidate_repos(workspace_root, explicit_roots)
    repo_results = [_scan_repo(repo_root) for repo_root in repos]
    copied_repos = [
        result["repo_name"]
        for result in repo_results
        if result["status"] == "copied-or-custom"
    ]
    return {
        "workspace_root": str(workspace_root),
        "repo_count": len(repo_results),
        "copied_or_custom_repo_count": len(copied_repos),
        "copied_or_custom_repos": copied_repos,
        "repos": repo_results,
    }


def _print_human(report: dict[str, Any]) -> None:
    print(f"Workspace: {report['workspace_root']}")
    print(f"Repos scanned: {report['repo_count']}")
    if report["copied_or_custom_repo_count"] == 0:
        print("No copied coordination trees detected.")
        return
    print("Repos with copied/custom coordination docs:")
    for repo_name in report["copied_or_custom_repos"]:
        print(f"- {repo_name}")


def main() -> int:
    """CLI entry point for coordination mirror scanning."""
    args = parse_args()
    workspace_root = Path(args.workspace_root).expanduser().resolve()
    if not workspace_root.exists():
        print(f"Workspace root not found: {workspace_root}", file=sys.stderr)
        return 2

    report = scan_workspace(workspace_root, args.repo_root)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_human(report)

    if args.fail_on_copied and report["copied_or_custom_repo_count"] > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
