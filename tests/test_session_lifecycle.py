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
    monkeypatch.setenv("CODEX_THREAD_ID", "heartbeat-test")

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


def _write_cross_agent_claim(
    claims_dir: Path,
    *,
    repo: Path,
    status: str,
    session_id: str = "codex:predecessor",
) -> Path:
    now = datetime.now(timezone.utc)
    claim_path = claims_dir / "codex_demo_cross-agent-lane.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 6,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["demo"],
                "scope": "cross-agent-lane",
                "intent": "exercise cross-agent handoff resume",
                "claim_type": "program",
                "plan_ref": "UNPLANNED",
                "write_paths": ["."],
                "repo_root": str(repo),
                "worktree_path": str(repo),
                "branch": "lane",
                "session_id": session_id,
                "session_name": "predecessor",
                "broader_goal": "Prove cross-agent handoff resume",
                "heartbeat_at": now.isoformat(),
                "status": status,
                "notes": "circuit-broken; resume in a fresh session",
                "broad_scope_mode": "bootstrap",
                "broad_scope_reason": "fixture bootstrap claim",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return claim_path


def _prepare_cross_agent_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "lane")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test User")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    return repo


def test_resume_session_transfers_claim_identity_to_a_different_handed_off_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim explicitly left in 'handoff' status by one agent can be resumed by another."""

    repo = _prepare_cross_agent_repo(tmp_path)
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    old_claim_path = _write_cross_agent_claim(claims_dir, repo=repo, status="handoff")

    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    monkeypatch.setattr(
        session_lifecycle,
        "_poll_mailbox_after_committed_transition",
        lambda **_: {"polled": True, "active_count": 0},
    )
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "successor-run")

    result = session_lifecycle.resume_session(
        agent="codex",
        project="demo",
        scope="cross-agent-lane",
        worktree_path=str(repo),
        branch="lane",
        current_phase="continue cross-agent work",
        successor_agent="claude-code",
    )

    assert result["action"] == "resumed"
    assert result["predecessor_agent"] == "codex"
    assert result["successor_agent"] == "claude-code"
    assert result["session_id"] == "claude-code:successor-run"
    assert not old_claim_path.exists()

    new_claim_path = claims_dir / "claude-code_demo_cross-agent-lane.yaml"
    persisted = yaml.safe_load(new_claim_path.read_text(encoding="utf-8"))
    assert persisted["agent"] == "claude-code"
    assert persisted["status"] == "active"
    assert persisted["session_id"] == "claude-code:successor-run"
    assert persisted["scope"] == "cross-agent-lane"


def test_resume_session_refuses_cross_agent_transfer_of_a_live_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live (non-handoff) claim cannot be picked up by a different agent."""

    repo = _prepare_cross_agent_repo(tmp_path)
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = _write_cross_agent_claim(claims_dir, repo=repo, status="active")
    before = claim_path.read_bytes()

    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "successor-run")

    with pytest.raises(ValueError, match="explicit 'handoff' claim status"):
        session_lifecycle.resume_session(
            agent="codex",
            project="demo",
            scope="cross-agent-lane",
            worktree_path=str(repo),
            branch="lane",
            current_phase="continue cross-agent work",
            successor_agent="claude-code",
        )

    assert claim_path.read_bytes() == before
    assert not (claims_dir / "claude-code_demo_cross-agent-lane.yaml").exists()


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


def test_bootstrap_closeout_resolves_real_target_instead_of_authority_sentinel(
    tmp_path: Path,
) -> None:
    """Early bootstrap failure must still clean the physical worktree it created."""

    target = tmp_path / "target-worktree"
    sentinel = Path(f"{target}.bootstrap-no-mutation-authority")
    claim = coordination_claims.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="lane",
        intent="exercise bootstrap closeout",
        plan_ref="UNPLANNED",
        claim_type="program",
        write_paths=["."],
        broad_scope_mode="bootstrap",
        broad_scope_reason="construct and narrow the exact maintenance lane",
        target_worktree_path=str(target),
        worktree_path=str(sentinel),
        repo_root=str(tmp_path),
        branch="lane",
        session_id="codex:bootstrap-closeout",
    )

    assert claim.worktree_path == str(target)
    assert session_lifecycle._resolve_closeout_worktree_path(claim, None) == target
    assert session_lifecycle._resolve_closeout_worktree_path(claim, str(target)) == target
