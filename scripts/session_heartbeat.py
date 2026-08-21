#!/usr/bin/env python3
"""Refresh heartbeat state for one sanctioned session."""

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

from enforced_planning import session_lifecycle  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the session selector and optional phase refresh."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope")
    parser.add_argument("--branch")
    parser.add_argument("--session-id")
    parser.add_argument("--current-phase")
    parser.add_argument(
        "--outcome-selected",
        action="store_true",
        help="Require exact selected outcome admission before heartbeat mutation.",
    )
    parser.add_argument(
        "--outcome-admission-receipt-path",
        type=Path,
        help="Override the append-only outcome-admission receipt stream.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Refresh the session heartbeat and expose its mailbox state."""
    args = parse_args(argv)
    try:
        payload = session_lifecycle.heartbeat_session(
            agent=args.agent,
            project=args.project,
            session_id=args.session_id,
            scope=args.scope,
            branch=args.branch,
            current_phase=args.current_phase,
            outcome_selected=args.outcome_selected,
            **(
                {"outcome_admission_receipt_path": args.outcome_admission_receipt_path}
                if args.outcome_admission_receipt_path is not None
                else {}
            ),
        )
    except session_lifecycle.OutcomeAdmissionDeniedError as exc:
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "code": "outcome_admission_denied",
                            "message": str(exc),
                        },
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"heartbeat: updated {payload['updated_count']} claims "
            f"for session {payload['session_id']} at {payload['heartbeat_at']}"
        )
        print(payload["coordination_mailbox"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
