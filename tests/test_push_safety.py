"""Tests for branch push safety and concern routing."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    claim_mutation_receipts,
    concern_routing,
    coordination_claims,
    coordination_messages,
    push_safety,
)


@pytest.fixture(autouse=True)
def _isolate_claim_mutation_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep push-safety fixtures out of the shared operator ledger."""

    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )


def _init_git_repo(repo_root: Path) -> None:
    """Create a tiny git repo with one initial commit and branch identity."""

    subprocess.run(["git", "init", "-b", "main", str(repo_root)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "seed"], check=True, capture_output=True, text=True)


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Persist one YAML claim fixture into the temporary claims dir."""

    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_push_check_warns_on_default_branch_without_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ownership policy, not this generic check, governs direct default pushes."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])

    payload = push_safety.evaluate_push_safety(repo_root)

    assert payload["ok"]
    assert {item["code"] for item in payload["warnings"]} >= {
        "default_branch_push",
        "missing_branch_claim",
    }


def test_push_check_ignores_untracked_local_session_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Untracked local session state cannot alter a Git push's published delta."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    session_artifact = repo_root / ".claude" / "sessions" / "current.json"
    session_artifact.parent.mkdir(parents=True)
    session_artifact.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])

    payload = push_safety.evaluate_push_safety(repo_root)

    assert payload["ok"]
    assert not any(item["code"] == "dirty_worktree" for item in payload["issues"])


def test_push_check_blocks_tracked_uncommitted_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tracked worktree changes still make a publication candidate ambiguous."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    (repo_root / "README.md").write_text("changed\n", encoding="utf-8")
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    assert any(item["code"] == "dirty_worktree" for item in payload["issues"])


@pytest.mark.parametrize("other_claim_type", ["write", "program"])
def test_push_check_detects_overlapping_live_write_owned_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    other_claim_type: str,
) -> None:
    """Push-check should block when branch delta overlaps another claim's write ownership
    AND the two branches' actual content would really conflict on integration."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    # The other lane branches from the same seed commit and independently adds
    # its own, differently-worded feature.py -- a genuine content conflict on
    # eventual integration, not just a branch pointer aliasing the same
    # commit. The merge-tree prediction added alongside this test now only
    # blocks on a declared-path overlap when a real conflict like this one is
    # predicted.
    other_worktree = tmp_path / "demo_worktrees" / "plan-99-other"
    other_worktree.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-99-other"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('a genuinely different version')\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "feature.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "other lane's divergent feature.py"], check=True, capture_output=True, text=True)

    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('hi')\n", encoding="utf-8")
    (repo_root / "independent.py").write_text("print('continue')\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "feature.py", "independent.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    _write_claim(
        claims_dir,
        "current.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-42-demo",
            "intent": "Own current branch",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-42-demo",
            "worktree_path": str(repo_root),
                "session_id": "codex:thread-1",
                "session_name": "current-branch-owner",
                "heartbeat_at": datetime.now(timezone.utc).isoformat(),
                "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-09T10:05:00+00:00",
            "expires_at": "2099-04-09T11:05:00+00:00",
            "projects": ["demo"],
            "scope": "reviewed-scope",
                "intent": "Touch feature file",
                "claim_type": other_claim_type,
                "write_paths": ["feature.py"],
                "branch": "plan-99-other",
                "worktree_path": str(other_worktree),
                "session_id": "claude-code:session-1",
                "status": "active",
            },
        )

    sent_calls: list[dict] = []

    def _fake_route_concern(**kwargs: object) -> dict:
        sent_calls.append(kwargs)
        return {
            "ok": True,
            "route": "coordination_mailbox",
            "destination": "fake/message/path.json",
            "target_branch": kwargs["target_branch"],
            "recipient": kwargs.get("recipient"),
            "evidence_state": "persisted",
        }

    monkeypatch.setattr(concern_routing, "route_concern", _fake_route_concern)

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    assert any(item["code"] == "overlapping_write_claim" for item in payload["issues"])
    assert payload["continuation"] == {
        "state": "integration_wait",
        "goal_blocked": False,
        "blocked_paths": ["feature.py"],
        "writable_paths": ["independent.py"],
        "integration_owners": [
            {"agent": "claude-code", "scope": "reviewed-scope"}
        ],
        "recommended_next_action": (
            "Split or defer the blocked paths, publish a claim-compatible checkpoint, "
            "and continue another authorized ready work unit."
        ),
    }

    # The colliding lane's owner is actually notified, not just detected.
    assert len(sent_calls) == 1
    call = sent_calls[0]
    assert call["target_branch"] == "plan-99-other"
    assert call["recipient"] == "claude-code:session-1"
    assert call["project"] == "demo"
    assert call["agent"] == "codex"
    assert "feature.py" in call["content"]
    assert call["idempotency_key"] == "overlapping_write_claim:plan-42-demo|reviewed-scope|feature.py"

    finding = next(item for item in payload["issues"] if item["code"] == "overlapping_write_claim")
    assert finding["details"]["notification"] == {
        "attempted": True,
        "ok": True,
        "route": "coordination_mailbox",
        "destination": "fake/message/path.json",
    }


