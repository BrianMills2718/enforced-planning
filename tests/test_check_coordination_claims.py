"""Tests for coordination-claim schema v2 and overlap detection."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import claim_mutation_receipts
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


@pytest.fixture(autouse=True)
def _isolate_claim_mutation_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep deterministic claim fixtures out of the shared operator ledger."""

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
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "config", "user.email", "test@example.com"],
        check=True,
        capture_output=True,
        text=True,
    )
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
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "work graph"], check=True, capture_output=True, text=True
    )
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
    assert result.to_dict()["continuation"] == {
        "state": "integration_wait",
        "goal_blocked": False,
        "blocked_paths": ["docs/ops/INDEX.md"],
        "writable_paths": [],
        "integration_owners": [{"agent": "claude-code", "scope": "docs-authority"}],
        "recommended_next_action": (
            "This candidate is path-blocked. Checkpoint any completed work and move "
            "to another authorized ready work unit; report the whole goal blocked only "
            "after its complete ready queue has been evaluated."
        ),
    }


def test_evaluate_claim_reports_non_overlapping_candidate_paths_as_writable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A narrow collision must expose candidate paths that can still be claimed."""
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
        scope="mixed-scope",
        intent="Patch docs and implementation",
        claim_type="write",
        write_paths=["docs/ops/INDEX.md", "src/worker.py"],
    )
    continuation = module.evaluate_claim(
        candidate,
        active_claims=module.check_claims("project-meta"),
    ).to_dict()["continuation"]

    assert continuation["state"] == "integration_wait"
    assert continuation["goal_blocked"] is False
    assert continuation["blocked_paths"] == ["docs/ops/INDEX.md"]
    assert continuation["writable_paths"] == ["src/worker.py"]


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
        return "projection.json", "d" * 64

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


def _assert_maintenance_mutation_holds_lock_through_projection_refresh(
    module,
    claims_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation,
) -> None:
    """Prove a maintenance mutation holds its lock through the derived refresh."""

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
        return "projection.json", "d" * 64

    monkeypatch.setattr(module._impl, "claim_registry_lock", recording_lock)
    monkeypatch.setattr(module._impl, "refresh_prewrite_authority_projection", refresh_while_locked)

    operation()

    assert phases == ["locked", "refreshed", "unlocked"]


def test_hydration_holds_registry_lock_through_projection_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hydration must not expose a changed YAML registry before refreshing projection."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "hydrate.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "hydrate",
            "intent": "hydrate",
            "claim_type": "program",
            "status": "active",
        },
    )

    _assert_maintenance_mutation_holds_lock_through_projection_refresh(
        module,
        claims_dir,
        monkeypatch,
        lambda: module.hydrate_missing_session_ids(agent="codex", project="demo", session_id="codex:hydrate"),
    )


def test_completion_and_every_prune_hold_registry_lock_through_projection_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every remaining sanctioned maintenance mutation is one critical section."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(module._impl, "CLAIMS_DIR", claims_dir)
    original_lock = module._impl.claim_registry_lock

    def exercise(name: str, payload: dict, operation) -> None:
        claims_dir.mkdir(parents=True, exist_ok=True)
        for path in claims_dir.glob("*.yaml"):
            path.unlink()
        _write_claim(claims_dir, f"{name}.yaml", payload)
        monkeypatch.setattr(module._impl, "claim_registry_lock", original_lock)
        _assert_maintenance_mutation_holds_lock_through_projection_refresh(module, claims_dir, monkeypatch, operation)

    active = {
        "agent": "codex",
        "claimed_at": "2026-04-05T12:00:00+00:00",
        "expires_at": "2099-04-05T13:00:00+00:00",
        "projects": ["demo"],
        "scope": "maintenance",
        "intent": "maintenance",
        "claim_type": "program",
        "status": "active",
        "plan_ref": "Plan #234",
    }
    exercise(
        "complete",
        active,
        lambda: module._impl.complete_claims_for_plan(project="demo", plan_ref="Plan #234"),
    )
    exercise(
        "expired",
        {**active, "expires_at": "2000-04-05T13:00:00+00:00"},
        module.prune_expired,
    )
    exercise(
        "stale",
        {**active, "worktree_path": str(tmp_path / "missing-worktree")},
        module.prune_stale,
    )
    exercise(
        "completed",
        {**active, "status": "completed"},
        module.prune_completed,
    )


def test_concurrent_sanctioned_hydration_leaves_projection_current(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two maintenance mutations serialize and leave the derived projection current."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    for scope in ("first", "second"):
        _write_claim(
            claims_dir,
            f"{scope}.yaml",
            {
                "agent": "codex",
                "projects": ["demo"],
                "scope": scope,
                "intent": scope,
                "claim_type": "program",
                "status": "active",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda scope: module.hydrate_missing_session_ids(
                    agent="codex",
                    project="demo",
                    scope=scope,
                    session_id=f"codex:{scope}",
                ),
                ("first", "second"),
            )
        )

    assert [result[0] for result in results] == [1, 1]
    projection = json.loads(projection_path_for(claims_dir).read_text(encoding="utf-8"))
    assert projection["registry_digest"] == registry_digest(claims_dir)
    assert {claim["session_id"] for claim in projection["claims"]} == {
        "codex:first",
        "codex:second",
    }


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


def test_native_session_binding_rejects_lane_name_in_place_of_codex_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A live Codex runtime must not create ownership under a fabricated ID."""

    module = _load_module()
    monkeypatch.setenv("CODEX_THREAD_ID", "019f9b0a-5a78-7a91-a6c6-940aa5393e6b")

    with pytest.raises(ValueError, match="does not match the current codex runtime"):
        module.validate_native_session_binding(
            "codex",
            "codex:second-slack-vertical-20260730",
        )


