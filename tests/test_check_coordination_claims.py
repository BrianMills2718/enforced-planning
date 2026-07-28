"""Tests for coordination-claim schema v2 and overlap detection."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.prewrite_claim_fast import projection_path_for, registry_digest


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "check_coordination_claims.py"


def _load_module():
    """Load the standalone coordination-claims script as a module."""
    module_name = "check_coordination_claims_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Write one YAML claim fixture into the temporary claims directory."""
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _plan_session_claim(
    module,
    *,
    agent: str,
    scope: str,
    claim_type: str,
    parent_scope: str | None = None,
    plan_ref: str = "Plan #0141",
):
    """Build one complete live claim for hierarchy validation tests."""

    return module.build_candidate_claim(
        agent=agent,
        project="onto-canon6",
        scope=scope,
        intent=f"work in {scope}",
        plan_ref=plan_ref,
        claim_type=claim_type,
        write_paths=[f"src/{scope}.py"] if claim_type == "write" else [],
        repo_root="~/projects/onto-canon6",
        worktree_path=f"~/projects/onto-canon6/worktrees/{scope}",
        branch=scope,
        session_name=scope,
        broader_goal="Complete Plan 0141",
        tracker_path=f"~/.claude/coordination/sessions/onto-canon6/{scope}.yaml",
        session_id=f"{agent}:{scope}",
        parent_scope=parent_scope,
    )


def _init_git_repo(repo_root: Path) -> None:
    """Create a minimal git repo with a configured identity."""
    subprocess.run(["git", "init", "-b", "main", str(repo_root)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "seed"], check=True, capture_output=True, text=True)


def _commit_work_graph(repo_root: Path, *, plan: int, unit: dict) -> str:
    """Commit one canonical work graph and return its repo-relative path."""

    relative = f"docs/plans/{plan}_fixture_work_graph.json"
    path = repo_root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"units": [unit]}, indent=2) + "\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", relative], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "work graph"], check=True, capture_output=True, text=True)
    return relative


def test_normalize_claim_reads_v1_schema_as_program_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Legacy v1 claims should normalize into the v2 in-memory record cleanly."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "legacy.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "project": "project-meta",
            "scope": "phase-6-ops-and-governance",
            "intent": "Broad governance cleanup",
        },
    )

    claims = module.check_claims("project-meta")

    assert len(claims) == 1
    claim = claims[0]
    assert claim.claim_type == "program"
    assert claim.projects == ["project-meta"]
    assert claim.write_paths == []
    assert claim.schema_version == 1


def test_evaluate_claim_detects_parent_child_write_overlap_as_hard_conflict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Write claims should hard-conflict on parent-directory and child-file overlap."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "existing.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "docs-authority",
            "intent": "Patch authority docs",
            "claim_type": "write",
            "write_paths": ["docs/ops"],
            "status": "active",
        },
    )

    candidate = module.build_candidate_claim(
        agent="codex",
        project="project-meta",
        scope="coordination-v2",
        intent="Patch claims tool",
        claim_type="write",
        write_paths=["docs/ops/INDEX.md"],
    )
    result = module.evaluate_claim(candidate, active_claims=module.check_claims("project-meta"))

    assert len(result.hard_conflicts) == 1
    conflict = result.hard_conflicts[0]
    assert conflict.reason == "write_paths overlap across active write claims"
    assert conflict.overlapping_write_paths == ["docs/ops/INDEX.md <-> docs/ops"]


def test_evaluate_claim_marks_review_vs_write_overlap_as_soft_overlap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Review claims should warn, not hard-block, against active write claims."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "existing.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "coordination-v2",
            "intent": "Patch claims tool",
            "claim_type": "write",
            "write_paths": ["scripts/check_coordination_claims.py"],
            "status": "active",
        },
    )

    candidate = module.build_candidate_claim(
        agent="codex",
        project="project-meta",
        scope="review-coordination-v2",
        intent="Review claim-tool patch",
        claim_type="review",
        write_paths=["scripts/check_coordination_claims.py"],
    )
    result = module.evaluate_claim(candidate, active_claims=module.check_claims("project-meta"))

    assert not result.hard_conflicts
    assert len(result.interactions) == 1
    assert result.interactions[0].severity == "soft_overlap"


def test_build_candidate_claim_rejects_write_claim_without_write_paths() -> None:
    """New narrow write claims should fail loudly without explicit write paths."""
    module = _load_module()

    with pytest.raises(ValueError, match="Write claims require at least one --write-path"):
        module.build_candidate_claim(
            agent="codex",
            project="project-meta",
            scope="coordination-v2",
            intent="Patch claims tool",
            claim_type="write",
            write_paths=[],
        )


