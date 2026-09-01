"""Tests for native-session, canonical-claim integration authority."""

from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning import coordination_claims
from enforced_planning import integration_authority as authority_module
from enforced_planning.integration_authority import (
    IntegrationAuthorityAssertionV1,
    IntegrationAuthorityError,
    IntegrationTargetV1,
    assert_integration_authority,
    canonical_sha256,
    integration_authority_guard,
    validate_integration_authority,
)

NOW = datetime(2026, 9, 1, 20, 0, tzinfo=UTC)
SESSION = "codex:owner-thread"
ROOT_SHA = "a" * 40
HEAD_SHA = "b" * 40
SPEC_SHA = "c" * 64


def target() -> IntegrationTargetV1:
    return IntegrationTargetV1(
        repository="BrianMills2718/enforced-planning",
        project="enforced-planning",
        pr_number=332,
        branch="fix/review",
        base_sha=ROOT_SHA,
        head_sha=HEAD_SHA,
        review_spec_sha256=SPEC_SHA,
    )


def claim(tmp_path: Path, **updates) -> coordination_claims.ClaimRecord:
    source = tmp_path / "claim.yaml"
    source.write_text("owner: codex:owner-thread\nrevision: 1\n", encoding="utf-8")
    item = coordination_claims.ClaimRecord(
        agent="codex",
        claimed_at=NOW.isoformat(),
        expires_at=(NOW + timedelta(hours=2)).isoformat(),
        projects=["enforced-planning"],
        scope="fix/review",
        intent="finish exact reviewed head",
        claim_type="program",
        write_paths=["scripts/worktree-coordination/finish_pr.py"],
        read_paths=[],
        worktree_path=str(tmp_path / "worktree"),
        repo_root=str(tmp_path / "repo"),
        branch="fix/review",
        session_name="finish-review",
        broader_goal="finish reviewed PR without a central coordinator",
        tracker_path=str(tmp_path / "tracker.yaml"),
        session_id=SESSION,
        heartbeat_at=NOW.isoformat(),
        status="active",
        updated_at=NOW.isoformat(),
        parent_scope=None,
        notes=None,
        plan_ref="UNPLANNED",
        source_file=str(source),
        schema_version=6,
        progress_at=NOW.isoformat(),
        progress_kind="verified_commit",
        evidence_ref=HEAD_SHA,
        next_action="finish reviewed PR",
    )
    return replace(item, **updates)


def arrange(monkeypatch, item: coordination_claims.ClaimRecord, *, status="healthy"):
    monkeypatch.setenv("CODEX_THREAD_ID", "owner-thread")
    monkeypatch.setattr(
        coordination_claims,
        "list_claims",
        lambda *_args, **_kwargs: [item],
    )
    monkeypatch.setattr(
        coordination_claims,
        "claim_runtime_status",
        lambda *_args, **_kwargs: status,
    )
    monkeypatch.setattr(
        authority_module,
        "_validate_claimed_git_identity",
        lambda *_args, **_kwargs: None,
    )


def test_assertion_binds_exact_native_session_claim_and_review_spec(tmp_path, monkeypatch) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
    )
    assert assertion.claim.session_id == SESSION
    assert assertion.claim.scope == item.scope
    assert assertion.target.review_spec_sha256 == SPEC_SHA
    validate_integration_authority(
        assertion, expected_target=target(), agent="codex",
        repo_root=Path(item.repo_root), now=NOW,
    )


@pytest.mark.parametrize("status", ["stalled", "weak", "stale"])
def test_nonhealthy_claim_status_never_grants_integration(
    tmp_path, monkeypatch, status
) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item, status=status)
    with pytest.raises(IntegrationAuthorityError, match=f"status is {status}"):
        assert_integration_authority(
            target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
        )


@pytest.mark.parametrize("claim_status", ["blocked", "handoff"])
def test_nonactive_canonical_live_status_never_grants_integration(
    tmp_path, monkeypatch, claim_status
) -> None:
    item = claim(tmp_path, status=claim_status)
    arrange(monkeypatch, item)
    with pytest.raises(IntegrationAuthorityError, match="exactly one active"):
        assert_integration_authority(
            target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
        )


