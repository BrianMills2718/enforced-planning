#!/usr/bin/env python3
"""Record canonical selected-outcome completion for a native Stop gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _bootstrap_package() -> None:
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
            from _upstream_enforced_planning import bootstrap_upstream_package

            bootstrap_upstream_package(current)
            return
    raise RuntimeError("Unable to locate the enforced_planning runtime package")


_bootstrap_package()

from enforced_planning.outcome_completion import (
    OutcomeCompletionError,
    record_selected_outcome_completion_for_session,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude-code"), default="codex")
    parser.add_argument("--project", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--session-id")
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--projection", type=Path, required=True)
    parser.add_argument("--proposal", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = record_selected_outcome_completion_for_session(
            agent=args.agent,
            project=args.project,
            scope=args.scope,
            session_id=args.session_id,
            claims_dir=args.claims_dir,
            projection_path=args.projection,
            proposal_path=args.proposal,
        )
    except OutcomeCompletionError as exc:
        print(json.dumps(exc.to_dict(), sort_keys=True), file=sys.stderr)
        return 2
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
