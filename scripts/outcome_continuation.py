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

from enforced_planning.outcome_continuation import (
    ContinuationError,
    evaluate_scenario,
    load_scenario,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the operator-facing JSON CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    evaluate = subparsers.add_parser("evaluate", help="Evaluate one continuation scenario")
    evaluate.add_argument("--scenario", required=True, help="Path to OutcomeContinuationScenarioV1 JSON")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Emit one deterministic result or one stable validation error."""

    args = parse_args(argv)
    try:
        scenario = load_scenario(args.scenario)
        result = evaluate_scenario(scenario)
    except (ContinuationError, ValidationError) as exc:
        if isinstance(exc, ContinuationError):
            error = exc.to_dict()
        else:
            error = {"code": "scenario_validation_failed", "message": str(exc)}
        print(json.dumps({"ok": False, "error": error}, indent=2, sort_keys=True))
        return 2
    print(result.model_dump_json(indent=2))
    return 0 if result.decision.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