def test_wrong_native_session_cannot_borrow_branch_claim(tmp_path, monkeypatch) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    monkeypatch.setenv("CODEX_THREAD_ID", "different-thread")
    with pytest.raises(IntegrationAuthorityError, match="exactly one active"):
        assert_integration_authority(
            target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
        )


def test_stale_assertion_and_claim_transfer_both_fail(tmp_path, monkeypatch) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(),
        agent="codex",
        repo_root=Path(item.repo_root),
        now=NOW,
        validity=timedelta(seconds=30),
    )
    with pytest.raises(IntegrationAuthorityError, match="stale"):
        validate_integration_authority(
            assertion,
            expected_target=target(),
            agent="codex",
            repo_root=Path(item.repo_root),
            now=NOW + timedelta(seconds=30),
        )

    transferred = replace(item, session_id="codex:successor-thread")
    monkeypatch.setattr(
        coordination_claims,
        "list_claims",
        lambda *_args, **_kwargs: [transferred],
    )
    with pytest.raises(IntegrationAuthorityError, match="exactly one active"):
        validate_integration_authority(
            assertion,
            expected_target=target(),
            agent="codex",
            repo_root=Path(item.repo_root),
            now=NOW + timedelta(seconds=1),
        )


def test_heartbeat_and_progress_churn_preserve_premerge_assertion(
    tmp_path, monkeypatch
) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
    )
    refreshed = replace(
        item,
        heartbeat_at=(NOW + timedelta(minutes=1)).isoformat(),
        progress_at=(NOW + timedelta(minutes=1)).isoformat(),
        updated_at=(NOW + timedelta(minutes=1)).isoformat(),
    )
    monkeypatch.setattr(
        coordination_claims,
        "list_claims",
        lambda *_args, **_kwargs: [refreshed],
    )
    validate_integration_authority(
        assertion,
        expected_target=target(),
        agent="codex",
        repo_root=Path(item.repo_root),
        now=NOW + timedelta(minutes=1),
    )


def test_stable_claim_authority_change_invalidates_assertion(tmp_path, monkeypatch) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
    )
    changed = replace(item, plan_ref="goal:different-authority")
    monkeypatch.setattr(
        coordination_claims,
        "list_claims",
        lambda *_args, **_kwargs: [changed],
    )
    with pytest.raises(IntegrationAuthorityError, match="claim changed"):
        validate_integration_authority(
            assertion,
            expected_target=target(),
            agent="codex",
            repo_root=Path(item.repo_root),
            now=NOW + timedelta(seconds=1),
        )


def test_changed_review_spec_digest_invalidates_premerge_assertion(
    tmp_path, monkeypatch
) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
    )
    changed = target().model_copy(update={"review_spec_sha256": "e" * 64})
    with pytest.raises(IntegrationAuthorityError, match="review spec changed"):
        validate_integration_authority(
            assertion,
            expected_target=changed,
            agent="codex",
            repo_root=Path(item.repo_root),
            now=NOW + timedelta(seconds=1),
        )


def test_recomputed_assertion_cannot_change_owner(tmp_path, monkeypatch) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
    )
    payload = assertion.model_dump(mode="json")
    payload["claim"]["session_id"] = "codex:invented-thread"
    payload["assertion_sha256"] = canonical_sha256(
        {key: value for key, value in payload.items() if key != "assertion_sha256"}
    )
    forged = IntegrationAuthorityAssertionV1.model_validate(payload)
    with pytest.raises(IntegrationAuthorityError, match="another native session"):
        validate_integration_authority(
            forged, expected_target=target(), agent="codex",
            repo_root=Path(item.repo_root), now=NOW,
        )


