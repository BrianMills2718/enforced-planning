"""Real Git/pytest controls for scoped plan-completion repository health."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.complete_plan import compare_repository_health


def _run_git(repo: Path, *args: str) -> str:
    """Run Git in a disposable test repository and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _make_worktree_repo(tmp_path: Path) -> tuple[Path, Path]:
    """Create a baseline repository plus a sibling-layout feature worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run_git(repo, "init", "-b", "main")
    _run_git(repo, "config", "user.email", "tests@example.invalid")
    _run_git(repo, "config", "user.name", "Completion Gate Tests")

    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (repo / "app.py").write_text("def value():\n    return 1\n", encoding="utf-8")
    (tests_dir / "test_baseline.py").write_text(
        """from pathlib import Path

from app import value


def test_sibling_path_assumption():
    assert (Path.cwd().parent / "required-sibling").exists()


def test_control_passes():
    assert True


def test_source_behavior():
    assert value() == 2
""",
        encoding="utf-8",
    )
    (repo / "README.md").write_text("baseline\n", encoding="utf-8")
    _run_git(repo, "add", ".")
    _run_git(repo, "commit", "-m", "baseline")

    worktree = repo / "worktrees" / "current"
    worktree.parent.mkdir()
    _run_git(repo, "worktree", "add", "-b", "feature", str(worktree), "main")
    return repo, worktree


def test_unchanged_worktree_failure_is_baseline_debt(tmp_path: Path) -> None:
    """A failure reproduced at the merge base is visible but non-blocking."""
    repo, worktree = _make_worktree_repo(tmp_path)
    (worktree / "README.md").write_text("bounded change\n", encoding="utf-8")

    comparison = compare_repository_health(
        worktree,
        verbose=False,
    )

    assert comparison.allowed is True
    assert comparison.status == "baseline_degraded"
    assert comparison.baseline_ref == "main"
    assert comparison.current.failure_count == 2
    assert comparison.baseline is not None
    assert comparison.baseline.failure_count == 2
    assert comparison.new_failures == ()
    assert comparison.changed_baseline_failures == ()
    assert not list((repo / "worktrees").glob(".completion-baseline-*"))


def test_green_repository_does_not_create_baseline_worktree(tmp_path: Path) -> None:
    """A green current run completes without paying for a control checkout."""
    repo, worktree = _make_worktree_repo(tmp_path)
    (repo / "worktrees" / "required-sibling").mkdir()
    (worktree / "app.py").write_text("def value():\n    return 2\n", encoding="utf-8")

    comparison = compare_repository_health(worktree, verbose=False)

    assert comparison.allowed is True
    assert comparison.status == "green"
    assert comparison.baseline is None
    assert not list((repo / "worktrees").glob(".completion-baseline-*"))


def test_new_failure_blocks_completion(tmp_path: Path) -> None:
    """A current-only failing test is a blocking repository regression."""
    _, worktree = _make_worktree_repo(tmp_path)
    (worktree / "tests" / "test_new_failure.py").write_text(
        "def test_new_regression():\n    assert False\n",
        encoding="utf-8",
    )

    comparison = compare_repository_health(
        worktree,
        baseline_ref="main",
        verbose=False,
    )

    assert comparison.allowed is False
    assert comparison.status == "regressed"
    assert len(comparison.new_failures) == 1
    assert "test_new_regression" in comparison.new_failures[0]


def test_changed_baseline_test_file_blocks_completion(tmp_path: Path) -> None:
    """A changed failing test cannot borrow its old identity as proof."""
    _, worktree = _make_worktree_repo(tmp_path)
    test_file = worktree / "tests" / "test_baseline.py"
    test_file.write_text(
        test_file.read_text(encoding="utf-8") + "\n# changed by this plan\n",
        encoding="utf-8",
    )

    comparison = compare_repository_health(
        worktree,
        baseline_ref="main",
        verbose=False,
    )

    assert comparison.allowed is False
    assert comparison.status == "regressed"
    assert comparison.new_failures == ()
    assert len(comparison.changed_baseline_failures) == 2
    assert any(
        "test_sibling_path_assumption" in failure
        for failure in comparison.changed_baseline_failures
    )


def test_changed_failure_cause_blocks_even_when_test_file_is_unchanged(tmp_path: Path) -> None:
    """A same-named failure with different evidence is a regression."""
    _, worktree = _make_worktree_repo(tmp_path)
    (worktree / "app.py").write_text("def value():\n    return 0\n", encoding="utf-8")

    comparison = compare_repository_health(
        worktree,
        baseline_ref="main",
        verbose=False,
    )

    assert comparison.allowed is False
    assert comparison.status == "regressed"
    assert comparison.new_failures == ()
    assert any(
        "test_source_behavior" in failure
        for failure in comparison.changed_baseline_failures
    )


def test_unavailable_baseline_blocks_completion(tmp_path: Path) -> None:
    """An unresolved baseline ref is unavailable evidence, never a pass."""
    _, worktree = _make_worktree_repo(tmp_path)

    comparison = compare_repository_health(
        worktree,
        baseline_ref="refs/heads/does-not-exist",
        verbose=False,
    )

    assert comparison.allowed is False
    assert comparison.status == "unavailable"
    assert comparison.baseline is None
    assert "merge base" in comparison.reason.lower()