def test_create_claim_requires_live_metadata_for_new_program_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New active program claims should fail loudly without live ownership metadata."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    with pytest.raises(ValueError, match="--branch, --worktree-path"):
        module.create_claim(
            "codex",
            "project-meta",
            "phase-6-ops-and-governance",
            "Broad governance cleanup",
            plan_ref="Plan #62",
        )


def test_create_claim_accepts_program_claim_with_live_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New live program claims should succeed once ownership metadata is explicit."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    ok, message = module.create_claim(
        "codex",
        "project-meta",
        "phase-6-ops-and-governance",
        "Broad governance cleanup",
        plan_ref="Plan #62",
        branch="plan-90-coordination-graph-runtime",
        worktree_path="~/projects/project-meta_worktrees/plan-90-coordination-graph-runtime",
        session_id="codex-session-1",
        session_name="coordination-governance",
    )

    assert ok
    assert "[program]" in message
    claim_file = claims_dir / "codex_project-meta_phase-6-ops-and-governance.yaml"
    payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert payload["claim_type"] == "program"
    assert payload["branch"] == "plan-90-coordination-graph-runtime"
    assert payload["session_id"] == "codex-session-1"
    projection_path = projection_path_for(claims_dir)
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    assert projection["registry_digest"] == registry_digest(claims_dir)
    assert projection["claims"][0]["session_id"] == "codex-session-1"


def test_heartbeat_and_release_refresh_prewrite_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every sanctioned live-claim mutation should leave a current projection."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    ok, _message = module.create_claim(
        "codex",
        "project-meta",
        "projection-refresh",
        "Verify derived projection refresh",
        branch="projection-refresh",
        worktree_path=str(tmp_path / "worktree"),
        session_id="codex:projection-refresh",
        session_name="projection-refresh",
    )
    assert ok
    projection_path = projection_path_for(claims_dir)
    created = json.loads(projection_path.read_text(encoding="utf-8"))

    count, scopes, _session, _heartbeat = module.heartbeat_claims(
        agent="codex",
        project="project-meta",
        scope="projection-refresh",
        session_id="codex:projection-refresh",
        require_exact_session=True,
    )
    heartbeat = json.loads(projection_path.read_text(encoding="utf-8"))
    heartbeat_registry_digest = registry_digest(claims_dir)
    released, _release_message = module.release_claim(
        "codex",
        "project-meta",
        "projection-refresh",
    )
    empty = json.loads(projection_path.read_text(encoding="utf-8"))

    assert count == 1 and scopes == ["projection-refresh"]
    assert heartbeat["registry_digest"] == heartbeat_registry_digest
    assert heartbeat["registry_digest"] != created["registry_digest"]
    assert released is True
    assert empty["registry_digest"] == registry_digest(claims_dir)
    assert empty["claims"] == []


def test_heartbeat_holds_registry_lock_through_projection_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent lifecycle hooks cannot split a heartbeat write from refresh."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    ok, _message = module.create_claim(
        "codex",
        "project-meta",
        "locked-heartbeat",
        "Verify heartbeat projection locking",
        branch="locked-heartbeat",
        worktree_path=str(tmp_path / "worktree"),
        session_id="codex:locked-heartbeat",
        session_name="locked-heartbeat",
    )
    assert ok

    phases: list[str] = []

    @contextmanager
    def recording_lock(path: Path):
        assert path == claims_dir
        phases.append("locked")
        try:
            yield
        finally:
            phases.append("unlocked")

    def refresh_while_locked(path: Path) -> tuple[str, str]:
        assert path == claims_dir
        assert phases == ["locked"]
        phases.append("refreshed")
        return "projection.json", "digest"

    monkeypatch.setattr(module._impl, "claim_registry_lock", recording_lock)
    monkeypatch.setattr(module._impl, "refresh_prewrite_authority_projection", refresh_while_locked)
    count, scopes, _session, _heartbeat = module.heartbeat_claims(
        agent="codex",
        project="project-meta",
        scope="locked-heartbeat",
        session_id="codex:locked-heartbeat",
        require_exact_session=True,
    )

    assert count == 1
    assert scopes == ["locked-heartbeat"]
    assert phases == ["locked", "refreshed", "unlocked"]


def test_create_claim_auto_resolves_codex_session_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New claims should auto-populate session_id from the Codex runtime when available."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-123")

    ok, _message = module.create_claim(
        "codex",
        "project-meta",
        "coordination-v2",
        "Patch claims tool",
        claim_type="write",
        write_paths=["scripts/check_coordination_claims.py"],
        branch="plan-62-coordination-v2",
        worktree_path="~/projects/project-meta_worktrees/plan-62-coordination-v2",
        session_name="coordination-claim-repair",
    )

    assert ok
    claim_file = claims_dir / "codex_project-meta_coordination-v2.yaml"
    payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert payload["session_id"] == "codex:thread-123"
    assert isinstance(payload["heartbeat_at"], str)