def test_push_check_overlapping_write_claim_surfaces_other_contact_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """overlapping_write_claim exposes the blocking claim's session_id and
    contact_ref, so the blocked session can resolve who owns it through
    ListAgents instead of only seeing an opaque session_id.

    This is the root-cause fix for the 2026-09-14 gap where a session blocked
    by check-enforced-planning-vendor-drift-20260914's broad claim had no way
    to correlate its session_id to a ListAgents entry and message the owner
    directly.
    """

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    other_worktree = tmp_path / "demo_worktrees" / "plan-99-other"
    other_worktree.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-99-other"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('a genuinely different version')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "other lane's divergent feature.py"], check=True, capture_output=True, text=True)

    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    _write_claim(
        claims_dir,
        "current.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-42-demo",
            "intent": "Own current branch",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-42-demo",
            "worktree_path": str(repo_root),
            "session_id": "codex:thread-1",
            "session_name": "current-branch-owner",
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-09T10:05:00+00:00",
            "expires_at": "2099-04-09T11:05:00+00:00",
            "projects": ["demo"],
            "scope": "reviewed-scope",
            "intent": "Touch feature file",
            "claim_type": "write",
            "write_paths": ["feature.py"],
            "branch": "plan-99-other",
            "worktree_path": str(other_worktree),
            "session_id": "claude-code:session-1",
            "contact_ref": "check-enforced-planning-vendor-drift-20260914",
            "status": "active",
        },
    )

    monkeypatch.setattr(concern_routing, "route_concern", lambda **kwargs: {"ok": True, "route": "coordination_mailbox", "destination": "x"})

    payload = push_safety.evaluate_push_safety(repo_root)

    finding = next(item for item in payload["issues"] if item["code"] == "overlapping_write_claim")
    assert finding["details"]["other_session_id"] == "claude-code:session-1"
    assert finding["details"]["other_contact_ref"] == "check-enforced-planning-vendor-drift-20260914"


def test_push_check_warns_instead_of_blocking_a_predicted_clean_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A declared write_paths overlap that would actually merge cleanly (two
    lanes editing different lines of the same file) warns instead of
    blocking -- the metadata overlap alone is not proof of a real conflict."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    (repo_root / "shared.py").write_text("line one\nline two\nline three\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "shared.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "seed shared.py"], check=True, capture_output=True, text=True)

    other_worktree = tmp_path / "demo_worktrees" / "plan-99-other"
    other_worktree.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-99-other"], check=True, capture_output=True, text=True)
    (repo_root / "shared.py").write_text("line one\nline two\nline three\nother lane's own new line\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "commit", "-am", "other lane appends its own line"], check=True, capture_output=True, text=True)

    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "shared.py").write_text("this lane's own new line\nline one\nline two\nline three\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "commit", "-am", "this lane prepends its own line"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    current_tracker_path = sessions_dir / "current.yaml"
    current_tracker_path.write_text("session_id: codex:thread-1\n", encoding="utf-8")
    _write_claim(
        claims_dir,
        "current.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-42-demo",
            "intent": "Own current branch",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-42-demo",
            "worktree_path": str(repo_root),
            "repo_root": str(repo_root),
            "broader_goal": "Demonstrate a predicted-clean overlap warning",
            "tracker_path": str(current_tracker_path),
            "session_id": "codex:thread-1",
            "session_name": "current-branch-owner",
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-09T10:05:00+00:00",
            "expires_at": "2099-04-09T11:05:00+00:00",
            "projects": ["demo"],
            "scope": "reviewed-scope",
            "intent": "Append to shared file",
            "claim_type": "write",
            "write_paths": ["shared.py"],
            "branch": "plan-99-other",
            "worktree_path": str(other_worktree),
            "session_id": "claude-code:session-1",
            "status": "active",
        },
    )

    def _fail_if_called(**_kwargs: object) -> dict:
        raise AssertionError("route_concern must not fire for a predicted-clean overlap")

    monkeypatch.setattr(concern_routing, "route_concern", _fail_if_called)

    payload = push_safety.evaluate_push_safety(repo_root)

    assert payload["ok"]
    assert not any(item["code"] == "overlapping_write_claim" for item in payload["issues"])
    assert any(
        item["code"] == "overlapping_write_claim_predicted_clean" for item in payload["warnings"]
    )


