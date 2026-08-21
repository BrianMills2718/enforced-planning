#!/usr/bin/env python3
"""Merge PR via GitHub CLI.

Usage:
    python scripts/merge_pr.py 123           # Merge PR #123
    python scripts/merge_pr.py 123 --dry-run # Check without merging
    python scripts/merge_pr.py 123 --defer-closeout
                                            # Merge, then reconcile before closeout

Note: Branch protection rules ensure:
- PRs require passing CI checks before merge
- Direct pushes to main are blocked
- GitHub handles concurrent merge attempts atomically

The previous lock mechanism was removed because branch protection
makes it redundant, and it cannot work (can't push directly to main).
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path


def run_cmd(
    cmd: list[str], check: bool = True, capture: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a command, optionally capturing output."""
    env = os.environ.copy()
    env["GIT_CONFIG_NOSYSTEM"] = "1"  # Fix for gh CLI
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
        env=env,
    )


def get_pr_branch(pr_number: int) -> str | None:
    """Get the head branch name for a PR."""
    result = run_cmd(
        ["gh", "pr", "view", str(pr_number), "--json", "headRefName"],
        check=False,
    )
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    branch = data.get("headRefName") if isinstance(data, dict) else None
    return branch if isinstance(branch, str) and branch else None


def get_pr_merge_commit(pr_number: int) -> str | None:
    """Return the canonical merge commit after GitHub reports the PR merged."""

    result = run_cmd(
        ["gh", "pr", "view", str(pr_number), "--json", "state,mergeCommit"],
        check=False,
    )
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    state = data.get("state") if isinstance(data, dict) else None
    merge_commit = data.get("mergeCommit") if isinstance(data, dict) else None
    oid = merge_commit.get("oid") if isinstance(merge_commit, dict) else None
    return oid if state == "MERGED" and isinstance(oid, str) and oid else None


def find_existing_script(paths: list[str]) -> Path | None:
    """Return the first existing script path from a priority-ordered list."""
    for script_path in paths:
        candidate = Path(script_path)
        if candidate.exists():
            return candidate
    return None


def find_worktree_for_branch(branch: str) -> Path | None:
    """Find local worktree path for a branch, if it exists."""
    result = run_cmd(["git", "worktree", "list", "--porcelain"], check=False)
    if result.returncode != 0:
        return None

    # Parse porcelain output: worktree path, HEAD sha, branch on separate lines
    current_path = None
    for line in result.stdout.strip().split("\n"):
        if line.startswith("worktree "):
            current_path = Path(line[9:])
        elif line.startswith("branch refs/heads/"):
            worktree_branch = line[18:]
            if worktree_branch == branch:
                return current_path
    return None


