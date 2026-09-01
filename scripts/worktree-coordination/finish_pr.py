#!/usr/bin/env python3
"""Merge one exact approved PR head, then close its claimed lane."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

APPROVAL_CONTEXT = "coordination-approval"
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")


@dataclass(frozen=True)
class PrSnapshot:
    head_sha: str
    head_branch: str
    base_branch: str
    state: str
    mergeable: str
    checks: tuple[dict[str, object], ...]


def run_cmd(
    cmd: list[str], check: bool = True, capture: bool = True, *,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd, check=check, capture_output=capture, text=True,
        env=dict(env) if env is not None else None,
    )


def is_in_worktree() -> bool:
    return Path(".git").is_file()


def get_main_repo_root() -> Path:
    result = run_cmd(["git", "rev-parse", "--git-common-dir"], check=False)
    return Path(result.stdout.strip()).parent if result.returncode == 0 else Path.cwd()


def _load_pr_auto() -> ModuleType:
    """Load the existing isolated account-routing seam beside this helper."""
    candidate = Path(__file__).resolve().parents[1] / "pr_auto.py"
    if not candidate.is_file():
        raise RuntimeError(f"GitHub account-routing seam is unavailable: {candidate}")
    spec = importlib.util.spec_from_file_location("finish_pr_pr_auto", candidate)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load GitHub account-routing seam: {candidate}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def github_repository_context() -> Iterator[tuple[str, dict[str, str]]]:
    """Select the origin owner in a private gh config; never mutate shared auth."""
    routing = _load_pr_auto()
    remote = run_cmd(["git", "config", "--get", "remote.origin.url"], check=False)
    if remote.returncode != 0:
        raise RuntimeError(f"Cannot resolve origin URL: {remote.stderr.strip()}")
    repo_slug = routing.parse_github_repo_slug(remote.stdout)
    if repo_slug is None:
        raise RuntimeError(f"Cannot parse GitHub origin URL: {remote.stdout.strip()}")
    account = repo_slug.split("/", 1)[0]
    gh_env = routing.sanitize_github_env(os.environ)
    with routing.isolated_github_auth(
        cwd=Path.cwd(), gh_env=gh_env, account=account
    ) as isolated_env:
        yield repo_slug, isolated_env


def _pr_view_command(pr_number: int, repo_slug: str) -> list[str]:
    return [
        "gh", "pr", "view", str(pr_number), "--repo", repo_slug, "--json",
        "headRefOid,headRefName,baseRefName,statusCheckRollup,mergeable,state,mergeCommit",
    ]


def _parse_pr_snapshot(raw: str) -> tuple[PrSnapshot, str | None]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"GitHub returned invalid PR JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise TypeError("GitHub PR response must be one JSON object")
    head_sha = data.get("headRefOid")
    head_branch = data.get("headRefName")
    base_branch = data.get("baseRefName")
    if not isinstance(head_sha, str) or not FULL_SHA_RE.fullmatch(head_sha):
        raise ValueError("PR headRefOid is missing or is not one full commit SHA")
    if not isinstance(head_branch, str) or not head_branch:
        raise ValueError("PR head branch is missing")
    if not isinstance(base_branch, str) or not base_branch:
        raise ValueError("PR base branch is missing")
    checks = data.get("statusCheckRollup") or []
    if not isinstance(checks, list) or not all(isinstance(item, dict) for item in checks):
        raise ValueError("PR statusCheckRollup is malformed")
    merge_commit = None
    raw_merge = data.get("mergeCommit")
    if isinstance(raw_merge, dict):
        candidate = raw_merge.get("oid")
        if isinstance(candidate, str) and FULL_SHA_RE.fullmatch(candidate):
            merge_commit = candidate
    return PrSnapshot(
        head_sha, head_branch, base_branch,
        str(data.get("state", "UNKNOWN")), str(data.get("mergeable", "UNKNOWN")),
        tuple(checks),
    ), merge_commit


def fetch_pr_snapshot(
    pr_number: int, repo_slug: str, gh_env: Mapping[str, str]
) -> tuple[PrSnapshot, str | None]:
    result = run_cmd(_pr_view_command(pr_number, repo_slug), check=False, env=gh_env)
    if result.returncode != 0:
        raise RuntimeError(
            "Failed to fetch PR head/check rollup: "
            + (result.stderr or result.stdout).strip()
        )
    return _parse_pr_snapshot(result.stdout)


def _check_name(check: Mapping[str, object]) -> str:
    name = check.get("name")
    if isinstance(name, str) and name:
        return name
    context = check.get("context")
    return context if isinstance(context, str) else ""


def _check_result(check: Mapping[str, object]) -> str:
    conclusion = check.get("conclusion")
    if isinstance(conclusion, str) and conclusion:
        return conclusion.upper()
    state = check.get("state")
    return state.upper() if isinstance(state, str) and state else "PENDING"


def require_coordination_approval(snapshot: PrSnapshot) -> tuple[bool, str]:
    matching = [c for c in snapshot.checks if _check_name(c) == APPROVAL_CONTEXT]
    if not matching:
        return False, f"missing required {APPROVAL_CONTEXT} on head {snapshot.head_sha}"
    non_success = [_check_result(c) for c in matching if _check_result(c) != "SUCCESS"]
    if non_success:
        return False, (
            f"{APPROVAL_CONTEXT} is not successful on head {snapshot.head_sha}: "
            + ", ".join(non_success)
        )
    return True, "OK"


def fetch_exact_pr_head(pr_number: int, expected_sha: str) -> tuple[bool, str]:
    fetched = run_cmd(
        ["git", "fetch", "--no-tags", "origin", f"refs/pull/{pr_number}/head"],
        check=False,
    )
    if fetched.returncode != 0:
        return False, (fetched.stderr or fetched.stdout).strip()
    resolved = run_cmd(["git", "rev-parse", "FETCH_HEAD"], check=False)
    actual = resolved.stdout.strip() if resolved.returncode == 0 else ""
    if actual != expected_sha:
        return False, f"fetched PR head {actual or 'unknown'} != API head {expected_sha}"
    return True, "OK"


def require_all_required_checks(
    pr_number: int, repo_slug: str, gh_env: Mapping[str, str]
) -> tuple[bool, str]:
    result = run_cmd(
        ["gh", "pr", "checks", str(pr_number), "--repo", repo_slug, "--required"],
        check=False, env=gh_env,
    )
    if result.returncode != 0:
        state = "pending" if result.returncode == 8 else "failing or unavailable"
        return False, f"required checks are {state}: {(result.stderr or result.stdout).strip()}"
    return True, "OK"


def prepare_merge_gate(
    pr_number: int, branch: str, repo_slug: str, gh_env: Mapping[str, str]
) -> PrSnapshot:
    first, _ = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if first.state != "OPEN":
        raise RuntimeError(f"PR state is {first.state}, not OPEN")
    if first.head_branch != branch:
        raise RuntimeError(f"PR head branch {first.head_branch!r} != requested {branch!r}")
    if first.mergeable == "CONFLICTING":
        raise RuntimeError("PR has merge conflicts")
    approved, reason = require_coordination_approval(first)
    if not approved:
        raise RuntimeError(reason)
    fetched, reason = fetch_exact_pr_head(pr_number, first.head_sha)
    if not fetched:
        raise RuntimeError(f"Cannot bind exact PR head: {reason}")
    checks_ok, reason = require_all_required_checks(pr_number, repo_slug, gh_env)
    if not checks_ok:
        raise RuntimeError(reason)
    second, _ = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if second.head_sha != first.head_sha:
        raise RuntimeError(
            f"PR head changed while checks ran: {first.head_sha} -> {second.head_sha}; approval is stale"
        )
    if second.state != "OPEN":
        raise RuntimeError(f"PR state changed to {second.state} before merge")
    approved, reason = require_coordination_approval(second)
    if not approved:
        raise RuntimeError(reason)
    return second


def merge_exact_head(
    pr_number: int, snapshot: PrSnapshot, repo_slug: str,
    gh_env: Mapping[str, str],
) -> tuple[bool, str]:
    result = run_cmd([
        "gh", "pr", "merge", str(pr_number), "--repo", repo_slug, "--squash",
        "--match-head-commit", snapshot.head_sha,
    ], check=False, env=gh_env)
    return (
        (True, "Merged") if result.returncode == 0
        else (False, (result.stderr or result.stdout).strip())
    )


def verify_merged_pr(
    pr_number: int, expected_head: str, repo_slug: str,
    gh_env: Mapping[str, str],
) -> tuple[bool, str | None, str]:
    snapshot, merge_commit = fetch_pr_snapshot(pr_number, repo_slug, gh_env)
    if snapshot.head_sha != expected_head:
        return False, None, "merged PR head differs from the approved head"
    if snapshot.state != "MERGED":
        return False, None, f"GitHub reports PR state {snapshot.state}, not MERGED"
    if merge_commit is None:
        return False, None, "GitHub did not report one full merge commit SHA"
    return True, merge_commit, "OK"


def close_merged_lane(branch: str, merge_commit: str, base_branch: str) -> tuple[bool, str]:
    close = run_cmd([
        "make", "worktree-remove", f"BRANCH={branch}",
        f"WORKTREE_MERGE_COMMIT={merge_commit}",
    ], check=False)
    if close.returncode != 0:
        return False, (close.stderr or close.stdout).strip()
    update = run_cmd(["git", "pull", "--ff-only", "origin", base_branch], check=False)
    if update.returncode != 0:
        return False, (update.stderr or update.stdout).strip()
    return True, "Closed"


def finish_pr(branch: str, pr_number: int) -> bool:
    if is_in_worktree():
        print("ERROR: finish_pr must run from the canonical repository checkout.")
        print(f"Run: cd {get_main_repo_root()} && make finish BRANCH={branch} PR={pr_number}")
        return False
    try:
        with github_repository_context() as (repo_slug, gh_env):
            snapshot = prepare_merge_gate(pr_number, branch, repo_slug, gh_env)
            print(f"Approved exact head {snapshot.head_sha}; all required checks passed.")
            merged, reason = merge_exact_head(pr_number, snapshot, repo_slug, gh_env)
            if not merged:
                print(f"ERROR: merge failed: {reason}")
                return False
            verified, merge_commit, reason = verify_merged_pr(
                pr_number, snapshot.head_sha, repo_slug, gh_env
            )
            if not verified or merge_commit is None:
                print(f"HIGH: merge command returned but verification failed: {reason}")
                return False
    except (RuntimeError, TypeError, ValueError) as exc:
        print(f"ERROR: merge gate denied: {exc}")
        return False
    closed, reason = close_merged_lane(branch, merge_commit, snapshot.base_branch)
    if not closed:
        print(f"HIGH: PR merged, but sanctioned lane closeout failed: {reason}")
        return False
    print(f"Done: PR #{pr_number} merged at {snapshot.head_sha} and lane closed.")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Merge one exact approved PR head and close its claimed lane."
    )
    parser.add_argument("--branch", "-b", required=True)
    parser.add_argument("--pr", "-p", type=int, required=True)
    args = parser.parse_args()
    return 0 if finish_pr(args.branch, args.pr) else 1


if __name__ == "__main__":
    sys.exit(main())
