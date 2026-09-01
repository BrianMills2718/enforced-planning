"""Regression tests for exact-head approval and merge command custody."""

from __future__ import annotations

import importlib.util
import json
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
SHA_C = "c" * 40


def _load():
    spec = importlib.util.spec_from_file_location("finish_pr_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def completed(cmd, returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def snapshot(module, sha=SHA_A, checks=(), base_sha=SHA_B):
    return module.PrSnapshot(
        base_sha, sha, "feature", "main", "OPEN", "MERGEABLE", tuple(checks)
    )


def test_review_spec_must_be_absolute_and_outside_repository(
    tmp_path, monkeypatch
) -> None:
    module = _load()
    repo = tmp_path / "repo"
    repo.mkdir()
    inside = repo / "review.json"
    inside.write_text("{}", encoding="utf-8")
    external_worktree = tmp_path / "external-worktree"
    external_worktree.mkdir()
    external_spec = external_worktree / "review.json"
    external_spec.write_text("{}", encoding="utf-8")
    outside = tmp_path / "review.json"
    outside.write_text("{}", encoding="utf-8")
    symlinked_spec = repo / "review-link.json"
    symlinked_spec.symlink_to(outside)

    roots = (repo, external_worktree)
    monkeypatch.setattr(module, "registered_worktree_roots", lambda _root: roots)
    for candidate in (Path("review.json"), inside, external_spec, symlinked_spec):
        try:
            module.load_trusted_review_spec(
                candidate,
                canonical_root=repo,
            )
        except ValueError as exc:
            assert "outside the repository" in str(exc)
        else:
            raise AssertionError("PR-controlled review specs must be rejected")

    expected = object()
    monkeypatch.setattr(module, "load_review_spec", lambda path: expected)
    assert module.load_trusted_review_spec(
        outside,
        canonical_root=repo,
    ) is expected


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


def test_base_change_after_review_invalidates_signoff(monkeypatch) -> None:
    module = _load()
    snapshots = iter([
        (snapshot(module), None),
        (snapshot(module), None),
        (snapshot(module, base_sha=SHA_C), None),
    ])
    monkeypatch.setattr(module, "fetch_pr_snapshot", lambda *_args: next(snapshots))
    monkeypatch.setattr(module, "fetch_exact_pr_head", lambda *_args: (True, "OK"))
    monkeypatch.setattr(module, "require_all_required_checks", lambda *_args: (True, "OK"))
    monkeypatch.setattr(module, "load_trusted_review_spec", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(module, "resolve_branch_worktree", lambda _branch: Path("/review"))
    monkeypatch.setattr(
        module,
        "run_local_review_gate",
        lambda **_kwargs: (object(), Path("/receipt.json")),
    )

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
        assert "changed after review" in str(exc)
    else:
        raise AssertionError("changed base must invalidate review")


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


def test_closeout_refreshes_remote_before_removal_and_uses_merge_receipt(monkeypatch) -> None:
    module = _load()
    calls = []

    def fake_run(cmd, check=True, capture=True, *, env=None):
        calls.append(cmd)
        return completed(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run)
    assert module.close_merged_lane("feature", SHA_B, "main") == (True, "Closed")
    assert calls == [
        ["git", "fetch", "--no-tags", "origin", "main"],
        ["git", "merge-base", "--is-ancestor", SHA_B, "origin/main"],
        ["make", "worktree-remove", "BRANCH=feature", f"WORKTREE_MERGE_COMMIT={SHA_B}"],
        ["git", "pull", "--ff-only", "origin", "main"],
    ]


def test_failed_merge_verification_never_closes_lane(monkeypatch, tmp_path) -> None:
    module = _load()
    closed = []

    @contextmanager
    def repository_context():
        yield "owner/repo", {}

    monkeypatch.setattr(module, "is_in_worktree", lambda: False)
    monkeypatch.setattr(module, "github_repository_context", repository_context)
    monkeypatch.setattr(
        module,
        "prepare_merge_gate",
        lambda *_args, **_kwargs: (snapshot(module), tmp_path / "receipt.json"),
    )
    monkeypatch.setattr(module, "merge_exact_head", lambda *_args: (True, "Merged"))
    monkeypatch.setattr(
        module,
        "verify_merged_pr",
        lambda *_args: (False, None, "missing merge evidence"),
    )
    monkeypatch.setattr(
        module,
        "close_merged_lane",
        lambda *_args: closed.append(True) or (True, "Closed"),
    )

    assert module.finish_pr(
        "feature",
        42,
        review_spec_path=tmp_path / "spec.json",
        review_output_root=tmp_path,
    ) is False
    assert closed == []


def test_hook_blocks_direct_merge_and_finish_command_variants() -> None:
    commands = (
        "python scripts/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "python ./scripts/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "/usr/bin/python3 scripts/meta/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "uv run python scripts/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "./scripts/meta/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "gh pr merge 42",
        "gh --repo owner/repo pr merge 42 --squash",
        "gh pr --repo owner/repo merge 42 --squash",
        "env gh pr merge 42",
        "command gh pr merge 42",
        "sudo gh pr merge 42",
        "GH_HOST=github.com gh pr merge 42",
        "bash -lc 'gh pr merge 42'",
        "sh -c 'python scripts/worktree-coordination/finish_pr.py --branch feature --pr 42'",
        "gh api --method PUT repos/owner/repo/pulls/42/merge",
        "true\ngh pr merge 42",
        "MERGER=gh; \"$MERGER\" pr merge 42 --squash",
        "SCRIPT=scripts/worktree-coordination/finish_pr.py; python \"$SCRIPT\" --branch feature --pr 42",
        "env python scripts/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "command python scripts/worktree-coordination/finish_pr.py --branch feature --pr 42",
        "PYTHONPATH=. python scripts/worktree-coordination/finish_pr.py --branch feature --pr 42",
    )
    for command in commands:
        payload = json.dumps({"tool_input": {"command": command}, "cwd": "/repo"})
        result = subprocess.run(
            ["bash", str(HOOK_PATH)],
            input=payload,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 2, command
        assert "make finish" in result.stderr


def test_hook_allows_search_that_only_mentions_finish_filename() -> None:
    payload = (
        '{"tool_input":{"command":"rg finish_pr.py scripts tests"},'
        '"cwd":"/repo"}'
    )
    result = subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
