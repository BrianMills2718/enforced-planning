"""Tests for claim-v2-aware safe worktree removal guards."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "worktree-coordination"
    / "safe_worktree_remove.py"
)


def _load() -> object:
    spec = importlib.util.spec_from_file_location("safe_worktree_remove_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_check_worktree_claimed_prefers_claim_v2_records(tmp_path: Path) -> None:
    """The cleanup guard should prefer the canonical claim-v2 worktree claim surface."""
    module = _load()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    worktree_path = tmp_path / "project-meta_worktrees" / "plan-111"
    worktree_path.mkdir(parents=True)

    (claims_dir / "claim.yaml").write_text(
        yaml.safe_dump(
            {
                "agent": "codex",
                "claimed_at": "2026-04-05T00:00:00+00:00",
                "expires_at": "2099-04-05T12:00:00+00:00",
                "projects": ["project-meta"],
                "scope": "lane-lifecycle-automation",
                "intent": "Implement lifecycle automation",
                "claim_type": "write",
                "write_paths": ["scripts/complete_plan.py"],
                "branch": "plan-111-lifecycle-automation",
                "worktree_path": str(worktree_path),
                "session_id": "codex:session",
                "plan_ref": "Plan #111",
                "status": "active",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    claimed, info = module.check_worktree_claimed(str(worktree_path), claims_file=claims_dir)  # type: ignore[attr-defined]

    assert claimed is True
    assert info is not None
    assert info["coordination_source"] == "claim_v2"
    assert info["agent"] == "codex"
    assert info["scope"] == "lane-lifecycle-automation"


def test_should_block_removal_uses_claim_v2_active_claims(tmp_path: Path) -> None:
    """Active claim-v2 ownership should block worktree removal even without legacy YAML."""
    module = _load()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    worktree_path = tmp_path / "project-meta_worktrees" / "plan-111"
    worktree_path.mkdir(parents=True)

    (claims_dir / "claim.yaml").write_text(
        yaml.safe_dump(
            {
                "agent": "codex",
                "claimed_at": "2026-04-05T00:00:00+00:00",
                "expires_at": "2099-04-05T12:00:00+00:00",
                "projects": ["project-meta"],
                "scope": "lane-lifecycle-automation",
                "intent": "Implement lifecycle automation",
                "claim_type": "write",
                "write_paths": ["scripts/complete_plan.py"],
                "branch": "plan-111-lifecycle-automation",
                "worktree_path": str(worktree_path),
                "session_id": "codex:session",
                "plan_ref": "Plan #111",
                "status": "active",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    blocked, reason, info = module.should_block_removal(  # type: ignore[attr-defined]
        str(worktree_path),
        force=False,
        claims_file=claims_dir,
        my_identity={"branch": "main", "cwd": "project-meta", "is_main": True},
    )

    assert blocked is True
    assert reason == "claim"
    assert info is not None
    assert info["coordination_source"] == "claim_v2"
