"""Real Git/pytest controls for scoped plan-completion repository health."""

from __future__ import annotations

import subprocess
from pathlib import Path

from scripts.complete_plan import compare_repository_health, parse_pytest_junit


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


def test_pytest_session_directory_does_not_change_failure_identity(tmp_path: Path) -> None:
    """Volatile pytest session IDs must not turn the same failure into a regression."""
    reports: list[Path] = []
    for session_id in (1448, 1449):
        report = tmp_path / f"pytest-{session_id}.xml"
        report.write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites tests="1" failures="1" errors="0" skipped="0">
  <testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0">
    <testcase classname="tests.test_sample" name="test_temp_path" file="tests/test_sample.py">
      <failure type="subprocess.CalledProcessError" message="Command used /tmp/pytest-of-brian/pytest-{session_id}/test_temp_path0/input.txt">trace at /tmp/pytest-of-brian/pytest-{session_id}/test_temp_path0/input.txt</failure>
    </testcase>
  </testsuite>
</testsuites>
""",
            encoding="utf-8",
        )
        reports.append(report)

    parsed = [
        parse_pytest_junit(
            report,
            project_root=Path("/repo/current"),
            commit="abc123",
            command=("python", "-m", "pytest"),
            returncode=1,
            output="",
        )
        for report in reports
    ]

    first_failure = parsed[0].failures[0]
    second_failure = parsed[1].failures[0]
    assert first_failure.detail_hash == second_failure.detail_hash
    assert "<pytest-tmp>/test_temp_path0/input.txt" in first_failure.detail_excerpt


def test_worktree_basename_does_not_change_failure_identity(tmp_path: Path) -> None:
    """A worktree-derived project label is layout noise, not changed behavior."""
    repo = tmp_path / "project-meta"
    (repo / ".git").mkdir(parents=True)
    worktrees = repo / "worktrees"
    roots = [worktrees / "feature-branch", worktrees / ".completion-baseline-123"]
    reports: list[Path] = []
    for index, root in enumerate(roots):
        root.mkdir(parents=True)
        report = tmp_path / f"worktree-{index}.xml"
        report.write_text(
            f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites tests="1" failures="1" errors="0" skipped="0">
  <testsuite name="pytest" tests="1" failures="1" errors="0" skipped="0">
    <testcase classname="tests.test_session" name="test_project_label" file="tests/test_session.py">
      <failure type="AssertionError" message="expected Memory (project-meta)">actual Memory ({root.name})</failure>
    </testcase>
  </testsuite>
</testsuites>
""",
            encoding="utf-8",
        )
        reports.append(report)

    parsed = [
        parse_pytest_junit(
            report,
            project_root=root,
            commit="abc123",
            command=("python", "-m", "pytest"),
            returncode=1,
            output="",
        )
        for report, root in zip(reports, roots, strict=True)
    ]

    assert parsed[0].failures[0].detail_hash == parsed[1].failures[0].detail_hash
    assert "actual Memory (<checkout>)" in parsed[0].failures[0].detail_excerpt