def test_create_claim_rejects_live_claim_without_session_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live claim cannot be attributable only to an opaque runtime ID."""
    module = _load_module()
    monkeypatch.setattr(module, "CLAIMS_DIR", tmp_path / "claims")

    with pytest.raises(ValueError, match="--session-name"):
        module.create_claim(
            "codex",
            "project-meta",
            "identity-contract",
            "Repair coordination identity contract",
            claim_type="write",
            write_paths=["enforced_planning/coordination_claims.py"],
            branch="fix/identity-contract",
            worktree_path="~/projects/project-meta/worktrees/fix/identity-contract",
            session_id="codex:thread-identity",
        )


def test_plan_bound_write_claim_rejects_blocked_canonical_work_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A blocked canonical work unit must fail before a claim file is written."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "mf03b",
            "status": "blocked",
            "readiness": {"status": "blocked", "approvals": [], "failed_guards": ["approval missing"]},
        },
    )

    with pytest.raises(ValueError, match="not claimable"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="mf03b",
            intent="apply host config",
            plan_ref="Plan #106",
            claim_type="write",
            write_paths=["scripts/apply.py"],
            repo_root=str(repo_root),
            worktree_path=str(repo_root / "worktrees" / "mf03b"),
            branch="mf03b",
            session_id="codex:test",
            session_name="mailbox",
            broader_goal="mailbox",
            tracker_path=str(tmp_path / "tracker.yaml"),
            work_graph_path=graph,
            work_unit_id="mf03b",
        )

    assert not claims_dir.exists()


def test_plan_bound_review_cannot_bypass_write_readiness_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Changing the claim label must not exempt owned write paths from readiness."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    with pytest.raises(ValueError, match="Plan-bound write ownership"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="review-mf03b",
            intent="review and patch host apply",
            plan_ref="Plan #106",
            claim_type="review",
            write_paths=["scripts/apply.py"],
            repo_root=str(tmp_path / "demo"),
            worktree_path=str(tmp_path / "demo" / "worktrees" / "review-mf03b"),
            branch="review-mf03b",
            session_id="codex:test",
            session_name="mailbox-review",
        )

    assert not claims_dir.exists()


def test_plan_bound_controlled_write_requires_declared_canonical_approval(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ready prose cannot replace a required exact approval record."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "mf03b",
            "status": "ready",
            "control_approval_types": ["readiness"],
            "readiness": {"status": "ready", "approvals": [], "failed_guards": []},
        },
    )

    with pytest.raises(ValueError, match="requires exactly one 'readiness' approval"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="mf03b",
            intent="apply host config",
            plan_ref="Plan #106",
            claim_type="write",
            write_paths=["scripts/apply.py"],
            repo_root=str(repo_root),
            worktree_path=str(repo_root / "worktrees" / "mf03b"),
            branch="mf03b",
            session_id="codex:test",
            session_name="mailbox",
            broader_goal="mailbox",
            tracker_path=str(tmp_path / "tracker.yaml"),
            work_graph_path=graph,
            work_unit_id="mf03b",
        )

    assert not claims_dir.exists()


def test_plan_bound_write_claim_persists_exact_canonical_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ready controlled unit binds graph bytes and exact approval revision."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    digest = "5e3936b23a642ba97418b83fcf03b151b65d80785ec81d9330464a4380ffa834"
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "mf03b",
            "status": "ready",
            "control_approval_types": ["readiness"],
            "readiness": {
                "status": "ready",
                "required_approval_types": ["readiness"],
                "approvals": [
                    {
                        "approval_type": "readiness",
                        "role": "user",
                        "approver_id": "brian",
                        "approved_revision": digest,
                        "approved_at": "2026-07-28T01:20:00+00:00",
                        "expires_at": None,
                    }
                ],
                "failed_guards": [],
            },
        },
    )

    ok, _message = module.create_claim(
        agent="codex",
        project="demo",
        scope="mf03b",
        intent="apply host config",
        plan_ref="Plan #106",
        claim_type="write",
        write_paths=["scripts/apply.py"],
        repo_root=str(repo_root),
        worktree_path=str(repo_root / "worktrees" / "mf03b"),
        branch="mf03b",
        session_id="codex:test",
        session_name="mailbox",
        broader_goal="mailbox",
        tracker_path=str(tmp_path / "tracker.yaml"),
        work_graph_path=graph,
        work_unit_id="mf03b",
    )

    assert ok is True
    payload = yaml.safe_load((claims_dir / "codex_demo_mf03b.yaml").read_text(encoding="utf-8"))
    assert payload["work_unit_id"] == "mf03b"
    assert payload["work_graph_path"] == graph
    assert len(payload["work_graph_sha256"]) == 64
    assert payload["approval_revisions"] == [f"readiness={digest}"]


def test_heartbeat_claims_refreshes_codex_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeat refresh should stamp session_id and heartbeat_at for Codex-owned live claims."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-789")
    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "codex-heartbeat",
            "intent": "Refresh heartbeat",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "branch": "plan-95-codex-heartbeat",
            "worktree_path": str(tmp_path / "project-meta_worktrees" / "plan-95-codex-heartbeat"),
            "status": "active",
        },
    )

    updated_count, updated_scopes, session_id, heartbeat_at = module.heartbeat_claims(
        agent="codex",
        project="project-meta",
        scope="codex-heartbeat",
    )

    assert updated_count == 1
    assert updated_scopes == ["codex-heartbeat"]
    assert session_id == "codex:thread-789"
    assert isinstance(heartbeat_at, str)
    payload = yaml.safe_load((claims_dir / "codex.yaml").read_text(encoding="utf-8"))
    assert payload["session_id"] == "codex:thread-789"
    assert payload["heartbeat_at"] == heartbeat_at


def test_heartbeat_replace_failure_preserves_existing_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed heartbeat replacement must never truncate the active claim."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-atomic")
    claim_path = claims_dir / "codex.yaml"
    original = {
        "agent": "codex",
        "claimed_at": "2026-04-05T12:00:00+00:00",
        "expires_at": "2099-04-05T13:00:00+00:00",
        "projects": ["project-meta"],
        "scope": "atomic-heartbeat",
        "intent": "Preserve claim on write failure",
        "claim_type": "write",
        "write_paths": ["README.md"],
        "branch": "atomic-heartbeat",
        "worktree_path": str(tmp_path),
        "session_id": "codex:thread-atomic",
        "status": "active",
    }
    _write_claim(claims_dir, claim_path.name, original)
    original_bytes = claim_path.read_bytes()

    def fail_replace(_source: Path, _destination: Path) -> None:
        raise OSError("simulated replacement failure")

    monkeypatch.setattr(module._impl.os, "replace", fail_replace)

    with pytest.raises(OSError, match="simulated replacement failure"):
        module.heartbeat_claims(
            agent="codex",
            project="project-meta",
            scope="atomic-heartbeat",
        )

    assert claim_path.read_bytes() == original_bytes
    assert list(claims_dir.glob(".*.tmp")) == []


def test_heartbeat_claims_refreshes_claude_code_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeat refresh should support Claude Code runtime session resolution."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session-42")
    _write_claim(
        claims_dir,
        "claude.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "claude-heartbeat",
            "intent": "Refresh heartbeat",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "branch": "plan-95-claude-heartbeat",
            "worktree_path": str(tmp_path / "project-meta_worktrees" / "plan-95-claude-heartbeat"),
            "status": "active",
        },
    )

    updated_count, updated_scopes, session_id, heartbeat_at = module.heartbeat_claims(
        agent="claude-code",
        project="project-meta",
        scope="claude-heartbeat",
    )

    assert updated_count == 1
    assert updated_scopes == ["claude-heartbeat"]
    assert session_id == "claude-code:claude-session-42"
    assert isinstance(heartbeat_at, str)
    payload = yaml.safe_load((claims_dir / "claude.yaml").read_text(encoding="utf-8"))
    assert payload["session_id"] == "claude-code:claude-session-42"
    assert payload["heartbeat_at"] == heartbeat_at


def test_claim_liveness_issues_detect_stale_session_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claims with a sufficiently old heartbeat should become stale by liveness."""
    module = _load_module()
    monkeypatch.setenv("COORDINATION_HEARTBEAT_STALE_MINUTES", "30")
    claim = module.build_candidate_claim(
        agent="codex",
        project="project-meta",
        scope="stale-heartbeat",
        intent="Detect stale session",
        claim_type="write",
        write_paths=["README.md"],
        branch="plan-95-stale-heartbeat",
        worktree_path=str(tmp_path / "project-meta_worktrees" / "plan-95-stale-heartbeat"),
        session_id="codex:thread-old",
        heartbeat_at="2026-04-05T09:00:00+00:00",
        status="active",
    )

    issues = module.claim_liveness_issues(
        claim,
        now=datetime(2026, 4, 5, 10, 0, tzinfo=timezone.utc),
    )

    assert issues == ["stale_session_heartbeat"]
    assert module.claim_runtime_status(claim) == "stale"


