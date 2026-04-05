"""Tests for coordination-claim schema v2 and overlap detection."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]


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


def _init_git_repo(repo_root: Path) -> None:
    """Create a minimal git repo with a configured identity."""
    subprocess.run(["git", "init", "-b", "main", str(repo_root)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "seed"], check=True, capture_output=True, text=True)


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
    )

    assert ok
    assert "[program]" in message
    claim_file = claims_dir / "codex_project-meta_phase-6-ops-and-governance.yaml"
    payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert payload["claim_type"] == "program"
    assert payload["branch"] == "plan-90-coordination-graph-runtime"
    assert payload["session_id"] == "codex-session-1"


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
        plan_ref="Plan #62",
        claim_type="write",
        write_paths=["scripts/check_coordination_claims.py"],
        branch="plan-62-coordination-v2",
        worktree_path="~/projects/project-meta_worktrees/plan-62-coordination-v2",
    )

    assert ok
    claim_file = claims_dir / "codex_project-meta_coordination-v2.yaml"
    payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert payload["session_id"] == "codex:thread-123"


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
    assert payload["claims"][0]["health_issues"] == ["missing_branch", "missing_worktree_path", "missing_session_id"]
    assert payload["check"]["has_hard_conflict"] is True
    assert payload["check"]["candidate_health_status"] == "weak"
    assert payload["check"]["interactions"][0]["severity"] == "hard_conflict"