def test_push_check_overlapping_write_claim_survives_notify_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A notification delivery failure never changes whether the push blocks."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    other_worktree = tmp_path / "demo_worktrees" / "plan-99-other"
    other_worktree.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-99-other"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('a genuinely different version')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "other lane's divergent feature.py"], check=True, capture_output=True, text=True)

    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    _write_claim(
        claims_dir,
        "current.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-42-demo",
            "intent": "Own current branch",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-42-demo",
            "worktree_path": str(repo_root),
            "session_id": "codex:thread-1",
            "session_name": "current-branch-owner",
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-09T10:05:00+00:00",
            "expires_at": "2099-04-09T11:05:00+00:00",
            "projects": ["demo"],
            "scope": "reviewed-scope",
            "intent": "Touch feature file",
            "claim_type": "write",
            "write_paths": ["feature.py"],
            "branch": "plan-99-other",
            "worktree_path": str(other_worktree),
            "session_id": "claude-code:session-1",
            "status": "active",
        },
    )

    def _raise(**_kwargs: object) -> dict:
        raise coordination_messages.UnknownSessionError("recipient session is stale")

    monkeypatch.setattr(concern_routing, "route_concern", _raise)

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    finding = next(item for item in payload["issues"] if item["code"] == "overlapping_write_claim")
    assert finding["details"]["notification"]["attempted"] is True
    assert finding["details"]["notification"]["ok"] is False
    assert "UnknownSessionError" in finding["details"]["notification"]["error"]