def test_native_session_binding_accepts_exact_runtime_or_external_hook_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exact native IDs pass, while hooks without ambient metadata stay usable."""

    module = _load_module()
    native = "codex:019f9b0a-5a78-7a91-a6c6-940aa5393e6b"
    monkeypatch.setenv("CODEX_THREAD_ID", native.removeprefix("codex:"))
    module.validate_native_session_binding("codex", native)

    monkeypatch.delenv("CODEX_THREAD_ID")
    module.validate_native_session_binding("codex", native)


def test_native_session_binding_does_not_confuse_claude_sse_fallback_with_exact_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fallback SSE port must not contradict an exact hook-provided session ID."""

    module = _load_module()
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "15193")

    module.validate_native_session_binding(
        "claude-code",
        "claude-code:019f9b0a-5a78-7a91-a6c6-940aa5393e6b",
    )


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
    assert list(module._impl._claim_write_staging_dir(claims_dir).glob("*.tmp")) == []


def test_registry_lock_prunes_only_old_sanctioned_write_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later locked mutation cleans interrupted writes without broad deletion."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    staging_dir = module._impl._claim_write_staging_dir(claims_dir)
    staging_dir.mkdir()
    legacy = claims_dir / ".codex_demo_scope.yaml.interrupted.tmp"
    staged = staging_dir / ".codex_demo_scope.yaml.interrupted.tmp"
    fresh = staging_dir / ".codex_demo_scope.yaml.fresh.tmp"
    unrelated = claims_dir / ".operator-note.tmp"
    for path in (legacy, staged, fresh, unrelated):
        path.write_text("partial\n", encoding="utf-8")
    old = time.time() - module._impl.CLAIM_WRITE_STAGING_MAX_AGE_SECONDS - 1
    os.utime(legacy, (old, old))
    os.utime(staged, (old, old))
    os.utime(unrelated, (old, old))

    with module._impl.claim_registry_lock(claims_dir):
        pass

    assert not legacy.exists()
    assert not staged.exists()
    assert fresh.exists()
    assert unrelated.exists()


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
    assert module.claim_hierarchy_issues(write_a, active_claims=[write_a, write_b]) == ["missing_program_root"]

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
    assert module.claim_hierarchy_issues(root_b, active_claims=[root_a, root_b]) == ["multiple_program_roots"]

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


