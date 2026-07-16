"""Tests for generated active-work registry outputs."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from enforced_planning import active_work_registry as module


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Write one YAML claim fixture for registry-generation tests."""
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


def test_generate_registry_outputs_json_and_markdown(tmp_path: Path) -> None:
    """Registry generation should emit machine-readable and compact markdown views."""
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"
    repo_root = tmp_path / "project-meta"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "branch", "coordination-a"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "branch", "plan-62-coordination-v2"], check=True, capture_output=True, text=True)
    worktrees_root = tmp_path / "project-meta_worktrees"
    coordination_a = worktrees_root / "coordination-a"
    coordination_b = worktrees_root / "plan-62-coordination-v2"
    coordination_a.mkdir(parents=True)
    coordination_b.mkdir(parents=True)

    _write_claim(
        claims_dir,
        "write-a.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["project-meta"],
            "scope": "coordination-v2-a",
            "intent": "Patch claims tool",
            "claim_type": "write",
            "write_paths": ["scripts"],
            "plan_ref": "Plan #62",
            "branch": "coordination-a",
            "worktree_path": str(coordination_a),
            "repo_root": str(repo_root),
            "session_id": "claude-code-session",
            "session_name": "coordination-v2",
            "broader_goal": "Coordination V2",
            "tracker_path": str(tmp_path / "sessions" / "claude.yaml"),
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "write-b.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-02T08:10:00+00:00",
            "expires_at": "2099-04-02T09:10:00+00:00",
            "projects": ["project-meta"],
            "scope": "coordination-v2-b",
            "intent": "Generate registry",
            "claim_type": "write",
            "write_paths": ["scripts/generate_active_work_registry.py"],
            "plan_ref": "Plan #62",
            "branch": "plan-62-coordination-v2",
            "worktree_path": str(coordination_b),
            "repo_root": str(repo_root),
            "session_id": "codex-session",
            "session_name": "coordination-v2",
            "broader_goal": "Coordination V2",
            "tracker_path": str(tmp_path / "sessions" / "codex.yaml"),
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "program.yaml",
        {
            "agent": "openclaw",
            "claimed_at": "2026-04-02T08:20:00+00:00",
            "expires_at": "2099-04-02T09:20:00+00:00",
            "project": "project-meta",
            "scope": "phase-6-ops-and-governance",
            "intent": "Broad governance sweep",
        },
    )

    exit_code = module.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["claim_count"] == 3
    assert payload["lane_count"] == 3
    assert payload["claims_by_type"] == {"program": 1, "write": 2}
    assert payload["lanes_by_project"] == {"project-meta": 3}
    assert payload["health_summary"] == {
        "overall_status": "attention",
        "stale_claim_count": 0,
        "weak_claim_count": 3,
        "hard_conflict_claim_count": 2,
        "soft_overlap_claim_count": 0,
    }
    execution_lane = next(
        lane for lane in payload["lanes"] if lane["branch"] == "plan-62-coordination-v2"
    )
    assert execution_lane["claim_count"] == 1
    assert execution_lane["health_status"] == "weak"
    assert execution_lane["health_issues"] == ["missing_program_root"]
    fallback_lane = next(
        lane for lane in payload["lanes"] if lane["fallback_scope"] == "phase-6-ops-and-governance"
    )
    assert fallback_lane["health_status"] == "weak"
    assert fallback_lane["claim_count"] == 1
    codex_entry = next(entry for entry in payload["claims"] if entry["agent"] == "codex")
    assert codex_entry["interaction_summary"]["hard_conflict_count"] == 1
    assert codex_entry["health_status"] == "weak"
    assert codex_entry["hierarchy_issues"] == ["missing_program_root"]
    assert any(note["severity"] == "hard_conflict" for note in codex_entry["conflict_notes"])
    program_entry = next(entry for entry in payload["claims"] if entry["agent"] == "openclaw")
    assert program_entry["health_status"] == "weak"
    assert program_entry["health_issues"] == [
        "missing_branch",
        "missing_worktree_path",
        "missing_session_id",
    ]
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "# Active Work Registry" in markdown
    assert "## Coordination Health" in markdown
    assert "## Active Lanes" in markdown
    assert "## Health Notes" in markdown
    assert "coordination-v2-b" in markdown
    assert "phase-6-ops-and-governance" in markdown
    assert "hard=1" in markdown
    assert "weak" in markdown


def test_generate_registry_handles_empty_claim_set(tmp_path: Path) -> None:
    """Registry generation should still emit valid empty outputs when no claims exist."""
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"

    exit_code = module.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["claim_count"] == 0
    assert payload["lane_count"] == 0
    assert payload["health_summary"]["overall_status"] == "idle"
    assert payload["claims"] == []
    assert payload["lanes"] == []
    assert "No live claims." in markdown_output.read_text(encoding="utf-8")


