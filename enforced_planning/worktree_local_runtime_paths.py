"""Identify ignored runtime paths that are physically isolated by worktree."""

from __future__ import annotations

import posixpath
import subprocess
from pathlib import Path

WORKTREE_LOCAL_RUNTIME_PATHS = frozenset({".company-planning/active-execution.json"})


def _normalize(path: str) -> str:
    normalized = posixpath.normpath(path.replace("\\", "/").strip())
    return "." if normalized in {"", "."} else normalized.removeprefix("./")


def _is_standard_lane_path(path: str | None, *, repo_root: Path) -> bool:
    if not path:
        return False
    candidate = Path(path).expanduser().resolve(strict=False)
    standard = (repo_root / "worktrees").resolve(strict=False)
    legacy = (repo_root.parent / f"{repo_root.name}_worktrees").resolve(strict=False)
    return candidate != repo_root and (
        candidate.is_relative_to(standard) or candidate.is_relative_to(legacy)
    )


def _git_says_worktree_local(repo_root: Path, path: str) -> bool:
    tracked = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode == 0:
        return False
    ignored = subprocess.run(
        ["git", "check-ignore", "--quiet", "--no-index", "--", path],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    return ignored.returncode == 0


def is_isolated_runtime_overlap(
    *,
    left_path: str,
    right_path: str,
    left_worktree_path: str | None,
    right_worktree_path: str | None,
    left_repo_root: str | None,
    right_repo_root: str | None,
) -> bool:
    """Return whether an apparent write overlap is isolated runtime state.

    This is deliberately narrower than a generic ignored-path exception.  It
    applies only to the declared Company Planning execution cursor, only when
    both claims resolve to the same canonical repository, only across distinct
    sanctioned lane locations, and only while Git confirms the path is ignored
    and untracked.  A tracked cursor or a parent-directory claim remains shared
    repository state and therefore conflicts normally.
    """

    left = _normalize(left_path)
    right = _normalize(right_path)
    if left != right or left not in WORKTREE_LOCAL_RUNTIME_PATHS:
        return False
    if not left_repo_root or not right_repo_root:
        return False
    left_root = Path(left_repo_root).expanduser().resolve(strict=False)
    right_root = Path(right_repo_root).expanduser().resolve(strict=False)
    if left_root != right_root or not (left_root / ".git").exists():
        return False
    if not _is_standard_lane_path(left_worktree_path, repo_root=left_root):
        return False
    if not _is_standard_lane_path(right_worktree_path, repo_root=left_root):
        return False
    if Path(left_worktree_path).expanduser().resolve(strict=False) == Path(
        right_worktree_path
    ).expanduser().resolve(strict=False):
        return False
    return _git_says_worktree_local(left_root, left)


__all__ = ["WORKTREE_LOCAL_RUNTIME_PATHS", "is_isolated_runtime_overlap"]