@pytest.mark.parametrize("existing_status", ["active", "blocked", "handoff"])
@pytest.mark.parametrize("existing_claim_type", ["write", "research"])
def test_runtime_session_counts_every_live_unparented_claim_as_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing_status: str,
    existing_claim_type: str,
) -> None:
    """Work classification must not let a session abandon an unresolved root."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    existing_kwargs = {
        "agent": "codex",
        "project": "workspace-instructions",
        "scope": "root-policy-edit",
        "intent": "Edit the shared workspace instruction",
        "claim_type": existing_claim_type,
        "write_paths": ["CLAUDE.md"] if existing_claim_type == "write" else None,
        "repo_root": str(tmp_path / "workspace-instructions"),
        "worktree_path": str(tmp_path / "workspace-instructions" / "worktrees" / "root-policy-edit"),
        "branch": "root-policy-edit",
        "session_id": "codex:week-long-session",
        "session_name": "workspace-maintenance",
        "status": existing_status,
    }
    ok, _message = module.create_claim(**existing_kwargs)
    assert ok is True

    with pytest.raises(ValueError, match="already owns an unresolved root lane"):
        module.create_claim(
            agent="codex",
            project="inside-success",
            scope="dagim-meeting-reconcile",
            intent="Open an unrelated root in another project",
            claim_type="program",
            repo_root=str(tmp_path / "inside-success"),
            worktree_path=str(tmp_path / "inside-success" / "worktrees" / "dagim-meeting-reconcile"),
            branch="dagim-meeting-reconcile",
            session_id="codex:week-long-session",
            session_name="workspace-maintenance",
        )

    ok, _message = module.create_claim(
        agent="codex",
        project="inside-success",
        scope="different-runtime-root",
        intent="Open a root owned by a different runtime",
        claim_type="program",
        repo_root=str(tmp_path / "inside-success"),
        worktree_path=str(tmp_path / "inside-success" / "worktrees" / "different-runtime-root"),
        branch="different-runtime-root",
        session_id="codex:different-session",
        session_name="independent-runtime",
    )
    assert ok is True


def test_runtime_session_can_refresh_same_non_program_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refreshing the exact claim slot must not look like a second root."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    kwargs = {
        "agent": "codex",
        "project": "workspace-instructions",
        "scope": "root-policy-edit",
        "intent": "Edit the shared workspace instruction",
        "claim_type": "write",
        "write_paths": ["CLAUDE.md"],
        "repo_root": str(tmp_path / "workspace-instructions"),
        "worktree_path": str(tmp_path / "workspace-instructions" / "worktrees" / "root-policy-edit"),
        "branch": "root-policy-edit",
        "session_id": "codex:week-long-session",
        "session_name": "workspace-maintenance",
    }
    ok, _message = module.create_claim(**kwargs)
    assert ok is True
    ok, _message = module.create_claim(**kwargs)
    assert ok is True
    assert len(module.check_claims()) == 1


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
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "plan-92-landed"], check=True, capture_output=True, text=True
    )
    (repo_root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--no-ff", "plan-92-landed", "-m", "merge feature"],
        check=True,
        capture_output=True,
        text=True,
    )

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
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "plan-107-landed"], check=True, capture_output=True, text=True
    )
    (repo_root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "feature"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--no-ff", "plan-107-landed", "-m", "merge"],
        check=True,
        capture_output=True,
        text=True,
    )
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
    subprocess.run(
        ["git", "-C", str(repo_root), "branch", "plan-93-healthy"], check=True, capture_output=True, text=True
    )
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


def test_prune_stale_honors_agent_project_and_scope_filters(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Explicit CLI filters must not prune unrelated stale claims."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    base = {
        "claimed_at": "2026-04-05T12:00:00+00:00",
        "expires_at": "2099-04-05T13:00:00+00:00",
        "intent": "Stale claim",
        "claim_type": "write",
        "write_paths": ["README.md"],
        "status": "active",
    }
    fixtures = {
        "selected.yaml": {
            **base,
            "agent": "codex",
            "projects": ["selected-project"],
            "scope": "selected-scope",
            "worktree_path": str(tmp_path / "missing-selected"),
        },
        "other-project.yaml": {
            **base,
            "agent": "codex",
            "projects": ["other-project"],
            "scope": "selected-scope",
            "worktree_path": str(tmp_path / "missing-project"),
        },
        "other-scope.yaml": {
            **base,
            "agent": "codex",
            "projects": ["selected-project"],
            "scope": "other-scope",
            "worktree_path": str(tmp_path / "missing-scope"),
        },
        "other-agent.yaml": {
            **base,
            "agent": "claude-code",
            "projects": ["selected-project"],
            "scope": "selected-scope",
            "worktree_path": str(tmp_path / "missing-agent"),
        },
    }
    for name, payload in fixtures.items():
        _write_claim(claims_dir, name, payload)

    exit_code = module.main(
        [
            "--prune-stale",
            "--agent",
            "codex",
            "--project",
            "selected-project",
            "--scope",
            "selected-scope",
            "--json",
        ]
    )

    assert exit_code == 0
    output = json.loads(capsys.readouterr().out)
    assert output == {
        "pruned": 1,
        "removed_scopes": ["selected-project:selected-scope"],
    }
    assert not (claims_dir / "selected.yaml").exists()
    assert (claims_dir / "other-project.yaml").exists()
    assert (claims_dir / "other-scope.yaml").exists()
    assert (claims_dir / "other-agent.yaml").exists()


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


def _completed_claim_payload(
    *,
    scope: str = "completed-scope",
    status: str = "completed",
    session_id: str | None = "codex:completed-scope",
) -> dict:
    """Return one exact completed-claim fixture payload."""

    return {
        "agent": "codex",
        "claimed_at": "2026-04-05T12:00:00+00:00",
        "expires_at": "2026-04-05T13:00:00+00:00",
        "projects": ["demo"],
        "scope": scope,
        "intent": "Preserve exact completed claim evidence",
        "claim_type": "program",
        "session_id": session_id,
        "status": status,
    }


def _append_historical_prune_event(
    *,
    target_claim_path: Path,
    scope: str = "completed-scope",
    session_id: str | None = "codex:completed-scope",
    result: str = "applied_projection_current",
) -> claim_mutation_receipts.ClaimMutationReceiptV1:
    """Append one historical mutation event suitable for legacy binding."""

    receipt = claim_mutation_receipts.ClaimMutationReceiptV1(
        operation="prune",
        result=result,
        writer_source_path="/framework/enforced_planning/coordination_claims.py",
        writer_source_sha256="a" * 64,
        writer_repo_root="/framework",
        process_id=123,
        session_id=session_id,
        target_project="demo",
        target_scope=scope,
        target_claim_path=str(target_claim_path),
        registry_digest_before="b" * 64,
        registry_digest_after="c" * 64,
        projection_digest_after="c" * 64,
        projection_current_after=True,
        error_code=None,
    )
    claim_mutation_receipts.append_receipt(receipt)
    return receipt


def test_prune_completed_archives_exact_bytes_before_unlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live pruning must retain exact bytes and a matching applied transaction."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    source_path = claims_dir / "completed.yaml"
    source_bytes = yaml.safe_dump(
        _completed_claim_payload(),
        sort_keys=False,
    ).encode("utf-8")
    claims_dir.mkdir(parents=True)
    source_path.write_bytes(source_bytes)

    removed, removed_scopes = module.prune_completed()

    assert removed == 1
    assert removed_scopes == ["demo:completed-scope"]
    assert not source_path.exists()
    archived = claim_mutation_receipts.load_completed_claim_archive_receipts()
    assert len(archived) == 1
    receipt = archived[0]
    assert receipt.source_kind == "live_prune"
    assert receipt.source_path == str(source_path)
    assert receipt.source_sha256 == hashlib.sha256(source_bytes).hexdigest()
    assert base64.b64decode(receipt.source_yaml_bytes, validate=True) == source_bytes
    assert receipt.agent == "codex"
    assert receipt.project == "demo"
    assert receipt.scope == "completed-scope"
    assert receipt.session_id == "codex:completed-scope"
    assert receipt.status == "completed"
    assert receipt.prune_binding.kind == "live_prune_transaction"
    mutation_receipts = claim_mutation_receipts.load_receipts()
    matching = [
        event for event in mutation_receipts if event.archive_transaction_id == receipt.prune_binding.transaction_id
    ]
    assert len(matching) == 1
    assert matching[0].operation == "prune"
    assert matching[0].result == "applied_projection_current"


def test_prune_completed_archive_failure_leaves_every_claim_byte_unchanged(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No registry file may unlink when any completed archive append fails."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    expected: dict[Path, bytes] = {}
    for scope in ("first", "second"):
        path = claims_dir / f"{scope}.yaml"
        source_bytes = yaml.safe_dump(
            _completed_claim_payload(scope=scope, session_id=f"codex:{scope}"),
            sort_keys=False,
        ).encode("utf-8")
        claims_dir.mkdir(parents=True, exist_ok=True)
        path.write_bytes(source_bytes)
        expected[path] = source_bytes

    calls = 0
    real_append = claim_mutation_receipts.append_completed_claim_archive_receipt

    def fail_second_append(receipt):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated archive outage")
        return real_append(receipt)

    monkeypatch.setattr(
        claim_mutation_receipts,
        "append_completed_claim_archive_receipt",
        fail_second_append,
    )

    with pytest.raises(
        claim_mutation_receipts.CompletedClaimArchiveError,
        match="completed_claim_archive_write_failed",
    ):
        module.prune_completed()

    assert calls == 2
    assert {path: path.read_bytes() for path in expected} == expected


def test_prune_completed_malformed_yaml_fails_before_any_registry_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed YAML cannot be silently skipped by completed housekeeping."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    claims_dir.mkdir(parents=True)
    malformed = claims_dir / "malformed.yaml"
    completed = claims_dir / "completed.yaml"
    malformed.write_bytes(b"status: [unterminated\n")
    completed.write_text(
        yaml.safe_dump(_completed_claim_payload(), sort_keys=False),
        encoding="utf-8",
    )
    before = {path: path.read_bytes() for path in claims_dir.glob("*.yaml")}

    with pytest.raises(
        claim_mutation_receipts.CompletedClaimArchiveError,
        match="invalid_completed_claim_source",
    ):
        module.prune_completed()

    assert {path: path.read_bytes() for path in claims_dir.glob("*.yaml")} == before
    assert not claim_mutation_receipts.DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH.exists()


def test_completed_claim_archive_rejects_noncompleted_and_corrupt_sources(
    tmp_path: Path,
) -> None:
    """Status, bytes, digest, parsed identity, and receipt digest are fail-closed."""

    source_path = tmp_path / "claim.yaml"
    active_bytes = yaml.safe_dump(
        _completed_claim_payload(status="active"),
        sort_keys=False,
    ).encode("utf-8")
    with pytest.raises(ValueError, match="completed claim"):
        claim_mutation_receipts.build_completed_claim_archive_receipt(
            source_kind="live_prune",
            source_path=source_path,
            source_bytes=active_bytes,
        )

    completed_bytes = yaml.safe_dump(
        _completed_claim_payload(),
        sort_keys=False,
    ).encode("utf-8")
    receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="live_prune",
        source_path=source_path,
        source_bytes=completed_bytes,
    )
    payload = receipt.model_dump(mode="json")
    invalid_payloads = [
        {**payload, "source_sha256": "0" * 64},
        {**payload, "source_yaml_bytes": base64.b64encode(b"different").decode("ascii")},
        {**payload, "scope": "wrong-scope"},
        {**payload, "receipt_sha256": "f" * 64},
    ]
    for invalid in invalid_payloads:
        with pytest.raises(ValueError):
            claim_mutation_receipts.CompletedClaimArchiveReceiptV1.model_validate(invalid)


def test_completed_claim_archive_append_is_idempotent_and_rejects_conflict(
    tmp_path: Path,
) -> None:
    """The same archive ID is a no-op; different content under it is corruption."""

    source_bytes = yaml.safe_dump(
        _completed_claim_payload(),
        sort_keys=False,
    ).encode("utf-8")
    receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="live_prune",
        source_path=tmp_path / "completed.yaml",
        source_bytes=source_bytes,
    )

    first_path, first_appended = claim_mutation_receipts.append_completed_claim_archive_receipt(receipt)
    second_path, second_appended = claim_mutation_receipts.append_completed_claim_archive_receipt(receipt)

    assert first_path == second_path
    assert first_appended is True
    assert second_appended is False
    assert len(first_path.read_text(encoding="utf-8").splitlines()) == 1
    conflicting_payload = receipt.model_dump(mode="json")
    conflicting_payload["source_kind"] = "legacy_reconciliation"
    conflicting_payload["prune_binding"] = {
        "kind": "legacy_prune_event",
        "transaction_id": None,
        "mutation_event_id": "different-event",
    }
    conflicting_payload["receipt_sha256"] = claim_mutation_receipts.completed_claim_archive_receipt_sha256(
        conflicting_payload
    )
    conflicting = claim_mutation_receipts.CompletedClaimArchiveReceiptV1.model_validate(conflicting_payload)
    with pytest.raises(ValueError, match="conflicting completed-claim archive"):
        claim_mutation_receipts.append_completed_claim_archive_receipt(conflicting)


def test_completed_claim_archive_append_does_not_rescan_whole_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Appending must cost the same against a large ledger as a small one.

    Regression guard. This append previously validated every record in the
    ledger on every call, and each record's validator base64-decodes the
    embedded claim, re-parses its YAML, and recomputes two SHA-256 digests.
    Pruning N completed claims therefore cost N full ledger validations while
    holding the global claim-registry lock: measured at roughly 18 minutes for
    791 claims against an 875-record ledger, which stalled every other agent
    session on the machine for the duration.
    """

    ledger_size = 40
    for index in range(ledger_size):
        source_bytes = yaml.safe_dump(
            _completed_claim_payload(
                scope=f"bulk-scope-{index:03d}",
                session_id=f"codex:bulk-scope-{index:03d}",
            ),
            sort_keys=False,
        ).encode("utf-8")
        claim_mutation_receipts.append_completed_claim_archive_receipt(
            claim_mutation_receipts.build_completed_claim_archive_receipt(
                source_kind="live_prune",
                source_path=tmp_path / f"bulk-{index:03d}.yaml",
                source_bytes=source_bytes,
            )
        )

    fresh_bytes = yaml.safe_dump(
        _completed_claim_payload(scope="fresh-scope", session_id="codex:fresh-scope"),
        sort_keys=False,
    ).encode("utf-8")
    fresh = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="live_prune",
        source_path=tmp_path / "fresh.yaml",
        source_bytes=fresh_bytes,
    )

    validations = 0
    real_validate = (
        claim_mutation_receipts.CompletedClaimArchiveReceiptV1.model_validate_json
    )

    def _counting_validate(*args: object, **kwargs: object):
        nonlocal validations
        validations += 1
        return real_validate(*args, **kwargs)

    monkeypatch.setattr(
        claim_mutation_receipts.CompletedClaimArchiveReceiptV1,
        "model_validate_json",
        _counting_validate,
    )

    _path, appended = claim_mutation_receipts.append_completed_claim_archive_receipt(fresh)

    assert appended is True
    # A new archive_id matches no existing record, so nothing needs validating.
    # The bound is deliberately far below ledger_size: the point is that this
    # does not grow with the ledger.
    assert validations < ledger_size, (
        f"append validated {validations} records against a {ledger_size}-record "
        "ledger; the whole-ledger rescan has been reintroduced"
    )


