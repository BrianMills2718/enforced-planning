"""Tests for the shared-ref movement report printed at session close.

Two properties under test. First, the report never lets "nothing landed here"
and "I could not find out" render as the same thing, since a closeout reader
draws opposite conclusions from them. Second, the lane's own commits are
excluded by reachability rather than by guessing at authorship -- the identity
signals available here cannot separate two agent sessions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from enforced_planning import concurrent_writers


def _git(repo: Path, *arguments: str, **env_overrides: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
        check=True,
        env={
            "GIT_AUTHOR_NAME": env_overrides.get("name", "Mine"),
            "GIT_AUTHOR_EMAIL": env_overrides.get("email", "mine@example.com"),
            "GIT_COMMITTER_NAME": env_overrides.get("name", "Mine"),
            "GIT_COMMITTER_EMAIL": env_overrides.get("email", "mine@example.com"),
            "PATH": "/usr/bin:/bin",
            "HOME": str(repo),
        },
    )
    return completed.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "--quiet", "--initial-branch=main")
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    _git(root, "add", "a.txt")
    _git(root, "commit", "--quiet", "-m", "base")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


def _commit(repo: Path, name: str, message: str, *, email: str) -> str:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name, email=email)
    _git(repo, "commit", "--quiet", "-m", message, email=email)
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD", email=email)
    return _git(repo, "rev-parse", "HEAD", email=email).strip()


def test_a_commit_from_outside_the_lane_is_reported_with_what_it_was(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "--quiet", "-b", "my-lane")
    _git(repo, "checkout", "--quiet", "main")
    _commit(repo, "b.txt", "another session landed this", email="other@example.com")

    report = concurrent_writers.collect_shared_ref_movement(
        repo, ref="origin/main", since_revision=base, lane_refs=("my-lane",)
    )

    assert report.state == concurrent_writers.OBSERVED
    assert len(report.commits) == 1
    assert report.commits[0].subject == "another session landed this"
    rendered = concurrent_writers.render_report(report)
    assert "another session landed this" in rendered


def test_this_lanes_own_commits_are_excluded_by_reachability(repo: Path) -> None:
    """The same operator email on both sides: only reachability can tell them apart."""
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "--quiet", "-b", "my-lane")
    _commit(repo, "b.txt", "my own lane work", email="mine@example.com")
    _git(repo, "checkout", "--quiet", "main")
    _git(repo, "merge", "--quiet", "--ff-only", "my-lane")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")

    report = concurrent_writers.collect_shared_ref_movement(
        repo, ref="origin/main", since_revision=base, lane_refs=("my-lane",)
    )

    assert report.state == concurrent_writers.OBSERVED_EMPTY


def test_this_lanes_squash_merge_is_not_reported_as_someone_elses_work(repo: Path) -> None:
    """A squash commit is reachable from no branch, so the branch name alone is not enough."""
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "--quiet", "-b", "my-lane")
    _commit(repo, "b.txt", "my lane work", email="mine@example.com")
    _git(repo, "checkout", "--quiet", "main")
    _git(repo, "merge", "--quiet", "--squash", "my-lane")
    _git(repo, "commit", "--quiet", "-m", "my lane work (#1)")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    squash = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "branch", "--quiet", "-D", "my-lane")

    without_squash = concurrent_writers.collect_shared_ref_movement(
        repo, ref="origin/main", since_revision=base, lane_refs=("my-lane",)
    )
    assert without_squash.state == concurrent_writers.OBSERVED

    with_squash = concurrent_writers.collect_shared_ref_movement(
        repo, ref="origin/main", since_revision=base, lane_refs=("my-lane", squash)
    )
    assert with_squash.state == concurrent_writers.OBSERVED_EMPTY


def test_two_sessions_sharing_one_author_identity_are_still_separated(repo: Path) -> None:
    """The case author-email filtering could never have caught."""
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "--quiet", "-b", "my-lane")
    _commit(repo, "mine.txt", "mine", email="mine@example.com")
    _git(repo, "checkout", "--quiet", "main")
    _git(repo, "merge", "--quiet", "--ff-only", "my-lane")
    _commit(repo, "theirs.txt", "the other session's commit", email="mine@example.com")

    report = concurrent_writers.collect_shared_ref_movement(
        repo, ref="origin/main", since_revision=base, lane_refs=("my-lane",)
    )

    assert report.state == concurrent_writers.OBSERVED
    subjects = [commit.subject for commit in report.commits]
    assert subjects == ["the other session's commit"]


def test_an_unreadable_range_is_never_reported_as_nobody_wrote(repo: Path) -> None:
    """The failure this whole module exists to prevent, in its smallest form."""
    report = concurrent_writers.collect_shared_ref_movement(
        repo,
        ref="origin/main",
        since_revision="0" * 40,
    )

    assert report.state == concurrent_writers.UNAVAILABLE
    assert report.state != concurrent_writers.OBSERVED_EMPTY
    rendered = concurrent_writers.render_report(report)
    assert "NOT CHECKED" in rendered
    assert "none" not in rendered


def test_a_lane_with_no_start_revision_is_unavailable_not_empty(repo: Path) -> None:
    report = concurrent_writers.collect_shared_ref_movement(
        repo,
        ref="origin/main",
        since_revision=None,
    )

    assert report.state == concurrent_writers.UNAVAILABLE
    assert "no start revision" in (report.unavailable_reason or "")


def test_a_missing_ref_is_unavailable_with_its_reason(repo: Path) -> None:
    base = _git(repo, "rev-parse", "HEAD").strip()

    report = concurrent_writers.collect_shared_ref_movement(
        repo,
        ref="origin/does-not-exist",
        since_revision=base,
    )

    assert report.state == concurrent_writers.UNAVAILABLE
    assert report.unavailable_reason


def test_a_report_cannot_claim_emptiness_while_carrying_commits() -> None:
    with pytest.raises(ValueError):
        concurrent_writers.SharedRefReport(
            ref="origin/main",
            state=concurrent_writers.OBSERVED_EMPTY,
            commits=(
                concurrent_writers.ForeignCommit(
                    sha="a" * 40, author_name="Other", subject="x"
                ),
            ),
        )


def test_an_unavailable_report_cannot_omit_its_reason() -> None:
    with pytest.raises(ValueError):
        concurrent_writers.SharedRefReport(
            ref="origin/main", state=concurrent_writers.UNAVAILABLE
        )
