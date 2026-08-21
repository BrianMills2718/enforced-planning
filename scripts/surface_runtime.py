#!/usr/bin/env python3
"""Operate revision-bound canonical and preview UI surface leases."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

for candidate in Path(__file__).resolve().parents:
    if (candidate / "enforced_planning").is_dir():
        if str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
        break
else:
    import importlib.util
    if importlib.util.find_spec("enforced_planning") is None:
        raise RuntimeError("cannot locate installed enforced_planning package")

from enforced_planning.surface_runtime import (
    SurfaceRuntimeError,
    audit_surface,
    list_leases,
    start_surface,
    stop_surface,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--state-root", type=Path)
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("up")
    start.add_argument("surface_id")
    start.add_argument("--mode", choices=("canonical", "preview"), default="canonical")

    status = subparsers.add_parser("status")
    status.add_argument("--project-id")

    stop = subparsers.add_parser("down")
    stop.add_argument("surface_id")
    stop.add_argument("--lease-id")

    audit = subparsers.add_parser("audit")
    audit.add_argument("surface_id")
    audit.add_argument("--require-running", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "up":
            payload = start_surface(
                args.repo_root, args.surface_id, mode=args.mode, state_root=args.state_root
            )
        elif args.command == "status":
            payload = {
                "leases": list_leases(state_root=args.state_root, project_id=args.project_id)
            }
        elif args.command == "down":
            payload = stop_surface(
                args.repo_root,
                args.surface_id,
                lease_id=args.lease_id,
                state_root=args.state_root,
            )
        else:
            payload = audit_surface(
                args.repo_root,
                args.surface_id,
                state_root=args.state_root,
                require_running=args.require_running,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload["ok"] else 1
    except SurfaceRuntimeError as exc:
        print(f"surface-runtime: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