def test_completed_claim_archive_append_still_detects_conflict_in_large_ledger(
    tmp_path: Path,
) -> None:
    """The targeted lookup must not let a conflicting record slip through."""

    conflicting_source = yaml.safe_dump(
        _completed_claim_payload(scope="target-scope", session_id="codex:target-scope"),
        sort_keys=False,
    ).encode("utf-8")
    target = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="live_prune",
        source_path=tmp_path / "target.yaml",
        source_bytes=conflicting_source,
    )
    claim_mutation_receipts.append_completed_claim_archive_receipt(target)

    # Bury the target under unrelated records so a naive "check the last line"
    # implementation would miss it.
    for index in range(25):
        filler_bytes = yaml.safe_dump(
            _completed_claim_payload(
                scope=f"filler-{index:03d}",
                session_id=f"codex:filler-{index:03d}",
            ),
            sort_keys=False,
        ).encode("utf-8")
        claim_mutation_receipts.append_completed_claim_archive_receipt(
            claim_mutation_receipts.build_completed_claim_archive_receipt(
                source_kind="live_prune",
                source_path=tmp_path / f"filler-{index:03d}.yaml",
                source_bytes=filler_bytes,
            )
        )

    # Same archive_id, different content: still corruption, still fails loud.
    conflicting_payload = target.model_dump(mode="json")
    conflicting_payload["source_kind"] = "legacy_reconciliation"
    conflicting_payload["prune_binding"] = {
        "kind": "legacy_prune_event",
        "transaction_id": None,
        "mutation_event_id": "different-event",
    }
    conflicting_payload["receipt_sha256"] = (
        claim_mutation_receipts.completed_claim_archive_receipt_sha256(conflicting_payload)
    )
    conflicting = claim_mutation_receipts.CompletedClaimArchiveReceiptV1.model_validate(
        conflicting_payload
    )

    with pytest.raises(ValueError, match="conflicting completed-claim archive"):
        claim_mutation_receipts.append_completed_claim_archive_receipt(conflicting)

    # And an exact replay of the buried record is still an idempotent no-op.
    _path, appended = claim_mutation_receipts.append_completed_claim_archive_receipt(target)
    assert appended is False


