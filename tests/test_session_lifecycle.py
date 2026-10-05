"""Lifecycle behaviour that is not covered by the session CLI or contract tests."""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    coordination_messages,
    session_contracts,
    session_lifecycle,
)


def _claim_with_tracker(tracker: Path) -> SimpleNamespace:
    return SimpleNamespace(
        agent="codex",
        scope="later-lane",
        session_id="codex:same-session",
        tracker_path=str(tracker),
        worktree_path="/repo/worktrees/later-lane",
        branch="later-lane",
        primary_project=lambda: "demo",
    )


def test_session_ended_reconciliation_accepts_digest_bound_stale_mutable_tracker_identity(
    tmp_path: Path,
) -> None:
    tracker = tmp_path / "codex__demo__codex-same-session__goal.yaml"
    tracker.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "claim": {
                    "agent": "codex",
                    "project": "demo",
                    "session_id": "codex:same-session",
                    "scope": "earlier-lane",
                    "worktree_path": "/repo/worktrees/earlier-lane",
                    "branch": "earlier-lane",
                },
                "tracker": {"current_phase": "session ended"},
            }
        ),
        encoding="utf-8",
    )

    resolved, mismatches = session_lifecycle._session_ended_reconciliation_tracker(
        _claim_with_tracker(tracker)
    )

    assert resolved == tracker
    assert mismatches == {
        "scope": {"claim": "later-lane", "tracker": "earlier-lane"},
        "worktree_path": {
            "claim": "/repo/worktrees/later-lane",
            "tracker": "/repo/worktrees/earlier-lane",
        },
        "branch": {"claim": "later-lane", "tracker": "earlier-lane"},
    }


def test_session_ended_reconciliation_rejects_stale_stable_tracker_identity(
    tmp_path: Path,
) -> None:
    tracker = tmp_path / "codex__demo__codex-same-session__goal.yaml"
    tracker.write_text(
        yaml.safe_dump(
            {
                "schema_version": 2,
                "claim": {
                    "agent": "codex",
                    "project": "other-project",
                    "session_id": "codex:same-session",
                    "scope": "earlier-lane",
                },
                "tracker": {"current_phase": "session ended"},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="stable owner identity differs in: project"):
        session_lifecycle._session_ended_reconciliation_tracker(_claim_with_tracker(tracker))


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


@pytest.mark.parametrize("status", ["handoff", coordination_claims.SESSION_ENDED_STATUS])
def test_resume_session_transfers_quiesced_claim_identity_to_a_different_agent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    """Explicit handoff and session end both prove the predecessor is quiescent."""

    repo = _prepare_cross_agent_repo(tmp_path)
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    old_claim_path = _write_cross_agent_claim(claims_dir, repo=repo, status=status)

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

    with pytest.raises(ValueError, match="explicit 'handoff' or 'session_ended'"):
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
    assert worktree.is_dir() and not any(worktree.iterdir())
    assert str(worktree.resolve()) not in _git(repo, "worktree", "list")


def test_remove_clean_worktree_with_initialized_submodule(tmp_path: Path) -> None:
    """Git's submodule-only force requirement must not strand a closed lane."""
    child = tmp_path / "child"
    parent = tmp_path / "parent"
    for repo in (child, parent):
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test User")
        (repo / "README.md").write_text("seed\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "seed")

    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "add",
            str(child),
            "vendor/child",
        ],
        cwd=parent,
        check=True,
        capture_output=True,
        text=True,
    )
    _git(parent, "commit", "-am", "add child")
    worktree = tmp_path / "lane-with-child"
    _git(parent, "worktree", "add", "-b", "lane-with-child", str(worktree))
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "submodule",
            "update",
            "--init",
        ],
        cwd=worktree,
        check=True,
        capture_output=True,
        text=True,
    )

    assert session_lifecycle._remove_worktree_path(parent, worktree) == "removed"
    assert worktree.is_dir() and not any(worktree.iterdir())


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


