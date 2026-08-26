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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import claim_mutation_receipts
from enforced_planning import coordination_claims as claims_impl
from enforced_planning import prewrite_claim_projection
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


@pytest.mark.parametrize("invalid_progress_at", [None, 123, {"not": "text"}])
def test_normalize_claim_preserves_explicit_invalid_progress_as_weak(
    invalid_progress_at: object,
    tmp_path: Path,
) -> None:
    """Wrong-typed or null keys cannot masquerade as field-absent legacy claims."""

    worktree = tmp_path / "legacy-or-invalid"
    worktree.mkdir()
    base = {
        "agent": "codex",
        "projects": ["demo"],
        "scope": "legacy-or-invalid",
        "intent": "Classify instrumentation",
        "claim_type": "program",
        "branch": "legacy-or-invalid",
        "worktree_path": str(worktree),
        "session_id": "codex:owner",
        "session_name": "legacy-or-invalid",
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
    }
    legacy = claims_impl.normalize_claim(base)
    invalid = claims_impl.normalize_claim({**base, "progress_at": invalid_progress_at})

    assert legacy is not None and claims_impl.claim_progress_issues(legacy) == []
    assert invalid is not None
    assert "incomplete_progress_event" in claims_impl.claim_progress_issues(invalid)
    assert "invalid_progress_at" in claims_impl.claim_progress_issues(invalid)
    assert claims_impl.claim_runtime_status(invalid) == "weak"


def test_valid_progress_remains_additive_for_implicit_v2_plan_write(tmp_path: Path) -> None:
    """Progress instrumentation cannot activate unrelated v3 work-graph requirements."""

    worktree = tmp_path / "legacy-plan-write"
    worktree.mkdir()
    base = {
        "agent": "codex",
        "projects": ["demo"],
        "scope": "legacy-plan-write",
        "intent": "Continue a pre-work-graph plan lane",
        "claim_type": "write",
        "write_paths": ["src/legacy.py"],
        "branch": "legacy-plan-write",
        "worktree_path": str(worktree),
        "repo_root": str(tmp_path / "repo"),
        "session_id": "codex:owner",
        "session_name": "legacy-plan-write",
        "broader_goal": "Preserve additive claim compatibility",
        "tracker_path": str(tmp_path / "tracker.yaml"),
        "heartbeat_at": "2026-08-21T09:59:00+00:00",
        "status": "active",
        "expires_at": "2099-08-22T00:00:00+00:00",
        "plan_ref": "Plan #70",
    }
    legacy = claims_impl.normalize_claim(base)
    instrumented = claims_impl.normalize_claim(
        {
            **base,
            "progress_at": "2026-08-21T09:30:00+00:00",
            "progress_kind": "verified_commit",
            "evidence_ref": "commit:abc123",
            "next_action": "run the focused compatibility check",
        }
    )

    assert legacy is not None and instrumented is not None
    assert legacy.schema_version == instrumented.schema_version == 2
    assert claims_impl.claim_health_issues(legacy) == []
    assert claims_impl.claim_health_issues(instrumented) == []
    assert (
        claims_impl.claim_progress_issues(
            instrumented,
            now=datetime.fromisoformat("2026-08-21T10:00:00+00:00"),
        )
        == []
    )


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
    assert conflict.reason == "write ownership overlaps across active claims"
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
    assert payload["progress_kind"] == "claim_started"
    assert payload["evidence_ref"] == "Plan #62"
    assert payload["next_action"] == "Broad governance cleanup"
    assert isinstance(payload["progress_at"], str)
    normalized = claims_impl.normalize_claim(payload)
    assert normalized is not None
    assert claims_impl.claim_progress_issues(normalized) == []
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
        plan_ref="UNPLANNED",
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
        plan_ref="UNPLANNED",
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
        plan_ref="UNPLANNED",
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


def test_direct_plan_bound_claim_cannot_bypass_enforced_integrity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The canonical claim seam must deny before registry mutation, even without Make."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "integrity-unit",
            "status": "ready",
            "readiness": {
                "status": "ready",
                "required_approval_types": [],
                "approvals": [],
                "failed_guards": [],
            },
        },
    )
    (repo_root / "meta-process.yaml").write_text(
        "meta_process:\n  plans:\n    integrity:\n      mode: enforce\n      contract_version: 1.0.0\n      minimum_plan_number: 106\n",
        encoding="utf-8",
    )
    plan_path = repo_root / "docs/plans/106_incomplete.md"
    plan_path.write_text("# Incomplete enforced plan\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "add", "meta-process.yaml", str(plan_path.relative_to(repo_root))],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "enforce incomplete plan"],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(ValueError, match="missing_epistemic_frontier"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="integrity-unit",
            intent="attempt direct claim bypass",
            plan_ref="demo#106",
            claim_type="write",
            write_paths=["src/feature.py"],
            repo_root=str(repo_root),
            worktree_path=str(repo_root / "worktrees" / "integrity-unit"),
            branch="integrity-unit",
            session_id="codex:test",
            session_name="integrity-unit",
            broader_goal="prove direct claim admission",
            tracker_path=str(tmp_path / "tracker.yaml"),
            work_graph_path=graph,
            work_unit_id="integrity-unit",
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
        work_graph_path=graph,
        work_unit_id="mf03b",
    )

    assert ok is True
    payload = yaml.safe_load((claims_dir / "codex_demo_mf03b.yaml").read_text(encoding="utf-8"))
    assert payload["work_unit_id"] == "mf03b"
    assert payload["work_graph_path"] == graph
    assert len(payload["work_graph_sha256"]) == 64
    assert payload["approval_revisions"] == [f"readiness={digest}"]
    assert payload["schema_version"] == 4
    assert (
        payload["start_revision"]
        == subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    )


def test_activated_plan_claim_rejects_branch_and_worktree_at_different_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tracker marks activation, so a claim for A cannot bless execution at B."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "revision-custody",
            "status": "ready",
            "readiness": {
                "status": "ready",
                "required_approval_types": [],
                "approvals": [],
                "failed_guards": [],
            },
        },
    )
    revision_a = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo_root / "README.md").write_text("advanced after A\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-am", "advance to B"],
        check=True,
        capture_output=True,
        text=True,
    )
    revision_b = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert revision_b != revision_a
    worktree = repo_root / "worktrees" / "revision-custody"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            "revision-custody",
            str(worktree),
            revision_a,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(ValueError, match="does not match retained start revision"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="revision-custody",
            intent="attempt false activation evidence",
            plan_ref="demo#106",
            claim_type="write",
            write_paths=["src/feature.py"],
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="revision-custody",
            session_id="codex:test",
            session_name="revision-custody",
            broader_goal="Preserve Revision Custody",
            tracker_path=str(tmp_path / "fake-tracker.yaml"),
            work_graph_path=graph,
            work_unit_id="revision-custody",
            start_point=revision_b,
        )

    assert not claims_dir.exists()


