#!/usr/bin/env python3
"""Evaluate explicit first-consumer outcome-admission boundaries."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pydantic import ValidationError

from enforced_planning.outcome_admission import (
    OutcomeAdmissionBootstrapV1,
    evaluate_first_consumer_bootstrap,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bootstrap = subparsers.add_parser(
        "bootstrap",
        help="Check the fixed source-repository allocation bootstrap scope.",
    )
    bootstrap.add_argument("--plan", type=int, required=True)
    bootstrap.add_argument("--write-path", action="append", default=[])
    bootstrap.add_argument(
        "--ordinary-denied",
        action="store_true",
        help="Retain an upstream ordinary-authority denial for precedence testing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command != "bootstrap":
            raise ValueError(f"unsupported outcome-admission command: {args.command}")
        result = evaluate_first_consumer_bootstrap(
            OutcomeAdmissionBootstrapV1(
                plan_number=args.plan,
                write_paths=tuple(args.write_path),
                ordinary_allowed=not args.ordinary_denied,
            )
        )
    except (ValidationError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "outcome_admission_request_invalid",
                        "message": str(exc),
                    },
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    payload = result.model_dump(mode="json")
    payload["ok"] = result.decision.disposition == "allow"
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
