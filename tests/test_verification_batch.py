"""Verify immutable terminal verification-batch transitions."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from enforced_planning.verification_batch import VerificationBatchError
from enforced_planning.verification_batch import check_batch
from enforced_planning.verification_batch import freeze_batch
from enforced_planning.verification_batch import history_path
from enforced_planning.verification_batch import load_batch
from enforced_planning.verification_batch import thaw_batch


def _repo(tmp_path: Path) -> Path:
    """Create one committed repository for real Git-state controls."""

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    (repo / "source.txt").write_text("one\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "seed"], check=True, capture_output=True)
    return repo


def test_freeze_and_check_bind_clean_exact_head(tmp_path: Path) -> None:
    """A clean batch remains valid while its exact bytes stay unchanged."""

    repo = _repo(tmp_path)
    batch = freeze_batch(repo, decision="Merge reviewed Greer runner", command="make check")

    assert batch.branch == "main"
    assert batch.revision == subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert check_batch(repo, require_active=True) == batch


def test_freeze_rejects_dirty_tracked_bytes(tmp_path: Path) -> None:
    """Verification cannot start over uncommitted reviewed bytes."""

    repo = _repo(tmp_path)
    (repo / "source.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(VerificationBatchError, match="tracked bytes"):
        freeze_batch(repo, decision="Merge", command="make check")


def test_freeze_rejects_untracked_execution_inputs_unless_narrowly_allowed(tmp_path: Path) -> None:
    """Untracked code cannot silently influence an exact-revision verification claim."""

    repo = _repo(tmp_path)
    untracked = repo / ".claude" / "messages" / "review.md"
    untracked.parent.mkdir(parents=True)
    untracked.write_text("coordination only\n", encoding="utf-8")

    with pytest.raises(VerificationBatchError, match="not captured by the revision"):
        freeze_batch(repo, decision="Merge", command="make check")

    batch = freeze_batch(
        repo,
        decision="Merge",
        command="make check",
        allowed_untracked=(".claude/messages/",),
    )
    assert batch.allowed_untracked == (".claude/messages",)
    assert check_batch(repo) == batch


def test_check_rejects_staged_or_unstaged_mutation(tmp_path: Path) -> None:
    """The active batch fails immediately when reviewed bytes are edited."""

    repo = _repo(tmp_path)
    freeze_batch(repo, decision="Merge", command="make check")
    (repo / "source.txt").write_text("changed\n", encoding="utf-8")

    with pytest.raises(VerificationBatchError, match="tracked bytes"):
        check_batch(repo)

    subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
    with pytest.raises(VerificationBatchError, match="tracked bytes"):
        check_batch(repo)


def test_check_rejects_new_commit_on_frozen_branch(tmp_path: Path) -> None:
    """Absorbing another ready branch invalidates the exact reviewed head."""

    repo = _repo(tmp_path)
    batch = freeze_batch(repo, decision="Merge", command="make check")
    (repo / "source.txt").write_text("two\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "source.txt"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-m", "unrelated integration"], check=True, capture_output=True)

    with pytest.raises(VerificationBatchError, match=f"HEAD changed from {batch.revision}"):
        check_batch(repo)


def test_thaw_requires_reason_and_retains_invalidation_history(tmp_path: Path) -> None:
    """A required scoped fix can restart verification without silent evidence loss."""

    repo = _repo(tmp_path)
    batch = freeze_batch(repo, decision="Merge", command="make check")

    with pytest.raises(VerificationBatchError, match="non-empty"):
        thaw_batch(repo, reason=" ")

    thaw_batch(repo, reason="Fix blocker found by independent review")
    assert load_batch(repo) is None
    history = history_path(repo).read_text(encoding="utf-8")
    assert batch.revision in history
    assert "Fix blocker found by independent review" in history


def test_require_active_distinguishes_unfrozen_lane(tmp_path: Path) -> None:
    """Terminal closeout can require a freeze while ordinary work remains unaffected."""

    repo = _repo(tmp_path)

    assert check_batch(repo) is None
    with pytest.raises(VerificationBatchError, match="no active"):
        check_batch(repo, require_active=True)


def test_source_wrapper_runs_from_in_repo_worktree_layout(tmp_path: Path) -> None:
    """The agent-facing CLI resolves its package without an editable install."""

    repo = _repo(tmp_path)
    wrapper = Path(__file__).resolve().parents[1] / "scripts" / "verification_batch.py"

    result = subprocess.run(
        ["python", str(wrapper), "--repo-root", str(repo), "--json", "check"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert '"active": false' in result.stdout
