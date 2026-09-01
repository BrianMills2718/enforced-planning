"""Closeout assigns custody only to the session's isolated linked worktrees."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from scripts import coordination_hook as hook


def _git(repository: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository_with_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repository = tmp_path / "repository"
    worktree = tmp_path / "worktree"
    repository.mkdir()
    _git(repository, "init", "--initial-branch=main")
    _git(repository, "config", "user.email", "hooks@example.invalid")
    _git(repository, "config", "user.name", "Hook Test")
    (repository / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "fixture")
    _git(repository, "worktree", "add", "-b", "task", str(worktree))
    return repository, worktree


def _claim(worktree: Path, *, session_id: str = "codex:current") -> SimpleNamespace:
    return SimpleNamespace(
        agent="codex",
        session_id=session_id,
        worktree_path=str(worktree),
    )


def test_canonical_checkout_delta_is_not_claimed_as_session_custody(tmp_path: Path) -> None:
    repository, _worktree = _repository_with_worktree(tmp_path)
    ledger = tmp_path / "ledgers"
    hook._write_closeout_baseline(
        payload={"cwd": str(repository)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
    )
    hook._record_touched_repositories(
        payload={"cwd": str(repository)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(),
    )
    (repository / "foreign.txt").write_text("another writer\n", encoding="utf-8")

    assert hook._repository_closeout_failure(
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(),
    ) is None


def test_non_git_workspace_root_is_not_recorded_as_a_touched_repository(tmp_path: Path) -> None:
    ledger = tmp_path / "ledgers"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    hook._write_closeout_baseline(
        payload={"cwd": str(workspace)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
    )

    hook._record_touched_repositories(
        payload={"cwd": str(workspace)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(),
    )

    [ledger_path] = ledger.glob("*.json")
    payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert payload["touched_repositories"] == []


def test_claimed_linked_worktree_delta_blocks_session_closeout(tmp_path: Path) -> None:
    repository, worktree = _repository_with_worktree(tmp_path)
    ledger = tmp_path / "ledgers"
    claim = _claim(worktree)
    hook._write_closeout_baseline(
        payload={"cwd": str(repository)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
    )
    hook._record_touched_repositories(
        payload={"cwd": str(repository)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(claim,),
    )
    (worktree / "owned.txt").write_text("session work\n", encoding="utf-8")

    failure = hook._repository_closeout_failure(
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(claim,),
    )
    assert failure is not None
    assert str(worktree) in failure


def test_stop_adds_owned_claimed_worktree_when_pretool_cwd_was_canonical(tmp_path: Path) -> None:
    repository, worktree = _repository_with_worktree(tmp_path)
    ledger = tmp_path / "ledgers"
    claim = _claim(worktree)
    hook._write_closeout_baseline(
        payload={"cwd": str(repository)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
    )
    (worktree / "owned.txt").write_text("session work\n", encoding="utf-8")

    failure = hook._repository_closeout_failure(
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(claim,),
    )

    assert failure is not None
    assert str(worktree) in failure


def test_foreign_claim_cannot_exempt_owned_linked_worktree(tmp_path: Path) -> None:
    _repository, worktree = _repository_with_worktree(tmp_path)
    ledger = tmp_path / "ledgers"
    owned = _claim(worktree)
    foreign = _claim(worktree, session_id="codex:other")
    hook._write_closeout_baseline(
        payload={"cwd": str(worktree)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
    )
    hook._record_touched_repositories(
        payload={"cwd": str(worktree)},
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(owned, foreign),
    )
    (worktree / "owned.txt").write_text("session work\n", encoding="utf-8")

    assert hook._repository_closeout_failure(
        agent="codex",
        session_id="codex:current",
        ledger_dir=ledger,
        active_claims=(owned, foreign),
    ) is not None
