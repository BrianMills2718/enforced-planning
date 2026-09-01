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


def test_finish_target_requires_and_forwards_external_review_spec() -> None:
    output = _dry_run_make(
        "finish",
        "BRANCH=feature",
        "PR=42",
        "REVIEW_SPEC=/tmp/review-spec.json",
    )

    assert 'scripts/worktree-coordination/finish_pr.py" --branch "feature"' in output
    assert '--pr "42" --review-spec "/tmp/review-spec.json"' in output


def test_consumer_template_exposes_the_same_finish_contract() -> None:
    recipe = _template_recipe("finish")

    assert "WORKTREE_FINISH_SCRIPT" in recipe
    assert '--review-spec "$(REVIEW_SPEC)"' in recipe


def test_maintenance_worktree_claim_declares_unplanned_ownership() -> None:
    """The maintenance lane must stamp UNPLANNED on its pre-worktree claim.

    Without this the claim is created planless, and the planless-claim guard
    rejects the very entrypoint it is meant to govern.
    """
    # A later command-line assignment wins, so this clears the SESSION_WRITE_PATHS
    # that _COMMON_MAKE_VARS supplies and exercises the undeclared-scope default.
    invocation = _claim_invocation(
        _dry_run_make("maintenance-worktree", "BRANCH=probe-unplanned", "SESSION_WRITE_PATHS=")
    )

    assert "--plan UNPLANNED" in invocation
    assert "#" not in invocation.split("--plan")[1]
    assert '--write-path "."' in invocation
    assert '--broad-scope-mode "bootstrap"' in invocation
    assert '--broad-scope-reason "construct this maintenance lane, then narrow before its first repository write"' in invocation
    assert '--target-worktree-path "' in invocation


def test_maintenance_worktree_keeps_an_explicitly_declared_write_scope() -> None:
    """Exact SESSION_WRITE_PATHS must reach the claim without bootstrap metadata.

    Hardcoding the repo-root bootstrap default discarded whatever the caller
    supplied, so every maintenance lane claimed the whole repository and
    conflicted with every other active lane by construction. The CONFLICT
    message format is "<yours> <-> <theirs>", which made the lane's own broad
    claim read as though it belonged to the other lanes.
    """
    invocation = _claim_invocation(
        _dry_run_make(
            "maintenance-worktree",
            "BRANCH=probe-narrow",
            "SESSION_WRITE_PATHS=Makefile docs/plans",
        )
    )

    assert '--write-path "Makefile"' in invocation
    assert '--write-path "docs/plans"' in invocation
    assert '--write-path "."' not in invocation
    # Exact paths are already narrow. Bootstrap metadata is valid only when the
    # entrypoint had to invent the repository-wide "." authority surface.
    assert '--broad-scope-mode' not in invocation
    assert '--broad-scope-reason' not in invocation
    assert '--target-worktree-path' not in invocation


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


TEMPLATE_PATH = PROJECT_ROOT / "templates" / "Makefile.worktree.block.template"


def _session_start_invocation(make_output: str) -> str:
    """Return the single session_start.py command from an expansion."""
    lines = make_output.splitlines()
    starts = [i for i, line in enumerate(lines) if line.lstrip().startswith(("python", '"python')) and "session_start.py" in line]
    assert len(starts) == 1, f"expected exactly one session_start invocation, got {len(starts)}"
    collected = []
    for line in lines[starts[0] :]:
        collected.append(line)
        if not line.rstrip().endswith("\\"):
            break
    return "\n".join(collected)


