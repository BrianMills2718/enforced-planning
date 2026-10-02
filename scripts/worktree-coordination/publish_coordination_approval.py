#!/usr/bin/env python3
"""Own or publish one exact protected coordination approval.

The command never changes branch protection and never merges a pull request.
`publish` supports the owner-status compatibility mode only; App publication
belongs in the coordinator-only credential service.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from enforced_planning.coordination_approval import (
    ApprovalLeaseStore,
    ApprovalProducerLeaseV1,
    ApprovalTargetV1,
    CoordinationApprovalError,
    LiveApprovalFactsV1,
    PublishedApprovalV1,
    build_publication_receipt,
    lease_sha256,
)


def _run(command: list[str]) -> str:
    result = subprocess.run(command, check=False, capture_output=True, text=True)
    if result.returncode != 0:
        raise CoordinationApprovalError(
            f"command failed ({' '.join(command[:3])}): "
            + (result.stderr or result.stdout).strip()
        )
    return result.stdout


def _json(command: list[str]) -> Any:
    try:
        return json.loads(_run(command))
    except json.JSONDecodeError as exc:
        raise CoordinationApprovalError("GitHub command returned invalid JSON") from exc


def _target(path: Path) -> ApprovalTargetV1:
    try:
        return ApprovalTargetV1.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise CoordinationApprovalError(f"invalid target file: {exc}") from exc


def _live_facts(target: ApprovalTargetV1, gh_command: str) -> LiveApprovalFactsV1:
    pr = _json([
        gh_command, "pr", "view", str(target.pr_number), "--repo", target.repository,
        "--json", "url,baseRefName,headRefOid,state",
    ])
    protection = _json([
        gh_command, "api",
        f"repos/{target.repository}/branches/{target.base_branch}/protection/required_status_checks",
    ])
    if not isinstance(pr, dict) or not isinstance(protection, dict):
        raise CoordinationApprovalError("GitHub live facts are malformed")
    checks = protection.get("checks")
    if not isinstance(checks, list):
        raise CoordinationApprovalError("branch protection does not expose check bindings")
    bindings = [
        row for row in checks
        if isinstance(row, dict)
        and row.get("context") in {"coordination-approval", "coordination-approval-frozen"}
    ]
    if len(bindings) != 1:
        raise CoordinationApprovalError("branch protection must expose one coordination approval binding")
    binding = bindings[0]
    return LiveApprovalFactsV1(
        observed_at=datetime.now(UTC),
        repository=target.repository,
        pr_number=target.pr_number,
        pr_url=pr.get("url"),
        base_branch=pr.get("baseRefName"),
        head_sha=pr.get("headRefOid"),
        pr_state=pr.get("state"),
        protection_context=binding.get("context"),
        protected_app_id=binding.get("app_id"),
    )


def _publish_compatibility_status(
    target: ApprovalTargetV1, gh_command: str
) -> PublishedApprovalV1:
    if target.approval_mode != "compatibility_status":
        raise CoordinationApprovalError(
            "github_app publication requires the coordinator-only App service"
        )
    response = _json([
        gh_command, "api", "--method", "POST",
        f"repos/{target.repository}/statuses/{target.head_sha}",
        "-f", "state=success", "-f", "context=coordination-approval",
        "-f", f"target_url={target.pr_url}",
        "-f", "description=Exact-head coordination review approved",
    ])
    if not isinstance(response, dict):
        raise CoordinationApprovalError("GitHub status response is malformed")
    status_id = response.get("id")
    statuses = _json([
        gh_command, "api", f"repos/{target.repository}/commits/{target.head_sha}/statuses",
    ])
    if not isinstance(statuses, list):
        raise CoordinationApprovalError("GitHub status readback is malformed")
    matches = [row for row in statuses if isinstance(row, dict) and row.get("id") == status_id]
    if len(matches) != 1:
        raise CoordinationApprovalError("published status was not found by exact provider ID")
    row = matches[0]
    creator = row.get("creator")
    return PublishedApprovalV1(
        kind="commit_status",
        context=row.get("context"),
        head_sha=target.head_sha,
        state=str(row.get("state", "")).upper(),
        creator_login=creator.get("login") if isinstance(creator, dict) else None,
        target_url=row.get("target_url"),
        app_id=None,
        provider_record_id=row.get("id"),
    )


def _lease_payload(
    lease: ApprovalProducerLeaseV1, receipt: Any, receipt_path: Path
) -> dict[str, Any]:
    return {
        "lease": lease.model_dump(mode="json"),
        "lease_sha256": lease_sha256(lease),
        "mutation_receipt": receipt.model_dump(mode="json"),
        "mutation_receipt_path": str(receipt_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--gh-command", default="gh")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in (
        "acquire", "heartbeat", "transfer", "takeover", "release", "status", "publish"
    ):
        command = subparsers.add_parser(operation)
        command.add_argument("--target", type=Path, required=True)
        if operation != "status":
            command.add_argument("--session-id", required=True)
        if operation in {"heartbeat", "transfer", "takeover", "release", "publish"}:
            command.add_argument("--expected-lease-sha256", required=True)
        if operation in {"acquire", "heartbeat", "transfer", "takeover"}:
            command.add_argument("--duration-seconds", type=int, default=900)
        if operation in {"acquire", "transfer", "takeover", "release"}:
            command.add_argument("--evidence-ref", required=True)
        if operation == "transfer":
            command.add_argument("--successor-session-id", required=True)
        if operation == "publish":
            command.add_argument("--repository-owner", required=True)
            command.add_argument("--candidate-receipt", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = ApprovalLeaseStore(args.state_root) if args.state_root else ApprovalLeaseStore()
    try:
        item = _target(args.target.expanduser().resolve())
        if args.operation == "status":
            current = store.current(item)
            print(json.dumps({
                "lease": current.model_dump(mode="json") if current else None,
                "lease_sha256": lease_sha256(current) if current else None,
            }, sort_keys=True))
            return 0
        if args.operation == "acquire":
            result = store.acquire(
                target=item, owner_session_id=args.session_id,
                duration=timedelta(seconds=args.duration_seconds),
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "heartbeat":
            result = store.heartbeat(
                target=item, owner_session_id=args.session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                duration=timedelta(seconds=args.duration_seconds),
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "transfer":
            result = store.transfer(
                target=item, owner_session_id=args.session_id,
                successor_session_id=args.successor_session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                duration=timedelta(seconds=args.duration_seconds),
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "takeover":
            result = store.takeover(
                target=item, successor_session_id=args.session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                duration=timedelta(seconds=args.duration_seconds),
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "release":
            receipt, receipt_path = store.release(
                target=item, owner_session_id=args.session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps({
                "mutation_receipt": receipt.model_dump(mode="json"),
                "mutation_receipt_path": str(receipt_path),
            }, sort_keys=True))
            return 0
        before = _live_facts(item, args.gh_command)
        candidate_receipt_bytes = args.candidate_receipt.expanduser().resolve().read_bytes()
        lease = store.assert_publishable(
            target=item, owner_session_id=args.session_id,
            expected_lease_sha256=args.expected_lease_sha256,
            live_facts=before,
            candidate_receipt_bytes=candidate_receipt_bytes,
        )
        approval = _publish_compatibility_status(item, args.gh_command)
        after = _live_facts(item, args.gh_command)
        receipt = build_publication_receipt(
            lease=lease, publisher_session_id=args.session_id,
            live_facts_before=before, published_approval=approval,
            live_facts_after=after, repository_owner=args.repository_owner,
        )
        receipt_path = store.persist_publication(receipt)
        print(json.dumps({
            "publication_receipt": receipt.model_dump(mode="json"),
            "publication_receipt_path": str(receipt_path),
        }, sort_keys=True))
        return 0
    except (CoordinationApprovalError, ValidationError, OSError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