def test_work_unit_binding_reads_graph_from_same_exact_plan_revision(tmp_path: Path) -> None:
    """A later graph edit cannot alter a binding validated against an older exact commit."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "same-revision",
            "status": "ready",
            "readiness": {
                "status": "ready",
                "required_approval_types": [],
                "approvals": [],
                "failed_guards": [],
            },
        },
    )
    revision_a = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo_root / graph).write_text(
        json.dumps(
            {
                "units": [
                    {
                        "id": "same-revision",
                        "status": "blocked",
                        "readiness": {
                            "status": "blocked",
                            "approvals": [],
                            "failed_guards": ["later blocker"],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "add", graph],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "block later graph"],
        check=True,
        capture_output=True,
        text=True,
    )

    _graph_sha, approvals, source_revision = claims_impl.resolve_canonical_work_unit_binding(
        repo_root=str(repo_root),
        plan_ref="demo#106",
        work_graph_path=graph,
        work_unit_id="same-revision",
        start_point=revision_a,
    )

    assert approvals == ()
    assert source_revision == revision_a


def test_new_plan_bound_claim_rejects_non_tip_revision_even_with_resume_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older permissive commit cannot open a new lane after the default tip advances."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "old-ready",
            "status": "ready",
            "readiness": {
                "status": "ready",
                "required_approval_types": [],
                "approvals": [],
                "failed_guards": [],
            },
        },
    )
    revision_a = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo_root / "README.md").write_text("new default tip\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-am", "advance default"],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(ValueError, match="--resume is not recovery evidence"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="old-ready",
            intent="attempt old-policy lane",
            plan_ref="demo#106",
            claim_type="write",
            write_paths=["src/feature.py"],
            repo_root=str(repo_root),
            worktree_path=str(repo_root / "worktrees" / "old-ready"),
            branch="old-ready",
            session_id="codex:test",
            session_name="old-ready",
            broader_goal="reject old policy",
            tracker_path=str(tmp_path / "tracker.yaml"),
            work_graph_path=graph,
            work_unit_id="old-ready",
            start_point=revision_a,
            resume_requested=True,
        )

    assert not claims_dir.exists()


def test_new_non_tip_claim_routes_exact_retained_artifacts_to_session_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even matching old artifacts do not turn new-claim bootstrap into recovery."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    graph = _commit_work_graph(
        repo_root,
        plan=106,
        unit={
            "id": "retained-old-lane",
            "status": "ready",
            "readiness": {
                "status": "ready",
                "required_approval_types": [],
                "approvals": [],
                "failed_guards": [],
            },
        },
    )
    revision_a = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    (repo_root / "README.md").write_text("new default tip\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-am", "advance default"],
        check=True,
        capture_output=True,
        text=True,
    )
    worktree = repo_root / "worktrees" / "retained-old-lane"
    subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "worktree",
            "add",
            "-b",
            "retained-old-lane",
            str(worktree),
            revision_a,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    with pytest.raises(ValueError, match="session-resume"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="retained-old-lane",
            intent="attempt new-claim recovery",
            plan_ref="demo#106",
            claim_type="write",
            write_paths=["src/feature.py"],
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="retained-old-lane",
            session_id="codex:test",
            session_name="retained-old-lane",
            broader_goal="Resume Existing Custody",
            tracker_path=str(tmp_path / "tracker.yaml"),
            work_graph_path=graph,
            work_unit_id="retained-old-lane",
            start_point=revision_a,
            resume_requested=True,
            require_new=True,
        )

    assert not claims_dir.exists()


def test_goal_bound_write_claim_preserves_authority_without_work_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sequential outcome goal is not graph-coordinated plan execution."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "demo"
    worktree = repo_root / "worktrees" / "owner-week"
    worktree.mkdir(parents=True)

    ok, _message = module.create_claim(
        agent="codex",
        project="demo",
        scope="owner-week",
        intent="advance one owner-visible outcome",
        plan_ref="goal:owner-visible-outcome",
        claim_type="program",
        write_paths=["src/vertical.py", "tests/test_vertical.py"],
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="owner-week",
        session_id="codex:goal-test",
        session_name="owner-visible-outcome",
        broader_goal="Owner visible outcome",
        tracker_path=str(tmp_path / "tracker.yaml"),
    )

    assert ok is True
    payload = yaml.safe_load((claims_dir / "codex_demo_owner-week.yaml").read_text(encoding="utf-8"))
    assert payload["plan_ref"] == "goal:owner-visible-outcome"
    assert payload["write_paths"] == ["src/vertical.py", "tests/test_vertical.py"]
    assert payload["work_graph_path"] is None
    assert payload["work_unit_id"] is None
    claim = module.normalize_claim(payload)
    assert claim is not None
    assert "missing_work_graph_path" not in module.claim_health_issues(claim)


@pytest.mark.parametrize("authority", ["Plan #117", "enforced-planning#117", "descriptive authority"])
def test_non_goal_write_authority_still_requires_work_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority: str,
) -> None:
    """The goal exception cannot weaken numbered or arbitrary plan authority."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    with pytest.raises(ValueError, match="Plan-bound write ownership"):
        module.create_claim(
            agent="codex",
            project="demo",
            scope="plan117",
            intent="execute coordinated authority",
            plan_ref=authority,
            claim_type="write",
            write_paths=["src/vertical.py"],
            repo_root=str(tmp_path / "demo"),
            worktree_path=str(tmp_path / "demo" / "worktrees" / "plan117"),
            branch="plan117",
            session_id="codex:plan-test",
            session_name="coordinated-authority",
            broader_goal="Coordinated authority",
            tracker_path=str(tmp_path / "tracker.yaml"),
        )

    assert not claims_dir.exists()


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
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
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
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
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


