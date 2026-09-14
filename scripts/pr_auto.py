#!/usr/bin/env python3
"""Autonomous PR workflow with deterministic preflight checks.

Usage:
  python scripts/meta/pr_auto.py --preflight-only --expected-origin-repo my-repo
  python scripts/meta/pr_auto.py --expected-origin-repo my-repo --fill --auto-merge
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

GITHUB_TOKEN_ENV_VARS: tuple[str, ...] = (
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
)

IGNORABLE_STATUS_PREFIXES: tuple[str, ...] = (
    "?? .claude/active-work.yaml",
    "?? .claude/sessions/",
)


def sanitize_github_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Return env with token overrides removed so gh uses stored auth."""
    base = dict(env if env is not None else os.environ)
    for var in GITHUB_TOKEN_ENV_VARS:
        base.pop(var, None)
    base.setdefault("GIT_CONFIG_NOSYSTEM", "1")
    return base


def parse_github_repo_slug(remote_url: str) -> str | None:
    """Parse owner/repo slug from common GitHub remote URL forms."""
    candidate = remote_url.strip()
    if not candidate:
        return None
    match = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?$", candidate)
    if not match:
        return None
    owner = match.group(1).strip()
    repo = match.group(2).strip()
    if not owner or not repo:
        return None
    return f"{owner}/{repo}"


def origin_matches_expected_repo(remote_url: str, expected_repo: str) -> bool:
    """Return True when origin URL resolves to the expected repository name."""
    slug = parse_github_repo_slug(remote_url)
    if slug is None:
        return False
    repo = slug.split("/", 1)[1]
    return repo == expected_repo


def resolve_github_account(explicit_account: str | None, remote_url: str) -> str:
    """Return the gh login to act as: explicit, else the origin repository owner.

    This script is installed into every governed consumer, so it must not
    default to one maintainer's login. finish_pr routes by owner the same way.
    """
    if explicit_account:
        return explicit_account
    slug = parse_github_repo_slug(remote_url)
    if slug is None:
        raise SystemExit(
            f"Cannot derive a GitHub account from origin '{remote_url}'; pass --account.",
        )
    return slug.split("/", 1)[0]


def filter_non_ignorable_status_lines(lines: list[str]) -> list[str]:
    """Drop known transient metadata files from git-status output lines."""
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(prefix) for prefix in IGNORABLE_STATUS_PREFIXES):
            continue
        out.append(stripped)
    return out


