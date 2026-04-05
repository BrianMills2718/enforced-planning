#!/usr/bin/env python3
"""CLI entrypoint for enforced_planning.create_worktree."""

from __future__ import annotations

import sys
from pathlib import Path

if str(Path(__file__).resolve().parents[2]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import enforced_planning.create_worktree as UPSTREAM_MODULE


StatusEntry = UPSTREAM_MODULE.StatusEntry
WorktreeStatusSummary = UPSTREAM_MODULE.WorktreeStatusSummary
WorktreeCreationResult = UPSTREAM_MODULE.WorktreeCreationResult
parse_args = UPSTREAM_MODULE.parse_args
run_git = UPSTREAM_MODULE.run_git
branch_exists = UPSTREAM_MODULE.branch_exists
resolve_main_repo_root = UPSTREAM_MODULE.resolve_main_repo_root
get_default_worktree_dir = UPSTREAM_MODULE.get_default_worktree_dir
parse_status_porcelain = UPSTREAM_MODULE.parse_status_porcelain
inspect_worktree_state = UPSTREAM_MODULE.inspect_worktree_state
classify_summary = UPSTREAM_MODULE.classify_summary
cleanup_failed_worktree = UPSTREAM_MODULE.cleanup_failed_worktree
ensure_safe_target_path = UPSTREAM_MODULE.ensure_safe_target_path
verify_scoped_write_claim = UPSTREAM_MODULE.verify_scoped_write_claim
main = UPSTREAM_MODULE.main


def _apply_overrides() -> dict[str, object]:
    """Apply wrapper helper overrides to the package module for one call."""
    original = {
        "run_git": UPSTREAM_MODULE.run_git,
        "branch_exists": UPSTREAM_MODULE.branch_exists,
        "parse_status_porcelain": UPSTREAM_MODULE.parse_status_porcelain,
        "inspect_worktree_state": UPSTREAM_MODULE.inspect_worktree_state,
        "classify_summary": UPSTREAM_MODULE.classify_summary,
        "cleanup_failed_worktree": UPSTREAM_MODULE.cleanup_failed_worktree,
        "ensure_safe_target_path": UPSTREAM_MODULE.ensure_safe_target_path,
        "verify_scoped_write_claim": UPSTREAM_MODULE.verify_scoped_write_claim,
    }
    UPSTREAM_MODULE.run_git = run_git
    UPSTREAM_MODULE.branch_exists = branch_exists
    UPSTREAM_MODULE.parse_status_porcelain = parse_status_porcelain
    UPSTREAM_MODULE.inspect_worktree_state = inspect_worktree_state
    UPSTREAM_MODULE.classify_summary = classify_summary
    UPSTREAM_MODULE.cleanup_failed_worktree = cleanup_failed_worktree
    UPSTREAM_MODULE.ensure_safe_target_path = ensure_safe_target_path
    UPSTREAM_MODULE.verify_scoped_write_claim = verify_scoped_write_claim
    return original


def _restore_globals(original: dict[str, object]) -> None:
    """Restore the package module helper bindings after one proxy call."""
    for name, value in original.items():
        setattr(UPSTREAM_MODULE, name, value)


def create_worktree(**kwargs):
    """Create one worktree using the wrapper's current helper bindings."""
    original = _apply_overrides()
    try:
        return UPSTREAM_MODULE.create_worktree(**kwargs)
    finally:
        _restore_globals(original)


if __name__ == "__main__":
    raise SystemExit(main())
