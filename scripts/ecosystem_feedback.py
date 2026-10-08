#!/usr/bin/env python3
"""Record, inspect, report, and disposition portable ecosystem feedback."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, get_args

from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from enforced_planning.ecosystem_feedback import (  # noqa: E402
    DEFAULT_FEEDBACK_PATH,
    EcosystemFeedbackCreateV1,
    EcosystemFeedbackDispositionCreateV1,
    EcosystemFeedbackError,
    EcosystemFeedbackSourceV1,
    FeedbackDispositionKind,
    FeedbackScopeKind,
    FeedbackStatus,
    FeedbackType,
    disposition_ecosystem_feedback,
    list_ecosystem_feedback,
    record_ecosystem_feedback,
    report_ecosystem_feedback,
)


def _add_feedback_path(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--feedback-path",
        type=Path,
        default=DEFAULT_FEEDBACK_PATH,
        help="Append-only JSONL stream (default: %(default)s).",
    )


def _add_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--type", choices=get_args(FeedbackType))
    parser.add_argument("--scope-kind", choices=get_args(FeedbackScopeKind))
    parser.add_argument("--scope-id")
    parser.add_argument("--status", choices=get_args(FeedbackStatus))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    record = subparsers.add_parser(
        "record",
        help="Append one evidence-backed feedback record.",
    )
    record.add_argument("--type", required=True, choices=get_args(FeedbackType))
    record.add_argument(
        "--scope-kind",
        required=True,
        choices=get_args(FeedbackScopeKind),
    )
    record.add_argument("--scope-id")
    record.add_argument("--observation", required=True)
    record.add_argument("--expected-behavior")
    record.add_argument("--recommendation", required=True)
    record.add_argument(
        "--evidence-ref",
        action="append",
        required=True,
        dest="evidence_refs",
        help="Privacy-safe evidence identity; repeat for additional evidence.",
    )
    record.add_argument("--source-client", default="cli")
    record.add_argument("--source-project")
    record.add_argument("--source-task-id")
    record.add_argument("--source-session-id")
    record.add_argument("--source-working-directory")
    _add_feedback_path(record)

    listing = subparsers.add_parser(
        "list",
        help="List validated feedback views in stream order.",
    )
    _add_filters(listing)
    _add_feedback_path(listing)

    report = subparsers.add_parser(
        "report",
        help="Summarize validated feedback with stable-ID step-downs.",
    )
    _add_filters(report)
    _add_feedback_path(report)

    disposition = subparsers.add_parser(
        "disposition",
        help="Append one terminal disposition for existing feedback.",
    )
    disposition.add_argument("--feedback-id", required=True)
    disposition.add_argument(
        "--disposition",
        required=True,
        choices=get_args(FeedbackDispositionKind),
    )
    disposition.add_argument("--rationale", required=True)
    disposition.add_argument("--successor-ref")
    _add_feedback_path(disposition)

    return parser


def _filters(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "feedback_type": args.type,
        "scope_kind": args.scope_kind,
        "scope_id": args.scope_id,
        "status": args.status,
    }


def _render_success(*, feedback_path: Path, payload: Any) -> None:
    print(
        json.dumps(
            {
                "feedback_path": str(feedback_path),
                "payload": payload,
            },
            indent=2,
            sort_keys=True,
        )
    )


def _concise_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        details = []
        for error in exc.errors(include_url=False, include_input=False):
            location = ".".join(str(part) for part in error["loc"])
            details.append(f"{location}: {error['msg']}" if location else error["msg"])
        return "; ".join(details)
    return " ".join(str(exc).split())


def main(argv: list[str] | None = None) -> int:
    """Dispatch one feedback operation through the shared public contract."""

    args = _parser().parse_args(argv)
    try:
        feedback_path = args.feedback_path.expanduser().resolve()
        if args.command == "record":
            source = EcosystemFeedbackSourceV1(
                client=args.source_client,
                project=args.source_project,
                task_id=args.source_task_id,
                session_id=args.source_session_id,
                working_directory=args.source_working_directory,
            )
            request = EcosystemFeedbackCreateV1(
                feedback_type=args.type,
                scope_kind=args.scope_kind,
                scope_id=args.scope_id,
                observation=args.observation,
                expected_behavior=args.expected_behavior,
                recommendation=args.recommendation,
                evidence_refs=tuple(args.evidence_refs),
                source=source,
            )
            payload: Any = record_ecosystem_feedback(
                request,
                feedback_path=feedback_path,
            ).model_dump(mode="json")
        elif args.command == "list":
            payload = [
                item.model_dump(mode="json")
                for item in list_ecosystem_feedback(
                    feedback_path=feedback_path,
                    **_filters(args),
                )
            ]
        elif args.command == "report":
            payload = report_ecosystem_feedback(
                feedback_path=feedback_path,
                **_filters(args),
            ).model_dump(mode="json")
        else:
            request = EcosystemFeedbackDispositionCreateV1(
                feedback_id=args.feedback_id,
                disposition=args.disposition,
                rationale=args.rationale,
                successor_ref=args.successor_ref,
            )
            payload = disposition_ecosystem_feedback(
                request,
                feedback_path=feedback_path,
            ).model_dump(mode="json")
    except (EcosystemFeedbackError, ValidationError, OSError, ValueError) as exc:
        print(f"Ecosystem feedback failed: {_concise_error(exc)}", file=sys.stderr)
        return 2

    _render_success(feedback_path=feedback_path, payload=payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
