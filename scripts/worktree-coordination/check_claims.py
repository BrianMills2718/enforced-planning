#!/usr/bin/env python3
"""Deprecated compatibility facade for canonical coordination claims.

Canonical command (installed consumers):
    python scripts/meta/check_coordination_claims.py ...

This path never reads or writes the retired repo-local
``.claude/active-work.yaml``; all claim state comes from the package-backed
canonical registry under ``~/.claude/coordination/claims/`` (enforced-planning
#610). It is shipped by ``install.sh --full`` as
``scripts/meta/worktree-coordination/check_claims.py`` and called by
``merge_pr.py`` as ``--release --id BRANCH --force`` after a merge.

Supported legacy translations:
    --release --id BRANCH [--force]  -> canonical branch release
    --verify-branch BRANCH           -> canonical branch claim lookup
    --verify-claim                   -> canonical current-branch claim lookup

Canonical CLI arguments are otherwise delegated unchanged. Obsolete legacy
claim-creation flags fail with migration guidance instead of creating state
in a second registry.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

# scripts/worktree-coordination/ (source) and scripts/meta/worktree-coordination/
# (installed) both sit one level below their check_coordination_claims.py.
CANONICAL_SCRIPT = Path(__file__).resolve().parent.parent / "check_coordination_claims.py"
CANONICAL_COMMAND = "python scripts/meta/check_coordination_claims.py"


def _load_canonical() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "_canonical_coordination_claims_cli",
        CANONICAL_SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load canonical coordination CLI: {CANONICAL_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_canonical = _load_canonical()


def _current_branch() -> str:
    result = subprocess.run(
        ["git", "branch", "--show-current"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _branch_has_claim(branch: str) -> bool:
    normalized = branch.strip()
    return bool(normalized) and any(
        claim.branch == normalized and claim.is_live() for claim in _canonical.check_claims()
    )


def _value_after(argv: list[str], flag: str) -> str | None:
    try:
        index = argv.index(flag)
    except ValueError:
        return None
    if index + 1 >= len(argv):
        return None
    return argv[index + 1]


def _migration_error(*, reason: str) -> int:
    print(
        "ERROR: legacy worktree claim CLI no longer owns claim state.\n"
        f"{reason}\n"
        f"Use the canonical package-backed command instead:\n  {CANONICAL_COMMAND} --help",
        file=sys.stderr,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)

    if "--verify-branch" in args:
        branch = _value_after(args, "--verify-branch")
        if not branch:
            return _migration_error(reason="--verify-branch requires a branch name.")
        if _branch_has_claim(branch):
            print(f"Canonical claim found for branch: {branch}")
            return 0
        print(f"No live canonical claim found for branch: {branch}")
        return 1

    if "--verify-claim" in args:
        branch = _current_branch()
        if not branch:
            print("Unable to resolve current branch.", file=sys.stderr)
            return 1
        if _branch_has_claim(branch):
            print(f"Canonical claim found for current branch: {branch}")
            return 0
        print(f"No live canonical claim found for current branch: {branch}")
        return 1

    if "--release" in args and "--id" in args:
        branch = _value_after(args, "--id")
        if not branch:
            return _migration_error(reason="legacy --release --id requires a branch name.")
        try:
            count, messages = _canonical.release_claims_for_branch(branch)
        except ValueError as exc:
            # A managed lane closes only through session-close.
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        for message in messages:
            print(message)
        if count == 0:
            print(f"No live canonical claim found for branch: {branch}")
        return 0

    obsolete = sorted(
        flag
        for flag in (
            "--id",
            "--task",
            "--feature",
            "--check-files",
            "--list-features",
            "--cleanup",
            "--force",
        )
        if flag in args
    )
    if obsolete:
        return _migration_error(
            reason=(
                "Unsupported legacy flag(s): " + ", ".join(obsolete) + ". "
                "Create/check claims with --agent, --project, --scope, --intent, "
                "and canonical write/read paths as applicable."
            )
        )

    return _canonical.main(args)


if __name__ == "__main__":
    raise SystemExit(main())