def test_write_claim_and_refresh_projection_restores_claim_on_refresh_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression for the 2026-09-14 stranded-claim incident.

    An unrelated OTHER claim's malformed YAML made
    refresh_prewrite_authority_projection fail loud (by design). Before this
    fix, _write_claim_and_refresh_projection had already written the new
    payload to disk by that point, so the claim was left permanently mutated
    to a status a caller like close_session never intended to be final --
    with no sanctioned recovery command for that exact intermediate state.
    """

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = claims_dir / "claude-code_demo_stranded-repro.yaml"
    original_payload = {"status": "active", "scope": "stranded-repro"}
    claim_path.write_text(yaml.safe_dump(original_payload, sort_keys=False), encoding="utf-8")
    original_bytes = claim_path.read_bytes()

    def fail_refresh(_claims_dir: Path | None = None) -> tuple[str, str]:
        raise ValueError("Cannot parse claim /some/other/claim.yaml: injected failure")

    monkeypatch.setattr(coordination_claims, "refresh_prewrite_authority_projection", fail_refresh)

    with pytest.raises(ValueError, match="injected failure"):
        session_lifecycle._write_claim_and_refresh_projection(
            claim_path,
            {"status": "closing", "scope": "stranded-repro"},
            claims_dir=claims_dir,
        )

    assert claim_path.read_bytes() == original_bytes, (
        "claim must be rolled back to its pre-call bytes when projection refresh fails, "
        "not left mutated to the never-completed intermediate status"
    )


def test_write_claim_and_refresh_projection_removes_new_claim_on_refresh_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The no-prior-file case: a brand-new claim must not survive a failed refresh either."""

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = claims_dir / "claude-code_demo_new-claim.yaml"
    assert not claim_path.exists()

    def fail_refresh(_claims_dir: Path | None = None) -> tuple[str, str]:
        raise ValueError("injected failure")

    monkeypatch.setattr(coordination_claims, "refresh_prewrite_authority_projection", fail_refresh)

    with pytest.raises(ValueError, match="injected failure"):
        session_lifecycle._write_claim_and_refresh_projection(
            claim_path,
            {"status": "active", "scope": "new-claim"},
            claims_dir=claims_dir,
        )

    assert not claim_path.exists(), "a brand-new claim must be removed, not left half-created"


