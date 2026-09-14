"""Tests for claim-v2-aware safe worktree removal guards."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
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


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _real_repo_with_readonly_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("root\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    worktree = tmp_path / "target-worktree"
    _git(repo, "worktree", "add", "-b", "target", str(worktree))
    readonly = worktree / "readonly"
    readonly.mkdir()
    (readonly / "nested.txt").write_text("safe\n", encoding="utf-8")
    _git(worktree, "add", "readonly/nested.txt")
    _git(worktree, "commit", "-m", "add readonly directory")
    readonly.chmod(0o555)
    return repo, worktree


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


def test_run_cmd_includes_stderr(tmp_path: Path) -> None:
    """A failed Git command must expose stderr for a recoverable diagnosis."""
    module = _load()
    success, output = module.run_cmd(["git", "rev-parse", "--git-dir"], cwd=str(tmp_path))  # type: ignore[attr-defined]
    assert success is False
    assert "not a git repository" in output


def test_remove_worktree_uses_target_repo_and_handles_readonly_directories(
    tmp_path: Path, monkeypatch
) -> None:
    """Clean cross-repo worktrees should not be partially unregistered by the guard."""
    module = _load()
    repo, worktree = _real_repo_with_readonly_worktree(tmp_path)
    monkeypatch.setattr(module, "should_block_removal", lambda *_args, **_kwargs: (False, "", None))

    assert module.remove_worktree(str(worktree)) is True  # type: ignore[attr-defined]
    assert not worktree.exists()
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout
    assert str(worktree) not in listed


def test_remove_worktree_restores_readonly_modes_after_git_failure(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """A failed removal restores temporary permission changes and exposes stderr."""
    module = _load()
    _repo, worktree = _real_repo_with_readonly_worktree(tmp_path)
    readonly = worktree / "readonly"
    original_run = module.run_cmd
    monkeypatch.setattr(module, "should_block_removal", lambda *_args, **_kwargs: (False, "", None))

    def fail_remove(command, cwd=None):
        if command[:3] == ["git", "worktree", "remove"]:
            return False, "permission denied"
        return original_run(command, cwd=cwd)

    monkeypatch.setattr(module, "run_cmd", fail_remove)

    assert module.remove_worktree(str(worktree)) is False  # type: ignore[attr-defined]
    assert readonly.stat().st_mode & 0o777 == 0o555
    assert "permission denied" in capsys.readouterr().out


def test_provisioning_marker_blocks_removal_even_in_force_mode(tmp_path: Path) -> None:
    """A partially populated worktree must never be mistaken for disposable residue."""
    module = _load()
    target = tmp_path / "worktrees" / "provisioning-lane"
    target.mkdir(parents=True)
    digest = hashlib.sha256(str(target.resolve()).encode("utf-8")).hexdigest()
    marker = target.parent / f".worktree-provisioning-{digest}.json"
    marker.write_text(json.dumps({"target_worktree_path": str(target.resolve())}), encoding="utf-8")

    blocked, reason, info = module.should_block_removal(str(target), force=True)

    assert blocked
    assert reason == "provisioning"
    assert info == {"marker_path": str(marker)}
