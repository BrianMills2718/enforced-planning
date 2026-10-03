"""Tests for canonical repository and workspace path resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

from enforced_planning.worktree_paths import resolve_canonical_repo_root


def _init_repo(path: Path) -> None:
    subprocess.run(
        ["git", "init", "-b", "main", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def test_resolves_missing_nested_in_repo_worktree_path(tmp_path: Path) -> None:
    repo = tmp_path / "sample"
    _init_repo(repo)
    missing = repo / "worktrees" / "feat" / "nested-branch"

    assert not missing.exists()
    assert resolve_canonical_repo_root(missing) == repo.resolve()


def test_resolves_missing_nested_legacy_sibling_worktree_path(tmp_path: Path) -> None:
    repo = tmp_path / "sample"
    _init_repo(repo)
    missing = tmp_path / "sample_worktrees" / "feat" / "nested-branch"

    assert not missing.exists()
    assert resolve_canonical_repo_root(missing) == repo.resolve()


def test_does_not_rewrite_unrelated_missing_path_with_worktrees_segment(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "not-a-repo" / "worktrees" / "feat" / "branch"

    assert resolve_canonical_repo_root(missing) == missing.resolve()


def test_resolves_claude_harness_worktree_to_owning_repo(tmp_path: Path) -> None:
    repo = tmp_path / "sample"
    _init_repo(repo)
    harness_worktree = repo / ".claude" / "worktrees" / "agent-abc123"
    harness_worktree.mkdir(parents=True)

    assert resolve_canonical_repo_root(harness_worktree) == repo.resolve()


def test_does_not_rewrite_claude_dir_without_owning_repo(tmp_path: Path) -> None:
    orphan = tmp_path / ".claude" / "worktrees" / "agent-abc123"
    orphan.mkdir(parents=True)

    assert resolve_canonical_repo_root(orphan) == orphan.resolve()
