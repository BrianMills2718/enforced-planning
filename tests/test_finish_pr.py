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
HOOK_PATH = (
    Path(__file__).resolve().parents[1]
    / "hooks"
    / "claude"
    / "worktree-coordination"
    / "enforce-make-merge.sh"
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
    return module.PrSnapshot(
        SHA_B, sha, "feature", "main", "OPEN", "MERGEABLE", tuple(checks)
    )


def test_review_spec_must_be_absolute_and_outside_repository(
    tmp_path, monkeypatch
) -> None:
    module = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    inside = repo / "review.json"
    inside.write_text("{}", encoding="utf-8")

    for candidate in (Path("review.json"), inside):
        try:
            module.load_trusted_review_spec(candidate, canonical_root=repo)
        except ValueError as exc:
            assert "outside the repository" in str(exc)
        else:
            raise AssertionError("PR-controlled review specs must be rejected")

    outside = tmp_path / "review.json"
    outside.write_text("{}", encoding="utf-8")
    expected = object()
    monkeypatch.setattr(module, "load_review_spec", lambda path: expected)
    assert module.load_trusted_review_spec(outside, canonical_root=repo) is expected


def test_head_change_invalidates_previously_successful_approval(monkeypatch) -> None:
    module = _load()
    snapshots = iter([
        (snapshot(module, SHA_A), None),
        (snapshot(module, SHA_B), None),
    ])
    monkeypatch.setattr(module, "fetch_pr_snapshot", lambda *_args: next(snapshots))
    monkeypatch.setattr(module, "fetch_exact_pr_head", lambda *_args: (True, "OK"))
    monkeypatch.setattr(module, "require_all_required_checks", lambda *_args: (True, "OK"))

    try:
        module.prepare_merge_gate(
            304,
            "feature",
            "owner/repo",
            {},
            review_spec_path=Path("/tmp/review.json"),
            review_output_root=Path("/tmp/reviews"),
        )
    except RuntimeError as exc:
        assert "review is stale" in str(exc)
    else:
        raise AssertionError("changed head must invalidate review")


def test_prepare_merge_gate_runs_local_review_and_rechecks_head(monkeypatch) -> None:
    module = _load()
    snapshots = iter([(snapshot(module), None)] * 3)
    monkeypatch.setattr(module, "fetch_pr_snapshot", lambda *_args: next(snapshots))
    monkeypatch.setattr(module, "fetch_exact_pr_head", lambda *_args: (True, "OK"))
    monkeypatch.setattr(module, "require_all_required_checks", lambda *_args: (True, "OK"))
    spec = SimpleNamespace()
    monkeypatch.setattr(module, "load_trusted_review_spec", lambda *_args, **_kwargs: spec)
    monkeypatch.setattr(module, "resolve_branch_worktree", lambda _branch: Path("/review"))
    observed = {}

    def review(**kwargs):
        observed.update(kwargs)
        return SimpleNamespace(verdict="signed_off"), Path("/receipts/receipt.json")

    monkeypatch.setattr(module, "run_local_review_gate", review)
    result, receipt = module.prepare_merge_gate(
        304,
        "feature",
        "owner/repo",
        {},
        review_spec_path=Path("/tmp/review.json"),
        review_output_root=Path("/tmp/reviews"),
    )
    assert result.head_sha == SHA_A
    assert receipt == Path("/receipts/receipt.json")
    assert observed["spec"] is spec
    assert observed["review_worktree"] == Path("/review")


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


def test_hook_blocks_real_finish_script_path_and_routes_to_make() -> None:
    payload = (
        '{"tool_input":{"command":"python scripts/worktree-coordination/finish_pr.py '
        '--branch feature --pr 42 --review-spec /tmp/spec.json"},'
        '"cwd":"/repo"}'
    )
    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    assert "make finish BRANCH=feature PR=42" in result.stderr
    assert "REVIEW_SPEC=/absolute/review-spec.json" in result.stderr
