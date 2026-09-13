#!/usr/bin/env python3
"""Revalidate and safely apply one accepted Plan 110 blocker disposition."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError


def _bootstrap_package() -> Path:
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            sys.path.insert(0, str(parent))
            return parent
    import importlib.util

    if importlib.util.find_spec("enforced_planning") is not None:
        for ancestor in current.parents:
            if (ancestor / ".git").exists():
                return ancestor
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


REPOSITORY_ROOT = _bootstrap_package()

from enforced_planning.blocker_policy import BlockerDecisionInputV1, BlockerDecisionResultV1
from enforced_planning.session_lifecycle import apply_blocker_disposition


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-json", required=True, help="Source BlockerDecisionInputV1 JSON file.")
    parser.add_argument("--decision-json", required=True, help="Accepted BlockerDecisionResultV1 JSON file.")
    parser.add_argument("--agent", required=True)
    parser.add_argument("--project", required=True)
    parser.add_argument("--root-scope", required=True)
    parser.add_argument("--session-id", help="Exact native session; ambient resolution is preferred.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        decision_input = BlockerDecisionInputV1.model_validate_json(
            Path(args.input_json).read_text(encoding="utf-8")
        )
        expected = BlockerDecisionResultV1.model_validate_json(
            Path(args.decision_json).read_text(encoding="utf-8")
        )
        result = apply_blocker_disposition(
            decision_input=decision_input,
            expected_result=expected,
            repository_root=REPOSITORY_ROOT,
            agent=args.agent,
            project=args.project,
            root_scope=args.root_scope,
            actor_session_id=args.session_id,
        )
        import json

        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return 0
    except (OSError, ValidationError, ValueError) as exc:
        print(f"blocker disposition application failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
