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

from enforced_planning import coordination_claims
from enforced_planning.outcome_admission import (
    DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
    OutcomeAdmissionBootstrapV1,
    bootstrap_admission_result,
    evaluate_selected_claim_admission,
    record_outcome_admission,
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
    bootstrap.add_argument(
        "--receipt-path",
        type=Path,
        default=DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
    )
    selected = subparsers.add_parser(
        "selected",
        help="Derive admission from one exact live selected claim.",
    )
    selected.add_argument("--agent", required=True)
    selected.add_argument("--project", required=True)
    selected.add_argument("--scope", required=True)
    selected.add_argument("--session-id", required=True)
    selected.add_argument(
        "--boundary",
        required=True,
        choices=("session_start", "session_resume", "heartbeat", "prewrite", "commit"),
    )
    selected.add_argument("--target-path")
    selected.add_argument("--renewal", action="store_true")
    selected.add_argument("--ordinary-denied", action="store_true")
    selected.add_argument("--claims-dir", type=Path)
    selected.add_argument(
        "--receipt-path",
        type=Path,
        default=DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
    )
    return parser


def _selected_claim(args: argparse.Namespace) -> coordination_claims.ClaimRecord:
    matches = [
        claim
        for claim in coordination_claims.list_claims(
            args.project,
            claims_dir=args.claims_dir,
        )
        if claim.agent == args.agent
        and claim.scope == args.scope
        and claim.session_id == args.session_id
    ]
    if len(matches) != 1:
        raise ValueError(
            "selected admission requires exactly one live claim for "
            f"agent={args.agent}, project={args.project}, scope={args.scope}, "
            f"session_id={args.session_id}; found {len(matches)}"
        )
    return matches[0]


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "bootstrap":
            result = bootstrap_admission_result(
                OutcomeAdmissionBootstrapV1(
                    plan_number=args.plan,
                    write_paths=tuple(args.write_path),
                    ordinary_allowed=not args.ordinary_denied,
                )
            )
        elif args.command == "selected":
            if args.boundary == "prewrite" and not args.target_path:
                raise ValueError("selected prewrite admission requires --target-path")
            result = evaluate_selected_claim_admission(
                _selected_claim(args),
                boundary=args.boundary,
                ordinary_allowed=not args.ordinary_denied,
                renewal=args.renewal,
                target_path=args.target_path,
            )
        else:
            raise ValueError(f"unsupported outcome-admission command: {args.command}")
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

    receipt = record_outcome_admission(
        result,
        receipt_path=args.receipt_path,
    )
    payload = result.model_dump(mode="json")
    if result.bootstrap_evidence is not None:
        payload["allowed_paths"] = list(result.bootstrap_evidence.allowed_paths)
        payload["rejected_paths"] = list(result.bootstrap_evidence.rejected_paths)
    payload["receipt"] = receipt.model_dump(mode="json")
    payload["ok"] = result.decision.disposition == "allow"
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