def _template_recipe(target: str) -> str:
    """Return the recipe body of one target from the consumer Makefile template."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith(f"{target}:")]
    assert len(starts) == 1, f"expected exactly one {target} target in the template, got {len(starts)}"
    collected = []
    for line in lines[starts[0] + 1 :]:
        if line and not line.startswith(("\t", " ")) and not line.startswith(("ifndef", "ifdef", "endif", "else")):
            break
        collected.append(line)
    return "\n".join(collected)


def test_session_start_forwards_the_unplanned_escape_hatch() -> None:
    """Refreshing an unplanned lane must reach session_start with --allow-unplanned.

    Creating the lane already forwards it; without the same forwarding here the
    lane it just created cannot refresh its own session contract.
    """
    invocation = _session_start_invocation(
        _dry_run_make("session-start", "BRANCH=probe-unplanned", "ALLOW_UNPLANNED=1")
    )

    assert "--allow-unplanned" in invocation


def test_session_start_withholds_the_escape_hatch_by_default() -> None:
    """Unplanned work stays explicit: no ALLOW_UNPLANNED means no flag."""
    invocation = _session_start_invocation(_dry_run_make("session-start", "BRANCH=probe-unplanned"))

    assert "--allow-unplanned" not in invocation


def test_session_start_keeps_a_plan_bound_lane_plan_bound() -> None:
    """A numbered plan lane must keep its qualified plan id, never UNPLANNED."""
    invocation = _session_start_invocation(
        _dry_run_make("session-start", "BRANCH=plan-42-probe", "PLAN=42")
    )

    assert '--plan "enforced-planning#42"' in invocation
    assert "UNPLANNED" not in invocation
    assert "--allow-unplanned" not in invocation


def test_consumer_template_session_start_forwards_the_unplanned_escape_hatch() -> None:
    """The template ships to every governed repo; the same omission there is fleet-wide."""
    recipe = _template_recipe("session-start")

    assert "$(if $(ALLOW_UNPLANNED),--allow-unplanned,)" in recipe


def test_consumer_template_session_start_keeps_plan_binding_conditional() -> None:
    """Plan-bound expansion in the template must stay the qualified plan id."""
    recipe = _template_recipe("session-start")

    assert '$(if $(PLAN),--plan "$(PLAN_PROJECT)#$(PLAN)",)' in recipe
    assert "--plan UNPLANNED" not in recipe


def test_session_narrow_make_target_forwards_only_exact_owner_and_paths() -> None:
    """The sanctioned Make recovery target maps its four inputs to one narrow CLI call."""

    output = _dry_run_make(
        "session-narrow",
        "BRANCH=host-gate-lane",
        "WORKTREE_AGENT=codex",
        "WORKTREE_PROJECT=enforced-planning",
        "SESSION_WRITE_PATHS=src/allowed.py docs/ops/INDEX.md",
    )

    assert 'scripts/session_narrow.py"' in output
    assert '--agent "codex"' in output
    assert '--project "enforced-planning"' in output
    assert '--scope "host-gate-lane"' in output
    assert '--write-path "src/allowed.py" --write-path "docs/ops/INDEX.md"' in output


def test_consumer_template_exposes_session_narrow_and_bootstrap_metadata() -> None:
    """Fleet Makefiles must retain the recovery target and authority-disabled bootstrap shape."""

    narrow = _template_recipe("session-narrow")
    maintenance = _template_recipe("maintenance-worktree")

    assert '"$(WORKTREE_SESSION_NARROW_SCRIPT)"' in narrow
    assert '--agent "$(WORKTREE_AGENT)"' in narrow
    assert '--project "$(WORKTREE_PROJECT)"' in narrow
    assert '--scope "$(BRANCH)"' in narrow
    assert '$(foreach path,$(SESSION_WRITE_PATHS),--write-path "$(path)")' in narrow
    assert 'SESSION_BROAD_SCOPE_MODE="$(MAINTENANCE_BROAD_SCOPE_MODE)"' in maintenance
    assert 'SESSION_BROAD_SCOPE_REASON="$(MAINTENANCE_BROAD_SCOPE_REASON)"' in maintenance
    assert 'SESSION_TARGET_WORKTREE_PATH="$(MAINTENANCE_TARGET_WORKTREE_PATH)"' in maintenance


def test_unplanned_session_start_without_permission_names_its_recovery() -> None:
    """The denial must be a loud operator error that names the escape hatch.

    A bare ValueError traceback tells the operator the lane is broken but not
    how to proceed, which is how an unplanned lane became unrefreshable.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "scripts" / "session_start.py"),
            "--agent", "claude-code",
            "--project", "enforced-planning",
            "--scope", "probe-unplanned",
            "--intent", "probe",
            "--repo-root", str(PROJECT_ROOT),
            "--worktree-path", str(PROJECT_ROOT),
            "--branch", "probe-unplanned",
            "--broader-goal", "probe goal",
            "--current-phase", "probe phase",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    combined = result.stdout + result.stderr
    assert result.returncode != 0, combined
    assert "Traceback (most recent call last)" not in combined, combined
    assert "ALLOW_UNPLANNED=1" in combined, combined
    assert "--allow-unplanned" in combined, combined