def test_claim_without_heartbeat_is_weak_and_explicitly_uninstrumented(tmp_path: Path) -> None:
    """Missing liveness evidence must not be promoted into a healthy-session claim."""

    module = _load_module()
    claim = module.build_candidate_claim(
        agent="codex",
        project="inside-success",
        scope="legacy-active-lane",
        intent="Represent an older live claim",
        claim_type="program",
        branch="main",
        worktree_path=str(tmp_path),
        session_id="codex:synthetic-session",
        status="active",
        claimed_at="2026-07-16T00:00:00+00:00",
        expires_at="2099-07-16T00:00:00+00:00",
    )

    assert module.claim_liveness_issues(claim) == ["missing_session_heartbeat"]
    assert module.claim_runtime_status(claim) == "weak"


def test_plan_bound_claim_without_session_contract_is_weak(tmp_path: Path) -> None:
    """A Plan 0141-shaped path claim must not appear healthy without its session contract."""

    module = _load_module()
    worktree = tmp_path / "onto-canon6" / "worktrees" / "plan0141-canonical-record-evidence"
    worktree.mkdir(parents=True)
    claim = module.build_candidate_claim(
        agent="codex",
        project="onto-canon6",
        scope="plan0141-canonical-record-evidence",
        intent="Add canonical-record evidence",
        plan_ref="Plan #0141 Greer row 10302 vertical slice",
        claim_type="write",
        write_paths=["src/onto_canon6/document_map/complete_document_semantic_v2.py"],
        branch="plan0141-canonical-record-evidence",
        worktree_path=str(worktree),
        session_id="codex:onto-canon6:plan0141-canonical-record-evidence:20260716",
        status="active",
    )

    assert module.claim_health_status(claim) == "weak"
    assert module.claim_health_issues(claim) == [
        "missing_session_name",
        "missing_repo_root",
        "missing_broader_goal",
        "missing_tracker_path",
        "missing_work_unit_id",
        "missing_work_graph_path",
        "missing_work_graph_sha256",
    ]