def test_live_claim_without_plan_ref_is_weak_blocking_and_rejected_for_creation(tmp_path: Path) -> None:
    """Every live session must name plan, goal, or explicit maintenance authority."""

    module = _load_module()
    worktree = tmp_path / "demo" / "worktrees" / "bounded-lane"
    worktree.mkdir(parents=True)
    common = {
        "agent": "claude-code",
        "project": "demo",
        "scope": "bounded-lane",
        "intent": "Exercise one bounded lane",
        "claim_type": "program",
        "branch": "bounded-lane",
        "worktree_path": str(worktree),
        "repo_root": str(tmp_path / "demo"),
        "session_name": "demo-bounded-outcome",
        "broader_goal": "Deliver the demo bounded outcome",
        "tracker_path": str(tmp_path / "tracker.yaml"),
        "session_id": "claude-code:demo-session",
        "status": "active",
    }
    missing = module.build_candidate_claim(**common)

    assert module.claim_health_issues(missing) == ["missing_plan_ref"]
    assert module.claim_health_status(missing) == "weak"
    assert module.claim_enforcement_issues(missing) == [
        {
            "code": "live_claim_missing_plan_ref",
            "severity": "high",
            "message": (
                "Live claim demo:bounded-lane has no plan_ref. Resume or recreate the lane "
                "through a sanctioned plan-, goal-, or UNPLANNED-bound entrypoint, or close "
                "it with an explicit disposition."
            ),
        }
    ]
    with pytest.raises(ValueError, match="explicit UNPLANNED"):
        module._impl.validate_claim_for_creation(missing)

    maintenance = module.build_candidate_claim(plan_ref="UNPLANNED", **common)
    assert module.claim_health_issues(maintenance) == []
    assert module.claim_enforcement_issues(maintenance) == []


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
        "plan_ref": "UNPLANNED",
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
            plan_ref="UNPLANNED",
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
        plan_ref="UNPLANNED",
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
        "plan_ref": "UNPLANNED",
    }
    ok, _message = module.create_claim(**kwargs)
    assert ok is True
    ok, _message = module.create_claim(**kwargs)
    assert ok is True
    assert len(module.check_claims()) == 1


def test_cross_session_refresh_cannot_replace_live_claim_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second runtime with the same client label must preserve the first owner."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    common = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "plan-116-prewrite-outcome-observe",
        "intent": "Exercise exact-slot ownership",
        "claim_type": "program",
        "write_paths": ["docs/evidence/plan116.json"],
        "repo_root": str(tmp_path / "repo"),
        "worktree_path": str(tmp_path / "worktrees" / "plan116-first"),
        "branch": "plan116-first",
        "session_name": "owner-first",
        "plan_ref": "UNPLANNED",
    }
    ok, _message = module.create_claim(session_id="codex:first-runtime", **common)
    assert ok is True
    claim_path = claims_dir / "codex_enforced-planning_plan-116-prewrite-outcome-observe.yaml"
    projection_path = projection_path_for(claims_dir)
    claim_before = claim_path.read_bytes()
    projection_before = projection_path.read_bytes()

    with pytest.raises(ValueError, match="owned by runtime session codex:first-runtime"):
        module.create_claim(
            session_id="codex:second-runtime",
            worktree_path=str(tmp_path / "worktrees" / "plan116-second"),
            branch="plan116-second",
            **{key: value for key, value in common.items() if key not in {"worktree_path", "branch"}},
        )

    assert claim_path.read_bytes() == claim_before
    assert projection_path.read_bytes() == projection_before