def run_cmd(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run command in cwd and return captured completed-process output."""
    return subprocess.run(
        cmd,
        cwd=cwd,
        env=env,
        check=check,
        capture_output=True,
        text=True,
    )


def _git_stdout(args: list[str], *, cwd: Path) -> str:
    return run_cmd(["git", *args], cwd=cwd).stdout.strip()


def _gh(
    args: list[str],
    *,
    cwd: Path,
    gh_env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return run_cmd(["gh", *args], cwd=cwd, env=gh_env, check=check)


def _ensure_clean_tree(cwd: Path) -> None:
    raw = _git_stdout(["status", "--short"], cwd=cwd).splitlines()
    filtered = filter_non_ignorable_status_lines(raw)
    if filtered:
        raise SystemExit(
            "Preflight failed: working tree has non-ignorable changes:\n"
            + "\n".join(f"  {line}" for line in filtered),
        )


def _ensure_branch(cwd: Path) -> str:
    branch = _git_stdout(["branch", "--show-current"], cwd=cwd)
    if branch in {"", "main", "master"}:
        raise SystemExit(
            "Preflight failed: run pr-auto from a feature branch (not main/master).",
        )
    return branch


def _ensure_origin(cwd: Path, expected_repo: str) -> None:
    origin_url = _git_stdout(["config", "--get", "remote.origin.url"], cwd=cwd)
    if not origin_matches_expected_repo(origin_url, expected_repo):
        raise SystemExit(
            f"Preflight failed: origin '{origin_url}' does not match expected repo '{expected_repo}'.",
        )


def _switch_gh_account(cwd: Path, gh_env: dict[str, str], account: str) -> None:
    result = _gh(["auth", "switch", "-u", account], cwd=cwd, gh_env=gh_env, check=False)
    if result.returncode != 0:
        raise SystemExit(
            "GitHub auth switch failed. Run: gh auth login\n"
            f"stderr: {result.stderr.strip()}",
        )


@contextmanager
def isolated_github_auth(
    *,
    cwd: Path,
    gh_env: dict[str, str],
    account: str,
) -> Iterator[dict[str, str]]:
    """Select one stored GitHub account without mutating the shared profile.

    Multiple agents can publish concurrently from different owners. ``gh auth
    switch`` rewrites the active account in its config directory, so perform it
    only in a private copy that lives for this PR operation.
    """

    source = Path(
        gh_env.get("GH_CONFIG_DIR", str(Path.home() / ".config" / "gh"))
    ).expanduser()
    if not source.is_dir():
        raise SystemExit(f"GitHub auth config directory does not exist: {source}")

    with tempfile.TemporaryDirectory(prefix="enforced-planning-gh-") as temp_dir:
        isolated = Path(temp_dir) / "gh"
        shutil.copytree(source, isolated)
        isolated_env = {**gh_env, "GH_CONFIG_DIR": str(isolated)}
        _switch_gh_account(cwd, isolated_env, account)
        yield isolated_env


def _remote_branch_exists(cwd: Path, branch: str) -> bool:
    expected_ref = f"refs/heads/{branch}"
    result = run_cmd(
        ["git", "ls-remote", "--exit-code", "--heads", "origin", expected_ref],
        cwd=cwd,
        check=False,
    )
    if result.returncode == 2:
        if result.stdout.strip():
            raise SystemExit(
                "Preflight failed: remote branch lookup reported absence with unexpected output.",
            )
        return False
    if result.returncode != 0:
        raise SystemExit(
            "Preflight failed: unable to determine whether the feature branch is published.\n"
            f"stderr: {result.stderr.strip()}",
        )

    lines = result.stdout.splitlines()
    if len(lines) != 1:
        raise SystemExit(
            "Preflight failed: remote branch lookup did not return exactly one ref.",
        )
    fields = lines[0].split()
    if (
        len(fields) != 2
        or re.fullmatch(r"[0-9a-fA-F]{40}", fields[0]) is None
        or fields[1] != expected_ref
    ):
        raise SystemExit(
            f"Preflight failed: remote branch lookup returned malformed or mismatched evidence for '{expected_ref}'.",
        )
    return True


def _is_ancestor(cwd: Path, ancestor: str, descendant: str = "HEAD") -> bool:
    result = run_cmd(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=cwd,
        check=False,
    )
    if result.returncode in {0, 1}:
        return result.returncode == 0
    raise SystemExit(
        f"Preflight failed: unable to compare '{ancestor}' with '{descendant}'.\n"
        f"stderr: {result.stderr.strip()}",
    )


@contextmanager
def _staged_rebased_history(cwd: Path, *, base: str) -> Iterator[tuple[str, str]]:
    """Yield a temporary ref containing rebased history without moving the branch."""
    temporary_ref = f"refs/pr-auto/{uuid.uuid4().hex}"
    worktree_added = False
    ref_created = False
    with tempfile.TemporaryDirectory(prefix="pr-auto-rebase-") as temp_dir:
        staging_worktree = Path(temp_dir) / "worktree"
        try:
            run_cmd(
                ["git", "worktree", "add", "--detach", str(staging_worktree), "HEAD"],
                cwd=cwd,
            )
            worktree_added = True
            run_cmd(["git", "rebase", f"origin/{base}"], cwd=staging_worktree)
            candidate = _git_stdout(["rev-parse", "HEAD"], cwd=staging_worktree)
            run_cmd(["git", "update-ref", temporary_ref, candidate], cwd=cwd)
            ref_created = True
            yield temporary_ref, candidate
        finally:
            primary_error = sys.exc_info()[1]
            cleanup_failures: list[str] = []
            if worktree_added:
                command = ["git", "worktree", "remove", "--force", str(staging_worktree)]
                try:
                    result = run_cmd(command, cwd=cwd, check=False)
                except subprocess.CalledProcessError as exc:
                    detail = str(exc.stderr).strip() if exc.stderr else str(exc)
                    cleanup_failures.append(f"{' '.join(command)}: {detail}")
                except (OSError, subprocess.SubprocessError) as exc:
                    cleanup_failures.append(f"{' '.join(command)}: {exc}")
                else:
                    if result.returncode != 0:
                        cleanup_failures.append(
                            f"{' '.join(command)}: {result.stderr.strip() or f'exit {result.returncode}'}",
                        )
            if ref_created:
                command = ["git", "update-ref", "-d", temporary_ref]
                try:
                    result = run_cmd(command, cwd=cwd, check=False)
                except subprocess.CalledProcessError as exc:
                    detail = str(exc.stderr).strip() if exc.stderr else str(exc)
                    cleanup_failures.append(f"{' '.join(command)}: {detail}")
                except (OSError, subprocess.SubprocessError) as exc:
                    cleanup_failures.append(f"{' '.join(command)}: {exc}")
                else:
                    if result.returncode != 0:
                        cleanup_failures.append(
                            f"{' '.join(command)}: {result.stderr.strip() or f'exit {result.returncode}'}",
                        )
            if cleanup_failures:
                message = "Temporary publication cleanup failed:\n" + "\n".join(
                    f"  {failure}" for failure in cleanup_failures
                )
                if primary_error is not None:
                    primary_error.add_note(message)
                else:
                    raise SystemExit(message)


def _publish_unpublished_branch(cwd: Path, *, branch: str, base: str) -> None:
    """Create a remote branch before advancing its clean local counterpart."""
    remote_ref = f"refs/heads/{branch}"
    with _staged_rebased_history(cwd, base=base) as (temporary_ref, candidate):
        run_cmd(
            [
                "git",
                "push",
                "--atomic",
                f"--force-with-lease={remote_ref}:",
                "origin",
                f"{temporary_ref}:{remote_ref}",
            ],
            cwd=cwd,
        )
        run_cmd(
            ["git", "fetch", "origin", f"+{remote_ref}:refs/remotes/origin/{branch}"],
            cwd=cwd,
        )
        run_cmd(["git", "reset", "--keep", candidate], cwd=cwd)
        run_cmd(["git", "branch", "--set-upstream-to", f"origin/{branch}", branch], cwd=cwd)


def _prepare_branch_for_push(cwd: Path, *, branch: str, base: str) -> bool:
    """Publish an unpublished branch or validate a published fast-forward push.

    Return True when the unpublished path already performed its create-only
    push. Once ``origin/<branch>`` exists, this workflow never rebases it and
    leaves the ordinary fast-forward push to the caller.
    """
    if not _remote_branch_exists(cwd, branch):
        run_cmd(["git", "fetch", "origin"], cwd=cwd)
        if _remote_branch_exists(cwd, branch):
            raise SystemExit(
                f"Preflight failed: branch '{branch}' was published while pr-auto was preparing it.\n"
                "No rebase or push was attempted. Rerun pr-auto so the published-branch safety "
                "checks can evaluate the current remote history.",
            )
        _publish_unpublished_branch(cwd, branch=branch, base=base)
        return True

    run_cmd(["git", "fetch", "origin"], cwd=cwd)
    remote_branch = f"origin/{branch}"
    remote_base = f"origin/{base}"
    if not _is_ancestor(cwd, remote_branch):
        raise SystemExit(
            f"Preflight failed: published branch '{branch}' is not an ancestor of local HEAD.\n"
            "pr-auto will not rebase or overwrite published history. Reconcile the local and "
            "remote branch explicitly, then push with --force-with-lease only if rewriting that "
            "published history is intentional.",
        )
    if not _is_ancestor(cwd, remote_base):
        raise SystemExit(
            f"Preflight failed: origin/{base} advanced after published branch '{branch}'.\n"
            f"pr-auto will not automatically rebase a published branch. Explicitly run "
            f"'git rebase origin/{base}', review the rewritten commits, then recover with "
            f"'git push --force-with-lease origin HEAD:{branch}' if the rewrite is intentional.",
        )
    return False


def _push_branch(cwd: Path) -> None:
    run_cmd(["git", "push", "-u", "origin", "HEAD"], cwd=cwd)


def _find_open_pr(
    *,
    cwd: Path,
    gh_env: dict[str, str],
    branch: str,
    base: str,
) -> tuple[int, str] | None:
    result = _gh(
        ["pr", "list", "--head", branch, "--base", base, "--state", "open", "--json", "number,url"],
        cwd=cwd,
        gh_env=gh_env,
    )
    data = json.loads(result.stdout)
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    return int(first["number"]), str(first["url"])


def _create_pr(
    *,
    cwd: Path,
    gh_env: dict[str, str],
    branch: str,
    base: str,
    fill: bool,
    title: str | None,
    body_file: Path | None,
) -> None:
    cmd = ["pr", "create", "--base", base, "--head", branch]
    if fill:
        cmd.append("--fill")
    if title:
        cmd.extend(["--title", title])
    if body_file:
        cmd.extend(["--body-file", str(body_file)])
    _gh(cmd, cwd=cwd, gh_env=gh_env)


def _enable_auto_merge(*, cwd: Path, gh_env: dict[str, str], pr_number: int) -> bool:
    result = _gh(
        ["pr", "merge", str(pr_number), "--squash", "--delete-branch", "--auto"],
        cwd=cwd,
        gh_env=gh_env,
        check=False,
    )
    if result.returncode == 0:
        return True

    stderr = result.stderr.strip()
    if "enablePullRequestAutoMerge" in stderr or "Auto merge is not allowed" in stderr:
        print("Auto-merge unavailable for this repository policy; PR remains open.")
        return False

    raise SystemExit(
        "Failed to enable auto-merge.\n"
        f"stdout: {result.stdout.strip()}\n"
        f"stderr: {stderr}",
    )


def main() -> int:
    """Execute preflighted non-interactive PR flow."""
    parser = argparse.ArgumentParser(description="Autonomous PR workflow with preflight checks.")
    parser.add_argument("--base", default="main", help="Target base branch.")
    parser.add_argument("--expected-origin-repo", required=True, help="Expected origin repo name (e.g., my-repo).")
    parser.add_argument(
        "--account",
        default=None,
        help="GitHub account for gh auth switch (default: the origin repository owner).",
    )
    parser.add_argument("--fill", action="store_true", help="Use gh --fill when creating PR.")
    parser.add_argument("--title", default=None, help="PR title (optional).")
    parser.add_argument("--body-file", type=Path, default=None, help="PR body file path.")
    parser.add_argument("--preflight-only", action="store_true", help="Run checks only; do not rebase/push/create.")
    parser.add_argument("--auto-merge", action="store_true", help="Enable auto-merge after PR create/reuse.")
    args = parser.parse_args()

    cwd = Path.cwd()
    gh_env = sanitize_github_env()

    branch = _ensure_branch(cwd)
    _ensure_clean_tree(cwd)
    _ensure_origin(cwd, args.expected_origin_repo)
    account = resolve_github_account(
        args.account, _git_stdout(["config", "--get", "remote.origin.url"], cwd=cwd)
    )
    with isolated_github_auth(cwd=cwd, gh_env=gh_env, account=account) as isolated_env:
        if args.preflight_only:
            print("Preflight passed.")
            return 0

        branch_published = _prepare_branch_for_push(cwd, branch=branch, base=args.base)
        if not branch_published:
            _push_branch(cwd)

        pr = _find_open_pr(cwd=cwd, gh_env=isolated_env, branch=branch, base=args.base)
        if pr is None:
            _create_pr(
                cwd=cwd,
                gh_env=isolated_env,
                branch=branch,
                base=args.base,
                fill=args.fill,
                title=args.title,
                body_file=args.body_file,
            )
            pr = _find_open_pr(cwd=cwd, gh_env=isolated_env, branch=branch, base=args.base)
            if pr is None:
                raise SystemExit("PR creation failed: unable to locate open PR after create.")

        pr_number, pr_url = pr
        print(f"PR: {pr_url}")

        if args.auto_merge:
            enabled = _enable_auto_merge(cwd=cwd, gh_env=isolated_env, pr_number=pr_number)
            if enabled:
                print(f"Auto-merge enabled for PR #{pr_number}.")
            else:
                print(f"Auto-merge not enabled for PR #{pr_number}.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
