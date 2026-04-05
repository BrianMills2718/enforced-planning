"""Tests for generated active-work registry outputs."""

from __future__ import annotations

import json
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from enforced_planning import active_work_registry as module


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Write one YAML claim fixture for registry-generation tests."""
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_generate_registry_outputs_json_and_markdown(tmp_path: Path) -> None:
    """Registry generation should emit machine-readable and compact markdown views."""
    claims_dir = tmp_path / "claims"
    json_output = tmp_path / "generated" / "runtime" / "active_work_registry.json"
    markdown_output = tmp_path / "generated" / "runtime" / "active_work_registry.md"

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
            "worktree_path": "~/projects/project-meta_worktrees/coordination-a",
            "session_id": "claude-code-session",
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
            "worktree_path": "~/projects/project-meta_worktrees/plan-62-coordination-v2",
            "session_id": "codex-session",
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
        "weak_claim_count": 1,
        "hard_conflict_claim_count": 2,
        "soft_overlap_claim_count": 0,
    }
    execution_lane = next(
        lane for lane in payload["lanes"] if lane["branch"] == "plan-62-coordination-v2"
    )
    assert execution_lane["claim_count"] == 1
    assert execution_lane["health_status"] == "attention"
    fallback_lane = next(
        lane for lane in payload["lanes"] if lane["fallback_scope"] == "phase-6-ops-and-governance"
    )
    assert fallback_lane["health_status"] == "weak"
    assert fallback_lane["claim_count"] == 1
    codex_entry = next(entry for entry in payload["claims"] if entry["agent"] == "codex")
    assert codex_entry["interaction_summary"]["hard_conflict_count"] == 1
    assert codex_entry["health_status"] == "healthy"
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