def test_legacy_completed_claim_backfill_requires_exact_applied_prune_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy reconciliation must bind exact calibration bytes to one prune event."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    registry_before = registry_digest(claims_dir)
    snapshot_path = tmp_path / "calibration" / "completed.yaml"
    snapshot_path.parent.mkdir()
    source_bytes = yaml.safe_dump(
        _completed_claim_payload(),
        sort_keys=False,
    ).encode("utf-8")
    snapshot_path.write_bytes(source_bytes)
    historical_path = tmp_path / "historical-claims" / module._claim_filename("codex", "demo", "completed-scope")
    with pytest.raises(ValueError, match="exactly one historical prune event"):
        module._impl.backfill_completed_claim_archive(
            source_claim_snapshot=snapshot_path,
            expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            prune_event_id="missing-event",
        )
    prune_event = _append_historical_prune_event(
        target_claim_path=historical_path,
    )

    receipt, appended = module._impl.backfill_completed_claim_archive(
        source_claim_snapshot=snapshot_path,
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        prune_event_id=prune_event.event_id,
    )
    repeated, repeated_appended = module._impl.backfill_completed_claim_archive(
        source_claim_snapshot=snapshot_path,
        expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
        prune_event_id=prune_event.event_id,
    )

    assert appended is True
    assert repeated_appended is False
    assert repeated.archive_id == receipt.archive_id
    assert receipt.source_kind == "legacy_reconciliation"
    assert receipt.source_path == str(historical_path)
    assert receipt.prune_binding.kind == "legacy_prune_event"
    assert receipt.prune_binding.mutation_event_id == prune_event.event_id
    assert registry_digest(claims_dir) == registry_before
    assert claim_mutation_receipts.load_completed_claim_archive_receipts() == [receipt]


