#!/usr/bin/env python3
"""Observe one claim owner and report resume-first continuity action."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning import (  # noqa: E402
    coordination_claims,
    coordination_messages,
    session_continuity,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--notify-minutes", type=int, default=15)
    parser.add_argument(
        "--send-resume-offer",
        action="store_true",
        help="Persist one idempotent exact-session resume offer when the assessment requests it.",
    )
    parser.add_argument("--sender-session-id")
    parser.add_argument(
        "--resume-offer-message-id",
        help="Review one exact prior resume offer against current owner activity and receipts.",
    )
    parser.add_argument("--successor-after-minutes", type=int, default=30)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    matches = [
        claim
        for claim in coordination_claims.check_claims()
        if claim.agent == args.agent
        and args.project in claim.projects
        and claim.scope == args.scope
    ]
    if len(matches) != 1:
        raise ValueError("session continuity requires one exact live claim")
    claim = matches[0]
    transcript = coordination_claims.session_transcript_path(claim.session_id)
    activity = (
        session_continuity.read_codex_activity(
            session_id=claim.session_id or "unknown",
            transcript_path=transcript,
        )
        if transcript is not None and claim.session_id is not None
        else None
    )
    assessment = session_continuity.assess_continuity(
        claim=claim,
        activity=activity,
        notify_after=timedelta(minutes=args.notify_minutes),
    )
    payload = assessment.model_dump(mode="json")
    payload["resume_offer"] = None
    payload["resume_offer_review"] = None
    store = coordination_messages.CoordinationMessageStore(
        root=coordination_messages.default_message_root(coordination_claims.CLAIMS_DIR),
        claims_dir=coordination_claims.CLAIMS_DIR,
    )
    if args.send_resume_offer and assessment.action == "notify_owner":
        resolved_sender = coordination_claims.resolve_session_id(args.agent, args.sender_session_id)
        if resolved_sender != args.sender_session_id:
            raise ValueError("resume offer sender must equal the current native session")
        request = session_continuity.build_resume_offer_request(
            assessment=assessment,
            sender_session_id=resolved_sender,
            project=args.project,
            scope=args.scope,
            next_action=claim.next_action or "reach the next verified checkpoint",
        )
        sent = store.send(request, require_live_claim=False)
        payload["resume_offer"] = {
            "message_id": sent.message.message_id,
            "recipient_session_id": sent.message.recipient_session_id,
            "idempotent_replay": sent.idempotent_replay,
            "delivery_mode": sent.local_host_delivery_capability.delivery_mode,
            "delivery_enforced": (
                sent.local_host_delivery_capability.delivery_mode == "enforced"
            ),
            "message_path": sent.message_path,
        }
    if args.resume_offer_message_id:
        status = store.status(
            coordination_messages.MessageStatusRequest(
                message_id=args.resume_offer_message_id
            )
        )
        review = session_continuity.assess_resume_offer(
            assessment=assessment,
            status=status,
            successor_after=timedelta(minutes=args.successor_after_minutes),
        )
        payload["resume_offer_review"] = review.model_dump(mode="json")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['activity_state']}: {payload['reason_code']}; "
            f"action={payload['action']}; transfer_eligible=false"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
