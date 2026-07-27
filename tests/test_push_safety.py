"""Tests for branch push safety and concern routing."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import concern_routing
from enforced_planning import coordination_claims
from enforced_planning import push_safety


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


def test_push_check_fails_on_default_branch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default-branch pushes should block even before overlap analysis."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    assert any(item["code"] == "default_branch_push" for item in payload["issues"])


def test_push_check_detects_overlapping_live_write_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Push-check should block when branch delta overlaps another live write claim."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('hi')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    other_worktree = tmp_path / "demo_worktrees" / "plan-99-other"
    other_worktree.mkdir(parents=True)
    subprocess.run(["git", "-C", str(repo_root), "branch", "plan-99-other"], check=True, capture_output=True, text=True)
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

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    assert any(item["code"] == "overlapping_write_claim" for item in payload["issues"])


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
            "branch": "plan-42-demo",
                "worktree_path": str(repo_root),
                "session_id": "codex:thread-1",
                "session_name": "current-branch-owner",
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
    assert default_payload["ok"]
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
            "branch": "plan-identity",
            "worktree_path": str(repo_root),
            "session_id": "codex:legacy",
            "status": "active",
        },
    )

    payload = push_safety.evaluate_push_safety(repo_root)

    assert not payload["ok"]
    finding = next(item for item in payload["issues"] if item["code"] == "no_healthy_branch_claim")
    assert finding["details"]["claims"][0]["health_issues"] == ["missing_session_name"]


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
    _write_claim(
        claims_dir,
        "attributed.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "plan-identity",
            "intent": "Attributed worktree lane",
            "claim_type": "program",
            "branch": "plan-identity",
            "worktree_path": str(worktree),
            "session_id": "codex:thread-identity",
            "session_name": "identity-enforcement",
            "heartbeat_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
        },
    )

    payload = push_safety.evaluate_push_safety(worktree)

    assert payload["ok"]
    assert payload["project"] == "demo"
    assert payload["branch_claim_count"] == 1


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