def test_require_new_preserves_occupied_same_session_claim_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """New-lane bootstrap cannot refresh and later roll back a pre-existing claim."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    kwargs = {
        "agent": "codex",
        "project": "demo",
        "scope": "owned-slot",
        "intent": "retain exact owner",
        "claim_type": "write",
        "write_paths": ["src/owned.py"],
        "repo_root": str(tmp_path / "demo"),
        "worktree_path": str(tmp_path / "demo" / "worktrees" / "owned-slot"),
        "branch": "owned-slot",
        "session_id": "codex:same-session",
        "session_name": "owned-slot",
        "plan_ref": "UNPLANNED",
    }
    ok, _message = module.create_claim(**kwargs)
    assert ok
    claim_path = claims_dir / "codex_demo_owned-slot.yaml"
    before = claim_path.read_bytes()

    with pytest.raises(ValueError, match="already exists"):
        module.create_claim(**kwargs, require_new=True)

    assert claim_path.read_bytes() == before


def test_guarded_release_preserves_claim_when_revision_or_session_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rollback cleanup releases only the exact claim custody it created."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "codex_demo_guarded.yaml",
        {
            "schema_version": 4,
            "agent": "codex",
            "projects": ["demo"],
            "scope": "guarded",
            "intent": "retain custody",
            "claim_type": "program",
            "branch": "guarded",
            "worktree_path": str(tmp_path / "worktrees" / "guarded"),
            "session_id": "codex:owner",
            "session_name": "guarded",
            "status": "active",
            "start_revision": "a" * 40,
        },
    )
    claim_path = claims_dir / "codex_demo_guarded.yaml"
    before = claim_path.read_bytes()

    with pytest.raises(ValueError, match="session custody changed"):
        module.release_claim(
            "codex",
            "demo",
            "guarded",
            expected_session_id="codex:other",
            expected_start_revision="a" * 40,
        )
    with pytest.raises(ValueError, match="start-revision custody changed"):
        module.release_claim(
            "codex",
            "demo",
            "guarded",
            expected_session_id="codex:owner",
            expected_start_revision="b" * 40,
        )

    assert claim_path.read_bytes() == before


def test_same_client_different_sessions_conflict_on_program_write_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Client type is not writer identity; independent Codex sessions can collide."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    existing = module.build_candidate_claim(
        agent="codex",
        project="enforced-planning",
        scope="first-lane",
        intent="Own the coordination module",
        claim_type="program",
        write_paths=["enforced_planning/coordination_claims.py"],
        session_id="codex:first-runtime",
    )
    candidate = module.build_candidate_claim(
        agent="codex",
        project="enforced-planning",
        scope="second-lane",
        intent="Attempt the same write",
        claim_type="program",
        write_paths=["enforced_planning/coordination_claims.py"],
        session_id="codex:second-runtime",
    )

    result = module.evaluate_claim(candidate, active_claims=[existing])

    assert len(result.hard_conflicts) == 1
    assert result.hard_conflicts[0].other_scope == "first-lane"
    assert result.hard_conflicts[0].reason == "write ownership overlaps across active claims"


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


@pytest.mark.parametrize("pending_kind", ["modified", "staged", "untracked"])
def test_claim_lifecycle_issues_preserve_dirty_work_after_branch_lands(
    tmp_path: Path,
    pending_kind: str,
) -> None:
    """Landed commit history must not erase distinct worktree-local work."""

    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    worktree_path = tmp_path / "worktree"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b", "plan-92-still-dirty", str(worktree_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    feature_path = worktree_path / "feature.txt"
    feature_path.write_text("landed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(worktree_path), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(worktree_path), "commit", "-m", "feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--no-ff", "plan-92-still-dirty", "-m", "merge feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    if pending_kind == "untracked":
        (worktree_path / "pending.txt").write_text("unique\n", encoding="utf-8")
    else:
        feature_path.write_text("landed\nunique\n", encoding="utf-8")
        if pending_kind == "staged":
            subprocess.run(
                ["git", "-C", str(worktree_path), "add", "feature.txt"],
                check=True,
                capture_output=True,
                text=True,
            )

    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="landed-but-dirty",
        intent="Preserve pending work",
        claim_type="write",
        plan_ref="UNPLANNED",
        write_paths=["feature.txt"],
        branch="plan-92-still-dirty",
        worktree_path=str(worktree_path),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == []
    assert module.claim_enforcement_issues(claim) == []


def test_claim_lifecycle_issues_fail_closed_when_worktree_status_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed cleanliness probe must not silently suppress merged enforcement."""

    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(
        ["git", "-C", str(repo_root), "checkout", "-b", "plan-92-status-failure"],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo_root / "feature.txt").write_text("feature\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.txt"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "commit", "-m", "feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--no-ff", "plan-92-status-failure", "-m", "merge feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    real_run_git = module._impl._run_git

    def fail_status(path: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[:2] == ["status", "--porcelain"]:
            return subprocess.CompletedProcess(["git", *args], 1, "", "status unavailable")
        return real_run_git(path, args)

    monkeypatch.setattr(module._impl, "_run_git", fail_status)
    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="landed-status-unavailable",
        intent="Fail closed",
        claim_type="write",
        plan_ref="UNPLANNED",
        write_paths=["feature.txt"],
        branch="plan-92-status-failure",
        worktree_path=str(repo_root),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == ["branch_merged_to_default"]
    assert module.claim_enforcement_issues(claim)[0]["code"] == "merged_active_claim_requires_disposition"


def test_claim_lifecycle_issues_treat_ignored_only_worktree_as_clean(tmp_path: Path) -> None:
    """Ignored artifacts do not represent closeout-blocking pending work."""

    module = _load_module()
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    worktree_path = tmp_path / "worktree"
    subprocess.run(
        ["git", "-C", str(repo_root), "worktree", "add", "-b", "plan-92-ignored", str(worktree_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    (worktree_path / "feature.txt").write_text("feature\n", encoding="utf-8")
    (worktree_path / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(worktree_path), "add", "feature.txt", ".gitignore"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(worktree_path), "commit", "-m", "feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_root), "merge", "--no-ff", "plan-92-ignored", "-m", "merge feature"],
        check=True,
        capture_output=True,
        text=True,
    )
    (worktree_path / "ignored.txt").write_text("ignored\n", encoding="utf-8")
    claim = module.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="landed-with-ignored-artifact",
        intent="Close landed work",
        claim_type="write",
        plan_ref="UNPLANNED",
        write_paths=["feature.txt"],
        branch="plan-92-ignored",
        worktree_path=str(worktree_path),
        session_id="codex:test",
    )

    assert module.claim_lifecycle_issues(claim) == ["branch_merged_to_default"]
    assert module.claim_enforcement_issues(claim)[0]["code"] == "merged_active_claim_requires_disposition"


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
            "plan_ref": "UNPLANNED",
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


def _drain_completed_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    completed: int,
) -> tuple[list, int, Path]:
    """Prune ``completed`` claims beside two live ones and report registry re-reads."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(module._impl, "CLAIMS_DIR", claims_dir)
    for index in range(2):
        _write_claim(
            claims_dir,
            f"live-{index}.yaml",
            {
                "agent": "codex",
                "claimed_at": "2026-04-05T12:00:00+00:00",
                "expires_at": "2099-04-05T13:00:00+00:00",
                "projects": ["demo"],
                "scope": f"live-scope-{index}",
                "intent": "Live lane that must survive the drain",
                "claim_type": "write",
                "session_id": f"codex:live-{index}",
                "repo_root": str(tmp_path / f"repo-{index}"),
                "worktree_path": str(tmp_path / f"repo-{index}" / "worktrees" / f"live-{index}"),
                "branch": f"live-{index}",
                "write_paths": [f"src/live_{index}.py"],
                "status": "active",
            },
        )
    for index in range(completed):
        _write_claim(
            claims_dir,
            f"done-{index}.yaml",
            _completed_claim_payload(
                scope=f"done-scope-{index}",
                session_id=f"codex:done-{index}",
            ),
        )

    projection_reads = 0
    original_loader = prewrite_claim_projection._load_projection_claims

    def counting_loader(claims_dir_arg: Path):
        nonlocal projection_reads
        projection_reads += 1
        return original_loader(claims_dir_arg)

    monkeypatch.setattr(prewrite_claim_projection, "_load_projection_claims", counting_loader)

    pruned, _labels = module.prune_completed()
    assert pruned == completed

    receipts = [
        event for event in claim_mutation_receipts.load_receipts() if event.operation == "prune"
    ]
    return receipts, projection_reads, claims_dir


def test_prune_completed_binds_every_receipt_without_rebuilding_per_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A drain must keep each receipt's projection digest exact at constant rebuild cost.

    Rebuilding the projection from disk after every unlink made a drain
    quadratic in claim count. The receipt contract still requires a non-null
    ``projection_digest_after`` equal to ``registry_digest_after`` on every
    applied mutation, so this asserts both halves at once: the per-claim digest
    chain stays exact, and the number of whole-registry re-reads does not grow
    with the number of claims pruned.
    """

    small_receipts, small_reads, small_dir = _drain_completed_claims(
        tmp_path / "small", monkeypatch, completed=3
    )
    large_receipts, large_reads, large_dir = _drain_completed_claims(
        tmp_path / "large", monkeypatch, completed=9
    )

    assert len(small_receipts) == 3
    assert len(large_receipts) == 12  # the ledger is shared across both drains
    assert small_reads == large_reads

    drained = large_receipts[3:]
    for receipt in drained:
        assert receipt.result == "applied_projection_current"
        assert receipt.projection_current_after is True
        assert receipt.projection_digest_after
        assert receipt.projection_digest_after == receipt.registry_digest_after
    for earlier, later in zip(drained, drained[1:]):
        assert earlier.registry_digest_after == later.registry_digest_before
    assert drained[-1].registry_digest_after == registry_digest(large_dir)

    for claims_dir in (small_dir, large_dir):
        assert sorted(path.name for path in claims_dir.glob("*.yaml")) == [
            "live-0.yaml",
            "live-1.yaml",
        ]
        assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)
        projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1.model_validate_json(
            projection_path_for(claims_dir).read_text(encoding="utf-8")
        )
        assert sorted(claim.scope for claim in projection.claims) == [
            "live-scope-0",
            "live-scope-1",
        ]


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
    real_validate = claim_mutation_receipts.CompletedClaimArchiveReceiptV1.model_validate_json

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
    conflicting_payload["receipt_sha256"] = claim_mutation_receipts.completed_claim_archive_receipt_sha256(
        conflicting_payload
    )
    conflicting = claim_mutation_receipts.CompletedClaimArchiveReceiptV1.model_validate(conflicting_payload)

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
            "plan_ref": "UNPLANNED",
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
            "--plan",
            "UNPLANNED",
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
            "plan_ref": "UNPLANNED",
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


from enforced_planning import coordination_claims  # noqa: E402

# ---------------------------------------------------------------------------
# Per-session claim identity
#
# Claims are filed through resolve_session_id, but the pre-write gate compares
# against the session_id Claude Code puts in its hook payload, which is the real
# per-session UUID. While resolve_session_id fell back to CLAUDE_CODE_SSE_PORT
# the two never matched, so a session that filed a claim correctly still failed
# its own gate -- and every session on one CLI server shared the port, so claim
# ownership was not per-session at all.
# ---------------------------------------------------------------------------


def _registry_with_self(tmp_path, session_id):
    import json
    import os

    entry = tmp_path / f"{os.getpid()}.json"
    entry.write_text(json.dumps({"pid": os.getpid(), "sessionId": session_id}), encoding="utf-8")
    return tmp_path


def test_session_id_recovered_from_process_tree(tmp_path):
    registry = _registry_with_self(tmp_path, "uuid-mine")
    assert coordination_claims.session_id_from_process_tree(registry_dir=registry) == "uuid-mine"


def test_absent_registry_entry_yields_no_identity(tmp_path):
    """No identity is better than a shared one: the caller must be able to tell."""
    assert coordination_claims.session_id_from_process_tree(registry_dir=tmp_path) is None


def test_malformed_registry_entry_does_not_raise(tmp_path):
    import os

    (tmp_path / f"{os.getpid()}.json").write_text("{not json", encoding="utf-8")
    assert coordination_claims.session_id_from_process_tree(registry_dir=tmp_path) is None


def test_shared_sse_port_is_not_minted_when_a_real_id_exists(monkeypatch, tmp_path):
    registry = _registry_with_self(tmp_path, "uuid-mine")
    monkeypatch.setattr(coordination_claims, "CLAUDE_SESSION_REGISTRY", registry)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "41292")

    resolved = coordination_claims.resolve_session_id("claude-code")
    assert resolved == "claude-code:uuid-mine"
    assert not resolved.startswith("claude-code:sse:")


def test_legacy_shared_identity_still_matches_an_existing_claim(monkeypatch, tmp_path):
    """Claims filed before this change must remain releasable by their owner."""
    registry = _registry_with_self(tmp_path, "uuid-mine")
    monkeypatch.setattr(coordination_claims, "CLAUDE_SESSION_REGISTRY", registry)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "41292")

    resolved = coordination_claims.resolve_session_id("claude-code")
    aliases = coordination_claims.session_identity_aliases("claude-code", resolved)
    assert resolved in aliases
    assert "claude-code:sse:41292" in aliases


