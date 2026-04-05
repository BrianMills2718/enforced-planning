#!/usr/bin/env python3
"""CLI entrypoint for enforced_planning.merge_pr."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enforced_planning.merge_pr as UPSTREAM_MODULE


run_cmd = UPSTREAM_MODULE.run_cmd
get_pr_branch = UPSTREAM_MODULE.get_pr_branch
find_existing_script = UPSTREAM_MODULE.find_existing_script
find_worktree_for_branch = UPSTREAM_MODULE.find_worktree_for_branch
release_claim_for_branch = UPSTREAM_MODULE.release_claim_for_branch
check_pr_mergeable = UPSTREAM_MODULE.check_pr_mergeable
merge_pr = UPSTREAM_MODULE.merge_pr
main = UPSTREAM_MODULE.main


def _apply_overrides() -> dict[str, object]:
    """Apply wrapper helper overrides to the package module for one call."""
    original = {
        "run_cmd": UPSTREAM_MODULE.run_cmd,
        "find_existing_script": UPSTREAM_MODULE.find_existing_script,
        "find_worktree_for_branch": UPSTREAM_MODULE.find_worktree_for_branch,
        "release_claim_for_branch": UPSTREAM_MODULE.release_claim_for_branch,
    }
    UPSTREAM_MODULE.run_cmd = run_cmd
    UPSTREAM_MODULE.find_existing_script = find_existing_script
    UPSTREAM_MODULE.find_worktree_for_branch = find_worktree_for_branch
    UPSTREAM_MODULE.release_claim_for_branch = release_claim_for_branch
    return original


def _restore_globals(original: dict[str, object]) -> None:
    """Restore the package module helper bindings after one proxy call."""
    for name, value in original.items():
        setattr(UPSTREAM_MODULE, name, value)


def cleanup_worktree(branch: str) -> bool:
    """Clean up one local worktree using the wrapper's current helper bindings."""
    original = _apply_overrides()
    try:
        return UPSTREAM_MODULE.cleanup_worktree(branch)
    finally:
        _restore_globals(original)


if __name__ == "__main__":
    raise SystemExit(main())