def test_registry_renders_plan_root_and_child_hierarchy(tmp_path: Path) -> None:
    """The derivative registry should expose one root plus its child scopes."""

    claims_dir = tmp_path / "claims"
    base = {
        "claimed_at": "2026-07-16T20:00:00+00:00",
        "expires_at": "2099-07-16T21:00:00+00:00",
        "projects": ["onto-canon6"],
        "repo_root": str(tmp_path / "onto-canon6"),
        "session_name": "complete-plan-0141",
        "broader_goal": "Complete Plan 0141",
        "tracker_path": str(tmp_path / "sessions" / "tracker.yaml"),
        "status": "active",
    }
    _write_claim(
        claims_dir,
        "root.yaml",
        {
            **base,
            "agent": "codex",
            "scope": "plan0141-root",
            "intent": "coordinate Plan 0141",
            "claim_type": "program",
            "plan_ref": "Plan #0141",
            "branch": "plan0141-root",
            "worktree_path": str(tmp_path / "onto-canon6" / "worktrees" / "root"),
            "session_id": "codex:root",
        },
    )
    _write_claim(
        claims_dir,
        "child.yaml",
        {
            **base,
            "agent": "claude-code",
            "scope": "plan0141-review",
            "intent": "review Plan 0141",
            "claim_type": "write",
            "write_paths": ["src/review.py"],
            "plan_ref": "Plan #141 reviewer slice",
            "branch": "plan0141-review",
            "worktree_path": str(tmp_path / "onto-canon6" / "worktrees" / "review"),
            "session_id": "claude-code:review",
            "parent_scope": "plan0141-root",
        },
    )

    claims = module.coordination_claims.check_claims(claims_dir=claims_dir)
    payload = module.build_registry_payload(claims=claims)
    markdown = module.render_markdown(payload)

    assert payload["plan_hierarchies"] == [
        {
            "project": "onto-canon6",
            "plan_identity": "Plan #141",
            "root_scope": "plan0141-root",
            "root_count": 1,
            "child_scopes": ["plan0141-review"],
            "claim_count": 2,
            "health_status": "healthy",
            "health_issues": [],
        }
    ]
    assert "## Plan Hierarchies" in markdown
    assert "plan0141-root" in markdown
    assert "plan0141-review" in markdown


def test_generate_registry_marks_stale_claims_and_lanes(tmp_path: Path) -> None:
    """Registry generation should classify stale claims separately from weak claims."""
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    subprocess.run(["git", "-C", str(repo_root), "branch", "plan-95-stale"], check=True, capture_output=True, text=True)

    _write_claim(
        claims_dir,
        "stale.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["demo"],
            "scope": "stale-lane",
            "intent": "Stale lane",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "plan_ref": "Plan #95",
            "branch": "plan-95-stale",
            "worktree_path": str(tmp_path / "demo_worktrees" / "plan-95-stale"),
            "session_id": "codex:test",
            "status": "active",
        },
    )

    exit_code = module.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["health_summary"]["stale_claim_count"] == 1
    assert payload["health_summary"]["overall_status"] == "attention"
    assert payload["claims"][0]["health_status"] == "stale"
    assert payload["claims"][0]["lifecycle_issues"] == ["missing_worktree_on_disk"]
    assert payload["lanes"][0]["health_status"] == "stale"
    assert payload["lanes"][0]["lifecycle_issues"] == ["missing_worktree_on_disk"]
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "Stale claims" in markdown
    assert "stale (missing_worktree_on_disk)" in markdown


def test_generate_registry_marks_stale_session_claims_and_lanes(tmp_path: Path, monkeypatch) -> None:
    """Registry generation should classify stale session heartbeats as stale."""
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"
    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    worktree_path = tmp_path / "demo_worktrees" / "plan-96-heartbeat"
    worktree_path.mkdir(parents=True)
    monkeypatch.setenv("COORDINATION_HEARTBEAT_STALE_MINUTES", "30")

    _write_claim(
        claims_dir,
        "stale-session.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-05T12:00:00+00:00",
            "expires_at": "2099-04-05T13:00:00+00:00",
            "projects": ["demo"],
            "scope": "stale-session-lane",
            "intent": "Stale session lane",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "plan_ref": "Plan #96",
            "branch": "plan-96-heartbeat",
            "worktree_path": str(worktree_path),
            "session_id": "codex:thread-old",
            "heartbeat_at": "2026-04-05T08:00:00+00:00",
            "status": "active",
        },
    )

    exit_code = module.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(json_output),
            "--markdown-output",
            str(markdown_output),
        ]
    )

    assert exit_code == 0
    payload = json.loads(json_output.read_text(encoding="utf-8"))
    assert payload["health_summary"]["stale_claim_count"] == 1
    assert payload["claims"][0]["health_status"] == "stale"
    assert payload["claims"][0]["liveness_issues"] == ["stale_session_heartbeat"]
    assert payload["lanes"][0]["health_status"] == "stale"
    assert payload["lanes"][0]["liveness_issues"] == ["stale_session_heartbeat"]
    markdown = markdown_output.read_text(encoding="utf-8")
    assert "stale_session_heartbeat" in markdown
