"""Regression tests for exact-head approval and merge command custody."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "worktree-coordination"
    / "finish_pr.py"
)
SHA_A = "a" * 40
SHA_B = "b" * 40


def _load():
    spec = importlib.util.spec_from_file_location("finish_pr_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def snapshot(module, sha=SHA_A, checks=()):
    return module.PrSnapshot(sha, "feature", "main", "OPEN", "MERGEABLE", tuple(checks))


def test_status_context_success_requires_exact_creator_and_target() -> None:
    module = _load()
    status = {
        "context": "coordination-approval",
        "state": "success",
        "creator": {"login": "owner"},
        "target_url": "https://github.com/owner/repo/pull/304",
    }
    assert module.evaluate_coordination_approval(
        statuses=[status], check_runs=[], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=None,
        expected_target_url="https://github.com/owner/repo/pull/304",
    ) == (True, "OK")

    status["creator"] = {"login": "other-user"}
    ok, reason = module.evaluate_coordination_approval(
        statuses=[status], check_runs=[], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=None,
        expected_target_url="https://github.com/owner/repo/pull/304",
    )
    assert ok is False
    assert "trusted producer" in reason


def test_missing_or_pending_coordination_approval_fails_visibly() -> None:
    module = _load()
    ok, missing = module.evaluate_coordination_approval(
        statuses=[], check_runs=[], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=None,
        expected_target_url="https://github.com/owner/repo/pull/304",
    )
    assert ok is False
    assert "missing required coordination-approval" in missing

    pending_run = {
        "name": "coordination-approval",
        "head_sha": SHA_A,
        "status": "in_progress",
        "conclusion": "success",
        "app": {"id": 99},
    }
    ok, pending = module.evaluate_coordination_approval(
        statuses=[], check_runs=[pending_run], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=99,
        expected_target_url="https://github.com/owner/repo/pull/304",
    )
    assert ok is False
    assert "trusted producer" in pending


def test_same_named_check_run_from_wrong_app_is_rejected() -> None:
    module = _load()
    run = {
        "name": "coordination-approval",
        "head_sha": SHA_A,
        "status": "completed",
        "conclusion": "success",
        "app": {"id": 55, "slug": "untrusted-app"},
    }
    ok, reason = module.evaluate_coordination_approval(
        statuses=[], check_runs=[run], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=99,
        expected_target_url="https://github.com/owner/repo/pull/304",
    )
    assert ok is False
    assert "trusted producer" in reason

    run["app"] = {"id": 99, "slug": "coordination-approver"}
    assert module.evaluate_coordination_approval(
        statuses=[], check_runs=[run], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=99,
        expected_target_url="https://github.com/owner/repo/pull/304",
    ) == (True, "OK")

    ok, reason = module.evaluate_coordination_approval(
        statuses=[], check_runs=[run], head_sha=SHA_A,
        trusted_creator="owner", trusted_check_app_id=None,
        expected_target_url="https://github.com/owner/repo/pull/304",
    )
    assert ok is False
    assert "trusted producer" in reason


def test_newer_pending_status_invalidates_older_success() -> None:
    module = _load()
    status_base = {
        "context": "coordination-approval",
        "creator": {"login": "owner"},
        "target_url": "https://github.com/owner/repo/pull/304",
    }
    ok, reason = module.evaluate_coordination_approval(
        statuses=[
            {**status_base, "state": "pending"},
            {**status_base, "state": "success"},
        ],
        check_runs=[], head_sha=SHA_A, trusted_creator="owner",
        trusted_check_app_id=None,
        expected_target_url="https://github.com/owner/repo/pull/304",
    )
    assert ok is False
    assert "trusted producer" in reason


def test_head_change_invalidates_previously_successful_approval(monkeypatch) -> None:
    module = _load()
    approval = ({"context": "coordination-approval", "state": "SUCCESS"},)
    snapshots = iter([
        (snapshot(module, SHA_A, approval), None),
        (snapshot(module, SHA_B, approval), None),
    ])
    monkeypatch.setattr(module, "fetch_pr_snapshot", lambda *_args: next(snapshots))
    monkeypatch.setattr(module, "fetch_exact_pr_head", lambda *_args: (True, "OK"))
    monkeypatch.setattr(module, "require_all_required_checks", lambda *_args: (True, "OK"))
    monkeypatch.setattr(module, "require_coordination_approval", lambda *_args: (True, "OK"))

    try:
        module.prepare_merge_gate(304, "feature", "owner/repo", {})
    except RuntimeError as exc:
        assert "approval is stale" in str(exc)
    else:
        raise AssertionError("changed head must invalidate approval")


def test_merge_uses_match_head_commit_and_never_deletes_branch(monkeypatch) -> None:
    module = _load()
    calls = []

    def fake_run(cmd, check=True, capture=True, *, env=None):
        calls.append(cmd)
        return completed(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run)
    ok, _ = module.merge_exact_head(304, snapshot(module), "owner/repo", {})
    assert ok is True
    assert calls == [[
        "gh", "pr", "merge", "304", "--repo", "owner/repo", "--squash",
        "--match-head-commit", SHA_A,
    ]]
    assert "--delete-branch" not in calls[0]


def test_repository_context_routes_to_origin_owner_in_isolated_auth(monkeypatch) -> None:
    module = _load()
    observed = {}

    @contextmanager
    def isolated_github_auth(*, cwd, gh_env, account):
        observed.update(cwd=cwd, gh_env=gh_env, account=account)
        yield {**gh_env, "GH_CONFIG_DIR": "/isolated"}

    routing = SimpleNamespace(
        parse_github_repo_slug=lambda _remote: "ExactOwner/repository",
        sanitize_github_env=lambda _env: {"PATH": "/bin"},
        isolated_github_auth=isolated_github_auth,
    )
    monkeypatch.setattr(module, "_load_pr_auto", lambda: routing)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True, env=None: completed(
            cmd, stdout="git@github.com:ExactOwner/repository.git\n"
        ),
    )

    with module.github_repository_context() as (slug, gh_env):
        assert slug == "ExactOwner/repository"
        assert gh_env["GH_CONFIG_DIR"] == "/isolated"
    assert observed["account"] == "ExactOwner"


def test_required_check_command_is_repository_bound(monkeypatch) -> None:
    module = _load()
    calls = []

    def fake_run(cmd, check=True, capture=True, *, env=None):
        calls.append(cmd)
        return completed(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run)
    assert module.require_all_required_checks(304, "owner/repo", {}) == (True, "OK")
    assert calls == [[
        "gh", "pr", "checks", "304", "--repo", "owner/repo", "--required",
    ]]


def test_closeout_precedes_canonical_pull_and_uses_merge_receipt(monkeypatch) -> None:
    module = _load()
    calls = []

    def fake_run(cmd, check=True, capture=True, *, env=None):
        calls.append(cmd)
        return completed(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run)
    assert module.close_merged_lane("feature", SHA_B, "main") == (True, "Closed")
    assert calls == [
        ["make", "worktree-remove", "BRANCH=feature", f"WORKTREE_MERGE_COMMIT={SHA_B}"],
        ["git", "pull", "--ff-only", "origin", "main"],
    ]