def test_write_claim_and_refresh_projection_succeeds_when_refresh_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Positive control: the ordinary success path still writes and returns normally."""

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = claims_dir / "claude-code_demo_ok.yaml"

    def succeed_refresh(_claims_dir: Path | None = None) -> tuple[str, str]:
        return (str(claims_dir / "prewrite-authority-v1.json"), "digest-123")

    monkeypatch.setattr(coordination_claims, "refresh_prewrite_authority_projection", succeed_refresh)

    projection_path, projection_digest = session_lifecycle._write_claim_and_refresh_projection(
        claim_path,
        {"status": "active", "scope": "ok"},
        claims_dir=claims_dir,
    )

    assert projection_digest == "digest-123"
    written = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert written == {"status": "active", "scope": "ok"}


# --- issue #2010: session-ended lane whose tracker never existed ----------------


def _trackerless_session_ended_lane_with_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    stage_changes: bool = True,
    keep_tracker: bool = False,
) -> tuple[Path, Path, Path, str]:
    """Replay the real shape: session_ended claim, tracker path that never existed.

    Mirrors the Plan #289 batch A lanes observed 2026-09-15 (project-meta issue
    #2010): the claim recorded a ``--tracker-path`` pointing at a plan file absent
    from the checkout, the owning session ended, and the worktree still holds
    staged conversions.
    """

    from tests.test_session_cli import (  # noqa: PLC0415
        _git as _cli_git,
        _real_repo_with_worktree,
        _start_real_closeout_claim,
    )

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", trackers_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH",
        tmp_path / "completed-claim-archive.jsonl",
    )
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    claim = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    if not keep_tracker:
        Path(claim["tracker_path"]).unlink()
        claim["tracker_path"] = str(tmp_path / "absent" / "289_plan.md")
    claim["write_paths"] = ["docs/plans"]
    claim_file.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    _cli_git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    if stage_changes:
        (worktree / "feature.txt").write_text("converted work\n", encoding="utf-8")
        _cli_git(worktree, "add", "feature.txt")
    session_lifecycle.end_runtime_session(
        agent="codex",
        session_id="codex:test-session",
        reason="runtime ended before the lane could be closed",
        claims_dir=claims_dir,
    )
    return claim_file, repo_root, worktree, branch


def _replacement_candidate(project: str = "enforced-planning") -> coordination_claims.ClaimRecord:
    """A fresh overlapping lane, built exactly as claim creation builds one."""

    candidate = coordination_claims.normalize_claim(
        {
            "agent": "claude-code",
            "projects": [project],
            "scope": "fresh-conversion-lane",
            "intent": "convert plans on a fresh lane",
            "claim_type": "write",
            "write_paths": ["docs/plans"],
            "read_paths": [],
            "session_id": "claude-code:replacement",
            "status": "active",
        }
    )
    assert candidate is not None
    return candidate


def _assert_preserved_lane_conflict(expected: bool) -> str | None:
    """Return the conflict message a replacement lane would hit, if any."""

    try:
        coordination_claims.validate_no_preserved_lane_conflict(
            _replacement_candidate(),
            claims=coordination_claims.list_claims(include_inactive=True),
        )
    except ValueError as exc:
        assert expected, f"unexpected preserved-lane conflict: {exc}"
        return str(exc)
    assert not expected, "expected a preserved-lane conflict and got none"
    return None


def test_tracker_absent_disposition_unblocks_a_replacement_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The stranded lane is dispositioned, its staged work captured, nothing deleted."""

    from tests.test_session_cli import _archived_claim_payload, _native_actor  # noqa: PLC0415

    claim_file, repo_root, worktree, branch = _trackerless_session_ended_lane_with_worktree(
        tmp_path, monkeypatch
    )
    blocked = _assert_preserved_lane_conflict(True)
    assert blocked is not None and "--tracker-absent" in blocked

    claim_digest = session_lifecycle._claim_sha256(claim_file)
    archive_dir = tmp_path / "archive" / "lane"
    with _native_actor("claude-code", "claude-code:reconciler"):
        payload = session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
            actor_session_id="claude-code:reconciler",
            reconcile_session_ended=True,
            tracker_absent=True,
            expected_claim_sha256=claim_digest,
            recovery_archive_dir=str(archive_dir),
            disposition="superseded",
            disposition_reason="superseded by fresh lane; conversion diff preserved",
        )

    assert payload["action"] == "closed"
    assert payload["worktree_action"] == "retained_uncommitted_state_captured"
    assert payload["branch_action"] == "retained_uncommitted_state_captured"
    assert not claim_file.exists()
    assert worktree.exists()
    assert session_lifecycle._branch_exists(repo_root, branch)

    capture = payload["lane_state_capture"]
    assert capture["uncommitted_changes"] is True
    assert capture["git_status_porcelain"] == ["M  feature.txt"]
    assert Path(capture["bundle_path"]).is_file()
    assert "converted work" in (archive_dir / "staged.diff").read_text(encoding="utf-8")
    # The recovery ref really carries the staged content, not just a commit id.
    stored = subprocess.run(
        ["git", "show", f"{capture['recovery_commit']}:feature.txt"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert stored == "converted work\n"

    archived = _archived_claim_payload(payload["claim_archive_id"])
    receipt = archived["session_ended_closeout_reconciliation"]
    assert receipt["tracker_absent_verified"] is True
    assert receipt["tracker_path"] is None
    assert receipt["claim_sha256"] == claim_digest
    assert archived["disposition"] == "superseded"
    assert archived["recovery_ref"] == capture["recovery_ref"]

    _assert_preserved_lane_conflict(False)


def test_tracker_absent_refuses_when_the_tracker_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing tracker means the ordinary digest-bound path must be used."""

    from tests.test_session_cli import _native_actor  # noqa: PLC0415

    claim_file, _repo_root, _worktree, branch = _trackerless_session_ended_lane_with_worktree(
        tmp_path, monkeypatch, keep_tracker=True
    )
    before = claim_file.read_bytes()
    with _native_actor("claude-code", "claude-code:reconciler"):
        with pytest.raises(ValueError, match="the recorded tracker exists"):
            session_lifecycle.close_session(
                agent="codex",
                project="enforced-planning",
                scope=branch,
                actor_session_id="claude-code:reconciler",
                reconcile_session_ended=True,
                tracker_absent=True,
                expected_claim_sha256=session_lifecycle._claim_sha256(claim_file),
                recovery_archive_dir=str(tmp_path / "archive" / "lane"),
                disposition="superseded",
                disposition_reason="should not apply",
            )
    assert claim_file.read_bytes() == before
    _assert_preserved_lane_conflict(True)


def test_tracker_absent_refuses_a_live_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only a preserved session_ended lane may be dispositioned this way."""

    from tests.test_session_cli import (  # noqa: PLC0415
        _native_actor,
        _real_repo_with_worktree,
        _start_real_closeout_claim,
    )

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", trackers_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    claim = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    Path(claim["tracker_path"]).unlink()
    claim["tracker_path"] = str(tmp_path / "absent" / "289_plan.md")
    claim_file.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    before = claim_file.read_bytes()

    with _native_actor("claude-code", "claude-code:reconciler"):
        with pytest.raises(ValueError, match="requires an exact session_ended claim"):
            session_lifecycle.close_session(
                agent="codex",
                project="enforced-planning",
                scope=branch,
                actor_session_id="claude-code:reconciler",
                reconcile_session_ended=True,
                tracker_absent=True,
                expected_claim_sha256=session_lifecycle._claim_sha256(claim_file),
                recovery_archive_dir=str(tmp_path / "archive" / "lane"),
                disposition="superseded",
                disposition_reason="should not apply",
            )
    assert claim_file.read_bytes() == before
    assert worktree.exists()


def test_tracker_absent_capture_failure_leaves_no_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed capture refuses the disposition; the lane stays exactly as it was."""

    from tests.test_session_cli import _native_actor  # noqa: PLC0415

    claim_file, repo_root, worktree, branch = _trackerless_session_ended_lane_with_worktree(
        tmp_path, monkeypatch
    )
    before = claim_file.read_bytes()
    blocked_archive = tmp_path / "archive-file"
    blocked_archive.write_text("not a directory\n", encoding="utf-8")

    with _native_actor("claude-code", "claude-code:reconciler"):
        with pytest.raises(ValueError, match="capture failed creating"):
            session_lifecycle.close_session(
                agent="codex",
                project="enforced-planning",
                scope=branch,
                actor_session_id="claude-code:reconciler",
                reconcile_session_ended=True,
                tracker_absent=True,
                expected_claim_sha256=session_lifecycle._claim_sha256(claim_file),
                recovery_archive_dir=str(blocked_archive),
                disposition="superseded",
                disposition_reason="should not apply",
            )

    assert claim_file.read_bytes() == before
    assert worktree.exists()
    assert session_lifecycle._branch_exists(repo_root, branch)
    assert (worktree / "feature.txt").read_text(encoding="utf-8") == "converted work\n"
    _assert_preserved_lane_conflict(True)


def test_tracker_absent_refuses_untracked_files_it_cannot_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A recovery ref cannot hold untracked files, so capture fails closed."""

    from tests.test_session_cli import _native_actor  # noqa: PLC0415

    claim_file, _repo_root, worktree, branch = _trackerless_session_ended_lane_with_worktree(
        tmp_path, monkeypatch
    )
    (worktree / "scratch-notes.txt").write_text("unsaved analysis\n", encoding="utf-8")
    before = claim_file.read_bytes()

    with _native_actor("claude-code", "claude-code:reconciler"):
        with pytest.raises(ValueError, match="refuses untracked files"):
            session_lifecycle.close_session(
                agent="codex",
                project="enforced-planning",
                scope=branch,
                actor_session_id="claude-code:reconciler",
                reconcile_session_ended=True,
                tracker_absent=True,
                expected_claim_sha256=session_lifecycle._claim_sha256(claim_file),
                recovery_archive_dir=str(tmp_path / "archive" / "lane"),
                disposition="superseded",
                disposition_reason="should not apply",
            )
    assert claim_file.read_bytes() == before
    assert (worktree / "scratch-notes.txt").is_file()


def test_closed_lane_leaves_reusable_placeholder_for_live_sessions(tmp_path: Path) -> None:
    """A removed lane path stays a valid (empty) directory and can be reused.

    Another agent session may still record the lane as its working directory;
    a vanished path froze every tool call there (process_tracing, 2026-10-05).
    """
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

    assert session_lifecycle._remove_worktree_path(repo, worktree) == "removed"
    assert worktree.is_dir() and not any(worktree.iterdir())
    assert session_lifecycle._remove_worktree_path(repo, worktree) == "already_missing"

    _git(repo, "worktree", "add", "-b", "lane-again", str(worktree))
    assert (worktree / "README.md").read_text(encoding="utf-8") == "seed\n"
