#!/usr/bin/env python3
"""CLI for the loop-engineering clean-room alpha fixture."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.cleanroom_alpha import CleanroomError
from enforced_planning.cleanroom_alpha import CleanroomSpec
from enforced_planning.cleanroom_alpha import current_git_revision
from enforced_planning.cleanroom_alpha import materialize_cleanroom
from enforced_planning.cleanroom_alpha import plan_cleanroom
from enforced_planning.cleanroom_alpha import reset_cleanroom
from enforced_planning.cleanroom_alpha import run_demo_deferred
from enforced_planning.cleanroom_alpha import status_cleanroom
from enforced_planning.cleanroom_alpha import verify_cleanroom


def build_parser() -> argparse.ArgumentParser:
    """Build the clean-room alpha CLI parser."""

    parser = argparse.ArgumentParser(description="Plan, apply, verify, status, and reset a clean-room alpha fixture")
    parser.add_argument("--root", default="./loop-engineering-cleanroom", help="Clean-room root path")
    parser.add_argument("--instance-id", default="cleanroom-alpha", help="Clean-room instance id")
    parser.add_argument("--component-revision", default=None, help="Immutable governance component revision")
    parser.add_argument("--projects-root", default=None, help="Projects workspace root used for isolation checks")
    parser.add_argument("--json", action="store_true", help="Emit JSON output; accepted for explicit agent calls")
    subparsers = parser.add_subparsers(dest="command")
    for command in ("plan", "apply", "verify", "status", "reset", "run-demo"):
        subparsers.add_parser(command)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the clean-room alpha CLI and return a process exit code."""

    parser = build_parser()
    args = parser.parse_args(argv)
    command = args.command or "plan"
    try:
        payload, exit_code = _run_command(args, command)
    except CleanroomError as exc:
        payload = {"operation": command, "verdict": "fail", "error": exc.to_dict()}
        exit_code = 1
    except subprocess_error_tuple() as exc:
        payload = {"operation": command, "verdict": "fail", "error": {"code": "subprocess_failed", "message": str(exc)}}
        exit_code = 1
    print(json.dumps(payload, indent=2, sort_keys=True))
    return exit_code


def _run_command(args: argparse.Namespace, command: str) -> tuple[dict[str, Any], int]:
    """Dispatch one CLI command to the importable clean-room implementation."""

    if command in {"plan", "apply"}:
        spec = _build_spec(args)
        if command == "plan":
            return plan_cleanroom(spec).to_dict(), 0
        return materialize_cleanroom(spec).to_dict(), 0
    if command == "verify":
        report = verify_cleanroom(args.root, projects_root=args.projects_root)
        return report.to_dict(), 0 if report.verdict == "pass" else 1
    if command == "status":
        return status_cleanroom(args.root).to_dict(), 0
    if command == "reset":
        report = reset_cleanroom(args.root)
        return report.to_dict(), 0 if report.verdict == "reset" else 1
    if command == "run-demo":
        return run_demo_deferred(args.root), 2
    raise CleanroomError("unknown_command", f"unknown command: {command}")


def _build_spec(args: argparse.Namespace) -> CleanroomSpec:
    """Build a clean-room spec from CLI arguments."""

    revision = args.component_revision or current_git_revision(REPO_ROOT)
    return CleanroomSpec.build(
        root=args.root,
        instance_id=args.instance_id,
        component_revision=revision,
        projects_root=args.projects_root,
    )


def subprocess_error_tuple() -> tuple[type[BaseException], ...]:
    """Return subprocess exceptions without importing subprocess into global CLI state."""

    import subprocess

    return (subprocess.CalledProcessError,)


if __name__ == "__main__":
    raise SystemExit(main())
