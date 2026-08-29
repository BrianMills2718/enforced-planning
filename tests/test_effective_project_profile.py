from __future__ import annotations

from pathlib import Path

import pytest

from enforced_planning.effective_project_profile import load_effective_project_profile
from enforced_planning.effective_project_profile import resolve_effective_project_profile
from enforced_planning.governed_repo_audit import audit_repo


def test_absent_configuration_is_default_on() -> None:
    profile = resolve_effective_project_profile(None)
    assert profile.master_enabled is True
    assert profile.master_source == "default"
    assert profile.controls["knowledge_navigation.enabled"].effective is True
    assert profile.controls["plans.integrity.mode"].effective == "enforce"
    assert profile.wiki_authority == "derived_navigation"


def test_master_off_forces_effective_off_but_preserves_configured_modes() -> None:
    payload = {"meta_process": {"governance": {"enabled": False}, "claims": {"prewrite_mode": "enforce"}, "knowledge_navigation": {"freshness_mode": "enforce"}}}
    profile = resolve_effective_project_profile(payload)
    assert profile.controls["claims.prewrite_mode"].configured == "enforce"
    assert profile.controls["claims.prewrite_mode"].effective == "off"
    assert profile.controls["knowledge_navigation.freshness_mode"].configured == "enforce"
    assert profile.controls["knowledge_navigation.freshness_mode"].effective == "off"
    payload["meta_process"]["governance"]["enabled"] = True
    restored = resolve_effective_project_profile(payload)
    assert restored.controls["claims.prewrite_mode"].effective == "enforce"
    assert restored.controls["knowledge_navigation.freshness_mode"].effective == "enforce"


def test_loader_rejects_invalid_master_value(tmp_path: Path) -> None:
    (tmp_path / "meta-process.yaml").write_text("meta_process:\n  governance:\n    enabled: sometimes\n", encoding="utf-8")
    with pytest.raises(ValueError, match="must be a boolean"):
        load_effective_project_profile(tmp_path)


def test_master_off_makes_missing_governance_nonblocking_in_audit(tmp_path: Path) -> None:
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  governance:\n    enabled: false\n", encoding="utf-8"
    )
    report = audit_repo(
        tmp_path,
        claude_file="CLAUDE.md",
        relationships_file="scripts/relationships.yaml",
        agents_file="AGENTS.md",
        plans_dir="docs/plans",
    )
    assert report["status"] == "PASS"
    assert report["classification"] == "disabled"
    assert report["missing_required"] == []
    assert report["suppressed_missing_required"]