def test_parallel_plan_claims_require_one_root_and_parented_children() -> None:
    """Parallel Plan 0141 lanes should reuse one program root and parent scope."""

    module = _load_module()
    root = _plan_session_claim(
        module,
        agent="codex",
        scope="plan0141-root",
        claim_type="program",
        plan_ref="Plan #0141 complete document graph",
    )
    child = _plan_session_claim(
        module,
        agent="claude-code",
        scope="plan0141-review",
        claim_type="write",
        parent_scope="plan0141-root",
        plan_ref="Plan #141 reviewer slice",
    )

    assert module.normalize_plan_identity(root.plan_ref) == "Plan #141"
    assert module.claim_hierarchy_issues(root, active_claims=[root, child]) == []
    assert module.claim_hierarchy_issues(child, active_claims=[root, child]) == []


def test_normalize_plan_identity_preserves_qualified_project() -> None:
    """Qualified identities must not collapse back to a global plan number."""
    module = _load_module()

    assert module.normalize_plan_identity("Project_Meta#0233") == "project-meta#233"


def test_parallel_plan_claims_reject_rootless_duplicate_root_and_wrong_parent() -> None:
    """Every invalid parallel hierarchy shape should name its exact defect."""

    module = _load_module()
    write_a = _plan_session_claim(
        module,
        agent="codex",
        scope="plan0141-write-a",
        claim_type="write",
    )
    write_b = _plan_session_claim(
        module,
        agent="claude-code",
        scope="plan0141-write-b",
        claim_type="write",
    )
    assert module.claim_hierarchy_issues(write_a, active_claims=[write_a, write_b]) == [
        "missing_program_root"
    ]

    root_a = _plan_session_claim(
        module,
        agent="codex",
        scope="plan0141-root-a",
        claim_type="program",
    )
    root_b = _plan_session_claim(
        module,
        agent="claude-code",
        scope="plan0141-root-b",
        claim_type="program",
    )
    assert module.claim_hierarchy_issues(root_b, active_claims=[root_a, root_b]) == [
        "multiple_program_roots"
    ]

    wrong_parent = _plan_session_claim(
        module,
        agent="claude-code",
        scope="plan0141-child",
        claim_type="write",
        parent_scope="not-the-root",
    )
    assert module.claim_hierarchy_issues(
        wrong_parent,
        active_claims=[root_a, wrong_parent],
    ) == ["missing_parent_claim", "wrong_parent_scope"]


def test_concurrent_program_root_creation_serializes_check_and_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent agents must not both pass the one-root check before writing."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    original_validate = module._impl.validate_claim_hierarchy_for_creation

    def delayed_validate(*args, **kwargs):
        original_validate(*args, **kwargs)
        time.sleep(0.05)

    monkeypatch.setattr(
        module._impl,
        "validate_claim_hierarchy_for_creation",
        delayed_validate,
    )

    def create_root(index: int) -> tuple[bool, str]:
        scope = f"plan77-root-{index}"
        try:
            return module.create_claim(
                agent=f"agent-{index}",
                project="demo",
                scope=scope,
                intent="coordinate Plan 77",
                plan_ref="Plan #77",
                claim_type="program",
                repo_root=str(tmp_path / "demo"),
                worktree_path=str(tmp_path / "demo" / "worktrees" / scope),
                branch=scope,
                session_id=f"agent-{index}:session",
                session_name="coordinate-plan-77",
                broader_goal="Coordinate Plan 77",
                tracker_path=str(tmp_path / "sessions" / f"{scope}.yaml"),
            )
        except ValueError as error:
            return False, str(error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(create_root, (1, 2)))

    assert sum(1 for ok, _message in results if ok) == 1
    assert sum("multiple_program_roots" in message for _ok, message in results) == 1
    assert len(list(claims_dir.glob("*.yaml"))) == 1



