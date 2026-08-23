"""Execution checks for the plan binding the Make worktree targets put on a claim.

The maintenance entrypoint and the plan-bound entrypoint share one recipe. These
tests expand that recipe with `make -n` and read the claim invocation it would
run, so a regression that drops the plan flag -- or hardcodes UNPLANNED onto
plan-bound lanes -- fails here instead of at a live lane creation.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import yaml  # type: ignore[import-untyped]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CREATE_WORKTREE_PATH = PROJECT_ROOT / "scripts" / "worktree-coordination" / "create_worktree.py"

_COMMON_MAKE_VARS = [
    'TASK=probe',
    'SESSION_GOAL=probe goal',
    'SESSION_PHASE=probe phase',
    'AGENT=claude-code',
    'SESSION_WRITE_PATHS=README.md',
]


def _dry_run_make(target: str, *extra_vars: str) -> str:
    """Expand one Make target without executing it."""
    result = subprocess.run(
        ["make", "-n", target, *_COMMON_MAKE_VARS, *extra_vars],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _claim_invocation(make_output: str) -> str:
    """Return the single check_coordination_claims --claim command from an expansion."""
    lines = make_output.splitlines()
    starts = [i for i, line in enumerate(lines) if "check_coordination_claims.py\" --claim" in line]
    assert len(starts) == 1, f"expected exactly one claim invocation, got {len(starts)}"
    collected = []
    for line in lines[starts[0] :]:
        collected.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return "\n".join(collected)


def test_maintenance_worktree_claim_declares_unplanned_ownership() -> None:
    """The maintenance lane must stamp UNPLANNED on its pre-worktree claim.

    Without this the claim is created planless, and the planless-claim guard
    rejects the very entrypoint it is meant to govern.
    """
    invocation = _claim_invocation(_dry_run_make("maintenance-worktree", "BRANCH=probe-unplanned"))

    assert "--plan UNPLANNED" in invocation
    assert "#" not in invocation.split("--plan")[1]


def test_plan_bound_worktree_claim_keeps_its_real_plan_reference() -> None:
    """A numbered plan lane must keep its qualified plan id, never UNPLANNED."""
    invocation = _claim_invocation(_dry_run_make("worktree", "BRANCH=plan-42-probe", "PLAN=42"))

    assert '--plan "enforced-planning#42"' in invocation
    assert "UNPLANNED" not in invocation


def _load_create_worktree():
    """Load the standalone worktree-creation script as a module."""
    spec = importlib.util.spec_from_file_location("create_worktree_target_module", CREATE_WORKTREE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run one git command against a temp repo."""
    return subprocess.run(["git", *args], cwd=str(repo_root), capture_output=True, text=True, check=False)


def _init_temp_repo(repo_root: Path) -> None:
    """Create a minimal committed git repo suitable for worktree tests."""
    repo_root.mkdir(parents=True, exist_ok=True)
    _run_git(repo_root, "init")
    _run_git(repo_root, "config", "user.name", "Test User")
    _run_git(repo_root, "config", "user.email", "test@example.com")
    (repo_root / "README.md").write_text("hello\n", encoding="utf-8")
    assert _run_git(repo_root, "add", "README.md").returncode == 0
    assert _run_git(repo_root, "commit", "-m", "init").returncode == 0


def _unplanned_claim(repo_root: Path, worktree_path: Path, **overrides: object) -> dict:
    """Build the claim shape the maintenance entrypoint creates before the worktree exists."""
    payload = {
        "agent": "claude-code",
        "claimed_at": "2026-08-23T08:00:00+00:00",
        "expires_at": "2099-08-23T09:00:00+00:00",
        "projects": ["repo"],
        "scope": "maintenance-probe",
        "intent": "Unplanned maintenance",
        "claim_type": "program",
        "write_paths": ["README.md"],
        "branch": "maintenance-probe",
        "worktree_path": str(worktree_path),
        "repo_root": str(repo_root),
        "session_id": "claude-code:session",
        "session_name": "maintenance-probe",
        "broader_goal": "maintenance-probe goal",
        "tracker_path": None,
        "plan_ref": "UNPLANNED",
        "status": "active",
    }
    payload.update(overrides)
    return payload


def _attempt(module, repo_root: Path, worktree_path: Path, claims_dir: Path):
    """Run claim-enforced worktree creation for the maintenance-probe lane."""
    return module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="maintenance-probe",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="claude-code",
        claim_project="repo",
        claim_write_paths=["README.md"],
        claims_dir=claims_dir,
    )


def test_unplanned_staged_claim_may_create_its_worktree_before_the_tracker_exists(tmp_path: Path) -> None:
    """The tracker is written by session-start, which runs after the worktree.

    The plan-bound lane already had this exemption; the unplanned lane did not,
    so a correctly UNPLANNED-stamped maintenance claim was rejected as weak.
    """
    module = _load_create_worktree()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "maintenance-probe"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "claim.yaml").write_text(
        yaml.safe_dump(_unplanned_claim(repo_root, worktree_path), sort_keys=False), encoding="utf-8"
    )

    result = _attempt(module, repo_root, worktree_path, claims_dir)

    assert result.ok, result.message


def test_unplanned_exemption_does_not_excuse_a_claim_without_session_ownership(tmp_path: Path) -> None:
    """The exemption covers only the tracker, never missing live ownership metadata."""
    module = _load_create_worktree()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "maintenance-probe"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / "claim.yaml").write_text(
        yaml.safe_dump(_unplanned_claim(repo_root, worktree_path, session_name=None), sort_keys=False),
        encoding="utf-8",
    )

    result = _attempt(module, repo_root, worktree_path, claims_dir)

    assert not result.ok
    assert "matching active write claim is weak" in result.message
    assert "missing_session_name" in result.message
