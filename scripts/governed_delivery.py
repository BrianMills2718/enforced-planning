#!/usr/bin/env python3
"""Prepare, probe, checkpoint, and verify configured governed tasks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _add_repo_root_to_path() -> None:
    """Make the source package importable from a checkout."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "enforced_planning").is_dir():
            sys.path.insert(0, str(parent))
            return
    import importlib.util
    if importlib.util.find_spec("enforced_planning") is not None:
        return
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


_add_repo_root_to_path()

from enforced_planning.governed_delivery import (
    GovernedDeliveryError,
    prepare_governed_task,
    probe_governed_task,
    record_course_checkpoint,
    verify_governed_task,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the agent-facing JSON CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Prepare a governed failing task baseline")
    prepare.add_argument("--cleanroom-root", required=True)
    prepare.add_argument("--framework-root", default=str(Path(__file__).resolve().parents[1]))
    prepare.add_argument("--profile", help="Optional consumer-owned governed-task profile JSON")

    probe = subparsers.add_parser("probe", help="Execute checks and return the next control decision")
    probe.add_argument("--task-root", required=True)

    checkpoint = subparsers.add_parser("checkpoint", help="Record a changed assumption and tactic")
    checkpoint.add_argument("--task-root", required=True)
    checkpoint.add_argument("--prior-assumption", required=True)
    checkpoint.add_argument("--changed-assumption", required=True)
    checkpoint.add_argument("--next-tactic", required=True)

    verify = subparsers.add_parser("verify", help="Run the independent terminal verifier")
    verify.add_argument("--task-root", required=True)
    verify.add_argument("--agent-session-id")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Run one command and emit only machine-readable JSON."""

    args = parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_governed_task(
                cleanroom_root=args.cleanroom_root,
                framework_root=args.framework_root,
                profile_path=args.profile,
            )
        elif args.command == "probe":
            result = probe_governed_task(args.task_root)
        elif args.command == "checkpoint":
            result = record_course_checkpoint(
                args.task_root,
                prior_assumption=args.prior_assumption,
                changed_assumption=args.changed_assumption,
                next_tactic=args.next_tactic,
            )
        else:
            result = verify_governed_task(
                args.task_root,
                agent_session_id=args.agent_session_id,
            )
    except GovernedDeliveryError as exc:
        print(json.dumps({"ok": False, "error": exc.to_dict()}, indent=2, sort_keys=True))
        return 2
    print(result.model_dump_json(indent=2))
    if getattr(result, "verdict", None) == "fail" or getattr(result, "decision", None) == "course_correction_required":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