def test_no_legacy_alias_is_offered_without_a_port(monkeypatch, tmp_path):
    registry = _registry_with_self(tmp_path, "uuid-mine")
    monkeypatch.setattr(coordination_claims, "CLAUDE_SESSION_REGISTRY", registry)
    monkeypatch.delenv("CLAUDE_CODE_SSE_PORT", raising=False)

    resolved = coordination_claims.resolve_session_id("claude-code")
    aliases = coordination_claims.session_identity_aliases("claude-code", resolved)
    assert all(not alias.startswith("claude-code:sse:") for alias in aliases)


def test_explicit_identity_still_wins(monkeypatch, tmp_path):
    """Lifecycle hooks and recovery tools pass an explicit id and must keep control."""
    monkeypatch.setattr(coordination_claims, "CLAUDE_SESSION_REGISTRY", _registry_with_self(tmp_path, "uuid-mine"))
    assert coordination_claims.resolve_session_id("claude-code", "claude-code:explicit") == "claude-code:explicit"


def test_codex_identity_is_untouched(monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "thread-xyz")
    assert coordination_claims.resolve_session_id("codex") == "codex:thread-xyz"


def test_record_progress_updates_exact_owner_and_preserves_sibling(tmp_path: Path) -> None:
    """Every accepted kind updates one exact owner without refreshing liveness or siblings."""

    claims_dir = tmp_path / "claims"
    heartbeat_at = "2026-08-21T08:00:00+00:00"
    ownership = {
        "agent": "codex",
        "projects": ["demo"],
        "scope": "progress-lane",
        "intent": "Implement the progress lease",
        "claim_type": "program",
        "write_paths": ["src/progress.py"],
        "read_paths": [],
        "worktree_path": str(tmp_path / "worktree"),
        "repo_root": str(tmp_path / "repo"),
        "branch": "plan-progress",
        "session_name": "progress-lease",
        "broader_goal": "Finish progress lease",
        "tracker_path": str(tmp_path / "tracker.yaml"),
        "session_id": "codex:progress-owner",
        "heartbeat_at": heartbeat_at,
        "status": "active",
        "claimed_at": "2026-08-21T07:00:00+00:00",
        "updated_at": heartbeat_at,
        "expires_at": "2099-08-22T00:00:00+00:00",
        "progress_at": "2026-08-21T07:00:00+00:00",
        "progress_kind": "claim_started",
        "evidence_ref": "Plan #110",
        "next_action": "Implement mutation",
        "expected_quiet_until": "2026-08-21T09:00:00+00:00",
        "quiet_reason": "bounded initial operation",
    }
    _write_claim(claims_dir, "owner.yaml", ownership)
    sibling = {**ownership, "scope": "sibling-lane", "write_paths": ["src/sibling.py"]}
    _write_claim(claims_dir, "sibling.yaml", sibling)
    sibling_before = (claims_dir / "sibling.yaml").read_bytes()

    kinds = [
        "claim_started",
        "verified_commit",
        "accepted_artifact",
        "new_diagnostic",
        "integration_result",
    ]
    for index, kind in enumerate(kinds, start=1):
        observed_at = datetime.fromisoformat(f"2026-08-21T08:00:0{index}+00:00")
        updated, event = claims_impl.record_progress_claims(
            agent="codex",
            project="demo",
            scope="progress-lane",
            progress_kind=kind,
            evidence_ref=f"receipt-{index}",
            next_action=f"continue-{index}",
            session_id="codex:progress-owner",
            claims_dir=claims_dir,
            now=observed_at,
        )
        assert updated.progress_kind == kind
        assert updated.evidence_ref == f"receipt-{index}"
        assert event.recorded_at == observed_at

    persisted = yaml.safe_load((claims_dir / "owner.yaml").read_text(encoding="utf-8"))
    assert persisted["heartbeat_at"] == heartbeat_at
    assert persisted["session_id"] == "codex:progress-owner"
    assert persisted["progress_kind"] == "integration_result"
    assert persisted["evidence_ref"] == "receipt-5"
    assert persisted["next_action"] == "continue-5"
    assert persisted["expected_quiet_until"] is None
    assert persisted["quiet_reason"] is None
    assert (claims_dir / "sibling.yaml").read_bytes() == sibling_before
    projection = json.loads(projection_path_for(claims_dir).read_text(encoding="utf-8"))
    assert projection["registry_digest"] == registry_digest(claims_dir)
    receipts = claim_mutation_receipts.load_receipts()
    assert [receipt.operation for receipt in receipts] == ["session_upsert"] * len(kinds)
    assert all(receipt.projection_current_after for receipt in receipts)
    owner_before_regression = (claims_dir / "owner.yaml").read_bytes()
    with pytest.raises(ValueError, match="must advance beyond"):
        claims_impl.record_progress_claims(
            agent="codex",
            project="demo",
            scope="progress-lane",
            progress_kind="integration_result",
            evidence_ref="older-receipt",
            next_action="must not replace newer evidence",
            session_id="codex:progress-owner",
            claims_dir=claims_dir,
            now=datetime.fromisoformat("2026-08-21T08:00:04+00:00"),
        )
    assert (claims_dir / "owner.yaml").read_bytes() == owner_before_regression
    assert len(claim_mutation_receipts.load_receipts()) == len(kinds)