def resolve_claim_identity(
    branch: str,
    *,
    agent: str,
    worktree_path: Path | None,
) -> tuple[str, str] | None:
    """Return the one live claim identity that owns the merged branch."""

    claims_script = find_existing_script(
        [
            "scripts/check_coordination_claims.py",
            "scripts/meta/check_coordination_claims.py",
        ]
    )
    if claims_script is None:
        return None
    result = run_cmd(
        ["python", str(claims_script), "--list", "--json"],
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    records = payload.get("claims", []) if isinstance(payload, dict) else []
    candidates: list[tuple[str, str]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        if record.get("agent") != agent or record.get("branch") != branch:
            continue
        if record.get("status") not in {"active", "blocked", "handoff", "session_ended"}:
            continue
        recorded_path = record.get("worktree_path")
        if (
            worktree_path is not None
            and recorded_path
            and Path(str(recorded_path)).expanduser().resolve()
            != worktree_path.expanduser().resolve()
        ):
            continue
        projects = record.get("projects")
        project = projects[0] if isinstance(projects, list) and projects else record.get("project")
        scope = record.get("scope")
        if isinstance(project, str) and project and isinstance(scope, str) and scope:
            candidates.append((project, scope))
    unique = sorted(set(candidates))
    return unique[0] if len(unique) == 1 else None


def canonical_repo_root() -> Path:
    """Resolve the primary checkout root even when invoked from a linked worktree."""

    result = run_cmd(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        check=False,
    )
    if result.returncode == 0:
        common_dir = Path(result.stdout.strip()).expanduser().resolve()
        if common_dir.name == ".git":
            return common_dir.parent
    return Path(__file__).resolve().parent.parent


def release_claim_for_branch(branch: str) -> bool:
    """Release any claim associated with this branch. PR merged = work done.

    Gracefully degrades if claims system is not installed (worktree-coordination module).
    """
    # Try both script locations (portable: scripts/meta, project: scripts, worktree-coord)
    claims_script = find_existing_script(
        [
            "scripts/worktree-coordination/check_claims.py",
            "scripts/meta/worktree-coordination/check_claims.py",
            "scripts/check_claims.py",
            "scripts/meta/check_claims.py",
        ]
    )
    if claims_script:
        result = run_cmd(
            ["python", str(claims_script), "--release", "--id", branch, "--force"],
            check=False,
        )
        if result.returncode == 0 and "Released" in result.stdout:
            print(f"   Released claim for '{branch}'")
            return True
        return False  # Script exists but no claim - that's fine
    # Claims system not installed - skip silently
    return False


def cleanup_worktree(
    branch: str,
    *,
    merge_commit: str | None = None,
    execute: bool = True,
) -> bool:
    """Execute or print the receipt-bound closeout for one merged lane."""
    if not execute and not merge_commit:
        print(
            "HIGH: deferred closeout requires GitHub's canonical merge receipt; the lane remains open."
        )
        return False

    worktree_path = find_worktree_for_branch(branch)
    action = "Closing" if execute else "Preparing deferred closeout for"
    print(f"🧹 {action} merged lane for branch '{branch}'...")

    safe_remove_script = find_existing_script(
        [
            "scripts/session_close.py",
            "scripts/meta/session_close.py",
        ]
    )
    if not execute and safe_remove_script is None:
        print(
            "HIGH: deferred closeout requires the sanctioned session-close "
            "entrypoint; no resumable closeout command was emitted."
        )
        return False

    if safe_remove_script:
        agent = (
            "codex"
            if os.environ.get("CODEX_THREAD_ID")
            else "claude-code"
            if os.environ.get("CLAUDE_SESSION_ID") or os.environ.get("CLAUDE_CODE_SSE_PORT")
            else "openclaw"
            if os.environ.get("OPENCLAW_SESSION_ID") or os.environ.get("OPENCLAW_RUN_ID")
            else None
        )
        if not execute and not agent:
            print(
                "HIGH: deferred closeout requires an exact runtime identity so "
                "the owning project and claim scope can be resolved."
            )
            return False
        if not agent:
            cleanup_cmd = ["make", "worktree-remove", f"BRANCH={branch}"]
            if merge_commit:
                cleanup_cmd.append(f"WORKTREE_MERGE_COMMIT={merge_commit}")
            manual_cmd = " ".join(cleanup_cmd)
        else:
            claim_identity = resolve_claim_identity(
                branch,
                agent=agent,
                worktree_path=worktree_path,
            )
            if claim_identity is None:
                print(
                    "HIGH: session-close is available, but no unambiguous live claim "
                    f"owns branch {branch!r}; refusing guessed project/scope closeout."
                )
                return False
            project, scope = claim_identity
            cleanup_cmd = [
                "python",
                str(safe_remove_script),
                "--agent",
                agent,
                "--project",
                project,
                "--scope",
                scope,
                "--branch",
                branch,
            ]
            if worktree_path:
                cleanup_cmd.extend(["--worktree-path", str(worktree_path)])
            if merge_commit:
                cleanup_cmd.extend(["--merge-commit", merge_commit])
            manual_cmd = " ".join(cleanup_cmd)
    else:
        if not worktree_path:
            print(
                "HIGH: merged lane has no discoverable worktree and no sanctioned "
                "session-close entrypoint; ownership disposition was not recorded."
            )
            return False
        safe_remove_script = find_existing_script(
        [
            "scripts/worktree-coordination/safe_worktree_remove.py",
            "scripts/meta/worktree-coordination/safe_worktree_remove.py",
            "scripts/safe_worktree_remove.py",
            "scripts/meta/safe_worktree_remove.py",
        ]
        )
        if safe_remove_script:
            cleanup_cmd = ["python", str(safe_remove_script), str(worktree_path)]
            manual_cmd = f"python {safe_remove_script} {worktree_path}"
        else:
            cleanup_cmd = ["make", "worktree-remove", f"BRANCH={branch}"]
            if merge_commit:
                cleanup_cmd.append(f"WORKTREE_MERGE_COMMIT={merge_commit}")
            manual_cmd = " ".join(cleanup_cmd)

    if not execute:
        root_anchored_command = (
            f"cd {shlex.quote(str(canonical_repo_root()))} && "
            f"{shlex.join(cleanup_cmd)}"
        )
        print(
            "MERGED; CLOSEOUT DEFERRED: the claim and worktree remain live until "
            "the required post-merge reconciliation is complete."
        )
        print(f"   Canonical merge receipt: {merge_commit}")
        print(f"   Then run from the canonical root: {root_anchored_command}")
        return True

    result = run_cmd(cleanup_cmd, check=False)

    if result.returncode != 0:
        # Worktree removal failed - warn but don't fail the merge
        print(f"⚠️  Could not auto-cleanup worktree: {result.stderr or result.stdout}")
        print(f"   Run manually: {manual_cmd}")
        return False

    print(f"✅ Closed merged lane for {branch}")
    return True


def check_pr_mergeable(pr_number: int) -> tuple[bool, str]:
    """Check if PR is mergeable. Returns (mergeable, reason)."""
    result = run_cmd(
        [
            "gh",
            "pr",
            "view",
            str(pr_number),
            "--json",
            "mergeable,mergeStateStatus,statusCheckRollup",
        ],
        check=False,
    )

    if result.returncode != 0:
        return False, f"Failed to get PR status: {result.stderr}"

    data = json.loads(result.stdout)

    mergeable = data.get("mergeable", "UNKNOWN")
    state = data.get("mergeStateStatus", "UNKNOWN")

    if mergeable == "CONFLICTING":
        return False, "PR has merge conflicts - needs rebase"

    if state == "BEHIND":
        return False, "PR is behind main - needs rebase"

    if state == "BLOCKED":
        # Check which checks are failing
        checks = data.get("statusCheckRollup", []) or []
        failing = [
            c.get("context", "unknown")
            for c in checks
            if c.get("conclusion") == "FAILURE"
            and c.get("context") != "feature-coverage"
        ]
        if failing:
            return False, f"Required checks failing: {', '.join(failing)}"

        pending = [
            c.get("context", "unknown")
            for c in checks
            if c.get("status") in ("IN_PROGRESS", "QUEUED", "PENDING")
        ]
        if pending:
            return False, f"Checks still running: {', '.join(pending)}"

    return True, "OK"


def merge_pr(
    pr_number: int,
    dry_run: bool = False,
    *,
    defer_closeout: bool = False,
) -> bool:
    """Merge a PR and close its lane, or explicitly defer that closeout."""
    print(f"🔍 Checking PR #{pr_number}...")

    # Get branch name before merge (needed for worktree cleanup)
    branch = get_pr_branch(pr_number)
    if not branch:
        print(
            f"❌ Refusing to merge PR #{pr_number}: its head branch could not be "
            "resolved, so closeout cannot be bound to an exact lane."
        )
        return False

    # Fetch latest
    print("📥 Fetching latest...")
    run_cmd(["git", "fetch", "origin"], check=False)

    # Check if PR is mergeable
    mergeable, reason = check_pr_mergeable(pr_number)
    if not mergeable:
        print(f"❌ PR #{pr_number} cannot be merged: {reason}")
        return False

    print(f"✅ PR #{pr_number} is mergeable")

    if dry_run:
        print(f"\n🔍 Dry run complete. PR #{pr_number} is ready to merge.")
        return True

    # Merge
    print(f"🚀 Merging PR #{pr_number}...")
    try:
        result = run_cmd(
            ["gh", "pr", "merge", str(pr_number), "--squash", "--delete-branch"],
            check=False,
        )

        if result.returncode != 0:
            # Check for specific errors
            stderr = result.stderr or ""
            if "used by worktree" in stderr:
                # Branch deleted on remote but local worktree exists - this is OK
                print(f"✅ PR #{pr_number} merged (local worktree still exists)")
            else:
                print(f"❌ Merge failed: {stderr}")
                return False
        else:
            print(f"✅ PR #{pr_number} merged successfully")

    except subprocess.CalledProcessError as e:
        print(f"❌ Merge failed: {e}")
        return False

    # Refresh the canonical remote ref and capture the immutable merge receipt.
    print("📥 Fetching merged default branch...")
    run_cmd(["git", "fetch", "origin", "main"], check=False)
    merge_commit = get_pr_merge_commit(pr_number)
    if not merge_commit:
        print("HIGH: GitHub did not return a canonical merge commit for the merged PR.")
        return False

    # Close immediately by default. A caller may explicitly retain the live lane
    # when canonical-Git verification or reconciliation must happen first.
    if not cleanup_worktree(
        branch,
        merge_commit=merge_commit,
        execute=not defer_closeout,
    ):
        print(
            "HIGH: PR merged, but claim/worktree closeout failed. "
            "The merge command is incomplete until the printed session-close action succeeds."
        )
        return False

    if defer_closeout:
        print(
            f"\n✅ PR #{pr_number} merged at {merge_commit}; closeout was explicitly deferred and remains mandatory."
        )
        return True

    print(f"\n✅ Done! PR #{pr_number} has been merged.")
    return True


def main() -> int:
    # Prevent CWD-in-deleted-worktree issue
    # Always run from project root, not from a worktree that may be deleted
    project_root = canonical_repo_root()
    os.chdir(project_root)

    parser = argparse.ArgumentParser(
        description="Merge PR via GitHub CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("pr", type=int, nargs="?", help="PR number to merge")
    parser.add_argument("--dry-run", action="store_true", help="Check without merging")
    parser.add_argument(
        "--defer-closeout",
        action="store_true",
        help=(
            "Merge and print the exact receipt-bound closeout command without "
            "executing it; use only when required post-merge reconciliation must "
            "precede closeout."
        ),
    )

    args = parser.parse_args()

    if not args.pr:
        parser.print_help()
        return 1

    return (
        0
        if merge_pr(
            args.pr,
            args.dry_run,
            defer_closeout=args.defer_closeout,
        )
        else 1
    )


if __name__ == "__main__":
    sys.exit(main())