def test_claim_lifecycle_issues_detect_missing_worktree_on_disk(tmp_path: Path) -> None:
    """Claims should become stale when their declared worktree path no longer exists."""
    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "branch", "plan-90-demo"],
        check=True,
        capture_output=True,
        text=True,
    )
    missing_worktree = tmp_path / "demo_worktrees" / "plan-90-demo"

    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="demo-scope",
        intent="Demo lifecycle issue",
        claim_type="write",
        write_paths=["README.md"],
        branch="plan-90-demo",
        worktree_path=str(missing_worktree),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == ["missing_worktree_on_disk"]
    assert module.claim_runtime_status(claim) == "stale"


def test_runtime_session_rejects_unrelated_second_root_unless_explicit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One long-running runtime must not accumulate accidental tangent roots."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    common = {
        "agent": "codex",
        "intent": "fixture root",
        "claim_type": "program",
        "session_id": "codex:week-long-session",
        "session_name": "complete-workspace-maintenance",
        "broader_goal": "Complete workspace maintenance",
    }
    ok, _message = module.create_claim(
        project="alpha",
        scope="plan-1-root",
        plan_ref="alpha#1",
        repo_root=str(tmp_path / "alpha"),
        worktree_path=str(tmp_path / "alpha" / "worktrees" / "plan-1-root"),
        branch="plan-1-root",
        tracker_path=str(tmp_path / "sessions" / "alpha.yaml"),
        **common,
    )
    assert ok is True

    with pytest.raises(ValueError, match="already owns an unresolved root lane"):
        module.create_claim(
            project="beta",
            scope="plan-2-root",
            plan_ref="beta#2",
            repo_root=str(tmp_path / "beta"),
            worktree_path=str(tmp_path / "beta" / "worktrees" / "plan-2-root"),
            branch="plan-2-root",
            tracker_path=str(tmp_path / "sessions" / "beta.yaml"),
            **common,
        )

    ok, _message = module.create_claim(
        project="beta",
        scope="plan-2-root",
        plan_ref="beta#2",
        repo_root=str(tmp_path / "beta"),
        worktree_path=str(tmp_path / "beta" / "worktrees" / "plan-2-root"),
        branch="plan-2-root",
        tracker_path=str(tmp_path / "sessions" / "beta.yaml"),
        allow_parallel=True,
        **common,
    )
    assert ok is True
    claims = module.check_claims()
    assert len(claims) == 2
    beta = next(claim for claim in claims if claim.projects == ["beta"])
    assert beta.parallel_root_authorized is True


def test_claim_lifecycle_issues_detect_missing_branch_ref(tmp_path: Path) -> None:
    """Claims should become stale when the declared branch ref no longer exists."""
    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    worktree_path = tmp_path / "demo_worktrees" / "plan-91-missing-branch"
    worktree_path.mkdir(parents=True)

    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="missing-branch",
        intent="Demo missing branch",
        claim_type="write",
        write_paths=["README.md"],
        branch="plan-91-missing-branch",
        worktree_path=str(worktree_path),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == ["missing_branch_ref"]
    assert module.claim_runtime_status(claim) == "stale"


def test_claim_lifecycle_issues_detect_branch_merged_to_default(tmp_path: Path) -> None:
    """Claims should become stale once the claimed branch has landed on the default branch."""
    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-92-landed"], check=True, capture_output=True, text=True)
    (repo_root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "merge", "--no-ff", "plan-92-landed", "-m", "merge feature"], check=True, capture_output=True, text=True)

    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="landed-branch",
        intent="Demo landed branch",
        claim_type="write",
        write_paths=["README.md"],
        branch="plan-92-landed",
        worktree_path=str(repo_root),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == ["branch_merged_to_default"]
    assert module.claim_runtime_status(claim) == "stale"


def test_claim_lifecycle_issues_detect_remote_merge_when_local_default_is_stale(tmp_path: Path) -> None:
    """Remote canonical integration must outrank a stale local main checkout."""

    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "plan-107-landed"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)
    feature_sha = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    base_sha = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tree_sha = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", f"{feature_sha}^{{tree}}"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    merged_sha = subprocess.run(
        ["git", "-C", str(repo_root), "commit-tree", tree_sha, "-p", base_sha, "-p", feature_sha, "-m", "remote merge"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "-C", str(repo_root), "update-ref", "refs/remotes/origin/main", merged_sha],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"],
        check=True,
        capture_output=True,
        text=True,
    )
    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="remote-landed",
        intent="Detect remote integration",
        claim_type="write",
        write_paths=["feature.txt"],
        branch="plan-107-landed",
        worktree_path=str(repo_root),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == ["branch_merged_to_default"]
    assert module.claim_enforcement_issues(claim)[0]["severity"] == "high"


