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

from enforced_planning import concurrent_writers  # noqa: E402
from enforced_planning import coordination_claims  # noqa: E402
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
        ("tracker_absent", args.tracker_absent),
        ("recovery_archive_dir", args.recovery_archive_dir),
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
        "--tracker-absent",
        action="store_true",
        help=(
            "With --reconcile-session-ended: dispose of a session-ended claim whose session tracker "
            "does not exist (verified). Captures git status, branch head, and a recovery ref first; "
            "uncommitted changes are also bundled under --recovery-archive-dir and the worktree and "
            "branch are retained."
        ),
    )
    parser.add_argument(
        "--recovery-archive-dir",
        help="Absolute, empty (or new) directory for --tracker-absent capture artifacts.",
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




def _resolve_durable_repo_root(repo_root: Path = REPO_ROOT) -> Path:
    """Return the canonical checkout that survives linked-worktree removal."""

    common_dir = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "rev-parse",
            "--path-format=absolute",
            "--git-common-dir",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if common_dir.returncode != 0 or not common_dir.stdout.strip():
        return repo_root.resolve()
    return Path(common_dir.stdout.strip()).resolve().parent


def _materialize_shared_ref_history(
    repo_root: Path,
    *,
    remote: str = "origin",
    branch: str = "main",
) -> str | None:
    """Refresh the durable shared-ref graph while the lane still owns writes.

    A partial clone can retain a remote-tracking ref without retaining every
    ancestor object. If the linked worktree and task branch are removed first,
    a later range walk may ask the promisor remote for the now-unadvertised
    start object and fail with ``upload-pack: not our ref``. Fetch the named
    branch through an advertised ref before destructive cleanup so both the
    tracking ref and its reachable history are locally usable by the report.

    A disconnected repository is still closeable: the existing report keeps
    its explicit ``NOT CHECKED`` state if the local graph remains unreadable.
    """

    destination = f"refs/remotes/{remote}/{branch}"
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_root),
            "fetch",
            "--quiet",
            "--no-tags",
            remote,
            f"+refs/heads/{branch}:{destination}",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode == 0:
        return None
    return completed.stderr.strip() or "shared-ref history refresh failed"


def _resolve_canonical_lock_module(
    *,
    repo_root: Path = REPO_ROOT,
    script_path: Path | None = None,
) -> Path | None:
    """Locate canonical_lock.py from either shipped script depth.

    The two copies of this script sit at different depths (``scripts/`` and
    ``scripts/meta/``), and the coordination module is installed beside
    whichever one a repo uses. Resolving only one layout fails closed and
    silently: the stale lock this reconcile exists to clear simply stays, and
    nothing reports it. Returns None only when the optional module is genuinely
    absent.
    """
    resolved_script = (script_path or Path(__file__)).resolve()
    here = resolved_script.parent
    bases: list[Path] = []
    canonical_root = _resolve_durable_repo_root(repo_root)
    if canonical_root != repo_root.resolve():
        try:
            script_directory = here.relative_to(repo_root.resolve())
        except ValueError:
            pass
        else:
            canonical_script_directory = canonical_root / script_directory
            bases.extend(
                (canonical_script_directory, canonical_script_directory.parent)
            )
    bases.extend((here, here.parent))
    for base in dict.fromkeys(bases):
        candidate = base / "worktree-coordination" / "canonical_lock.py"
        if candidate.exists():
            return candidate
    return None


def _reconcile_canonical_lock(scope: str, module_path: Path | None = None) -> None:
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
    module_path = module_path or _resolve_canonical_lock_module()
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



def _lane_range_basis(project: str, scope: str, branch: str | None) -> tuple[str | None, str]:
    """The revision this lane branched from, read before the claim is released.

    A claim's ``start_revision`` is recorded once and never moves, which is what
    this report wants, but it is populated only for plan-graph-backed lanes: 2 of
    72 live claims carried one when this was written. So an unplanned maintenance
    lane -- the common case -- falls back to its branch's merge-base against the
    shared ref, which keeps the report alive at a cost the rendered text states.
    """
    for claim in coordination_claims._load_claims():
        if claim.scope == scope and project in claim.projects and claim.start_revision:
            return claim.start_revision, concurrent_writers.BASIS_START_REVISION

    candidate = branch or scope
    completed = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge-base", candidate, "origin/main"],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return None, concurrent_writers.BASIS_MERGE_BASE
    return completed.stdout.strip() or None, concurrent_writers.BASIS_MERGE_BASE


def _report_shared_ref_movement(
    since_revision: str | None,
    basis: str,
    lane_refs: tuple[str, ...],
    *,
    repo_root: Path = REPO_ROOT,
) -> None:
    """Say whether the shared branch moved from outside this lane while it was open.

    Policy shared-surface-state-claims: a closeout that describes what was
    written is only ever speaking for its own session. Printed to stderr so it
    reaches the operator without disturbing --json consumers.
    """
    report = concurrent_writers.collect_shared_ref_movement(
        repo_root,
        ref="origin/main",
        since_revision=since_revision,
        lane_refs=lane_refs,
        basis=basis,
    )
    print(concurrent_writers.render_report(report), file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    durable_repo_root = _resolve_durable_repo_root()
    _materialize_shared_ref_history(durable_repo_root)
    since_revision, range_basis = _lane_range_basis(args.project, args.scope, args.branch)
    # Resolve this while the lane still exists. close_session() can remove the
    # worktree containing this script, so a relative lookup after closeout can
    # no longer find the reconciliation helper.
    canonical_lock_module = _resolve_canonical_lock_module()
    payload = session_lifecycle.close_session(**_supported_closeout_kwargs(args))
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['action']}: worktree={payload['worktree_action']} "
            f"branch={payload['branch_action']} disposition={payload['disposition']} "
            f"released={payload['released']}"
        )
    _reconcile_canonical_lock(args.scope, canonical_lock_module)
    _report_shared_ref_movement(
        since_revision,
        range_basis,
        tuple(
            dict.fromkeys(
                ref
                for ref in (
                    args.branch or args.scope,
                    args.merge_commit,
                    payload.get("merge_commit"),
                )
                if ref
            )
        ),
        repo_root=durable_repo_root,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
