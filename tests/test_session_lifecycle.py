"""Lifecycle behaviour that is not covered by the session CLI or contract tests."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    coordination_messages,
    session_lifecycle,
)


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def test_mailbox_poll_without_a_live_claim_degrades_instead_of_raising() -> None:
    """`session-resume` is the recovery a preserved lane names, and it crashed.

    The preserved-lane check refuses a new claim and tells the operator to
    resume or take over the lane. A fresh runtime therefore arrives holding no
    live claim, the poll could not resolve its session, and `UnknownSessionError`
    escaped as an unhandled traceback -- leaving closing the lane as the only
    named route that worked, and making the recovery circular.
    """

    notice = session_lifecycle._poll_mailbox(
        agent="claude-code",
        project="project-meta",
        session_id="claude-code:no-live-claim-owns-this",
    )

    assert notice["polled"] is False
    assert notice["degraded_reason"] == "no_live_claim_owns_session"
    assert notice["active_count"] == 0
    assert notice["message_ids"] == []


def test_a_degraded_poll_is_not_reported_as_an_empty_inbox() -> None:
    """The guide forbids both halves of the obvious shortcut.

    An adapter failure "cannot truthfully assert mailbox debt or manufacture a
    block", so it must not crash; and it must not fabricate the opposite either.
    "no active messages" is what a successful empty poll says, so a failed poll
    must not be indistinguishable from one.
    """

    notice = session_lifecycle._poll_mailbox(
        agent="claude-code",
        project="project-meta",
        session_id="claude-code:no-live-claim-owns-this",
    )

    summary = notice["summary"]
    assert "NOT POLLED" in summary
    assert "no active messages" not in summary
    assert "may be pending" in summary


def test_other_mailbox_failures_still_surface() -> None:
    """Only the unresolvable-session case degrades; real faults stay loud."""

    def explode(**_: object) -> None:
        raise coordination_messages.CoordinationMessageError("store corrupt")

    original = coordination_messages.poll_session_inbox
    coordination_messages.poll_session_inbox = explode  # type: ignore[assignment]
    try:
        with pytest.raises(coordination_messages.CoordinationMessageError):
            session_lifecycle._poll_mailbox(
                agent="claude-code", project="project-meta", session_id="s"
            )
    finally:
        coordination_messages.poll_session_inbox = original  # type: ignore[assignment]


def test_bounded_broad_heartbeat_preserves_expiry_and_polls_mailbox(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A heartbeat refreshes liveness, never silently extends a bounded lease."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "lane")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "docs").mkdir()
    (repo / "docs" / "README.md").write_text("docs\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(timezone.utc)
    expiry = (now + timedelta(hours=1)).isoformat()
    claim_path = claims_dir / "codex_demo_lane.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 6,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": expiry,
                "projects": ["demo"],
                "scope": "lane",
                "intent": "exercise bounded lease heartbeat",
                "claim_type": "write",
                "plan_ref": "UNPLANNED",
                "write_paths": ["docs"],
                "repo_root": str(repo),
                "worktree_path": str(repo),
                "branch": "lane",
                "session_id": "codex:heartbeat-test",
                "session_name": "heartbeat-test",
                "broader_goal": "Prove lease bounds survive heartbeat",
                "heartbeat_at": (now - timedelta(minutes=1)).isoformat(),
                "status": "active",
                "broad_scope_mode": "bounded",
                "broad_scope_reason": "the fixture deliberately owns the docs tree",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    mailbox_calls: list[tuple[str, str, str]] = []

    def poll_mailbox(*, agent: str, project: str, session_id: str) -> dict[str, object]:
        mailbox_calls.append((agent, project, session_id))
        return {"polled": True, "active_count": 0}

    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    monkeypatch.setattr(session_lifecycle, "_poll_mailbox", poll_mailbox)

    result = session_lifecycle.heartbeat_session(
        agent="codex",
        project="demo",
        session_id="codex:heartbeat-test",
        scope="lane",
    )

    persisted = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert persisted["expires_at"] == expiry
    assert persisted["broad_scope_mode"] == "bounded"
    assert persisted["broad_scope_reason"] == "the fixture deliberately owns the docs tree"
    assert persisted["heartbeat_at"] == result["heartbeat_at"]
    assert result["coordination_mailbox"] == {"polled": True, "active_count": 0}
    assert mailbox_calls == [("codex", "demo", "codex:heartbeat-test")]


def test_remove_worktree_reanchors_process_cwd_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = tmp_path / "lane"
    _git(repo, "worktree", "add", "-b", "lane", str(worktree))
    monkeypatch.chdir(worktree)

    action = session_lifecycle._remove_worktree_path(repo, worktree)

    assert action == "removed"
    assert Path.cwd() == repo.resolve()
    assert not worktree.exists()
