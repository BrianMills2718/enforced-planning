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

from enforced_planning import coordination_claims, session_continuity  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--notify-minutes", type=int, default=15)
    parser.add_argument("--transfer-observe-minutes", type=int, default=30)
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
        transfer_observe_after=timedelta(minutes=args.transfer_observe_minutes),
    )
    payload = assessment.model_dump(mode="json")
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