@pytest.mark.parametrize(
    ("overrides", "error"),
    [
        ({"session_id": "codex:wrong-owner"}, "matched no exact live owning claim"),
        ({"progress_kind": "blocker"}, "invalid progress event"),
        ({"progress_kind": "handoff"}, "invalid progress event"),
        ({"evidence_ref": "  "}, "invalid progress event"),
        (
            {"expected_quiet_until": "2026-08-21T09:00:00", "quiet_reason": "suite"},
            "invalid progress event",
        ),
        ({"expected_quiet_until": "2026-08-21T09:00:00+00:00"}, "invalid progress event"),
    ],
)
def test_record_progress_rejects_invalid_or_wrong_owner_without_mutation(
    tmp_path: Path,
    overrides: dict[str, str],
    error: str,
) -> None:
    """Rejected progress input leaves canonical claim bytes and receipts unchanged."""

    claims_dir = tmp_path / "claims"
    _write_claim(
        claims_dir,
        "owner.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "progress-lane",
            "intent": "Implement progress",
            "claim_type": "program",
            "session_id": "codex:owner",
            "status": "active",
            "expires_at": "2099-08-22T00:00:00+00:00",
            "progress_at": "2026-08-21T07:00:00+00:00",
            "progress_kind": "claim_started",
            "evidence_ref": "Plan #110",
            "next_action": "continue",
        },
    )
    claim_path = claims_dir / "owner.yaml"
    before = claim_path.read_bytes()
    kwargs = {
        "agent": "codex",
        "project": "demo",
        "scope": "progress-lane",
        "progress_kind": "verified_commit",
        "evidence_ref": "abc123",
        "next_action": "run focused tests",
        "session_id": "codex:owner",
        "claims_dir": claims_dir,
        "now": datetime.fromisoformat("2026-08-21T08:00:00+00:00"),
        **overrides,
    }

    with pytest.raises(ValueError, match=error):
        claims_impl.record_progress_claims(**kwargs)

    assert claim_path.read_bytes() == before
    assert claim_mutation_receipts.load_receipts() == []


def test_record_progress_rejects_ambiguous_exact_claim_without_mutation(tmp_path: Path) -> None:
    """Duplicate exact identities fail before either claim can be changed."""

    claims_dir = tmp_path / "claims"
    payload = {
        "agent": "codex",
        "projects": ["demo"],
        "scope": "duplicate-lane",
        "intent": "Repair duplicates",
        "claim_type": "program",
        "session_id": "codex:owner",
        "status": "active",
        "expires_at": "2099-08-22T00:00:00+00:00",
    }
    _write_claim(claims_dir, "duplicate-a.yaml", payload)
    _write_claim(claims_dir, "duplicate-b.yaml", payload)
    before = {path.name: path.read_bytes() for path in claims_dir.glob("*.yaml")}

    with pytest.raises(ValueError, match="matched multiple live claims"):
        claims_impl.record_progress_claims(
            agent="codex",
            project="demo",
            scope="duplicate-lane",
            progress_kind="new_diagnostic",
            evidence_ref="duplicate-receipt",
            next_action="repair claim identity",
            session_id="codex:owner",
            claims_dir=claims_dir,
            now=datetime.fromisoformat("2026-08-21T08:00:00+00:00"),
        )

    assert {path.name: path.read_bytes() for path in claims_dir.glob("*.yaml")} == before
    assert claim_mutation_receipts.load_receipts() == []


def test_record_progress_rejects_quiet_interval_without_bounded_claim_expiry(tmp_path: Path) -> None:
    """Malformed legacy expiry cannot authorize an effectively indefinite quiet interval."""

    claims_dir = tmp_path / "claims"
    _write_claim(
        claims_dir,
        "owner.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "quiet-lane",
            "intent": "Bound quiet work",
            "claim_type": "program",
            "session_id": "codex:owner",
            "status": "active",
            "expires_at": "not-a-timestamp",
        },
    )
    claim_path = claims_dir / "owner.yaml"
    before = claim_path.read_bytes()

    with pytest.raises(ValueError, match="requires a valid timezone-aware claim expiry"):
        claims_impl.record_progress_claims(
            agent="codex",
            project="demo",
            scope="quiet-lane",
            progress_kind="new_diagnostic",
            evidence_ref="trace:1",
            next_action="wait for the bounded tool run",
            expected_quiet_until="2026-08-21T09:00:00+00:00",
            quiet_reason="bounded tool run",
            session_id="codex:owner",
            claims_dir=claims_dir,
            now=datetime.fromisoformat("2026-08-21T08:00:00+00:00"),
        )

    assert claim_path.read_bytes() == before
    assert claim_mutation_receipts.load_receipts() == []


