#!/usr/bin/env python3
"""Poll the canonical coordination mailbox for one live agent session."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _find_repo_root() -> Path:
    """Locate the installed package root for source and governed-repo layouts."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            return parent
    raise RuntimeError("Unable to locate repo root containing enforced_planning/")


REPO_ROOT = _find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning import coordination_messages  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse an agent-drivable inbox poll command."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--no-observe", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Poll, optionally append observation evidence, and render the notice."""

    args = parse_args(argv)
    try:
        notice = coordination_messages.poll_session_inbox(
            agent=args.agent,
            project=args.project,
            session_id=args.session_id,
            observe=not args.no_observe,
            claims_dir=args.claims_dir,
            root=args.root,
        )
    except coordination_messages.CoordinationMessageError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}))
        else:
            print(f"coordination mailbox unavailable: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(notice.model_dump_json(indent=2))
    elif notice.active_count:
        print(notice.summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
