"""Tests for the shared worktree-creation guardrail wrapper."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]


MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "worktree-coordination"
    / "create_worktree.py"
)


def _load_module():
    """Load the standalone worktree-creation script as a module."""
    spec = importlib.util.spec_from_file_location("create_worktree_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command against a temp repo."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _init_temp_repo(repo_root: Path) -> None:
    """Create a minimal committed git repo suitable for worktree tests."""
    repo_root.mkdir(parents=True, exist_ok=True)
    _run_git(repo_root, "init")
    _run_git(repo_root, "config", "user.name", "Test User")
    _run_git(repo_root, "config", "user.email", "test@example.com")
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
    add_result = _run_git(repo_root, "add", "README.md")
    assert add_result.returncode == 0, add_result.stdout + add_result.stderr
    commit_result = _run_git(repo_root, "commit", "-m", "init")
    assert commit_result.returncode == 0, commit_result.stdout + commit_result.stderr



def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    """Write one YAML claim fixture for worktree-enforcement tests."""
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")



def test_parse_status_porcelain_classifies_split_brain_like() -> None:
    """Mass deleted plus mass untracked entries should classify as split-brain-like."""
    module = _load_module()
    porcelain = "\n".join(
        [
            "## plan-39-repro",
            " D README.md",
            " D src/a.py",
            " D src/b.py",
            " D src/c.py",
            " D tests/test_a.py",
            "?? repo/README.md",
            "?? repo/src/a.py",
            "?? repo/src/b.py",
            "?? repo/src/c.py",
            "?? repo/tests/test_a.py",
        ]
    )

    summary = module.parse_status_porcelain(porcelain, split_brain_threshold=5)

    assert not summary.clean
    assert summary.deleted_count == 5
    assert summary.untracked_count == 5
    assert summary.split_brain_like
    assert module.classify_summary(summary) == "split-brain-like"



def test_create_worktree_creates_clean_temp_repo_worktree(tmp_path: Path) -> None:
    """The wrapper should create a clean worktree in a temp git repo."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo-worktrees" / "plan-39-test"
    _init_temp_repo(repo_root)

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-39-test",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
    )

    assert result.ok, result.message
    assert result.classification == "clean"
    assert result.status is not None and result.status.clean
    assert worktree_path.exists()

    cleanup_result = _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
    assert cleanup_result.returncode == 0, cleanup_result.stdout + cleanup_result.stderr
    delete_branch = _run_git(repo_root, "branch", "-D", "plan-39-test")
    assert delete_branch.returncode == 0, delete_branch.stdout + delete_branch.stderr


def test_create_worktree_excludes_required_nested_container_from_canonical_status(
    tmp_path: Path,
) -> None:
    """A sanctioned nested worktree must not make the canonical checkout dirty."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = repo_root / "worktrees" / "plan-39-nested"
    _init_temp_repo(repo_root)

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-39-nested",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
    )

    assert result.ok, result.message
    canonical_status = _run_git(repo_root, "status", "--porcelain", "--untracked-files=all")
    assert canonical_status.returncode == 0
    assert canonical_status.stdout == ""
    exclude_path = repo_root / ".git" / "info" / "exclude"
    assert exclude_path.read_text(encoding="utf-8").splitlines().count("/worktrees/") == 1

    assert module.ensure_default_worktree_container_excluded(repo_root, worktree_path)
    assert exclude_path.read_text(encoding="utf-8").splitlines().count("/worktrees/") == 1

    cleanup_result = _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
    assert cleanup_result.returncode == 0, cleanup_result.stdout + cleanup_result.stderr
    delete_branch = _run_git(repo_root, "branch", "-D", "plan-39-nested")
    assert delete_branch.returncode == 0, delete_branch.stdout + delete_branch.stderr



def test_create_worktree_cleans_up_detected_dirty_initial_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wrapper should fail loud and clean up when initial state is unsafe."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo-worktrees" / "plan-39-dirty"
    _init_temp_repo(repo_root)

    dirty_summary = module.WorktreeStatusSummary(
        branch_line="plan-39-dirty",
        entries=[module.StatusEntry(code=" D", path="README.md")] * 5
        + [module.StatusEntry(code="??", path="repo/README.md")] * 5,
        deleted_count=5,
        untracked_count=5,
        split_brain_like=True,
        clean=False,
    )

    monkeypatch.setattr(module, "inspect_worktree_state", lambda *args, **kwargs: dirty_summary)

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-39-dirty",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
    )

    assert not result.ok
    assert result.classification == "split-brain-like"
    assert result.cleanup_performed
    assert not worktree_path.exists()

    branch_check = _run_git(repo_root, "show-ref", "--verify", "refs/heads/plan-39-dirty")
    assert branch_check.returncode != 0



def test_get_default_worktree_dir_uses_canonical_repo_root_from_worktree(
    tmp_path: Path,
) -> None:
    """Canonical default worktree dir should be stable across root and linked worktree contexts."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    # Worktrees live inside the repo under worktrees/<branch>/ per current policy.
    linked_worktree = repo_root / "worktrees" / "plan-42-proof"
    _init_temp_repo(repo_root)

    add_result = _run_git(repo_root, "worktree", "add", "-b", "plan-42-proof", str(linked_worktree))
    assert add_result.returncode == 0, add_result.stdout + add_result.stderr

    expected = repo_root / "worktrees"
    assert module.get_default_worktree_dir(repo_root) == expected
    assert module.get_default_worktree_dir(linked_worktree) == expected
    assert module.get_canonical_project_name(repo_root) == "repo"
    assert module.get_canonical_project_name(linked_worktree) == "repo"

    cleanup_result = _run_git(repo_root, "worktree", "remove", "--force", str(linked_worktree))
    assert cleanup_result.returncode == 0, cleanup_result.stdout + cleanup_result.stderr
    delete_branch = _run_git(repo_root, "branch", "-D", "plan-42-proof")
    assert delete_branch.returncode == 0, delete_branch.stdout + delete_branch.stderr



