#!/usr/bin/env python3
"""Validate whether the current branch is safe to push."""

from __future__ import annotations

import argparse
import json
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

from enforced_planning import push_safety  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--project")
    parser.add_argument("--branch")
    parser.add_argument(
        "--include-active-decisions",
        action="store_true",
        help="Explicitly query agent-memory for active-decision warnings.",
    )
    parser.add_argument("--fail-on-active-decisions", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def _print_notification_line(issue: dict[str, object]) -> None:
    """Surface whether the colliding claim's owner was notified.

    The `overlapping_write_claim` block already computes and returns this in
    `details.notification` (real delivery, not just detection -- see
    push_safety.py), but the real pre-push hook invokes this script without
    `--json`, so a pusher who actually hits a real conflict never saw it: the
    ``--json`` payload had it, the terminal output a person actually reads
    did not. Found via `/audit` 2026-09-14.
    """

    details = issue.get("details")
    notification = details.get("notification") if isinstance(details, dict) else None
    if notification is None:
        return
    if not notification.get("attempted"):
        return
    if notification.get("ok"):
        print(f"       notified the other lane's owner via {notification.get('route')}")
    else:
        print(f"       could not notify the other lane's owner: {notification.get('error')}")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = push_safety.evaluate_push_safety(
        args.repo_root,
        project=args.project,
        branch=args.branch,
        include_active_decisions=args.include_active_decisions,
        fail_on_active_decisions=args.fail_on_active_decisions,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"push-check: branch={payload['branch']} default={payload['default_branch']} "
            f"issues={len(payload['issues'])} warnings={len(payload['warnings'])}"
        )
        for issue in payload["issues"]:
            print(f"ERROR {issue['code']}: {issue['message']}")
            _print_notification_line(issue)
        for warning in payload["warnings"]:
            print(f"WARN  {warning['code']}: {warning['message']}")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