@pytest.mark.parametrize(
    ("claim_session_id", "change_after_integration", "integration_allowed"),
    [
        ("codex:thread-1", False, True),
        ("codex:thread-2", False, False),
        ("codex:thread-1", True, False),
    ],
)
def test_default_push_allows_only_current_session_integrated_source_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    claim_session_id: str,
    change_after_integration: bool,
    integration_allowed: bool,
) -> None:
    """Integration may retain its source claim, but another session still blocks."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "maintenance-source"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "feature.py").write_text("integrated\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "feature.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "maintenance source"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "main"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--ff-only", "maintenance-source"],
        check=True,
        capture_output=True,
        text=True,
    )
    if change_after_integration:
        (repo_root / "feature.py").write_text("changed after integration\n", encoding="utf-8")
        subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-am", "later claimed-path change"],
            check=True,
            capture_output=True,
            text=True,
        )

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-1")
    now = datetime.now(timezone.utc).isoformat()
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir(parents=True)
    tracker_path = sessions_dir / "source.yaml"
    tracker_path.write_text(f"session_id: {claim_session_id}\n", encoding="utf-8")
    _write_claim(
        claims_dir,
        "source.yaml",
        {
            "schema_version": 3,
            "agent": "codex",
            "claimed_at": now,
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "maintenance-source",
            "intent": "Own the integrated feature path until publication",
            "plan_ref": "UNPLANNED",
            "claim_type": "write",
            "write_paths": ["feature.py"],
            "repo_root": str(repo_root),
            "branch": "maintenance-source",
            "worktree_path": str(repo_root),
            "session_id": claim_session_id,
            "session_name": "maintenance-source",
            "broader_goal": "Publish maintenance source",
            "tracker_path": str(tracker_path),
            "heartbeat_at": now,
            "updated_at": now,
            "progress_at": now,
            "progress_kind": "verified_commit",
            "evidence_ref": "maintenance-source",
            "next_action": "Publish the integrated commit",
            "status": "active",
        },
    )

    payload = push_safety.evaluate_push_safety(repo_root)

    issue_codes = {item["code"] for item in payload["issues"]}
    warning_codes = {item["code"] for item in payload["warnings"]}
    if integration_allowed:
        assert payload["ok"]
        assert "overlapping_write_claim" not in issue_codes
        assert "same_session_integrated_claim" in warning_codes
    else:
        assert not payload["ok"]
        assert "overlapping_write_claim" in issue_codes
        assert "same_session_integrated_claim" not in warning_codes


def test_push_check_warns_on_active_decisions_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Active decisions should surface as warnings unless explicitly promoted to blockers."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    tracker_path = tmp_path / "current-tracker.yaml"
    tracker_path.write_text("session_id: codex:thread-1\n", encoding="utf-8")
    _write_claim(
        claims_dir,
        "current.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-42-demo",
            "intent": "Own current branch",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-42-demo",
            "worktree_path": str(repo_root),
            "repo_root": str(repo_root),
            "session_id": "codex:thread-1",
            "session_name": "current-branch-owner",
            "broader_goal": "Own the current branch",
            "tracker_path": str(tracker_path),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        },
    )
    decision_queries: list[str] = []

    def _load_decisions(project: str, limit: int = 5) -> list[dict[str, str]]:
        decision_queries.append(project)
        return [{"content": "Do not mutate scoring interfaces until Plan #9 closes."}]

    monkeypatch.setattr(push_safety, "load_active_decisions", _load_decisions)

    default_payload = push_safety.evaluate_push_safety(repo_root)
    assert default_payload["ok"], default_payload
    assert decision_queries == []
    assert not any(
        item["code"] == "active_decisions_present"
        for item in default_payload["warnings"]
    )

    payload = push_safety.evaluate_push_safety(
        repo_root,
        include_active_decisions=True,
    )

    assert payload["ok"]
    assert decision_queries == ["demo"]
    assert any(item["code"] == "active_decisions_present" for item in payload["warnings"])


def test_push_check_rejects_branch_claim_without_complete_session_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A branch cannot satisfy push safety with an anonymous legacy-style claim."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-identity"], check=True, capture_output=True, text=True)
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    _write_claim(
        claims_dir,
        "anonymous.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "plan-identity",
            "intent": "Unattributed legacy lane",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-identity",
            "worktree_path": str(repo_root),
            "repo_root": str(repo_root),
            "session_id": "codex:legacy",
            "broader_goal": "Preserve anonymous-claim rejection coverage",
            "tracker_path": str(tmp_path / "anonymous-tracker.yaml"),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": "2099-08-22T00:00:00+00:00",
            "status": "active",
            "progress_at": "2000-01-01T00:00:00+00:00",
            "progress_kind": "verified_commit",
            "evidence_ref": "commit:legacy",
            "next_action": "publish only with a complete owner contract",
        },
    )

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    finding = next(item for item in payload["issues"] if item["code"] == "no_healthy_branch_claim")
    assert finding["details"]["claims"][0]["health_issues"] == ["missing_session_name"]
    assert coordination_claims.claim_runtime_status(
        coordination_claims.check_claims("demo")[0]
    ) == "weak"


def test_push_check_preserves_authority_for_report_only_stalled_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A progress stall requests action but cannot revoke the live branch owner's push authority."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "plan-110-progress"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "progress.py").write_text("result = 'observed'\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "progress.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "progress"],
        check=True,
        capture_output=True,
        text=True,
    )
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    _write_claim(
        claims_dir,
        "owner.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "plan-110-progress",
            "intent": "Own the progress branch",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-110-progress",
            "worktree_path": str(repo_root),
            "repo_root": str(repo_root),
            "session_id": "codex:owner",
            "session_name": "progress-owner",
            "broader_goal": "Own the progress branch",
            "tracker_path": str(tmp_path / "progress-tracker.yaml"),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": "2099-08-22T00:00:00+00:00",
            "status": "active",
            "progress_at": "2000-01-01T00:00:00+00:00",
            "progress_kind": "verified_commit",
            "evidence_ref": "commit:abc123",
            "next_action": "publish the checkpoint",
        },
    )

    payload = push_safety.evaluate_push_safety(repo_root)

    assert payload["ok"]
    assert coordination_claims.claim_runtime_status(
        coordination_claims.check_claims("demo")[0]
    ) == "stalled"
    assert not any(item["code"] == "no_healthy_branch_claim" for item in payload["issues"])


def test_push_check_resolves_canonical_project_from_linked_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A linked worktree must query claims under its canonical repository name."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    worktree = repo_root / "worktrees" / "plan-identity"
    worktree.parent.mkdir()
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b", "plan-identity", str(worktree)],
        check=True,
        capture_output=True,
        text=True,
    )
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    tracker_path = tmp_path / "identity-tracker.yaml"
    tracker_path.write_text("session_id: codex:thread-identity\n", encoding="utf-8")
    _write_claim(
        claims_dir,
        "attributed.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "plan-identity",
            "intent": "Attributed worktree lane",
            "claim_type": "program",
            "plan_ref": "UNPLANNED",
            "branch": "plan-identity",
            "worktree_path": str(worktree),
            "repo_root": str(repo_root),
            "session_id": "codex:thread-identity",
            "session_name": "identity-enforcement",
            "broader_goal": "Exercise linked-worktree project resolution",
            "tracker_path": str(tracker_path),
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        },
    )

    payload = push_safety.evaluate_push_safety(worktree)

    assert payload["ok"]
    assert payload["project"] == "demo"
    assert payload["branch_claim_count"] == 1


def test_changed_paths_prefers_remote_default_over_stale_local_main(tmp_path: Path) -> None:
    """Already-merged remote files must not reappear because local main is stale."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "feature"], check=True, capture_output=True, text=True)
    (repo_root / "merged.py").write_text("merged\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "merged.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "remote merged state"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/main", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "feature.py").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature delta"], check=True, capture_output=True, text=True)

    assert push_safety.changed_paths_since_default(repo_root, "main") == ["feature.py"]


