#!/usr/bin/env python3
"""Narrow one live claim to strict descendant write paths."""

from __future__ import annotations

import argparse
import importlib.util
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
    if importlib.util.find_spec("enforced_planning") is not None:
        return
    raise RuntimeError("Unable to locate local or upstream enforced_planning support")


_bootstrap_package()

from enforced_planning import claim_mutation_receipts, session_lifecycle  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the exact owner/session-bound narrowing contract."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", required=True, choices=["codex", "claude-code", "openclaw"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--write-path", action="append", required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Narrow the claim and render its committed projection/receipt evidence."""

    args = parse_args(argv)
    try:
        payload = session_lifecycle.narrow_session_claim(
            agent=args.agent,
            project=args.project,
            scope=args.scope,
            session_id=args.session_id,
            write_paths=args.write_path,
        )
    except claim_mutation_receipts.MutationAuditError as exc:
        failure = {"ok": False, **exc.to_dict()}
        if args.json:
            print(json.dumps(failure, indent=2, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 2
    except ValueError as exc:
        failure = {"ok": False, "error_code": "claim_narrow_denied", "message": str(exc)}
        if args.json:
            print(json.dumps(failure, indent=2, sort_keys=True))
        else:
            print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"ok": True, **payload}, indent=2, sort_keys=True))
    else:
        print(
            f"narrowed {args.project}:{args.scope}: "
            f"{', '.join(payload['old_write_paths'])} -> {', '.join(payload['new_write_paths'])}"
        )
        print(payload["coordination_mailbox"]["summary"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
