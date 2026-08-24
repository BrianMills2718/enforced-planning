#!/usr/bin/env python3
"""Close one claimed lane: cleanup worktree/branch and release claim together."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            return parent
    import importlib.util
    if importlib.util.find_spec("enforced_planning") is not None:
        for _ancestor in Path(__file__).resolve().parents:
            if (_ancestor / ".git").exists():
                return _ancestor
        return Path(__file__).resolve().parents[1]
    raise RuntimeError("Unable to locate repo root containing enforced_planning/")


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning import session_lifecycle  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--worktree-path")
    parser.add_argument("--branch")
    parser.add_argument("--note")
    parser.add_argument(
        "--mailbox-disposition",
        choices=sorted(session_lifecycle.MAILBOX_CLOSEOUT_DISPOSITIONS),
        help="Explicit disposition for active messages addressed to the closing session.",
    )
    parser.add_argument(
        "--mailbox-note",
        help="Required durable reason when --mailbox-disposition defers active messages.",
    )
    parser.add_argument(
        "--disposition",
        default=session_lifecycle.MERGED_DISPOSITION,
        choices=sorted(session_lifecycle.WORKTREE_DISPOSITIONS),
        help="Recorded lane outcome; merged is the safe default closeout path.",
    )
    parser.add_argument("--disposition-reason")
    parser.add_argument("--recovery-ref")
    parser.add_argument(
        "--merge-commit",
        help="Canonical squash-merge commit whose exact patch must match the task branch.",
    )
    parser.add_argument(
        "--allow-discard-unique",
        action="store_true",
        help="Explicitly authorize unique-commit deletion for disposition=abandoned.",
    )
    parser.add_argument("--keep-branch", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)




def _resolve_canonical_lock_module() -> Path | None:
    """Locate canonical_lock.py from either shipped script depth.

    The two copies of this script sit at different depths (``scripts/`` and
    ``scripts/meta/``), and the coordination module is installed beside
    whichever one a repo uses. Resolving only one layout fails closed and
    silently: the stale lock this reconcile exists to clear simply stays, and
    nothing reports it. Returns None only when the optional module is genuinely
    absent.
    """
    here = Path(__file__).resolve().parent
    for base in (here, here.parent):
        candidate = base / "worktree-coordination" / "canonical_lock.py"
        if candidate.exists():
            return candidate
    return None


def _reconcile_canonical_lock(scope: str) -> None:
    """Release the canonical lock once the lane that justified it is closed.

    close_session() releases the claim, but nothing was re-deriving lock state
    from the claim registry afterwards, so every closed lane left the canonical
    checkout read-only behind a claim that no longer existed. The next session
    then met a bare "Permission denied" from git or an editor with no live lane
    to explain it. safe_worktree_remove.py already reconciles for the same
    reason; this is the sanctioned closeout path and it was missing it.

    Reconcile is claim-driven, not path-driven: if another lane is still live
    against the same repository the lock correctly stays in place.
    """
    module_path = _resolve_canonical_lock_module()
    if module_path is None:
        # The optional worktree-coordination module is not installed here, so
        # there is no canonical lock to reconcile.
        return
    result = subprocess.run(
        [sys.executable, str(module_path), "--reconcile", "--quiet", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        print(
            "WARNING: canonical lock state could not be reconciled after closing "
            f"{scope}. The canonical checkout may still be read-only.\n"
            f"  Repair with: python3 {module_path} --reconcile\n"
            f"{result.stdout}{result.stderr}",
            file=sys.stderr,
        )
    elif result.stdout.strip():
        print(result.stdout.strip(), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = session_lifecycle.close_session(
        agent=args.agent,
        project=args.project,
        scope=args.scope,
        worktree_path=args.worktree_path,
        branch=args.branch,
        note=args.note,
        delete_branch=not args.keep_branch,
        disposition=args.disposition,
        disposition_reason=args.disposition_reason,
        recovery_ref=args.recovery_ref,
        merge_commit=args.merge_commit,
        allow_discard_unique=args.allow_discard_unique,
        mailbox_disposition=args.mailbox_disposition,
        mailbox_note=args.mailbox_note,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['action']}: worktree={payload['worktree_action']} "
            f"branch={payload['branch_action']} disposition={payload['disposition']} "
            f"released={payload['released']}"
        )
    _reconcile_canonical_lock(args.scope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