def test_check_json_fails_high_when_active_claim_branch_is_merged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The standard claim check must fail until merged ownership is disposed."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-107-landed"], check=True, capture_output=True, text=True)
    (repo_root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "merge", "--no-ff", "plan-107-landed", "-m", "merge"], check=True, capture_output=True, text=True)
    _write_claim(
        claims_dir,
        "codex-demo-landed.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-07-27T00:00:00+00:00",
            "expires_at": "2099-07-28T00:00:00+00:00",
            "projects": ["demo"],
            "scope": "landed",
            "intent": "merged work",
            "claim_type": "write",
            "write_paths": ["feature.txt"],
            "branch": "plan-107-landed",
            "worktree_path": str(repo_root),
            "session_id": "codex:test",
            "session_name": "test",
            "status": "active",
        },
    )

    exit_code = module.main(["--check", "--project", "demo", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["has_high_severity_issues"] is True
    assert payload["enforcement_issues"][0]["code"] == "merged_active_claim_requires_disposition"


def test_hydrate_session_ids_backfills_matching_live_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hydration should patch only matching live claims that are missing session IDs."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-456")
    _write_claim(
        claims_dir,
        "missing.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "branch-normalization",
            "intent": "Normalize default branch",
            "claim_type": "write",
            "write_paths": ["docs/plans/91_cross-repo-default-branch-normalization.md"],
            "branch": "plan-91-branch-normalization",
            "worktree_path": "~/projects/project-meta_worktrees/plan-91-branch-normalization",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "existing.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:05:00+00:00",
            "expires_at": "2099-04-05T13:05:00+00:00",
            "projects": ["project-meta"],
            "scope": "already-good",
            "intent": "Keep existing session",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "branch": "plan-92-something",
            "worktree_path": "~/projects/project-meta_worktrees/plan-92-something",
            "session_id": "codex:preexisting",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other-project.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:10:00+00:00",
            "expires_at": "2099-04-05T13:10:00+00:00",
            "projects": ["ecosystem-ops"],
            "scope": "other-project",
            "intent": "Different project",
            "claim_type": "write",
            "write_paths": ["CLAUDE.md"],
            "branch": "plan-12-default-branch-normalization",
            "worktree_path": "~/projects/ecosystem-ops_worktrees/plan-12-default-branch-normalization",
            "status": "active",
        },
    )

    updated_count, updated_scopes, resolved_session_id = module.hydrate_missing_session_ids(
        agent="codex",
        project="project-meta",
    )

    assert updated_count == 1
    assert updated_scopes == ["branch-normalization"]
    assert resolved_session_id == "codex:thread-456"
    hydrated = yaml.safe_load((claims_dir / "missing.yaml").read_text(encoding="utf-8"))
    assert hydrated["session_id"] == "codex:thread-456"
    untouched = yaml.safe_load((claims_dir / "existing.yaml").read_text(encoding="utf-8"))
    assert untouched["session_id"] == "codex:preexisting"
    other_project = yaml.safe_load((claims_dir / "other-project.yaml").read_text(encoding="utf-8"))
    assert "session_id" not in other_project
    assert "heartbeat_at" not in other_project


def test_prune_stale_removes_only_mechanically_stale_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stale pruning should remove only claims with proven lifecycle issues."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "branch", "plan-93-healthy"], check=True, capture_output=True, text=True)
    healthy_worktree = tmp_path / "demo_worktrees" / "plan-93-healthy"
    healthy_worktree.mkdir(parents=True)

    _write_claim(
        claims_dir,
        "stale.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["demo"],
            "scope": "stale-scope",
            "intent": "Stale claim",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "branch": "plan-94-missing",
            "worktree_path": str(tmp_path / "demo_worktrees" / "plan-94-missing"),
            "session_id": "codex:test",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "healthy.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:05:00+00:00",
            "expires_at": "2099-04-05T13:05:00+00:00",
            "projects": ["demo"],
            "scope": "healthy-scope",
            "intent": "Healthy claim",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "branch": "plan-93-healthy",
            "worktree_path": str(healthy_worktree),
            "session_id": "codex:test",
            "status": "active",
        },
    )

    removed, removed_scopes = module.prune_stale()

    assert removed == 1
    assert removed_scopes == ["demo:stale-scope"]
    assert not (claims_dir / "stale.yaml").exists()
    assert (claims_dir / "healthy.yaml").exists()


