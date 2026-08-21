#!/usr/bin/env python3
"""Evaluate a Plan 110 ready queue or blocker request without changing state."""

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
    raise RuntimeError("Unable to locate repository root containing enforced_planning/")


REPOSITORY_ROOT = _bootstrap_package()

from enforced_planning import coordination_claims
from enforced_planning.blocker_policy import (
    BlockerDecisionInputV1,
    ClaimQueueSnapshotV1,
    evaluate_blocker_request,
    evaluate_ready_queue,
)


def _read_text(path: str) -> str:
    return sys.stdin.read() if path == "-" else Path(path).read_text(encoding="utf-8")


def _canonical_claim_snapshots(goal_scope: str) -> tuple[ClaimQueueSnapshotV1, ...]:
    """Project live canonical claims into the queue's immutable input contract."""

    if "#" not in goal_scope:
        raise ValueError("canonical CLI goal scope must be a project-qualified plan identity")
    project = goal_scope.split("#", 1)[0]
    snapshots: list[ClaimQueueSnapshotV1] = []
    claims = coordination_claims.list_claims(project)
    for claim in claims:
        if claim.session_id is None:
            raise ValueError(f"live canonical claim {claim.scope} has no session identity")
        health_issues = coordination_claims.coordination_health_issues(
            claim,
            active_claims=claims,
        )
        liveness_issues = coordination_claims.claim_liveness_issues(claim)
        if health_issues or liveness_issues:
            issues = [*health_issues, *liveness_issues]
            raise ValueError(f"live canonical claim {claim.scope} is not current and healthy: " + ", ".join(issues))
        snapshots.append(
            ClaimQueueSnapshotV1(
                session_id=claim.session_id,
                status=claim.status,
                goal_or_graph_scope=claim.plan_ref or claim.scope,
                work_unit_id=claim.work_unit_id,
                work_graph_path=claim.work_graph_path,
                work_graph_sha256=claim.work_graph_sha256,
                claimed_paths=tuple(claim.write_paths),
            )
        )
    return tuple(snapshots)


def _require_native_session(session_id: str) -> None:
    """Bind public decisions to the exact agent runtime invoking the CLI."""

    agent, separator, _identity = session_id.partition(":")
    if not separator or not agent:
        raise ValueError("public CLI session identity must be agent-qualified")
    native_session_id = coordination_claims.resolve_session_id(agent)
    if native_session_id is None:
        raise ValueError(f"public CLI cannot resolve a native {agent!r} session identity")
    coordination_claims.validate_native_session_binding(agent, session_id)
    if native_session_id != session_id:
        raise ValueError(
            f"public CLI session identity {session_id!r} does not match native runtime {native_session_id!r}"
        )


def _require_requesting_claim_binding(
    *,
    claim_snapshots: tuple[ClaimQueueSnapshotV1, ...],
    session_id: str,
    goal_scope: str,
    work_graph_ref: str,
    expected_sha256: str,
) -> None:
    """Require public evaluation authority from one exact live canonical claim."""

    matches = [
        claim
        for claim in claim_snapshots
        if claim.session_id == session_id
        and claim.goal_or_graph_scope == goal_scope
        and claim.work_graph_path == work_graph_ref
        and claim.work_graph_sha256 == expected_sha256
    ]
    if len(matches) != 1:
        raise ValueError(
            "public CLI requires exactly one healthy invoking-session claim bound to "
            "the requested project-qualified plan, graph path, and graph digest"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)

    queue = subparsers.add_parser("queue", help="Evaluate one exact work graph and optional claim snapshot.")
    queue.add_argument(
        "--work-graph-ref",
        required=True,
        help="Portable repository-relative identity used by claims and receipts.",
    )
    queue.add_argument("--expected-sha256", required=True)
    queue.add_argument("--session-id", required=True)
    queue.add_argument("--goal-scope", required=True)

    decide = subparsers.add_parser("decide", help="Produce one deterministic blocker disposition.")
    decide.add_argument(
        "--input-json",
        required=True,
        help="Source-bound BlockerDecisionInputV1 JSON file, or '-' for stdin.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.operation == "queue":
            _require_native_session(args.session_id)
            claims = _canonical_claim_snapshots(args.goal_scope)
            _require_requesting_claim_binding(
                claim_snapshots=claims,
                session_id=args.session_id,
                goal_scope=args.goal_scope,
                work_graph_ref=args.work_graph_ref,
                expected_sha256=args.expected_sha256,
            )
            result = evaluate_ready_queue(
                repository_root=REPOSITORY_ROOT,
                work_graph_ref_path=args.work_graph_ref,
                expected_sha256=args.expected_sha256,
                session_id=args.session_id,
                goal_or_graph_scope=args.goal_scope,
                claim_snapshots=claims,
            )
            print(result.model_dump_json(indent=2))
            return 3 if result.coverage == "unavailable" else 0

        decision_input = BlockerDecisionInputV1.model_validate_json(_read_text(args.input_json))
        if decision_input.claim_snapshots:
            raise ValueError("public CLI rejects caller-supplied claim snapshots")
        if decision_input.mailbox_evidence or decision_input.request.mailbox_dependency:
            raise ValueError("public CLI rejects caller-supplied mailbox state until a canonical loader owns it")
        _require_native_session(decision_input.request.session_id)
        claims = _canonical_claim_snapshots(decision_input.request.claim_scope)
        _require_requesting_claim_binding(
            claim_snapshots=claims,
            session_id=decision_input.request.session_id,
            goal_scope=decision_input.request.claim_scope,
            work_graph_ref=decision_input.work_graph_ref_path,
            expected_sha256=decision_input.expected_work_graph_sha256,
        )
        decision_input = decision_input.model_copy(update={"claim_snapshots": claims})
        result = evaluate_blocker_request(decision_input, repository_root=REPOSITORY_ROOT)
        print(result.model_dump_json(indent=2))
        return 3 if result.ready_queue.coverage == "unavailable" else 0
    except (OSError, ValidationError, ValueError) as exc:
        print(f"blocker evaluation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
