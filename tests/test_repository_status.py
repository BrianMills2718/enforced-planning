"""Tests for read-only repository authority freshness reporting."""

from __future__ import annotations

import subprocess
from pathlib import Path

from enforced_planning import repository_status


def _git(cwd: Path, *args: str) -> str:
    """Run one real Git command and return stripped stdout."""

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _repo_with_remote(tmp_path: Path) -> tuple[Path, Path]:
    """Create one working repository with a reachable bare origin."""

    remote = tmp_path / "remote.git"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", str(remote))
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "tests@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("one\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-u", "origin", "main")
    _git(remote, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(repo, "remote", "set-head", "origin", "-a")
    return repo, remote


def _advance_remote(tmp_path: Path, remote: Path, text: str = "two\n") -> str:
    """Advance remote main from an independent writer clone."""

    writer = tmp_path / "writer"
    _git(tmp_path, "clone", str(remote), str(writer))
    _git(writer, "config", "user.email", "writer@example.com")
    _git(writer, "config", "user.name", "Writer")
    (writer / "README.md").write_text(text, encoding="utf-8")
    _git(writer, "add", "README.md")
    _git(writer, "commit", "-m", "advance remote")
    _git(writer, "push", "origin", "main")
    return _git(writer, "rev-parse", "HEAD")


def test_current_default_branch_reports_exact_remote_identity(tmp_path: Path) -> None:
    """A fetched current default branch should be safe current authority."""

    repo, _remote = _repo_with_remote(tmp_path)

    result = repository_status.inspect_repository(repo, fetch_remote=True)

    assert result.status == "current"
    assert result.exit_code == 0
    assert result.current_branch == "main"
    assert result.default_branch == "main"
    assert result.local_default_commit == result.remote_default_commit
    assert result.behind_count == 0
    assert result.fetch_succeeded is True


def test_stale_default_branch_fails_without_mutating_local_state(tmp_path: Path) -> None:
    """A behind default branch must fail after fetch without changing local bytes or HEAD."""

    repo, remote = _repo_with_remote(tmp_path)
    local_head = _git(repo, "rev-parse", "HEAD")
    local_bytes = (repo / "README.md").read_bytes()
    remote_head = _advance_remote(tmp_path, remote)

    result = repository_status.inspect_repository(repo, fetch_remote=True)

    assert result.status == "stale"
    assert result.exit_code != 0
    assert result.behind_count == 1
    assert result.default_status == "stale"
    assert result.current_behind_count == 1
    assert result.local_default_commit == local_head
    assert result.remote_default_commit == remote_head
    assert _git(repo, "rev-parse", "HEAD") == local_head
    assert (repo / "README.md").read_bytes() == local_bytes


def test_current_feature_is_not_mislabeled_by_stale_local_default(
    tmp_path: Path,
) -> None:
    """Feature relation and canonical local-main drift must remain distinct."""

    repo, remote = _repo_with_remote(tmp_path)
    remote_head = _advance_remote(tmp_path, remote)
    _git(repo, "fetch", "origin")
    _git(repo, "switch", "-c", "feature", "origin/main")

    result = repository_status.inspect_repository(repo, fetch_remote=True)

    assert result.status == "feature"
    assert result.exit_code == 0
    assert result.current_commit == remote_head
    assert result.current_behind_count == 0
    assert result.default_status == "stale"
    assert result.behind_count == 1


def test_feature_remote_does_not_replace_default_branch_authority(
    tmp_path: Path,
) -> None:
    """A feature's fork remote must not replace main's tracked origin."""

    repo, _remote = _repo_with_remote(tmp_path)
    fork = tmp_path / "fork.git"
    _git(tmp_path, "init", "--bare", str(fork))
    _git(repo, "remote", "add", "fork", str(fork))
    _git(repo, "switch", "-c", "feature")
    _git(repo, "config", "branch.feature.remote", "fork")

    result = repository_status.inspect_repository(repo, fetch_remote=True)

    assert result.status == "feature"
    assert result.exit_code == 0
    assert result.remote_name == "origin"
    assert result.default_status == "current"


def test_unreachable_remote_is_freshness_unknown_not_current(tmp_path: Path) -> None:
    """A failed metadata refresh must not license a current-authority claim."""

    repo, remote = _repo_with_remote(tmp_path)
    remote.rename(tmp_path / "unreachable.git")

    result = repository_status.inspect_repository(repo, fetch_remote=True)

    assert result.status == "freshness_unknown"
    assert result.exit_code != 0
    assert result.fetch_succeeded is False
    assert result.fetch_error


def test_feature_worktree_exposes_default_branch_drift_without_blocking_status(
    tmp_path: Path,
) -> None:
    """Feature work remains inspectable while canonical default drift stays visible."""

    repo, remote = _repo_with_remote(tmp_path)
    _git(repo, "switch", "-c", "feature")
    _advance_remote(tmp_path, remote)

    result = repository_status.inspect_repository(repo, fetch_remote=True)

    assert result.status == "feature_base_stale"
    assert result.exit_code == 0
    assert result.current_branch == "feature"
    assert result.default_branch == "main"
    assert result.behind_count == 1
    assert result.default_status == "stale"
    assert result.current_behind_count == 1
