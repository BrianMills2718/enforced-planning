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


# Issue #610: a linked worktree outside <repo>/worktrees must resolve through
# its .git gitfile, not to itself.


def test_resolves_real_external_linked_worktree_through_gitfile(tmp_path: Path) -> None:
    repo = tmp_path / "code" / "sample"
    _init_repo(repo)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "--allow-empty", "-m", "init"],
        check=True,
        capture_output=True,
        text=True,
        env={
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
            "PATH": "/usr/bin:/bin",
        },
    )
    external = tmp_path / "elsewhere" / "lane"
    subprocess.run(
        ["git", "-C", str(repo), "worktree", "add", "-b", "lane", str(external)],
        check=True,
        capture_output=True,
        text=True,
    )

    assert (external / ".git").is_file()
    assert resolve_canonical_repo_root(external) == repo.resolve()


def test_resolves_absolute_gitdir_without_commondir(tmp_path: Path) -> None:
    canonical = tmp_path / "code" / "repo"
    admin = canonical / ".git" / "worktrees" / "architecture-lane"
    admin.mkdir(parents=True)
    worktree = tmp_path / "projects" / "worktrees" / "architecture-lane"
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {admin}\n", encoding="utf-8")

    assert resolve_canonical_repo_root(worktree) == canonical.resolve()


def test_resolves_relative_gitdir(tmp_path: Path) -> None:
    canonical = tmp_path / "repo"
    admin = canonical / ".git" / "worktrees" / "lane"
    admin.mkdir(parents=True)
    worktree = canonical / "external" / "lane"
    worktree.mkdir(parents=True)
    relative = Path("../..") / ".git" / "worktrees" / "lane"
    (worktree / ".git").write_text(f"gitdir: {relative}\n", encoding="utf-8")

    assert resolve_canonical_repo_root(worktree) == canonical.resolve()


def test_keeps_main_checkout_with_git_directory(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo)

    assert resolve_canonical_repo_root(repo) == repo.resolve()


def test_submodule_gitfile_is_not_resolved_to_superproject(tmp_path: Path) -> None:
    superproject = tmp_path / "super"
    modules_dir = superproject / ".git" / "modules" / "child"
    modules_dir.mkdir(parents=True)
    child = superproject / "child"
    child.mkdir()
    (child / ".git").write_text("gitdir: ../.git/modules/child\n", encoding="utf-8")

    assert resolve_canonical_repo_root(child) == child.resolve()


def test_gitfile_pointing_at_missing_common_dir_is_ignored(tmp_path: Path) -> None:
    worktree = tmp_path / "lane"
    worktree.mkdir()
    (worktree / ".git").write_text(
        f"gitdir: {tmp_path / 'gone' / '.git' / 'worktrees' / 'lane'}\n",
        encoding="utf-8",
    )

    assert resolve_canonical_repo_root(worktree) == worktree.resolve()