def test_create_worktree_requires_scoped_write_claim_when_enabled(tmp_path: Path) -> None:
    """Strict worktree enforcement should fail loudly when no matching write claim exists."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "plan-62-missing-claim"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-62-missing-claim",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/ops"],
        claims_dir=claims_dir,
    )

    assert not result.ok
    assert result.classification == "coordination-error"
    assert "no active matching write claim" in result.message
    assert not worktree_path.exists()



def test_create_worktree_rejects_conflicting_scoped_write_claim(tmp_path: Path) -> None:
    """Strict worktree enforcement should block conflicting active write claims."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "plan-62-conflict"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)

    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["repo"],
            "scope": "coordination-v2",
            "intent": "Patch docs",
            "claim_type": "write",
            "write_paths": ["docs/ops"],
            "branch": "plan-62-conflict",
            "worktree_path": "~/projects/repo_worktrees/plan-62-conflict",
            "session_id": "codex-session",
            "session_name": "coordination-v2",
            "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "claude.yaml",
        {
            "agent": "claude-code",
            "claimed_at": "2026-04-02T08:05:00+00:00",
            "expires_at": "2099-04-02T09:05:00+00:00",
            "projects": ["repo"],
            "scope": "other-docs",
            "intent": "Patch docs too",
            "claim_type": "write",
            "write_paths": ["docs"],
            "branch": "claude-docs",
            "worktree_path": "~/projects/repo_worktrees/claude-docs",
            "session_id": "claude-session",
            "session_name": "other-docs",
            "status": "active",
        },
    )

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-62-conflict",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/ops/INDEX.md"],
        claims_dir=claims_dir,
    )

    assert not result.ok
    assert result.classification == "coordination-error"
    assert "conflicting active write claim" in result.message
    assert not worktree_path.exists()


def test_verify_clean_main_root_reports_dirty_primary_checkout(tmp_path: Path) -> None:
    """Publish-lane creation should fail loud when the canonical main checkout is dirty."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    _init_temp_repo(repo_root)
    (repo_root / "README.md").write_text("dirty\n", encoding="utf-8")

    ok, message = module.verify_clean_main_root(repo_root)

    assert not ok
    assert "canonical main checkout is not clean" in message
    assert "classification=main-root-dirty" in message


def test_create_worktree_blocks_dirty_main_root_when_required(tmp_path: Path) -> None:
    """Optional main-root cleanliness enforcement should block publish worktree creation."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "publish-lane"
    _init_temp_repo(repo_root)
    (repo_root / "README.md").write_text("dirty\n", encoding="utf-8")

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="publish-lane",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_clean_main_root=True,
    )

    assert not result.ok
    assert result.classification == "main-root-dirty"
    assert "canonical main checkout is not clean" in result.message
    assert not worktree_path.exists()



def test_create_worktree_allows_matching_scoped_write_claim(tmp_path: Path) -> None:
    """Strict worktree enforcement should allow a matching non-conflicting scoped claim."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "plan-62-valid"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)

    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["repo"],
            "scope": "coordination-v2",
            "intent": "Patch docs",
            "claim_type": "write",
            "write_paths": ["docs/ops"],
            "branch": "plan-62-valid",
            "worktree_path": "~/projects/repo_worktrees/plan-62-valid",
            "session_id": "codex-session",
            "session_name": "coordination-v2",
            "status": "active",
        },
    )

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-62-valid",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/ops/INDEX.md"],
        claims_dir=claims_dir,
    )

    assert result.ok, result.message
    assert result.classification == "clean"
    assert result.coordination_checked
    assert result.coordination_message is not None
    assert "Scoped write claim verified" in result.coordination_message
    assert worktree_path.exists()

    cleanup_result = _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
    assert cleanup_result.returncode == 0, cleanup_result.stdout + cleanup_result.stderr
    delete_branch = _run_git(repo_root, "branch", "-D", "plan-62-valid")
    assert delete_branch.returncode == 0, delete_branch.stdout + delete_branch.stderr


def test_create_worktree_rejects_weak_matching_write_claim(tmp_path: Path) -> None:
    """Strict worktree enforcement should reject a matching claim that is still weak."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "plan-90-weak-claim"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)

    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "agent": "codex",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["repo"],
            "scope": "coordination-v2",
            "intent": "Patch docs",
            "claim_type": "write",
            "write_paths": ["docs/ops"],
            "branch": "plan-90-weak-claim",
            "status": "active",
        },
    )

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="plan-90-weak-claim",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/ops/INDEX.md"],
        claims_dir=claims_dir,
    )

    assert not result.ok
    assert result.classification == "coordination-error"
    assert "matching active write claim is weak" in result.message
    assert "missing_worktree_path" in result.message
    assert not worktree_path.exists()
