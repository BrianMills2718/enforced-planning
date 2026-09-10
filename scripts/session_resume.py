#!/usr/bin/env python3
"""Resume one plan-bound sanctioned session with a fresh runtime attachment."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_package() -> None:
    """Load local package support or the target repo's upstream bootstrap."""
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    for parent in current.parents:
        helper = parent / "scripts" / "_upstream_enforced_planning.py"
        if helper.is_file():
            if str(helper.parent) not in sys.path:
                sys.path.insert(0, str(helper.parent))
            from _upstream_enforced_planning import bootstrap_upstream_package  # type: ignore[import-not-found]

            bootstrap_upstream_package(current)
            return
    import importlib.util
    if importlib.util.find_spec("enforced_planning") is not None:
        return
    raise RuntimeError("Unable to locate local or upstream enforced_planning support")


_bootstrap_package()

from enforced_planning import coordination_claims, session_lifecycle
from enforced_planning.session_continuity import (
    SuccessorCustodyAcceptanceV1,
    SuccessorCustodyOfferV1,
    accept_successor_custody_offer,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the bounded session-resume identity and phase contract."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--current-phase", required=True)
    parser.add_argument("--session-id")
    parser.add_argument(
        "--successor-agent",
        help=(
            "Different supported agent legitimately taking over a claim the "
            "recorded agent explicitly left in 'handoff' status. Proves this "
            "agent's own native identity and transfers claim custody/filename "
            "to it. Refused for any status other than handoff."
        ),
    )
    parser.add_argument(
        "--predecessor-process-pid",
        type=int,
        help="Exact prior Codex process PID to verify and terminate before cross-session transfer.",
    )
    parser.add_argument(
        "--predecessor-process-start-ticks",
        type=int,
        help="Exact /proc start ticks for the predecessor PID generation.",
    )
    parser.add_argument("--note")
    parser.add_argument(
        "--abort-unfenced-takeover-reservation",
        action="store_true",
        help="Cancel only this successor's unjournalized reservation after a pre-fence validation failure.",
    )
    parser.add_argument(
        "--repair-worktree-path",
        action="store_true",
        help=(
            "Accept a --worktree-path that differs from the claim's recorded one, "
            "only when the recorded path is genuinely gone and the provided path is "
            "a real linked worktree checked out on the exact claimed branch. For a "
            "worktree legitimately relocated to the sanctioned "
            "<repo>/worktrees/<branch>/ convention after the claim was created."
        ),
    )
    parser.add_argument(
        "--repair-missing-plan-ref",
        action="store_true",
        help=(
            "Stamp the explicit UNPLANNED marker onto a claim whose plan_ref is "
            "absent, then resume normally. Only for a lane written before the "
            "--allow-unplanned/--plan UNPLANNED fallback existed; it refuses a "
            "claim that already records a real plan authority."
        ),
    )
    parser.add_argument(
        "--successor-custody-offer",
        type=Path,
        help="Exact offer JSON that this successor explicitly accepted.",
    )
    parser.add_argument(
        "--verify-successor-custody-offer-only",
        action="store_true",
        help=(
            "Verify the exact offer against current claim and Git state without "
            "accepting, reserving, fencing, or transferring custody."
        ),
    )
    acceptance = parser.add_mutually_exclusive_group()
    acceptance.add_argument(
        "--successor-custody-acceptance",
        type=Path,
        help="Successor-authored acceptance JSON bound to the exact offer.",
    )
    acceptance.add_argument(
        "--accept-successor-custody-offer",
        action="store_true",
        help=(
            "Explicitly accept the exact offer as the current native session and pass "
            "the resulting bound receipt directly into the custody transaction."
        ),
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Resume the session and expose its current mailbox state."""
    args = parse_args(argv)
    has_offer = args.successor_custody_offer is not None
    has_acceptance = (
        args.successor_custody_acceptance is not None
        or args.accept_successor_custody_offer
    )
    if args.verify_successor_custody_offer_only:
        if not has_offer or has_acceptance:
            raise ValueError(
                "offer-only verification requires one offer and no acceptance mode"
            )
    elif has_offer != has_acceptance:
        raise ValueError(
            "automatic successor resume requires an offer and exactly one acceptance mode"
        )
    offer = (
        SuccessorCustodyOfferV1.model_validate_json(
            args.successor_custody_offer.expanduser().read_text(encoding="utf-8")
        )
        if args.successor_custody_offer is not None
        else None
    )
    if args.abort_unfenced_takeover_reservation:
        if has_offer or args.predecessor_process_pid is not None or args.predecessor_process_start_ticks is not None:
            raise ValueError("unfenced takeover abort cannot be combined with transfer or predecessor-process arguments")
        payload = session_lifecycle.abort_unfenced_session_takeover(
            agent=args.agent,
            project=args.project,
            scope=args.scope,
            worktree_path=args.worktree_path,
            session_id=args.session_id,
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"{payload['action']}: {payload['session_id']}")
        return 0
    successor_session_id = args.session_id
    if args.verify_successor_custody_offer_only:
        payload = session_lifecycle.verify_successor_custody_offer_state(
            agent=args.agent,
            project=args.project,
            scope=args.scope,
            worktree_path=args.worktree_path,
            branch=args.branch,
            successor_custody_offer=offer,
        )
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"{payload['action']}: {payload['offer_id']}")
        return 0
    if offer is not None and args.accept_successor_custody_offer:
        successor_session_id = coordination_claims.resolve_session_id(
            args.agent, args.session_id
        )
        if successor_session_id is None:
            raise ValueError(
                "explicit successor acceptance requires a current native session identity"
            )
        acceptance = accept_successor_custody_offer(
            offer=offer,
            successor_session_id=successor_session_id,
            project=args.project,
            scope=args.scope,
            branch=args.branch,
            worktree_path=args.worktree_path,
            claim_epoch_sha256=offer.claim_epoch_sha256,
            head_revision=offer.head_revision,
            next_action=offer.next_action,
        )
    else:
        acceptance = (
            SuccessorCustodyAcceptanceV1.model_validate_json(
                args.successor_custody_acceptance.expanduser().read_text(
                    encoding="utf-8"
                )
            )
            if args.successor_custody_acceptance is not None
            else None
        )
    payload = session_lifecycle.resume_session(
        agent=args.agent,
        project=args.project,
        scope=args.scope,
        worktree_path=args.worktree_path,
        branch=args.branch,
        current_phase=args.current_phase,
        session_id=successor_session_id,
        note=args.note,
        predecessor_process_pid=args.predecessor_process_pid,
        predecessor_process_start_ticks=args.predecessor_process_start_ticks,
        successor_custody_offer=offer,
        successor_custody_acceptance=acceptance,
        repair_worktree_path=args.repair_worktree_path,
        repair_missing_plan_ref=args.repair_missing_plan_ref,
        successor_agent=args.successor_agent,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"{payload['action']}: {payload['plan_ref']} -> {payload['session_id']}")
        print(payload["coordination_mailbox"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