def test_create_review_claim_uses_target_branch_as_parent_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review claims should advertise the target branch they are inspecting."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "review-lane"], check=True, capture_output=True, text=True)
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-999")

    payload = concern_routing.create_review_claim(
        repo_root=repo_root,
        agent="codex",
        project="demo",
        target_branch="plan-99-target",
        intent="Inspect target lane",
        write_paths=["src/demo.py|tests/test_demo.py"],
        plan_ref="UNPLANNED",
        session_name="review-plan-99",
    )

    assert payload["ok"]
    claim_file = claims_dir / "codex_demo_review-plan-99-target.yaml"
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["claim_type"] == "review"
    assert claim_payload["parent_scope"] == "plan-99-target"
    assert claim_payload["write_paths"] == ["src/demo.py", "tests/test_demo.py"]


def test_create_review_claim_allows_read_only_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Read-only review should be visible without claiming false write ownership."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "review-lane"],
        check=True,
        capture_output=True,
        text=True,
    )
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-read-only")
    _write_claim(
        claims_dir,
        "writer.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-99-target",
            "intent": "Implement the target lane",
            "claim_type": "write",
            "plan_ref": "UNPLANNED",
            "write_paths": ["src/demo.py"],
            "branch": "plan-99-target",
            "worktree_path": str(tmp_path / "target-worktree"),
            "session_id": "claude-code:target-writer",
            "status": "active",
        },
    )

    payload = concern_routing.create_review_claim(
        repo_root=repo_root,
        agent="codex",
        project="demo",
        target_branch="plan-99-target",
        intent="Inspect target lane without applying fixes",
        write_paths=[],
        plan_ref="UNPLANNED",
        session_name="review-plan-99",
    )

    assert payload["ok"]
    assert payload["write_paths"] == []
    claim_file = claims_dir / "codex_demo_review-plan-99-target.yaml"
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["claim_type"] == "review"
    assert claim_payload["parent_scope"] == "plan-99-target"
    assert claim_payload["write_paths"] == []
    claims = coordination_claims.check_claims("demo")
    review_claim = next(item for item in claims if item.claim_type == "review")
    writer_claim = next(item for item in claims if item.claim_type == "write")
    interaction = coordination_claims.evaluate_claim(
        review_claim,
        active_claims=[writer_claim],
    )
    assert interaction.hard_conflicts == []
    assert interaction.interactions[0].overlapping_write_paths == []


