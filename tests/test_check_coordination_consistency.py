"""Tests for coordination consistency checks across claims, registry outputs, and worktrees."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from enforced_planning import active_work_registry, coordination_claims, coordination_consistency


def _run(cmd: list[str], cwd: Path) -> None:
    """Run one git command and fail loudly when setup breaks."""
    subprocess.run(cmd, cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(repo_root: Path) -> None:
    """Create a minimal git repo with one initial commit."""
    repo_root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], cwd=repo_root)
    _run(["git", "config", "user.email", "codex@example.com"], cwd=repo_root)
    _run(["git", "config", "user.name", "Codex"], cwd=repo_root)
    (repo_root / "README.md").write_text("demo\n", encoding="utf-8")
    _run(["git", "add", "README.md"], cwd=repo_root)
    _run(["git", "commit", "-m", "init"], cwd=repo_root)


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Write one YAML v2 claim fixture."""
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_coordination_consistency_passes_when_registry_and_worktrees_match(tmp_path: Path) -> None:
    """An empty claim set with a synced registry and only the main worktree should pass cleanly."""
    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)

    claims_dir = tmp_path / "claims"
    coordination_claims.CLAIMS_DIR = claims_dir

    registry_json = repo_root / "generated" / "runtime" / "active_work_registry.json"
    registry_markdown = repo_root / "generated" / "runtime" / "active_work_registry.md"
    assert active_work_registry.main(
        [
            "--claims-dir",
            str(claims_dir),
            "--json-output",
            str(registry_json),
            "--markdown-output",
            str(registry_markdown),
        ]
    ) == 0

    exit_code = coordination_consistency.main(
        [
            "--workspace-root",
            str(workspace),
            "--repo",
            "project-meta",
            "--claims-dir",
            str(claims_dir),
            "--registry-json",
            str(registry_json),
            "--registry-markdown",
            str(registry_markdown),
            "--json",
        ]
    )

    assert exit_code == 0