def test_progress_cli_requires_and_uses_exact_native_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The public command accepts its ambient owner and rejects asserted or absent identity."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(claims_impl, "CLAIMS_DIR", claims_dir)
    _write_claim(
        claims_dir,
        "owner.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "native-lane",
            "intent": "Exercise public progress",
            "claim_type": "program",
            "session_id": "codex:native-owner",
            "heartbeat_at": "2026-08-21T08:00:00+00:00",
            "status": "active",
            "expires_at": "2099-08-22T00:00:00+00:00",
        },
    )
    claim_path = claims_dir / "owner.yaml"
    monkeypatch.setenv("CODEX_THREAD_ID", "native-owner")
    args = [
        "--progress",
        "--agent",
        "codex",
        "--project",
        "demo",
        "--scope",
        "native-lane",
        "--progress-kind",
        "integration_result",
        "--evidence-ref",
        "receipt:public-cli",
        "--next-action",
        "inspect public status",
        "--json",
    ]

    assert claims_impl.main(args) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["progress_event"]["kind"] == "integration_result"
    assert "recorded_at" in result["progress_event"]
    persisted = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert persisted["heartbeat_at"] == "2026-08-21T08:00:00+00:00"
    assert persisted["evidence_ref"] == "receipt:public-cli"
    after_success = claim_path.read_bytes()

    monkeypatch.delenv("CODEX_THREAD_ID")
    assert claims_impl.main([*args[:-1], "--session-id", "codex:native-owner", "--json"]) == 1
    missing_native = json.loads(capsys.readouterr().out)
    assert "requires the current native codex runtime" in missing_native["error"]
    assert claim_path.read_bytes() == after_success

    monkeypatch.setenv("CODEX_THREAD_ID", "different-owner")
    assert claims_impl.main([*args[:-1], "--session-id", "codex:native-owner", "--json"]) == 1
    mismatch = json.loads(capsys.readouterr().out)
    assert "does not match the current codex runtime" in mismatch["error"]
    assert claim_path.read_bytes() == after_success

    monkeypatch.setenv("CODEX_THREAD_ID", "native-owner")
    missing_scope_args = ["missing-scope" if value == "native-lane" else value for value in args]
    assert claims_impl.main(missing_scope_args) == 1
    zero_match = json.loads(capsys.readouterr().out)
    assert "matched no exact live owning claim" in zero_match["error"]
    assert claim_path.read_bytes() == after_success


