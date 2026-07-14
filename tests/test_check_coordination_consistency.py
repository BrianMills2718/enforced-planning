"""Tests for coordination consistency checks across claims, registry outputs, and worktrees."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml  # type: ignore[import-untyped]

from enforced_planning import active_work_registry
from enforced_planning import coordination_claims
from enforced_planning import coordination_consistency


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


def test_sanctioned_worktree_path_requires_a_strict_descendant(tmp_path: Path) -> None:
    """The container directory itself and similarly prefixed siblings are not branch worktrees."""
    sanctioned_root = tmp_path / "repo" / "worktrees"

    assert coordination_consistency._is_within_directory(
        path=sanctioned_root / "plan-68",
        directory=sanctioned_root,
    )
    assert not coordination_consistency._is_within_directory(
        path=sanctioned_root,
        directory=sanctioned_root,
    )
    assert not coordination_consistency._is_within_directory(
        path=tmp_path / "repo" / "worktrees-retired" / "plan-68",
        directory=sanctioned_root,
    )


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
    linked_worktree = repo_root / "worktrees" / "plan-93-unclaimed"
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
    assert not any(issue["code"] == "worktree-outside-sanctioned-root" for issue in payload["issues"])


def test_coordination_consistency_reports_retired_worktree_path_without_enforcement(
    tmp_path: Path, capsys
) -> None:
    """Report mode should expose a retired sibling-layout worktree without blocking."""
    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    linked_worktree = workspace / "project-meta_worktrees" / "plan-93-retired"
    _run(["git", "worktree", "add", "-b", "plan-93-retired", str(linked_worktree)], cwd=repo_root)

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
    path_issues = [
        issue for issue in payload["issues"] if issue["code"] == "worktree-outside-sanctioned-root"
    ]
    assert exit_code == 0
    assert len(path_issues) == 1
    assert path_issues[0]["severity"] == "warning"
    assert path_issues[0]["worktree_path"] == str(linked_worktree)


def test_coordination_consistency_rejects_retired_worktree_path_when_enforced(
    tmp_path: Path, capsys
) -> None:
    """Enforcement mode should hard-fail the same retired sibling-layout worktree."""
    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    _init_repo(repo_root)
    linked_worktree = workspace / "project-meta_worktrees" / "plan-93-retired"
    _run(["git", "worktree", "add", "-b", "plan-93-retired", str(linked_worktree)], cwd=repo_root)

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
            "--enforce-sanctioned-worktree-root",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    path_issues = [
        issue for issue in payload["issues"] if issue["code"] == "worktree-outside-sanctioned-root"
    ]
    assert exit_code == 1
    assert len(path_issues) == 1
    assert path_issues[0]["severity"] == "hard"


def test_coordination_consistency_can_scope_claims_to_selected_repositories(
    tmp_path: Path, capsys
) -> None:
    """Repository-local mode should ignore otherwise valid claims for other repositories."""
    workspace = tmp_path / "workspace"
    repo_root = workspace / "project-meta"
    other_repo = workspace / "other-project"
    _init_repo(repo_root)
    _init_repo(other_repo)

    claims_dir = tmp_path / "claims"
    _write_claim(
        claims_dir,
        "other-claim.yaml",
        {
            "agent": "codex",
            "projects": ["other-project"],
            "scope": "other-scope",
            "intent": "Work in another repository",
            "claim_type": "program",
            "write_paths": [],
            "worktree_path": str(other_repo),
            "branch": "main",
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
            "--scope-claims-to-repos",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["claim_count"] == 0
    assert not any(issue["code"] == "claim-project-out-of-scope" for issue in payload["issues"])
