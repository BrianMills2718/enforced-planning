#!/usr/bin/env python3
"""Close one claimed lane: cleanup worktree/branch and release claim together."""

from __future__ import annotations

import argparse
import inspect
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


def _mailbox_dispositions() -> list[str]:
    """Use mailbox closeout choices only when the installed lifecycle supports them.

    The bounded claim-projection refresh profile deliberately updates the
    coordination adapter without replacing a target's whole session-lifecycle
    implementation. Older lifecycle modules therefore remain valid consumers
    of this wrapper: they retain their existing closeout contract while their
    updated ``coordination_claims`` dependency refreshes the projection.
    """

    supported = getattr(session_lifecycle, "MAILBOX_CLOSEOUT_DISPOSITIONS", None)
    if supported is None:
        supported = session_lifecycle.WORKTREE_DISPOSITIONS
    return sorted(supported)


def _supported_closeout_kwargs(args: argparse.Namespace) -> dict[str, object]:
    """Pass new closeout fields only to lifecycle modules that declare them."""

    kwargs: dict[str, object] = {
        "agent": args.agent,
        "project": args.project,
        "scope": args.scope,
        "worktree_path": args.worktree_path,
        "branch": args.branch,
        "note": args.note,
        "delete_branch": not args.keep_branch,
        "disposition": args.disposition,
        "disposition_reason": args.disposition_reason,
        "recovery_ref": args.recovery_ref,
        "allow_discard_unique": args.allow_discard_unique,
    }
    supported = inspect.signature(session_lifecycle.close_session).parameters
    for name, value in (
        ("merge_commit", args.merge_commit),
        ("reconcile_missing_worktree", args.reconcile_missing_worktree),
        ("expected_tracker_sha256", args.tracker_sha256),
        ("reconcile_canonical_root", args.reconcile_canonical_root),
        ("reconcile_session_ended", args.reconcile_session_ended),
        ("expected_claim_sha256", args.claim_sha256),
        ("mailbox_disposition", args.mailbox_disposition),
        ("mailbox_note", args.mailbox_note),
        ("actor_session_id", args.session_id),
        ("terminalize_shared_child", args.terminalize_shared_child),
    ):
        if name in supported:
            kwargs[name] = value
    return kwargs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--worktree-path")
    parser.add_argument("--branch")
    parser.add_argument("--note")
    parser.add_argument(
        "--mailbox-disposition",
        choices=_mailbox_dispositions(),
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
        "--reconcile-missing-worktree",
        action="store_true",
        help="Close only an exact session-ended lane whose recorded worktree is already absent.",
    )
    parser.add_argument(
        "--tracker-sha256",
        help="Exact SHA-256 of the preserved session tracker required for reconciliation.",
    )
    parser.add_argument(
        "--reconcile-canonical-root",
        action="store_true",
        help=(
            "Archive an exact session-ended legacy claim whose recorded worktree is the clean canonical "
            "repository root, retaining the filesystem and branch."
        ),
    )
    parser.add_argument(
        "--reconcile-session-ended",
        action="store_true",
        help=(
            "Terminally close one exact session-ended linked worktree as the current native "
            "actor without transferring predecessor write custody; requires claim and tracker digests."
        ),
    )
    parser.add_argument(
        "--claim-sha256",
        help="Exact SHA-256 required for canonical-root or session-ended reconciliation.",
    )
    parser.add_argument(
        "--terminalize-shared-child",
        action="store_true",
        help=(
            "Archive one merged child claim while retaining the exact live parent's shared "
            "worktree and branch."
        ),
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
    payload = session_lifecycle.close_session(**_supported_closeout_kwargs(args))
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
