#!/usr/bin/env python3
"""Archive one orphaned session tracker: no live claim, no worktree, no branch touched."""

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

from enforced_planning import session_lifecycle


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tracker-path",
        required=True,
        help="Exact session tracker under ~/.claude/coordination/sessions/ to archive.",
    )
    parser.add_argument(
        "--tracker-sha256",
        required=True,
        help="Exact SHA-256 of the tracker bytes; archival refuses on any mismatch.",
    )
    parser.add_argument(
        "--note",
        help="Durable reason recorded in the archived tracker.",
    )
    parser.add_argument(
        "--allow-unique-branch-commits",
        action="store_true",
        help=(
            "Explicitly authorize archiving a tracker whose branch still holds commits with no "
            "patch-equivalent on the canonical default branch. The branch itself is never deleted."
        ),
    )
    parser.add_argument(
        "--archive-root",
        help="Override the archive root; defaults to the sessions-archive tree beside sessions/.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = session_lifecycle.archive_orphaned_session_tracker(
        tracker_path=args.tracker_path,
        expected_tracker_sha256=args.tracker_sha256,
        note=args.note,
        allow_unique_branch_commits=args.allow_unique_branch_commits,
        archive_root=args.archive_root,
    )
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['action']}: {payload['project']}:{payload['scope']} "
            f"branch={payload['branch_state']} branch_action={payload['branch_action']} "
            f"archived_to={payload['archived_tracker_path']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
