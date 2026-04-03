"""Resolve shared workspace and canonical repo roots for worktree checkouts.

These helpers keep meta-process tools truthful when they run from a
``*_worktrees/<branch>`` checkout. The active worktree remains the write target,
but canonical source files may still live in the main repo root when they are
intentionally untracked in git, such as ``project-meta/research_texts``.
"""

from __future__ import annotations

from pathlib import Path


def detect_workspace_root(project_root: Path) -> Path:
    """Resolve the shared workspace root from main or worktree checkouts."""
    if project_root.parent.name.endswith("_worktrees"):
        return project_root.parent.parent
    return project_root.parent


def resolve_canonical_repo_root(repo_root: Path) -> Path:
    """Return the canonical repo root for a main checkout or worktree clone."""
    resolved_repo_root = repo_root.resolve()
    parent = resolved_repo_root.parent
    if not parent.name.endswith("_worktrees"):
        return resolved_repo_root

    workspace_root = parent.parent
    canonical_name = parent.name.removesuffix("_worktrees")
    canonical_repo_root = (workspace_root / canonical_name).resolve()
    if canonical_repo_root.exists():
        return canonical_repo_root
    return resolved_repo_root
