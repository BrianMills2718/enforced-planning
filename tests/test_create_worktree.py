"""Tests for the shared worktree-creation guardrail wrapper."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "worktree-coordination" / "create_worktree.py"


def test_source_repo_worktree_facade_matches_canonical_source() -> None:
    installed = Path(__file__).resolve().parents[1] / "scripts" / "meta" / "worktree-coordination" / "create_worktree.py"
    assert installed.read_bytes() == MODULE_PATH.read_bytes()


def _load_module():
    """Load the standalone worktree-creation script as a module."""
    spec = importlib.util.spec_from_file_location("create_worktree_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_canonical_lock_resolves_source_and_installed_layouts(tmp_path: Path) -> None:
    module = _load_module()
    source_script = tmp_path / "scripts" / "worktree-coordination" / "create_worktree.py"
    source_helper = source_script.parent / "canonical_lock.py"
    source_helper.parent.mkdir(parents=True)
    source_helper.touch()
    assert module._canonical_lock_module_path(source_script) == source_helper.resolve()

    installed_script = tmp_path / "installed" / "scripts" / "meta" / "worktree-coordination" / "create_worktree.py"
    installed_helper = installed_script.parents[1] / "canonical_lock.py"
    installed_script.parent.mkdir(parents=True)
    installed_helper.touch()
    assert module._canonical_lock_module_path(installed_script) == installed_helper.resolve()

    source_facade = tmp_path / "source" / "scripts" / "meta" / "worktree-coordination" / "create_worktree.py"
    source_helper = source_facade.parents[2] / "worktree-coordination" / "canonical_lock.py"
    source_facade.parent.mkdir(parents=True)
    source_helper.parent.mkdir(parents=True)
    source_helper.touch()
    assert module._canonical_lock_module_path(source_facade) == source_helper.resolve()


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


def _init_repo_with_stale_origin(tmp_path: Path) -> Path:
    """Build a repo whose local main is behind its origin/main, for staleness tests."""
    origin_root = tmp_path / "origin"
    _init_temp_repo(origin_root)

    repo_root = tmp_path / "repo"
    clone_result = _run_git(tmp_path, "clone", str(origin_root), str(repo_root))
    assert clone_result.returncode == 0, clone_result.stdout + clone_result.stderr
    _run_git(repo_root, "config", "user.name", "Test User")
    _run_git(repo_root, "config", "user.email", "test@example.com")

    # A commit lands on origin after the clone, so the local checkout falls behind.
    (origin_root / "README.md").write_text("hello again\n", encoding="utf-8")
    _run_git(origin_root, "add", "README.md")
    commit_result = _run_git(origin_root, "commit", "-m", "advance origin past the clone")
    assert commit_result.returncode == 0, commit_result.stdout + commit_result.stderr

    return repo_root


def test_create_worktree_uses_fetched_upstream_when_local_start_point_is_stale(tmp_path: Path) -> None:
    """Default root-start branches from freshly fetched upstream, not stale local HEAD."""
    module = _load_module()
    repo_root = _init_repo_with_stale_origin(tmp_path)
    worktree_path = tmp_path / "repo-worktrees" / "stale-test"

    expected = _run_git(tmp_path / "origin", "rev-parse", "HEAD").stdout.strip()
    stale_local = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="stale-test",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
    )

    assert result.ok, result.message
    assert _run_git(worktree_path, "rev-parse", "HEAD").stdout.strip() == expected
    assert expected != stale_local


def test_create_worktree_allows_stale_start_point_when_opted_out(tmp_path: Path) -> None:
    """The staleness check should not fire when explicitly opted out."""
    module = _load_module()
    repo_root = _init_repo_with_stale_origin(tmp_path)
    worktree_path = tmp_path / "repo-worktrees" / "stale-allowed-test"

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="stale-allowed-test",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        allow_stale_start_point=True,
    )

    assert result.ok, result.message
    assert worktree_path.exists()


def test_create_worktree_fetch_failure_leaves_no_branch_or_worktree(tmp_path: Path) -> None:
    """Fresh-start failure is atomic before branch or worktree creation."""

    module = _load_module()
    repo_root = _init_repo_with_stale_origin(tmp_path)
    worktree_path = tmp_path / "repo-worktrees" / "fetch-failure"
    assert _run_git(repo_root, "remote", "set-url", "origin", str(tmp_path / "missing-origin")).returncode == 0

    with pytest.raises(ValueError, match="Unable to refresh upstream"):
        module.create_worktree(
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch="fetch-failure",
            start_point="HEAD",
            split_brain_threshold=5,
            keep_failed_worktree=False,
        )

    assert not worktree_path.exists()
    assert _run_git(repo_root, "show-ref", "--verify", "refs/heads/fetch-failure").returncode != 0


def test_fresh_start_fails_closed_for_ambiguous_non_origin_remotes(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = tmp_path / "repo"
    _init_temp_repo(repo_root)
    assert _run_git(repo_root, "remote", "add", "alpha", str(tmp_path / "alpha")).returncode == 0
    assert _run_git(repo_root, "remote", "add", "beta", str(tmp_path / "beta")).returncode == 0

    with pytest.raises(ValueError, match="multiple remotes"):
        module.resolve_fresh_start_revision(repo_root=repo_root, start_point="HEAD")


def test_fresh_start_uses_advertised_default_when_local_remote_head_is_stale(tmp_path: Path) -> None:
    module = _load_module()
    repo_root = _init_repo_with_stale_origin(tmp_path)
    origin_root = tmp_path / "origin"
    stale_remote_head = _run_git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD").stdout.strip()
    assert _run_git(origin_root, "switch", "-c", "new-default").returncode == 0
    (origin_root / "DEFAULT.txt").write_text("new default\n", encoding="utf-8")
    assert _run_git(origin_root, "add", "DEFAULT.txt").returncode == 0
    assert _run_git(origin_root, "commit", "-m", "new advertised default").returncode == 0
    expected = _run_git(origin_root, "rev-parse", "HEAD").stdout.strip()

    resolved = module.resolve_fresh_start_revision(repo_root=repo_root, start_point="HEAD")

    assert resolved == expected
    assert _run_git(repo_root, "symbolic-ref", "refs/remotes/origin/HEAD").stdout.strip() == stale_remote_head


def test_fresh_start_rejects_successful_fetch_with_stale_tracking_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_module()
    repo_root = _init_repo_with_stale_origin(tmp_path)
    real_run_git = module.run_git
    advertised = "f" * 40
    remote_head = _run_git(repo_root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD").stdout.strip()
    advertised_branch = remote_head.split("/", 1)[1]

    def controlled_run_git(args: list[str], *, cwd: Path):
        if args == ["fetch", "origin"]:
            return subprocess.CompletedProcess(["git", *args], 0, "", "")
        if args == ["ls-remote", "--symref", "origin", "HEAD"]:
            return subprocess.CompletedProcess(
                ["git", *args],
                0,
                f"ref: refs/heads/{advertised_branch}\tHEAD\n{advertised}\tHEAD\n",
                "",
            )
        return real_run_git(args, cwd=cwd)

    monkeypatch.setattr(module, "run_git", controlled_run_git)
    with pytest.raises(ValueError, match="does not match advertised HEAD"):
        module.resolve_fresh_start_revision(repo_root=repo_root, start_point="HEAD")


def test_create_worktree_reuses_only_branch_at_exact_start_revision(tmp_path: Path) -> None:
    """A pre-existing branch is recoverable only when it already retains the requested commit."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo-worktrees" / "retained-branch"
    _init_temp_repo(repo_root)
    revision_a = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    assert _run_git(repo_root, "branch", "retained-branch", revision_a).returncode == 0

    matched = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="retained-branch",
        start_point=revision_a,
        split_brain_threshold=5,
        keep_failed_worktree=False,
    )
    assert matched.ok
    assert matched.created_branch is False
    assert _run_git(worktree_path, "rev-parse", "HEAD").stdout.strip() == revision_a
    assert _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path)).returncode == 0

    (repo_root / "README.md").write_text("later\n", encoding="utf-8")
    assert _run_git(repo_root, "commit", "-am", "advance").returncode == 0
    revision_b = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(ValueError, match="does not match requested start revision"):
        module.create_worktree(
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch="retained-branch",
            start_point=revision_b,
            split_brain_threshold=5,
            keep_failed_worktree=False,
        )

    assert not worktree_path.exists()
    assert _run_git(repo_root, "rev-parse", "retained-branch").stdout.strip() == revision_a


