"""Tests for narrowly worktree-local runtime write ownership."""

from __future__ import annotations

import subprocess
from pathlib import Path

from enforced_planning import coordination_claims as cc
from enforced_planning.worktree_local_runtime_paths import is_isolated_runtime_overlap

CURSOR = ".company-planning/active-execution.json"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _repo(tmp_path: Path, *, ignored: bool = True, tracked: bool = False) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    assert _git(repo, "init", "-q", "-b", "main").returncode == 0
    assert _git(repo, "config", "user.name", "Test User").returncode == 0
    assert _git(repo, "config", "user.email", "test@example.com").returncode == 0
    (repo / "README.md").write_text("test\n", encoding="utf-8")
    if ignored:
        (repo / ".gitignore").write_text(".company-planning/**\n", encoding="utf-8")
    if tracked:
        cursor = repo / CURSOR
        cursor.parent.mkdir(parents=True)
        cursor.write_text("{}\n", encoding="utf-8")
        assert _git(repo, "add", "-f", CURSOR).returncode == 0
    assert _git(repo, "add", "README.md", ".gitignore" if ignored else "README.md").returncode == 0
    assert _git(repo, "commit", "-m", "init").returncode == 0
    return repo


def _isolated(repo: Path, *, left_path: str = CURSOR, right_path: str = CURSOR) -> bool:
    return is_isolated_runtime_overlap(
        left_path=left_path,
        right_path=right_path,
        left_worktree_path=str(repo / "worktrees" / "left"),
        right_worktree_path=str(repo / "worktrees" / "right"),
        left_repo_root=str(repo),
        right_repo_root=str(repo),
    )


def test_exact_ignored_untracked_cursor_is_isolated_across_lane_paths(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert _isolated(repo)


def test_tracked_cursor_remains_shared_repository_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path, tracked=True)

    assert not _isolated(repo)


def test_unignored_cursor_remains_shared_repository_state(tmp_path: Path) -> None:
    repo = _repo(tmp_path, ignored=False)

    assert not _isolated(repo)


def test_parent_directory_claim_is_not_exempt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert not _isolated(
        repo,
        left_path=".company-planning",
        right_path=CURSOR,
    )


def test_same_lane_path_is_not_exempt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    lane = str(repo / "worktrees" / "same")

    assert not is_isolated_runtime_overlap(
        left_path=CURSOR,
        right_path=CURSOR,
        left_worktree_path=lane,
        right_worktree_path=lane,
        left_repo_root=str(repo),
        right_repo_root=str(repo),
    )


def test_nonstandard_worktree_path_is_not_exempt(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert not is_isolated_runtime_overlap(
        left_path=CURSOR,
        right_path=CURSOR,
        left_worktree_path=str(tmp_path / "elsewhere-left"),
        right_worktree_path=str(tmp_path / "elsewhere-right"),
        left_repo_root=str(repo),
        right_repo_root=str(repo),
    )


def _claim(repo: Path, *, scope: str, session_id: str, lane: str, path: str = CURSOR):
    return cc.build_candidate_claim(
        agent="codex",
        project="demo",
        scope=scope,
        intent="Run one isolated execution loop",
        plan_ref="UNPLANNED",
        claim_type="write",
        write_paths=[path],
        worktree_path=str(repo / "worktrees" / lane),
        repo_root=str(repo),
        branch=f"fix/{lane}",
        session_id=session_id,
        session_name="run-one-isolated-execution-loop",
        broader_goal="Run one isolated execution loop",
        parallel_root_authorized=True,
    )


def test_two_linked_worktrees_can_concurrently_claim_exact_execution_cursor(
    tmp_path: Path,
) -> None:
    """The ignored cursor's identical repo-relative name is not shared bytes."""

    repo = _repo(tmp_path)
    left = _claim(repo, scope="left", session_id="codex:left", lane="left")
    right = _claim(repo, scope="right", session_id="codex:right", lane="right")

    result = cc.evaluate_claim(right, active_claims=[left])

    assert result.hard_conflicts == []
    assert cc._compute_overlapping_write_paths(right, left) == []


def test_two_linked_worktrees_still_conflict_on_ordinary_shared_path(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    left = _claim(
        repo,
        scope="left",
        session_id="codex:left",
        lane="left",
        path="README.md",
    )
    right = _claim(
        repo,
        scope="right",
        session_id="codex:right",
        lane="right",
        path="README.md",
    )

    result = cc.evaluate_claim(right, active_claims=[left])

    assert len(result.hard_conflicts) == 1
    assert result.hard_conflicts[0].overlapping_write_paths == [
        "README.md <-> README.md"
    ]