def test_progress_cli_reports_applied_mutation_when_receipt_append_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A ledger outage returns nonzero without pretending the applied claim write rolled back."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(claims_impl, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "audit-owner")
    _write_claim(
        claims_dir,
        "owner.yaml",
        {
            "agent": "codex",
            "projects": ["demo"],
            "scope": "audit-lane",
            "intent": "Prove audit failure semantics",
            "claim_type": "program",
            "session_id": "codex:audit-owner",
            "heartbeat_at": "2026-08-21T08:00:00+00:00",
            "status": "active",
            "expires_at": "2099-08-22T00:00:00+00:00",
        },
    )

    def fail_append(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated progress receipt outage")

    monkeypatch.setattr(claim_mutation_receipts, "append_receipt", fail_append)
    exit_code = claims_impl.main(
        [
            "--progress",
            "--agent",
            "codex",
            "--project",
            "demo",
            "--scope",
            "audit-lane",
            "--progress-kind",
            "new_diagnostic",
            "--evidence-ref",
            "trace:audit",
            "--next-action",
            "repair receipt sink",
            "--json",
        ]
    )

    assert exit_code == 1
    failure = json.loads(capsys.readouterr().out)
    assert failure["mutation_applied"] is True
    assert failure["error_code"] == "mutation_applied_audit_failed"
    persisted = yaml.safe_load((claims_dir / "owner.yaml").read_text(encoding="utf-8"))
    assert persisted["progress_kind"] == "new_diagnostic"
    assert persisted["evidence_ref"] == "trace:audit"
    assert json.loads(projection_path_for(claims_dir).read_text(encoding="utf-8"))[
        "registry_digest"
    ] == registry_digest(claims_dir)


def test_progress_classifier_has_frozen_boundaries_and_stale_precedence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One frozen clock distinguishes healthy, stalled, quiet, malformed, legacy, and stale."""

    repo_root = tmp_path / "repo"
    _init_git_repo(repo_root)
    base = claims_impl.build_candidate_claim(
        agent="codex",
        project="demo",
        scope="progress-lane",
        intent="Classify progress",
        claim_type="program",
        plan_ref="UNPLANNED",
        worktree_path=str(repo_root),
        repo_root=str(repo_root),
        branch="main",
        session_name="progress-lane",
        broader_goal="Progress lease",
        tracker_path=str(tmp_path / "tracker.yaml"),
        session_id="codex:owner",
        heartbeat_at="2026-08-21T09:59:00+00:00",
        expires_at="2099-08-22T00:00:00+00:00",
        progress_at="2026-08-21T09:00:00+00:00",
        progress_kind="verified_commit",
        evidence_ref="abc123",
        next_action="run integration",
    )
    before = datetime.fromisoformat("2026-08-21T09:59:59+00:00")
    boundary = datetime.fromisoformat("2026-08-21T10:00:00+00:00")

    assert claims_impl.claim_runtime_status(base, now=before) == "healthy"
    assert claims_impl.claim_progress_issues(base, now=boundary) == ["stalled_progress_lease"]
    assert claims_impl.claim_runtime_status(base, now=boundary) == "stalled"

    quiet = replace(
        base,
        expected_quiet_until="2026-08-21T10:15:00+00:00",
        quiet_reason="bounded repository suite",
    )
    assert (
        claims_impl.claim_progress_issues(
            quiet,
            now=datetime.fromisoformat("2026-08-21T10:14:59+00:00"),
        )
        == []
    )
    assert claims_impl.claim_progress_issues(
        quiet,
        now=datetime.fromisoformat("2026-08-21T10:15:00+00:00"),
    ) == ["stalled_progress_lease"]
    unbounded_quiet = replace(quiet, expires_at="not-a-timestamp")
    assert "quiet_interval_requires_valid_claim_expiry" in claims_impl.claim_progress_issues(
        unbounded_quiet,
        now=datetime.fromisoformat("2026-08-21T10:14:59+00:00"),
    )

    malformed = replace(base, evidence_ref=None)
    assert claims_impl.claim_runtime_status(malformed, now=boundary) == "weak"
    assert "incomplete_progress_event" in claims_impl.claim_progress_issues(malformed, now=boundary)
    future = replace(base, progress_at="2026-08-21T10:01:00+00:00")
    assert claims_impl.claim_progress_issues(future, now=boundary) == ["future_progress_at"]
    assert claims_impl.claim_runtime_status(future, now=boundary) == "weak"
    legacy = replace(
        base,
        progress_at=None,
        progress_kind=None,
        evidence_ref=None,
        next_action=None,
    )
    assert claims_impl.claim_progress_issues(legacy, now=boundary) == []
    assert claims_impl.claim_runtime_status(legacy, now=boundary) == "healthy"

    stale = replace(base, heartbeat_at="2026-08-21T07:00:00+00:00")
    assert claims_impl.claim_runtime_status(stale, now=boundary) == "stale"
    missing_heartbeat = replace(base, heartbeat_at=None)
    assert claims_impl.claim_progress_issues(missing_heartbeat, now=boundary) == ["stalled_progress_lease"]
    assert claims_impl.claim_runtime_status(missing_heartbeat, now=boundary) == "weak"
    monkeypatch.setenv("COORDINATION_PROGRESS_STALE_MINUTES", "not-a-number")
    with pytest.raises(ValueError, match="must be a positive number"):
        claims_impl.claim_progress_issues(base, now=boundary)


def test_heartbeat_file_dirt_and_stalled_prune_preserve_progress_and_ownership(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-progress activity cannot renew or release a fresh-heartbeat stalled claim."""

    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)
    repo_root = tmp_path / "repo"
    _init_git_repo(repo_root)
    claim_payload = {
        "agent": "codex",
        "projects": ["demo"],
        "scope": "stalled-lane",
        "intent": "Preserve stalled work",
        "claim_type": "program",
        "plan_ref": "UNPLANNED",
        "write_paths": ["src/progress.py"],
        "worktree_path": str(repo_root),
        "repo_root": str(repo_root),
        "branch": "main",
        "session_name": "stalled-lane",
        "broader_goal": "Preserve stalled lane custody",
        "tracker_path": str(tmp_path / "tracker.yaml"),
        "session_id": "codex:owner",
        "heartbeat_at": datetime.now(timezone.utc).isoformat(),
        "status": "active",
        "expires_at": "2099-08-22T00:00:00+00:00",
        "progress_at": "2000-01-01T00:00:00+00:00",
        "progress_kind": "verified_commit",
        "evidence_ref": "abc123",
        "next_action": "record real advancement or hand off",
    }
    _write_claim(claims_dir, "stalled.yaml", claim_payload)
    path = claims_dir / "stalled.yaml"
    invariant_fields = (
        "agent",
        "projects",
        "scope",
        "status",
        "claim_type",
        "write_paths",
        "worktree_path",
        "repo_root",
        "branch",
        "session_id",
        "expires_at",
        "progress_at",
        "progress_kind",
        "evidence_ref",
        "next_action",
    )
    before = yaml.safe_load(path.read_text(encoding="utf-8"))

    count, scopes, _session, _heartbeat = module.heartbeat_claims(
        agent="codex",
        project="demo",
        scope="stalled-lane",
        session_id="codex:owner",
        require_exact_session=True,
    )
    assert (count, scopes) == (1, ["stalled-lane"])
    after_heartbeat = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert {field: after_heartbeat.get(field) for field in invariant_fields} == {
        field: before.get(field) for field in invariant_fields
    }

    (repo_root / "untracked.txt").write_text("local work\n", encoding="utf-8")
    claim = module.check_claims("demo")[0]
    assert module.claim_runtime_status(claim) == "stalled"
    after_dirt = path.read_bytes()
    removed, scopes = module.prune_stale(agent="codex", project="demo", scope="stalled-lane")
    assert (removed, scopes) == (0, [])
    assert path.read_bytes() == after_dirt
    assert path.exists()


def test_session_liveness_reads_the_clients_own_transcript(tmp_path: Path) -> None:
    """A claim's heartbeat lags; the client's transcript is written every turn."""

    codex_root = tmp_path / "codex-sessions"
    day = codex_root / "2026" / "08" / "25"
    day.mkdir(parents=True)
    transcript = day / "rollout-2026-08-25T07-20-07-01a0394a-ee7e-7b22-bedc-82ddb2a253f2.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    written_at = datetime(2026, 8, 26, 18, 18, 37, tzinfo=timezone.utc)
    os.utime(transcript, (written_at.timestamp(), written_at.timestamp()))

    found = claims_impl.session_last_active_at(
        "codex:01a0394a-ee7e-7b22-bedc-82ddb2a253f2", codex_root=codex_root
    )

    assert found == written_at


def test_session_liveness_reports_unknown_rather_than_idle(tmp_path: Path) -> None:
    """Absence of a transcript is not evidence that a session ended."""

    for session_id in (
        "codex:no-such-session",
        "claude-code:no-such-session",
        "openclaw:whatever",
        "malformed",
        None,
    ):
        assert (
            claims_impl.session_last_active_at(
                session_id, codex_root=tmp_path / "codex", claude_root=tmp_path / "claude"
            )
            is None
        )


def test_session_activity_is_described_without_licensing_a_takeover() -> None:
    """An operator reading a conflict sees liveness, never permission."""

    now = datetime(2026, 8, 26, 18, 30, tzinfo=timezone.utc)
    describe = claims_impl.describe_session_activity

    assert describe(None, now=now) == "liveness unknown"
    assert describe(datetime(2026, 8, 26, 18, 29, 30, tzinfo=timezone.utc), now=now) == (
        "active seconds ago"
    )
    assert describe(datetime(2026, 8, 26, 18, 11, tzinfo=timezone.utc), now=now) == (
        "last active 19 min ago"
    )
    quiet = describe(datetime(2026, 8, 25, 15, 11, tzinfo=timezone.utc), now=now)
    assert quiet.startswith("last active 27h ago")
    assert "likely ended without releasing" in quiet
