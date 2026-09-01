#!/usr/bin/env python3
"""Own or publish one exact protected coordination approval.

The command never changes branch protection and never merges a pull request.
`publish` supports the owner-status compatibility mode only; App publication
belongs in the coordinator-only credential service.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import ValidationError

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from enforced_planning import coordination_claims
from enforced_planning.coordination_approval import (
    DEFAULT_STATE_ROOT,
    ApprovalLeaseStore,
    ApprovalProducerLeaseV1,
    ApprovalTargetV1,
    CoordinationApprovalError,
    LiveApprovalFactsV1,
    PublishedApprovalV1,
    build_publication_intent,
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
        f"repos/{target.repository}/branches/{target.base_branch}/protection",
    ])
    if not isinstance(pr, dict) or not isinstance(protection, dict):
        raise CoordinationApprovalError("GitHub live facts are malformed")
    required = protection.get("required_status_checks")
    enforce_admins = protection.get("enforce_admins")
    if not isinstance(required, dict) or not isinstance(enforce_admins, dict):
        raise CoordinationApprovalError("branch protection omits required-check or admin enforcement facts")
    checks = required.get("checks")
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
        strict_required_checks=required.get("strict"),
        enforce_admins=enforce_admins.get("enabled"),
    )


def _native_owner(agent: str, explicit_session_id: str | None, target: ApprovalTargetV1) -> str:
    session_id = coordination_claims.resolve_session_id(agent, explicit_session_id)
    if not session_id:
        raise CoordinationApprovalError("unable to resolve current native session")
    try:
        coordination_claims.validate_native_session_binding(
            agent, session_id, require_native_marker=True
        )
    except ValueError as exc:
        raise CoordinationApprovalError(str(exc)) from exc
    _require_live_claim_session(target, session_id)
    return session_id


def _require_live_claim_session(target: ApprovalTargetV1, session_id: str) -> None:
    if os.environ.get("ENFORCED_PLANNING_APPROVAL_TESTING") == "1":
        return
    project = target.repository.rsplit("/", 1)[-1]
    live = coordination_claims.list_claims(project=project)
    if not any(claim.session_id == session_id for claim in live):
        raise CoordinationApprovalError(
            f"no canonical live {project} claim belongs to session {session_id}"
        )


def _publish_compatibility_status(
    target: ApprovalTargetV1, gh_command: str, publication_intent_id: str
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
        "-f", f"description=coordination-intent:{publication_intent_id}",
    ])
    if not isinstance(response, dict):
        raise CoordinationApprovalError("GitHub status response is malformed")
    status_id = response.get("id")
    return _find_compatibility_status(
        target, gh_command, publication_intent_id, expected_provider_id=status_id
    )


def _find_compatibility_status(
    target: ApprovalTargetV1, gh_command: str, publication_intent_id: str,
    *, expected_provider_id: int | None = None,
) -> PublishedApprovalV1:
    statuses = _json([
        gh_command, "api", f"repos/{target.repository}/commits/{target.head_sha}/statuses",
    ])
    if not isinstance(statuses, list):
        raise CoordinationApprovalError("GitHub status readback is malformed")
    description = f"coordination-intent:{publication_intent_id}"
    matches = [
        row for row in statuses
        if isinstance(row, dict)
        and row.get("context") == "coordination-approval"
        and row.get("target_url") == target.pr_url
        and row.get("description") == description
        and (expected_provider_id is None or row.get("id") == expected_provider_id)
    ]
    if len(matches) != 1:
        raise CoordinationApprovalError("published status was not found by exact intent provenance")
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
        publication_intent_id=publication_intent_id,
        provider_recorded_at=row.get("created_at"),
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
        "acquire", "heartbeat", "transfer", "takeover", "release", "status",
        "publish", "reconcile-publication",
    ):
        command = subparsers.add_parser(operation)
        command.add_argument("--target", type=Path, required=True)
        if operation != "status":
            command.add_argument("--agent", choices=("codex", "claude-code", "openclaw"), required=True)
            command.add_argument("--session-id")
        if operation in {"heartbeat", "transfer", "takeover", "release", "publish"}:
            command.add_argument("--expected-lease-sha256", required=True)
        if operation in {"acquire", "heartbeat", "transfer", "takeover"}:
            command.add_argument("--duration-seconds", type=int, default=900)
        if operation in {"acquire", "transfer", "takeover", "release"}:
            command.add_argument("--evidence-ref", required=True)
        if operation == "transfer":
            command.add_argument("--successor-session-id", required=True)
        if operation == "publish":
            command.add_argument("--candidate-receipt", type=Path, required=True)
        if operation == "reconcile-publication":
            command.add_argument("--publication-intent-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    testing = os.environ.get("ENFORCED_PLANNING_APPROVAL_TESTING") == "1"
    if args.state_root and args.state_root.expanduser().resolve() != DEFAULT_STATE_ROOT.resolve() and not testing:
        print(json.dumps({"ok": False, "error": "custom state roots are test-only"}), file=sys.stderr)
        return 2
    if args.gh_command != "gh" and not testing:
        print(json.dumps({"ok": False, "error": "custom GitHub commands are test-only"}), file=sys.stderr)
        return 2
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
        session_id = _native_owner(args.agent, args.session_id, item)
        if args.operation == "acquire":
            result = store.acquire(
                target=item, owner_session_id=session_id,
                duration=timedelta(seconds=args.duration_seconds),
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "heartbeat":
            result = store.heartbeat(
                target=item, owner_session_id=session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                duration=timedelta(seconds=args.duration_seconds),
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "transfer":
            _require_live_claim_session(item, args.successor_session_id)
            result = store.transfer(
                target=item, owner_session_id=session_id,
                successor_session_id=args.successor_session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                duration=timedelta(seconds=args.duration_seconds),
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "takeover":
            result = store.takeover(
                target=item, successor_session_id=session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                duration=timedelta(seconds=args.duration_seconds),
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps(_lease_payload(*result), sort_keys=True))
            return 0
        if args.operation == "release":
            receipt, receipt_path = store.release(
                target=item, owner_session_id=session_id,
                expected_lease_sha256=args.expected_lease_sha256,
                evidence_ref=args.evidence_ref,
            )
            print(json.dumps({
                "mutation_receipt": receipt.model_dump(mode="json"),
                "mutation_receipt_path": str(receipt_path),
            }, sort_keys=True))
            return 0
        if args.operation == "reconcile-publication":
            pending = [
                intent for intent in store.pending_publication_intents(item)
                if intent.intent_id == args.publication_intent_id
            ]
            if len(pending) != 1:
                raise CoordinationApprovalError("exact publication intent is not pending")
            intent = pending[0]
            if intent.publisher_session_id != session_id:
                raise CoordinationApprovalError("only the intent owner may reconcile publication")
            approval = _find_compatibility_status(item, args.gh_command, intent.intent_id)
            after = _live_facts(item, args.gh_command)
            receipt = build_publication_receipt(
                publication_intent=intent,
                published_approval=approval,
                live_facts_after=after,
            )
            receipt_path = store.complete_publication(intent=intent, receipt=receipt)
            print(json.dumps({
                "publication_receipt": receipt.model_dump(mode="json"),
                "publication_receipt_path": str(receipt_path),
            }, sort_keys=True))
            return 0

        before = _live_facts(item, args.gh_command)
        candidate_receipt_bytes = args.candidate_receipt.expanduser().resolve().read_bytes()
        lease, candidate_receipt = store.assert_publishable(
            target=item, owner_session_id=session_id,
            expected_lease_sha256=args.expected_lease_sha256,
            live_facts=before,
            candidate_receipt_bytes=candidate_receipt_bytes,
        )
        pending = store.pending_publication_intents(item)
        if pending:
            if len(pending) != 1:
                raise CoordinationApprovalError("multiple publication intents are pending")
            intent = pending[0]
            expected = build_publication_intent(
                lease=lease, publisher_session_id=session_id,
                candidate_receipt=candidate_receipt,
                live_facts_before=intent.live_facts_before,
                prepared_at=intent.prepared_at,
            )
            if expected != intent:
                raise CoordinationApprovalError("pending publication intent differs from current custody")
        else:
            intent = build_publication_intent(
                lease=lease, publisher_session_id=session_id,
                candidate_receipt=candidate_receipt,
                live_facts_before=before,
            )
            store.persist_publication_intent(intent)
        try:
            approval = _find_compatibility_status(item, args.gh_command, intent.intent_id)
        except CoordinationApprovalError:
            approval = _publish_compatibility_status(item, args.gh_command, intent.intent_id)
        after = _live_facts(item, args.gh_command)
        receipt = build_publication_receipt(
            publication_intent=intent, published_approval=approval,
            live_facts_after=after,
        )
        receipt_path = store.complete_publication(intent=intent, receipt=receipt)
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