def test_plan_bound_claim_for_old_revision_cannot_authorize_new_worktree_without_cli_assertion(
    tmp_path: Path,
) -> None:
    """The helper-resolved revision enforces custody even when the optional assertion is omitted."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo-worktrees" / "revision-bound"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)
    revision_a = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    (repo_root / "README.md").write_text("later\n", encoding="utf-8")
    assert _run_git(repo_root, "commit", "-am", "advance").returncode == 0
    revision_b = _run_git(repo_root, "rev-parse", "HEAD").stdout.strip()
    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "schema_version": 4,
            "agent": "codex",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["repo"],
            "scope": "revision-bound",
            "intent": "Patch docs",
            "claim_type": "write",
            "write_paths": ["docs/ops"],
            "branch": "revision-bound",
            "worktree_path": str(worktree_path),
            "session_id": "codex:session",
            "session_name": "revision-bound",
            "plan_ref": "repo#1",
            "work_unit_id": "revision-bound",
            "work_graph_path": "docs/plans/1_graph.json",
            "work_graph_sha256": "c" * 64,
            "start_revision": revision_a,
            "status": "active",
        },
    )

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="revision-bound",
        start_point=revision_b,
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
    assert f"start_revision={revision_b}" in result.message
    assert not worktree_path.exists()


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


@pytest.mark.parametrize("authorizing_claim_type", ["write", "program"])
def test_create_worktree_rejects_conflicting_scoped_write_claim(
    tmp_path: Path,
    authorizing_claim_type: str,
) -> None:
    """Every write-authorizing claim should remain subject to conflict checks."""
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
            "claim_type": authorizing_claim_type,
            "write_paths": ["docs/ops"],
            "branch": "plan-62-conflict",
            "repo_root": str(repo_root),
            "worktree_path": str(worktree_path),
            "session_id": "codex-session",
            "session_name": "coordination-v2",
            "broader_goal": "Verify conflict enforcement",
            "plan_ref": "UNPLANNED",
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
            "repo_root": str(repo_root),
            "worktree_path": str(worktree_path),
            "session_id": "codex-session",
            "session_name": "coordination-v2",
            "broader_goal": "Verify scoped worktree creation",
            "plan_ref": "UNPLANNED",
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


def test_create_worktree_allows_staged_goal_reservation_without_tracker(
    tmp_path: Path,
) -> None:
    """A typed goal claim may reserve its exact worktree before session activation."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "goal-runtime-sync"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)

    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "schema_version": 6,
            "agent": "codex",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["repo"],
            "scope": "goal-runtime-sync",
            "intent": "Execute the accepted runtime-sync goal",
            "claim_type": "write",
            "write_paths": ["docs/goal.md"],
            "branch": "goal-runtime-sync",
            "repo_root": str(repo_root),
            "worktree_path": str(worktree_path),
            "session_id": "codex-session",
            "session_name": "runtime-sync",
            "broader_goal": "Converge the installed runtime",
            "tracker_path": None,
            "plan_ref": "goal:coordination-runtime-consumer-sync",
            "status": "active",
        },
    )

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="goal-runtime-sync",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/goal.md"],
        claims_dir=claims_dir,
    )

    assert result.ok, result.message
    assert result.classification == "clean"
    assert result.coordination_message is not None
    assert "Scoped write claim verified" in result.coordination_message

    cleanup_result = _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
    assert cleanup_result.returncode == 0, cleanup_result.stdout + cleanup_result.stderr
    delete_branch = _run_git(repo_root, "branch", "-D", "goal-runtime-sync")
    assert delete_branch.returncode == 0, delete_branch.stdout + delete_branch.stderr