def test_prune_completed_removes_only_completed_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Completed pruning must not remove active claims, even when expired."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    base_payload = {
        "agent": "codex",
        "claimed_at": "2026-04-05T12:00:00+00:00",
        "expires_at": "2026-04-05T13:00:00+00:00",
        "projects": ["demo"],
        "intent": "Cleanup claim",
        "claim_type": "program",
    }
    _write_claim(
        claims_dir,
        "completed.yaml",
        {**base_payload, "scope": "completed-scope", "status": "completed"},
    )
    _write_claim(
        claims_dir,
        "complete.yaml",
        {**base_payload, "scope": "complete-scope", "status": "complete"},
    )
    _write_claim(
        claims_dir,
        "expired-active.yaml",
        {**base_payload, "scope": "expired-active-scope", "status": "active"},
    )

    exit_code = module.main(["--prune-completed", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload == {
        "pruned": 2,
        "removed_scopes": ["demo:complete-scope", "demo:completed-scope"],
    }
    assert not (claims_dir / "completed.yaml").exists()
    assert not (claims_dir / "complete.yaml").exists()
    assert (claims_dir / "expired-active.yaml").exists()


def test_listing_expired_claim_is_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Listing filters expired claims without deleting their source records."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "expired-active.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2026-04-05T13:00:00+00:00",
            "projects": ["demo"],
            "scope": "expired-active-scope",
            "intent": "Historical expired claim",
            "claim_type": "program",
            "status": "active",
        },
    )

    exit_code = module.main(["--list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["claims"] == []
    assert (claims_dir / "expired-active.yaml").exists()


def test_check_json_outputs_claims_and_candidate_conflict_classification(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Structured JSON output should include both claims and candidate conflict classification."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "existing.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "coordination-v2",
            "intent": "Patch claims tool",
            "claim_type": "write",
            "write_paths": ["scripts"],
            "status": "active",
        },
    )

    exit_code = module.main(
        [
            "--check",
            "--json",
            "--project",
            "project-meta",
            "--agent",
            "codex",
            "--scope",
            "registry-gen",
            "--intent",
            "Generate active-work registry",
            "--claim-type",
            "write",
            "--write-path",
            "scripts/generate_active_work_registry.py",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert len(payload["claims"]) == 1
    assert payload["claims"][0]["health_status"] == "weak"
    assert payload["claims"][0]["health_issues"] == [
        "missing_branch",
        "missing_worktree_path",
        "missing_session_id",
        "missing_session_name",
    ]
    assert payload["check"]["has_hard_conflict"] is True
    assert payload["check"]["candidate_health_status"] == "weak"
    assert payload["check"]["interactions"][0]["severity"] == "hard_conflict"


def test_check_json_outputs_stale_session_liveness_issue(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Structured JSON output should surface stale-session liveness issues."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("COORDINATION_HEARTBEAT_STALE_MINUTES", "30")
    _write_claim(
        claims_dir,
        "stale-session.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T08:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "stale-session",
            "intent": "Test stale session",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "branch": "plan-95-stale-session",
            "worktree_path": str(tmp_path / "project-meta_worktrees" / "plan-95-stale-session"),
            "session_id": "codex:thread-old",
            "heartbeat_at": "2026-04-05T08:00:00+00:00",
            "status": "active",
        },
    )

    exit_code = module.main(
        [
            "--check",
            "--json",
            "--project",
            "project-meta",
        ]
    )

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert payload["claims"][0]["health_status"] == "stale"
    assert payload["claims"][0]["liveness_issues"] == ["stale_session_heartbeat"]


def test_unregistered_format_claim_files_surface_in_list(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Free-form .md/.txt claim files must be reported, not silently ignored.

    2026-07-06 adversarial review: 10 live Codex free-form claims were invisible
    to --list because loading globbed *.yaml only.
    """
    module = _load_module()
    claims_dir = tmp_path / "claims"
    _write_claim(
        claims_dir,
        "claude-code_project-meta_main.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2099-01-01T00:00:00+00:00",
            "expires_at": "2099-01-02T00:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "main",
            "intent": "test",
            "claim_type": "program",
            "status": "active",
            "schema_version": 2,
        },
    )
    (claims_dir / "codex-freeform-claim.md").write_text("# Claim: editing scripts\n", encoding="utf-8")
    (claims_dir / "legacy-note.txt").write_text("codex: doing things\n", encoding="utf-8")
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    files = module.unregistered_claim_files()
    assert [Path(f).name for f in files] == ["codex-freeform-claim.md", "legacy-note.txt"]

    exit_code = module.main(["--list", "--json"])
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert exit_code == 0
    assert len(payload["claims"]) == 1
    assert [Path(f).name for f in payload["unregistered_claim_files"]] == [
        "codex-freeform-claim.md",
        "legacy-note.txt",
    ]

    exit_code = module.main(["--list"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert "unregistered format" in captured.err
    assert "codex-freeform-claim.md" in captured.err