@pytest.mark.parametrize(
    ("mutation_override", "expected_error"),
    [
        ({"target_project": "other"}, "identity"),
        ({"target_scope": "other"}, "identity"),
        ({"session_id": "codex:other"}, "session"),
        ({"target_claim_path": "/historical/wrong.yaml"}, "path"),
        ({"result": "not_applied"}, "applied prune"),
    ],
)
def test_legacy_completed_claim_backfill_rejects_mismatched_prune_event(
    tmp_path: Path,
    mutation_override: dict,
    expected_error: str,
) -> None:
    """A historical event cannot validate a different completed claim."""

    module = _load_module()
    snapshot_path = tmp_path / "completed.yaml"
    source_bytes = yaml.safe_dump(
        _completed_claim_payload(),
        sort_keys=False,
    ).encode("utf-8")
    snapshot_path.write_bytes(source_bytes)
    target_path = tmp_path / "historical" / module._claim_filename("codex", "demo", "completed-scope")
    base = {
        "operation": "prune",
        "result": "applied_projection_current",
        "writer_source_path": "/framework/enforced_planning/coordination_claims.py",
        "writer_source_sha256": "a" * 64,
        "writer_repo_root": "/framework",
        "process_id": 123,
        "session_id": "codex:completed-scope",
        "target_project": "demo",
        "target_scope": "completed-scope",
        "target_claim_path": str(target_path),
        "registry_digest_before": "b" * 64,
        "registry_digest_after": "c" * 64,
        "projection_digest_after": "c" * 64,
        "projection_current_after": True,
        "error_code": None,
    }
    event = claim_mutation_receipts.ClaimMutationReceiptV1(**{**base, **mutation_override})
    claim_mutation_receipts.append_receipt(event)

    with pytest.raises(ValueError, match=expected_error):
        module._impl.backfill_completed_claim_archive(
            source_claim_snapshot=snapshot_path,
            expected_source_sha256=hashlib.sha256(source_bytes).hexdigest(),
            prune_event_id=event.event_id,
        )
    assert not claim_mutation_receipts.DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH.exists()


def test_legacy_completed_claim_backfill_cli_fails_on_changed_snapshot_digest(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The sanctioned CLI must require the operator-reviewed calibration digest."""

    module = _load_module()
    snapshot_path = tmp_path / "completed.yaml"
    source_bytes = yaml.safe_dump(
        _completed_claim_payload(),
        sort_keys=False,
    ).encode("utf-8")
    snapshot_path.write_bytes(source_bytes)

    exit_code = module.main(
        [
            "--backfill-completed-claim-archive",
            "--source-claim-snapshot",
            str(snapshot_path),
            "--expected-source-sha256",
            "0" * 64,
            "--prune-event-id",
            "missing-event",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["ok"] is False
    assert payload["error_code"] == "completed_claim_archive_backfill_failed"
    assert "source SHA-256 mismatch" in payload["error"]
    assert not claim_mutation_receipts.DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH.exists()


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
