#!/usr/bin/env python3
"""Pre-commit validator for locked couplings in relationships.yaml V2.

A "locked" coupling declares: if source file X changes, coupled doc Y
must also be updated in the same commit. This script checks that invariant
at commit time.

Algorithm:
    1. Load relationships.yaml (V2) from the repo root.
    2. Get staged files from `git diff --cached --name-only`.
    3. For each `type: locked` coupling:
       a. Expand glob patterns in `sources` and `docs`.
       b. If any staged file matches a source: require at least one staged
          file to match a doc from that coupling.
       c. Violations are reported; in --strict mode the script exits 1.

Exit codes:
    0 — No violations (or not a V2 relationships.yaml, or no staged matches).
    1 — At least one locked coupling violated (--strict only).
    2 — Usage / config error.

Usage:
    python check_locked_couplings.py
    python check_locked_couplings.py --strict
    python check_locked_couplings.py --repo /path/to/repo --strict
"""

from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed — pip install pyyaml", file=sys.stderr)
    sys.exit(2)


RELATIONSHIPS_PATHS = [
    "scripts/relationships.yaml",
    "relationships.yaml",
]


def _find_relationships_yaml(repo_root: Path) -> Path | None:
    """Find the relationships.yaml file in a repo."""
    for rel in RELATIONSHIPS_PATHS:
        p = repo_root / rel
        if p.exists():
            return p
    return None


def _load_relationships(path: Path) -> dict[str, Any] | None:
    """Load and return relationships.yaml, or None if not V2."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as e:
        print(f"WARNING: Could not parse {path}: {e}", file=sys.stderr)
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != 2:
        return None  # V1 — skip
    return data


def _staged_files(repo_root: Path) -> list[str]:
    """Return list of staged file paths (relative to repo root)."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return [f.strip() for f in result.stdout.splitlines() if f.strip()]


def _matches_pattern(file_path: str, patterns: list[str]) -> bool:
    """Return True if file_path matches any glob pattern in patterns."""
    for pattern in patterns:
        if fnmatch.fnmatch(file_path, pattern):
            return True
        # Also try without leading repo path prefix
        # Pattern "llm_client/core/*.py" should match "llm_client/core/client.py"
        if fnmatch.fnmatchcase(file_path, pattern):
            return True
    return False


def check_locked_couplings(repo_root: Path) -> list[dict[str, Any]]:
    """Run the locked coupling pre-commit check.

    Returns a list of violation dicts:
        {coupling_description, source_matched, docs_required, staged_files}
    """
    rel_path = _find_relationships_yaml(repo_root)
    if rel_path is None:
        return []  # No relationships.yaml — nothing to check

    data = _load_relationships(rel_path)
    if data is None:
        return []  # V1 or parse error — skip

    couplings = data.get("couplings", [])
    staged = _staged_files(repo_root)
    if not staged:
        return []

    violations = []
    for coupling in couplings:
        if coupling.get("type") != "locked":
            continue
        sources = coupling.get("sources", [])
        docs = coupling.get("docs", [])
        description = coupling.get("description", "unlabeled coupling")

        # Find which staged files match the coupling's sources
        matched_sources = [f for f in staged if _matches_pattern(f, sources)]
        if not matched_sources:
            continue  # None of the staged files touch this coupling

        # Check if any coupled doc is also staged
        matched_docs = [f for f in staged if _matches_pattern(f, docs)]
        if matched_docs:
            continue  # At least one doc updated — coupling satisfied

        violations.append({
            "coupling_description": description,
            "sources_matched": matched_sources,
            "docs_required": docs,
            "staged_files": staged,
        })

    return violations


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(
        description="Validate locked couplings before commit"
    )
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="Repo root (default: git rev-parse --show-toplevel)",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 on violations (default: warn only)",
    )
    args = parser.parse_args()

    if args.repo:
        repo_root = args.repo.resolve()
    else:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print("ERROR: Not in a git repo", file=sys.stderr)
            return 2
        repo_root = Path(result.stdout.strip())

    violations = check_locked_couplings(repo_root)

    if not violations:
        return 0

    print(f"\n{'ERROR' if args.strict else 'WARNING'}: Locked coupling violations detected!\n")
    for v in violations:
        print(f"  Coupling: {v['coupling_description']}")
        print(f"    Staged source(s): {', '.join(v['sources_matched'])}")
        print("    Required doc(s) not staged:")
        for doc in v["docs_required"]:
            print(f"      - {doc}")
        print()
    print("  Commit blocked by locked coupling. Update the coupled docs and re-stage them.")
    print("  To bypass (not recommended): git commit --no-verify\n")

    return 1 if args.strict else 0


if __name__ == "__main__":
    raise SystemExit(main())