def test_coordination_consistency_detects_missing_claim_worktree(tmp_path: Path, capsys) -> None:
    """A live claim pointing at a missing worktree path should hard-fail."""
    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)

    claims_dir = tmp_path / "claims"
    missing_worktree = workspace / "project-meta_worktrees" / "plan-93-missing"
    _write_claim(
        claims_dir,
        "claim.yaml",
        {
            "agent": "codex",
            "projects": ["project-meta"],
            "scope": "wave-5",
            "intent": "Run consistency lane",
            "claim_type": "write",
            "write_paths": ["scripts"],
            "worktree_path": str(missing_worktree),
            "branch": "plan-93-wave5-coordination-state",
            "status": "active",
            "claimed_at": "2026-04-04T08:00:00+00:00",
            "expires_at": "2099-04-04T09:00:00+00:00",
        },
    )
    coordination_claims.CLAIMS_DIR = claims_dir

    exit_code = coordination_consistency.main(
        [
            "--workspace-root",
            str(workspace),
            "--repo",
            "project-meta",
            "--claims-dir",
            str(claims_dir),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["hard_issue_count"] >= 1
    assert any(issue["code"] == "claim-worktree-missing" for issue in payload["issues"])


def test_coordination_consistency_warns_on_unclaimed_linked_worktree(tmp_path: Path, capsys) -> None:
    """A linked non-main worktree without a live claim should warn but not hard-fail."""
    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    linked_worktree = workspace / "project-meta_worktrees" / "plan-93-unclaimed"
    _run(["git", "worktree", "add", "-b", "plan-93-unclaimed", str(linked_worktree)], cwd=repo_root)

    claims_dir = tmp_path / "claims"
    coordination_claims.CLAIMS_DIR = claims_dir

    exit_code = coordination_consistency.main(
        [
            "--workspace-root",
            str(workspace),
            "--repo",
            "project-meta",
            "--claims-dir",
            str(claims_dir),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["warning_count"] >= 1
    assert any(issue["code"] == "worktree-unclaimed" for issue in payload["issues"])


def test_cli_filters_foreign_claims_and_accepts_explicit_repo_paths(tmp_path: Path, capsys) -> None:
    """A scoped audit must not misclassify claims owned by repositories outside its target set."""

    workspace = tmp_path / "workspace"
    repo_root = workspace / "nested" / "project-meta"
    foreign_root = workspace / "foreign"
    _init_repo(repo_root)
    _init_repo(foreign_root)

    claims_dir = tmp_path / "claims"
    _write_claim(
        claims_dir,
        "foreign.yaml",
        {
            "agent": "codex",
            "projects": ["foreign"],
            "scope": "foreign-lane",
            "intent": "Unrelated work",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "worktree_path": str(foreign_root),
            "repo_root": str(foreign_root),
            "branch": "main",
            "status": "active",
            "claimed_at": "2026-04-04T08:00:00+00:00",
            "expires_at": "2099-04-04T09:00:00+00:00",
        },
    )

    exit_code = coordination_consistency.main(
        [
            "--repo",
            f"project-meta={repo_root}",
            "--claims-dir",
            str(claims_dir),
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["claim_count"] == 0
    assert payload["repos"] == {"project-meta": str(repo_root.resolve())}
    assert not any(issue["code"] == "claim-project-out-of-scope" for issue in payload["issues"])


def test_cli_can_require_current_prewrite_projection(tmp_path: Path, capsys) -> None:
    """The operator audit should visibly reject a missing or stale hook projection."""

    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    claims_dir = tmp_path / "claims"

    exit_code = coordination_consistency.main(
        [
            "--workspace-root",
            str(workspace),
            "--repo",
            "project-meta",
            "--claims-dir",
            str(claims_dir),
            "--verify-prewrite-projection",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["prewrite_projection_current"] is False
    assert any(issue["code"] == "prewrite-projection-drift" for issue in payload["issues"])


def _make_prunable_worktree(repo_root: Path, path: Path, branch: str) -> None:
    """Create a linked worktree, then simulate an interrupted filesystem removal."""

    _run(["git", "worktree", "add", "-b", branch, str(path)], cwd=repo_root)
    shutil.rmtree(path)


def test_reconciler_prunes_only_missing_unclaimed_registration(tmp_path: Path, capsys) -> None:
    """A vanished unclaimed path is removed from Git metadata while its branch survives."""

    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    missing = workspace / "project-meta_worktrees" / "interrupted"
    _make_prunable_worktree(repo_root, missing, "interrupted")

    exit_code = coordination_consistency.main(
        [
            "--repo",
            f"project-meta={repo_root}",
            "--claims-dir",
            str(tmp_path / "claims"),
            "--prune-missing-registrations",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["reconciliation"]["pruned_count"] == 1
    assert payload["reconciliation"]["remaining_prunable_paths"] == []
    listed = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert str(missing) not in listed
    branch = subprocess.run(
        ["git", "branch", "--list", "interrupted"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "interrupted" in branch


def test_reconciler_reports_existing_unclaimed_dirty_lane_without_removing_it(
    tmp_path: Path,
    capsys,
) -> None:
    """Existing non-live state remains visible and physically untouched."""

    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    linked = workspace / "project-meta_worktrees" / "dirty-unclaimed"
    _run(["git", "worktree", "add", "-b", "dirty-unclaimed", str(linked)], cwd=repo_root)
    (linked / "LOCAL.txt").write_text("preserve me\n", encoding="utf-8")

    exit_code = coordination_consistency.main(
        [
            "--repo",
            f"project-meta={repo_root}",
            "--claims-dir",
            str(tmp_path / "claims"),
            "--prune-missing-registrations",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["reconciliation"]["pruned_count"] == 0
    assert linked.exists()
    assert (linked / "LOCAL.txt").read_text(encoding="utf-8") == "preserve me\n"
    assert any(
        issue["code"] == "worktree-unclaimed" and issue["worktree_path"] == str(linked)
        for issue in payload["issues"]
    )


def test_reconciler_blocks_repo_when_missing_registration_has_live_claim(
    tmp_path: Path,
    capsys,
) -> None:
    """Repository-wide Git pruning cannot cross a live claim, even for an absent path."""

    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    missing = workspace / "project-meta_worktrees" / "claimed-missing"
    _make_prunable_worktree(repo_root, missing, "claimed-missing")
    claims_dir = tmp_path / "claims"
    _write_claim(
        claims_dir,
        "claim.yaml",
        {
            "agent": "codex",
            "projects": ["project-meta"],
            "scope": "claimed-missing",
            "intent": "Preserve interrupted lane",
            "claim_type": "write",
            "write_paths": ["README.md"],
            "worktree_path": str(missing),
            "branch": "claimed-missing",
            "status": "active",
            "claimed_at": "2026-04-04T08:00:00+00:00",
            "expires_at": "2099-04-04T09:00:00+00:00",
        },
    )

    exit_code = coordination_consistency.main(
        [
            "--repo",
            f"project-meta={repo_root}",
            "--claims-dir",
            str(claims_dir),
            "--prune-missing-registrations",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["reconciliation"]["actions"][0]["action"] == "blocked_live_claim"
    assert payload["reconciliation"]["pruned_count"] == 0
    assert str(missing) in payload["reconciliation"]["remaining_prunable_paths"]


def test_reconciler_dry_run_preserves_registration(tmp_path: Path, capsys) -> None:
    """Dry-run proves eligibility without mutating Git's worktree registry."""

    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    missing = workspace / "project-meta_worktrees" / "dry-run"
    _make_prunable_worktree(repo_root, missing, "dry-run")

    exit_code = coordination_consistency.main(
        [
            "--repo",
            f"project-meta={repo_root}",
            "--claims-dir",
            str(tmp_path / "claims"),
            "--prune-missing-registrations",
            "--dry-run",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 1
    assert payload["reconciliation"]["actions"][0]["action"] == "would_prune"
    assert payload["reconciliation"]["pruned_count"] == 0
    assert str(missing) in payload["reconciliation"]["remaining_prunable_paths"]
