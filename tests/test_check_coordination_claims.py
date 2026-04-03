"""Tests for coordination-claim schema v2 and overlap detection."""

from __future__ import annotations

import importlib.util
import json
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


def test_create_claim_without_write_paths_stays_backward_compatible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy-style claim creation without write paths should still produce a broad program claim."""
    module = _load_module()
    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(module, "CLAIMS_DIR", claims_dir)

    ok, message = module.create_claim(
        "codex",
        "project-meta",
        "phase-6-ops-and-governance",
        "Broad governance cleanup",
        plan_ref="Plan #62",
    )

    assert ok
    assert "[program]" in message
    claim_file = claims_dir / "codex_project-meta_phase-6-ops-and-governance.yaml"
    payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert payload["claim_type"] == "program"
    assert payload["write_paths"] == []


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
    assert payload["check"]["has_hard_conflict"] is True
    assert payload["check"]["interactions"][0]["severity"] == "hard_conflict"
