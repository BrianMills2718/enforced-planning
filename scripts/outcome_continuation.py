#!/usr/bin/env python3
"""Evaluate one strict outcome-continuation scenario as machine-readable JSON."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError


def _add_repo_root_to_path() -> None:
    """Make the source package importable from a checkout."""

    for parent in Path(__file__).resolve().parents:
        if (parent / "enforced_planning").is_dir():
            sys.path.insert(0, str(parent))
            return
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


_add_repo_root_to_path()

from enforced_planning.coordination_claims import CLAIMS_DIR
from enforced_planning.outcome_continuation import (
    ContinuationError,
    evaluate_scenario,
    load_scenario,
)
from enforced_planning.outcome_selection import (
    OutcomeSelectionError,
    restart_selected_outcome_for_session,
    select_outcome_for_session,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the operator-facing JSON CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate", help="Evaluate one continuation scenario")
    evaluate.add_argument("--scenario", required=True, help="Path to OutcomeContinuationScenarioV1 JSON")
    select = subparsers.add_parser("select", help="Bind one immutable scenario to an exact live session")
    select.add_argument("--scenario", required=True, type=Path)
    select.add_argument("--execution-authority", required=True)
    select.add_argument("--agent", required=True, choices=("codex", "claude-code", "openclaw"))
    select.add_argument("--project", required=True)
    select.add_argument("--scope", required=True)
    select.add_argument("--session-id")
    select.add_argument("--claims-dir", type=Path, default=CLAIMS_DIR)
    restart = subparsers.add_parser(
        "restart",
        help="Replace stalled selected state through one exact RestartDeltaV1",
    )
    restart.add_argument("--successor-scenario", required=True, type=Path)
    restart.add_argument("--restart-delta", required=True, type=Path)
    restart.add_argument("--agent", required=True, choices=("codex", "claude-code", "openclaw"))
    restart.add_argument("--project", required=True)
    restart.add_argument("--scope", required=True)
    restart.add_argument("--session-id")
    restart.add_argument("--claims-dir", type=Path, default=CLAIMS_DIR)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Emit one deterministic result or one stable validation error."""

    args = parse_args(argv)
    try:
        if args.command == "evaluate":
            scenario = load_scenario(args.scenario)
            result = evaluate_scenario(scenario)
        elif args.command == "select":
            selection = select_outcome_for_session(
                agent=args.agent,
                project=args.project,
                scope=args.scope,
                session_id=args.session_id,
                execution_authority_ref=args.execution_authority,
                scenario_path=args.scenario,
                claims_dir=args.claims_dir,
            )
        else:
            restart = restart_selected_outcome_for_session(
                agent=args.agent,
                project=args.project,
                scope=args.scope,
                session_id=args.session_id,
                successor_scenario_path=args.successor_scenario,
                restart_delta_path=args.restart_delta,
                claims_dir=args.claims_dir,
            )
    except (ContinuationError, OutcomeSelectionError, ValidationError, ValueError) as exc:
        if isinstance(exc, (ContinuationError, OutcomeSelectionError)):
            error = exc.to_dict()
        else:
            error = {"code": "input_validation_failed", "message": str(exc)}
        print(json.dumps({"ok": False, "error": error}, indent=2, sort_keys=True))
        return 2
    if args.command == "select":
        print(selection.model_dump_json(indent=2))
        return 0
    if args.command == "restart":
        print(restart.model_dump_json(indent=2))
        return 0
    print(result.model_dump_json(indent=2))
    return 0 if result.decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