def test_bootstrap_claim_validates_exact_target_without_granting_worktree_authority(
    tmp_path: Path,
) -> None:
    """Construction matches target_worktree_path while legacy mutation binding stays detached."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "bootstrap-lane"
    claims_dir = tmp_path / "claims"
    _init_temp_repo(repo_root)
    sentinel = f"{worktree_path}.bootstrap-no-mutation-authority"
    _write_claim(
        claims_dir,
        "codex.yaml",
        {
            "schema_version": 6,
            "agent": "codex",
            "claimed_at": "2026-04-02T08:00:00+00:00",
            "expires_at": "2099-04-02T09:00:00+00:00",
            "projects": ["repo"],
            "scope": "bootstrap-lane",
            "intent": "construct then narrow",
            "claim_type": "program",
            "write_paths": ["."],
            "branch": "bootstrap-lane",
            "repo_root": str(repo_root),
            "worktree_path": sentinel,
            "target_worktree_path": str(worktree_path),
            "broad_scope_mode": "bootstrap",
            "broad_scope_reason": "construct then narrow before the first write",
            "session_id": "codex:owner",
            "session_name": "bootstrap-lane",
            "broader_goal": "Prove separated bootstrap authority",
            "tracker_path": str(tmp_path / "tracker.yaml"),
            "plan_ref": "UNPLANNED",
            "status": "active",
        },
    )

    ok, message = module.verify_scoped_write_claim(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="bootstrap-lane",
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/file.md"],
        claims_dir=claims_dir,
    )

    assert ok, message
    assert not Path(sentinel).exists()
    assert not worktree_path.exists()


def test_create_worktree_allows_program_claim_with_exact_write_paths(tmp_path: Path) -> None:
    """A program claim with explicit paths should carry the same write authority."""
    module = _load_module()
    repo_root = tmp_path / "repo"
    worktree_path = tmp_path / "repo_worktrees" / "goal-owner-week"
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
            "scope": "owner-week",
            "intent": "Complete one bounded owner outcome",
            "claim_type": "program",
            "write_paths": ["docs/reviews/owner-week.md"],
            "branch": "goal-owner-week",
            "repo_root": str(repo_root),
            "worktree_path": str(worktree_path),
            "session_id": "codex-session",
            "session_name": "complete-one-bounded-owner-outcome",
            "broader_goal": "Complete one bounded owner outcome",
            "plan_ref": "UNPLANNED",
            "status": "active",
        },
    )

    result = module.create_worktree(
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch="goal-owner-week",
        start_point="HEAD",
        split_brain_threshold=5,
        keep_failed_worktree=False,
        require_write_claim=True,
        claim_agent="codex",
        claim_project="repo",
        claim_write_paths=["docs/reviews/owner-week.md"],
        claims_dir=claims_dir,
    )

    assert result.ok, result.message
    assert result.classification == "clean"
    assert result.coordination_message is not None
    assert "program claim" in result.coordination_message

    cleanup_result = _run_git(repo_root, "worktree", "remove", "--force", str(worktree_path))
    assert cleanup_result.returncode == 0, cleanup_result.stdout + cleanup_result.stderr
    delete_branch = _run_git(repo_root, "branch", "-D", "goal-owner-week")
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