def test_plain_digest_tamper_is_rejected() -> None:
    payload = {
        "schema_version": "1.0",
        "record_type": "integration_authority_assertion",
        "target": target().model_dump(mode="json"),
        "claim": {
            "agent": "codex",
            "session_id": SESSION,
            "scope": "fix/review",
            "claim_authority_sha256": "d" * 64,
            "plan_ref": "UNPLANNED",
            "work_graph_sha256": None,
            "work_unit_id": None,
            "approval_revisions": [],
        },
        "asserted_at": NOW.isoformat(),
        "valid_until": (NOW + timedelta(minutes=1)).isoformat(),
        "assertion_sha256": "0" * 64,
    }
    with pytest.raises(ValidationError, match="digest"):
        IntegrationAuthorityAssertionV1.model_validate(payload)


def test_guard_holds_registry_lock_across_caller_operation(tmp_path, monkeypatch) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root), now=NOW,
    )
    events: list[str] = []

    @contextmanager
    def locked(_claims_dir=None):
        events.append("lock")
        yield
        events.append("unlock")

    monkeypatch.setattr(coordination_claims, "claim_registry_lock", locked)
    with integration_authority_guard(
        assertion, expected_target=target(), agent="codex",
        repo_root=Path(item.repo_root), now=NOW,
    ):
        events.append("remote-head-cas")
    assert events == ["lock", "remote-head-cas", "unlock"]


def test_authentic_linked_worktree_identity_and_exact_head_are_required(
    tmp_path, monkeypatch
) -> None:
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    repo.mkdir()

    def git(*args: str, cwd: Path = repo) -> str:
        result = subprocess.run(
            ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()

    git("init", "-b", "main")
    git("config", "user.email", "test@example.invalid")
    git("config", "user.name", "Integration Authority Test")
    (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
    git("add", "tracked.txt")
    git("commit", "-m", "base")
    git("worktree", "add", "-b", "fix/review", str(worktree))
    head = git("rev-parse", "HEAD", cwd=worktree)

    item = claim(
        tmp_path,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="fix/review",
    )
    monkeypatch.setenv("CODEX_THREAD_ID", "owner-thread")
    monkeypatch.setattr(
        coordination_claims, "list_claims", lambda *_args, **_kwargs: [item]
    )
    monkeypatch.setattr(
        coordination_claims,
        "claim_runtime_status",
        lambda *_args, **_kwargs: "healthy",
    )
    exact_target = target().model_copy(update={"head_sha": head})
    assertion = assert_integration_authority(
        target=exact_target, agent="codex", repo_root=repo, now=NOW,
    )
    assert assertion.target.head_sha == head

    (worktree / "untracked.txt").write_text("dirty\n", encoding="utf-8")
    with pytest.raises(IntegrationAuthorityError, match="dirty"):
        validate_integration_authority(
            assertion,
            expected_target=exact_target,
            agent="codex",
            repo_root=repo,
            now=NOW + timedelta(seconds=1),
        )


def test_process_death_releases_registry_lock_for_transferred_successor(
    tmp_path, monkeypatch
) -> None:
    item = claim(tmp_path)
    arrange(monkeypatch, item)
    claims_dir = tmp_path / "claims"
    current = [item]
    monkeypatch.setattr(
        coordination_claims,
        "list_claims",
        lambda *_args, **_kwargs: current,
    )
    assertion = assert_integration_authority(
        target=target(), agent="codex", repo_root=Path(item.repo_root),
        claims_dir=claims_dir, now=NOW,
    )

    pid = os.fork()
    if pid == 0:
        with integration_authority_guard(
            assertion,
            expected_target=target(),
            agent="codex",
            repo_root=Path(item.repo_root),
            claims_dir=claims_dir,
            now=NOW,
        ):
            os._exit(17)
        os._exit(99)
    _pid, status = os.waitpid(pid, 0)
    assert os.waitstatus_to_exitcode(status) == 17

    successor = replace(item, session_id="codex:successor-thread")
    current[0] = successor
    monkeypatch.setenv("CODEX_THREAD_ID", "successor-thread")
    replacement = assert_integration_authority(
        target=target(),
        agent="codex",
        repo_root=Path(item.repo_root),
        claims_dir=claims_dir,
        now=NOW + timedelta(seconds=1),
    )
    assert replacement.claim.session_id == "codex:successor-thread"