def test_route_concern_uses_canonical_mailbox_when_no_pr_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unpublished branches should receive concerns through the canonical mailbox."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "review-lane"], check=True, capture_output=True, text=True)
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(concern_routing, "_open_pr_for_branch", lambda repo_root, branch: None)
    monkeypatch.setenv("CODEX_THREAD_ID", "sender-123")
    _write_claim(
        claims_dir,
        "sender.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "review-lane",
            "intent": "Review target lane",
            "claim_type": "program",
            "branch": "review-lane",
            "session_id": "codex:sender-123",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "target.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-09T10:00:00+00:00",
            "expires_at": "2099-04-09T11:00:00+00:00",
            "projects": ["demo"],
            "scope": "plan-99-target",
            "intent": "Target lane",
            "claim_type": "program",
            "branch": "plan-99-target",
            "worktree_path": str(tmp_path / "demo_worktrees" / "plan-99-target"),
            "session_name": "target-lane-session",
            "session_id": "claude-code:target-456",
            "status": "active",
        },
    )

    payload = concern_routing.route_concern(
        repo_root=repo_root,
        agent="codex",
        project="demo",
        target_branch="plan-99-target",
        subject="Boundary concern",
        content="Please stop mutating the shared surface directly.",
    )

    assert payload["ok"]
    assert payload["route"] == "coordination_mailbox"
    assert payload["recipient"] == "claude-code:target-456"
    assert payload["evidence_state"] == "persisted"
    message_file = Path(payload["destination"])
    assert message_file.exists()
    assert "Boundary concern" in message_file.read_text(encoding="utf-8")
    assert not (repo_root / ".claude" / "messages").exists()


def test_route_concern_labels_pr_comment_as_fallback_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful PR comment must never masquerade as mailbox observation."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    monkeypatch.setattr(
        concern_routing,
        "_open_pr_for_branch",
        lambda repo_root, branch: {
            "number": 42,
            "url": "https://example.invalid/pull/42",
        },
    )
    monkeypatch.setattr(
        concern_routing,
        "_run_gh",
        lambda repo_root, args: subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr=""),
    )

    payload = concern_routing.route_concern(
        repo_root=repo_root,
        agent="codex",
        project="demo",
        target_branch="published-lane",
        subject="Review concern",
        content="Please inspect the boundary.",
    )

    assert payload["route"] == "pr_comment"
    assert payload["evidence_state"] == "fallback_published"
    assert payload["message_id"] is None


def test_load_active_decisions_ignores_prefix_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    """CLI noise before the JSON payload should not break raw decision parsing."""

    payload = "TIMEOUT_DISABLED[embed]: ignored\n[{\"content\": \"test\"}]"

    def _fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(args=["agent-memory"], returncode=0, stdout=payload, stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    records = push_safety.load_active_decisions("demo")

    assert records == [{"content": "test"}]


def test_publishing_an_append_only_entry_is_not_claim_contention() -> None:
    """A lane must be able to publish the entry the append-only exemption let it create."""

    claim = coordination_claims.normalize_claim(
        {
            "agent": "codex",
            "projects": ["project-meta"],
            "scope": "another-learning-lane",
            "claim_type": "program",
            "intent": "record another learning",
            "write_paths": ["learnings/entries"],
        },
        source_file="/tmp/other.yaml",
    )
    assert claim is not None

    overlaps = push_safety._claim_overlap_for_paths(
        ["learnings/entries/lrn-20260826T191238509799Z-ff032639cf.json"], claim
    )

    assert overlaps == []


def test_a_real_shared_path_still_blocks_publication() -> None:
    """The exemption is scoped to append-only stores, not to claims generally."""

    claim = coordination_claims.normalize_claim(
        {
            "agent": "codex",
            "projects": ["project-meta"],
            "scope": "docs-lane",
            "claim_type": "program",
            "intent": "edit ops docs",
            "write_paths": ["docs/ops", "learnings"],
        },
        source_file="/tmp/other.yaml",
    )
    assert claim is not None

    assert push_safety._claim_overlap_for_paths(["docs/ops/POLICY.md"], claim) == [
        "docs/ops/POLICY.md <-> docs/ops"
    ]
    # `learnings` also reaches learnings.md, which lanes rewrite, so it stays exclusive.
    assert push_safety._claim_overlap_for_paths(["learnings/entries/lrn-x.json"], claim) == [
        "learnings/entries/lrn-x.json <-> learnings"
    ]
