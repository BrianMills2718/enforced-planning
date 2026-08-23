"""Session lifecycle operations for sanctioned worktree flows.

The session contract lives partly on the canonical claim and partly in the
linked tracker artifact. This module keeps those surfaces in sync without
inventing a second coordination registry.
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    coordination_messages,
    doc_authority,
    outcome_admission,
    outcome_selection,
    push_safety,
    session_contracts,
    surface_runtime,
)
from enforced_planning.worktree_paths import resolve_canonical_repo_root

WORKTREE_LIFECYCLE_CONFIG_PATH = Path(__file__).with_name("worktree_lifecycle.yaml")


class SessionTransferIncompleteError(RuntimeError):
    """A cross-file session transfer failed and exact rollback was incomplete."""

    code = "session_transfer_incomplete"


class OutcomeAdmissionDeniedError(PermissionError):
    """One recorded outcome denial raised before lifecycle mutation."""

    code = "outcome_admission_denied"


def _poll_mailbox(*, agent: str, project: str, session_id: str) -> dict[str, Any]:
    """Inject canonical mailbox state into a shared lifecycle response."""

    notice = coordination_messages.poll_session_inbox(
        agent=agent,
        project=project,
        session_id=session_id,
        observe=True,
    )
    return notice.model_dump(mode="json")


def _load_worktree_lifecycle_policy(path: Path) -> tuple[str, frozenset[str], frozenset[str], frozenset[str]]:
    """Load and validate the configurable disposition vocabulary."""

    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise ValueError(f"Invalid worktree lifecycle config schema: {path}")
    dispositions = raw.get("dispositions")
    if not isinstance(dispositions, dict):
        raise ValueError(f"Missing dispositions mapping in worktree lifecycle config: {path}")

    merged = dispositions.get("merged")
    if not isinstance(merged, str) or not merged.strip():
        raise ValueError(f"Worktree lifecycle config requires a non-empty merged disposition: {path}")

    def _string_set(field: str) -> frozenset[str]:
        values = dispositions.get(field)
        if not isinstance(values, list) or not values:
            raise ValueError(f"Worktree lifecycle config requires a non-empty {field} list: {path}")
        if any(not isinstance(value, str) or not value.strip() for value in values):
            raise ValueError(f"Worktree lifecycle config {field} must contain strings: {path}")
        normalized = frozenset(value.strip().lower() for value in values)
        if len(normalized) != len(values):
            raise ValueError(f"Worktree lifecycle config {field} contains blanks or duplicates: {path}")
        return normalized

    non_closeable = _string_set("non_closeable")
    recovery_required = _string_set("recovery_required")
    discard_authorized = _string_set("discard_requires_authorization")
    groups = ({merged.strip().lower()}, set(non_closeable), set(recovery_required), set(discard_authorized))
    flattened = set().union(*groups)
    if sum(len(group) for group in groups) != len(flattened):
        raise ValueError(f"Worktree lifecycle disposition groups overlap: {path}")
    return merged.strip().lower(), non_closeable, recovery_required, discard_authorized


(
    MERGED_DISPOSITION,
    NON_CLOSEABLE_DISPOSITIONS,
    RECOVERY_REQUIRED_DISPOSITIONS,
    DISCARD_AUTHORIZATION_DISPOSITIONS,
) = _load_worktree_lifecycle_policy(WORKTREE_LIFECYCLE_CONFIG_PATH)
WORKTREE_DISPOSITIONS = frozenset(
    {MERGED_DISPOSITION}
    | set(NON_CLOSEABLE_DISPOSITIONS)
    | set(RECOVERY_REQUIRED_DISPOSITIONS)
    | set(DISCARD_AUTHORIZATION_DISPOSITIONS)
)
MAILBOX_CLOSEOUT_DISPOSITIONS = frozenset({"deferred"})


@dataclass(frozen=True)
class CloseoutPreflight:
    """Validated branch state that licenses one closeout mutation sequence."""

    disposition: str
    branch_exists: bool
    default_branch: str | None
    merged_to_default: bool | None
    default_remote_ref: str | None
    default_branch_pushed: bool | None
    merge_commit: str | None
    merge_evidence: str | None
    recovery_ref: str | None
    force_delete_branch: bool

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe representation for CLI payloads and audit records."""

        return asdict(self)


def _tracker_sha256(path: Path) -> str:
    """Return the exact byte digest used to bind missing-worktree closeout."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def _exact_tracker_candidates(claim: coordination_claims.ClaimRecord) -> list[Path]:
    """Return trackers matching every preserved claim identity field."""

    if not claim.session_id:
        raise ValueError("Missing-worktree reconciliation requires a canonical session ID")
    project = claim.primary_project()
    if not project:
        raise ValueError("Missing-worktree reconciliation requires a canonical project")
    safe_session_id = re.sub(r"[^a-zA-Z0-9._-]+", "-", claim.session_id)
    root = (
        Path(claim.tracker_path).expanduser().parent
        if claim.tracker_path
        else session_contracts.DEFAULT_SESSION_TRACKERS_DIR / project
    )
    matches: list[Path] = []
    for path in sorted(root.glob(f"{claim.agent}__{project}__{safe_session_id}__*.yaml")):
        payload = session_contracts.read_session_tracker(path)
        contract = payload.get("claim")
        if not isinstance(contract, dict):
            raise ValueError(f"Session tracker at {path} is missing claim metadata")
        if (
            contract.get("agent") == claim.agent
            and contract.get("project") == project
            and contract.get("scope") == claim.scope
            and contract.get("session_id") == claim.session_id
        ):
            matches.append(path)
    return matches


def _validate_missing_worktree_reconciliation(
    *,
    claim: coordination_claims.ClaimRecord,
    expected_tracker_sha256: str | None,
) -> dict[str, str]:
    """Fail closed before reconciling one preserved lane with no worktree."""

    if claim.status != coordination_claims.SESSION_ENDED_STATUS:
        raise ValueError(
            f"Missing-worktree reconciliation requires an exact session_ended claim; found {claim.status!r}."
        )
    if not claim.worktree_path:
        raise ValueError("Missing-worktree reconciliation requires a recorded worktree path")
    recorded_worktree = Path(claim.worktree_path).expanduser()
    if recorded_worktree.exists():
        raise ValueError(
            "Missing-worktree reconciliation rejects an existing recorded worktree; "
            "use ordinary sanctioned closeout instead."
        )
    expected_digest = (expected_tracker_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("Missing-worktree reconciliation requires --tracker-sha256 as a SHA-256 digest.")
    trackers = _exact_tracker_candidates(claim)
    if not trackers:
        raise ValueError("Missing-worktree reconciliation requires one exact session tracker")
    if len(trackers) != 1:
        rendered = ", ".join(str(path) for path in trackers)
        raise ValueError("Ambiguous exact session trackers for missing-worktree reconciliation: " + rendered)
    tracker = trackers[0]
    if claim.tracker_path and Path(claim.tracker_path).expanduser() != tracker:
        raise ValueError("Claim tracker path does not match the exact reconciliation tracker")
    actual_digest = _tracker_sha256(tracker)
    if actual_digest != expected_digest:
        raise ValueError(
            "Missing-worktree reconciliation tracker digest mismatch; preserve the lane and regenerate evidence."
        )
    return {
        "schema_version": "1.0",
        "claim_status_before": claim.status,
        "recorded_worktree_path": str(recorded_worktree),
        "tracker_path": str(tracker),
        "tracker_sha256": actual_digest,
        "filesystem_action": "not_attempted_absent_recorded_worktree",
    }


def _resolve_active_mailbox_for_closeout(
    *,
    claim: coordination_claims.ClaimRecord,
    mailbox_disposition: str | None,
    mailbox_note: str | None,
) -> dict[str, Any]:
    """Require an explicit durable disposition for active recipient messages.

    Closeout retains the exact recipient session in the claim record, including
    for a preserved ``session_ended`` lane.  It may therefore write an
    acknowledgement only for that same recipient, never for another session.
    This prevents a closed session from leaving actionable mailbox messages
    replaying indefinitely while preserving the existing recipient boundary.
    """

    recipient_session_id = claim.session_id
    if not recipient_session_id:
        raise ValueError("Cannot close a claimed lane without a canonical session ID for mailbox reconciliation")
    claims_dir = coordination_claims.CLAIMS_DIR.expanduser().resolve()
    store = coordination_messages.CoordinationMessageStore(
        root=coordination_messages.default_message_root(claims_dir),
        claims_dir=claims_dir,
    )
    inbox = store.poll(
        coordination_messages.PollMessagesRequest(
            current_session_id=recipient_session_id,
            project=claim.primary_project(),
            observe=False,
        ),
        require_live_claim=False,
    )
    active = [view for view in inbox.messages if not view.expired and not view.acknowledged]
    if not active:
        return {"mailbox_disposition": None, "mailbox_message_ids": []}

    normalized_disposition = mailbox_disposition.strip().lower() if mailbox_disposition else None
    if normalized_disposition is None:
        message_ids = ", ".join(view.message.message_id for view in active)
        raise ValueError(
            "Cannot close a session with active mailbox message(s): "
            f"{message_ids}. Read and acknowledge each message, or pass "
            "--mailbox-disposition deferred with --mailbox-note to record a durable closeout deferral."
        )
    if normalized_disposition not in MAILBOX_CLOSEOUT_DISPOSITIONS:
        supported = ", ".join(sorted(MAILBOX_CLOSEOUT_DISPOSITIONS))
        raise ValueError(
            f"Unsupported mailbox closeout disposition '{mailbox_disposition}'. Supported values: {supported}"
        )
    normalized_note = mailbox_note.strip() if mailbox_note else ""
    if not normalized_note:
        raise ValueError("--mailbox-note is required when deferring active mailbox messages at closeout")

    acknowledgement_paths: list[str] = []
    for view in active:
        acknowledgement = store.acknowledge(
            coordination_messages.AcknowledgeMessageRequest(
                current_session_id=recipient_session_id,
                message_id=view.message.message_id,
                disposition="deferred",
                note=normalized_note,
            ),
            require_live_claim=False,
        )
        acknowledgement_paths.append(acknowledgement.receipt_path)
    return {
        "mailbox_disposition": normalized_disposition,
        "mailbox_message_ids": [view.message.message_id for view in active],
        "mailbox_acknowledgement_paths": acknowledgement_paths,
    }


def _split_cli_values(values: list[str] | None) -> list[str]:
    """Normalize repeated or delimiter-packed CLI values into one clean list."""

    items: list[str] = []
    for value in values or []:
        for chunk in value.replace(";", "|").split("|"):
            text = chunk.strip()
            if text:
                items.append(text)
    return items


def _claim_path(agent: str, project: str, scope: str) -> Path:
    """Return the canonical YAML path for one claim."""

    return coordination_claims.CLAIMS_DIR / coordination_claims._claim_filename(agent, project, scope)


def _load_claim_payload(agent: str, project: str, scope: str) -> dict[str, Any] | None:
    """Load one claim payload if it exists."""

    path = _claim_path(agent, project, scope)
    if not path.exists():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"Claim file at {path} must be a YAML mapping")
    return raw


def _write_claim_payload(path: Path, payload: dict[str, Any]) -> None:
    """Persist one normalized claim payload through the canonical atomic writer."""

    coordination_claims._atomic_write_claim(path, payload)


def _atomic_restore_bytes(path: Path, content: bytes) -> None:
    """Atomically restore exact preflight bytes for a failed two-file transfer."""

    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=resolved.parent,
            prefix=f".{resolved.name}.",
            suffix=".rollback.tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, resolved)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _rollback_outcome_session_transfer(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    successor_session_id: str,
    claim_bytes: bytes,
    tracker_path: Path,
    tracker_bytes: bytes,
) -> None:
    """Restore the exact claim and tracker bytes after a failed transfer."""

    with (
        coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR),
        session_contracts.session_tracker_lock(tracker_path),
    ):
        current = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        if not isinstance(current, dict) or current.get("session_id") != successor_session_id:
            raise ValueError("resumed claim changed before transfer rollback; refusing to overwrite current ownership")
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        _atomic_restore_bytes(claim_file, claim_bytes)
        if tracker_path.read_bytes() != tracker_bytes:
            _atomic_restore_bytes(tracker_path, tracker_bytes)
        _projection_path, projection_digest_after = coordination_claims.refresh_prewrite_authority_projection(
            coordination_claims.CLAIMS_DIR
        )
        coordination_claims.record_claim_mutation(
            operation="session_upsert",
            claims_dir=coordination_claims.CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=claim.primary_project(),
            target_scope=claim.scope,
            target_claim_path=claim_file,
            session_id=claim.session_id,
            projection_digest_after=projection_digest_after,
        )


def _apply_claim_payload_updates(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    updates: dict[str, Any],
    operation: claim_mutation_receipts.MutationOperation = "session_upsert",
    expected_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply one lifecycle mutation and refresh its projection under one lock."""

    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        current = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        if not isinstance(current, dict):
            raise ValueError(f"Claim file at {claim_file} must be a YAML mapping")
        for field, expected in (expected_fields or {}).items():
            if current.get(field) != expected:
                raise ValueError(
                    f"Claim at {claim_file} changed while preparing {operation}; retry from current ownership state"
                )
        current.update(updates)
        _write_claim_payload(claim_file, current)
        _projection_path, projection_digest_after = coordination_claims.refresh_prewrite_authority_projection(
            coordination_claims.CLAIMS_DIR
        )
        coordination_claims.record_claim_mutation(
            operation=operation,
            claims_dir=coordination_claims.CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=claim.primary_project(),
            target_scope=claim.scope,
            target_claim_path=claim_file,
            session_id=current.get("session_id"),
            projection_digest_after=projection_digest_after,
        )
    return current


def _upsert_session_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    intent: str,
    plan_ref: str | None,
    repo_root: str,
    worktree_path: str,
    branch: str,
    session_id: str,
    broader_goal: str,
    session_name: str,
    tracker_path: str,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    parent_scope: str | None = None,
    work_graph_path: str | None = None,
    work_unit_id: str | None = None,
    start_revision: str | None = None,
    ttl_hours: float = coordination_claims.DEFAULT_TTL_HOURS,
    allow_parallel: bool = False,
    staged_reservation: coordination_claims.ClaimRecord | None = None,
) -> str:
    """Create or update the compact claim-side session contract metadata."""

    coordination_claims.validate_native_session_binding(agent, session_id)
    path = _claim_path(agent, project, scope)
    now = datetime.now(timezone.utc)
    existing_payload = _load_claim_payload(agent, project, scope)
    if existing_payload is None:
        ok, message = coordination_claims.create_claim(
            agent=agent,
            project=project,
            scope=scope,
            intent=intent,
            plan_ref=plan_ref,
            claim_type=claim_type or "program",
            write_paths=write_paths,
            read_paths=read_paths,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            session_id=session_id,
            session_name=session_name,
            broader_goal=broader_goal,
            tracker_path=tracker_path,
            parent_scope=parent_scope,
            work_graph_path=work_graph_path,
            work_unit_id=work_unit_id,
            start_point=start_revision or "HEAD",
            ttl_hours=ttl_hours,
            allow_parallel=allow_parallel,
            require_native_session_binding=True,
        )
        if not ok:
            raise ValueError(message)
        return "created"

    with coordination_claims.claim_registry_lock():
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        refreshed_payload = _load_claim_payload(agent, project, scope)
        if refreshed_payload is None:
            raise ValueError(f"Claim at {path} disappeared during session activation; retry session start")
        existing = coordination_claims.normalize_claim(
            refreshed_payload,
            source_file=str(path),
        )
        if existing is None:
            raise ValueError(f"Existing claim at {path} is invalid")
        if staged_reservation is not None:
            if existing != staged_reservation:
                raise ValueError(
                    f"Claim at {path} changed after selection-pending validation; refusing tracker attachment"
                )
            if existing.tracker_path is not None:
                raise ValueError(
                    f"Claim at {path} already links a tracker; selection-pending activation is no longer valid"
                )
        if existing.agent != agent:
            raise ValueError(f"Claim at {path} belongs to {existing.agent}, not {agent}")
        if existing.session_id and existing.session_id != session_id:
            raise ValueError(f"Claim at {path} belongs to session {existing.session_id}, not {session_id}")

        effective_claim_type = claim_type or existing.claim_type
        effective_write_paths = existing.write_paths if write_paths is None else write_paths
        effective_read_paths = existing.read_paths if read_paths is None else read_paths
        effective_parent_scope = existing.parent_scope if parent_scope is None else parent_scope
        effective_work_graph_path = existing.work_graph_path if work_graph_path is None else work_graph_path
        effective_work_unit_id = existing.work_unit_id if work_unit_id is None else work_unit_id
        if start_revision is not None and existing.start_revision not in {None, start_revision}:
            raise ValueError(f"Claim at {path} retains start revision {existing.start_revision}, not {start_revision}")
        effective_start_revision = existing.start_revision or start_revision
        work_graph_sha256 = existing.work_graph_sha256
        approval_revisions = existing.approval_revisions
        if effective_write_paths and coordination_claims.requires_work_graph(plan_ref):
            if existing.start_revision is None and existing.tracker_path is not None:
                raise ValueError(
                    f"Legacy plan-bound claim at {path} already has a session tracker but no "
                    "start revision; refusing to invent historical revision custody. Close and "
                    "recreate the lane from a verified revision, or use an explicit recovery "
                    "migration that preserves the original evidence."
                )
            if not effective_work_graph_path or not effective_work_unit_id:
                raise ValueError("Plan-bound write ownership requires --work-graph and --work-unit-id")
            work_graph_sha256, approval_revisions, resolved_start_revision = (
                coordination_claims.resolve_canonical_work_unit_binding(
                    repo_root=repo_root,
                    plan_ref=plan_ref,
                    work_graph_path=effective_work_graph_path,
                    work_unit_id=effective_work_unit_id,
                    start_point=effective_start_revision or "HEAD",
                )
            )
            if effective_start_revision is not None and resolved_start_revision != effective_start_revision:
                raise ValueError("session upsert resolved a different start revision than the existing claim")
            effective_start_revision = resolved_start_revision
            if existing.tracker_path is None:
                coordination_claims.validate_start_revision_targets(
                    repo_root=repo_root,
                    start_revision=effective_start_revision,
                    branch=branch,
                    worktree_path=worktree_path,
                    require_branch=True,
                    require_worktree=True,
                )
        candidate = coordination_claims.build_candidate_claim(
            agent=agent,
            project=project,
            scope=scope,
            intent=intent,
            plan_ref=plan_ref,
            claim_type=effective_claim_type,
            write_paths=effective_write_paths,
            read_paths=effective_read_paths,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            session_id=session_id,
            session_name=session_name,
            broader_goal=broader_goal,
            tracker_path=tracker_path,
            parent_scope=effective_parent_scope,
            work_graph_path=effective_work_graph_path,
            work_unit_id=effective_work_unit_id,
            work_graph_sha256=work_graph_sha256,
            approval_revisions=approval_revisions,
            start_revision=effective_start_revision,
            parallel_root_authorized=(allow_parallel or existing.parallel_root_authorized),
        )
        coordination_claims.validate_claim_hierarchy_for_creation(
            candidate,
            active_claims=coordination_claims.check_claims(project),
        )
        coordination_claims.validate_session_root_for_creation(
            candidate,
            active_claims=coordination_claims.check_claims(),
        )
        coordination_claims.validate_claim_for_creation(candidate)
        conflict_result = coordination_claims.evaluate_claim(
            candidate,
            active_claims=coordination_claims.check_claims(project),
        )
        if conflict_result.hard_conflicts:
            formatted = "; ".join(
                f"{item.other_agent} ({item.other_scope}: {', '.join(item.overlapping_write_paths)})"
                for item in conflict_result.hard_conflicts
            )
            raise ValueError(
                f"CONFLICT: existing-session update would overlap active write ownership in "
                f"{project!r} — {formatted}. Narrow the requested write paths or coordinate "
                "with the current owner before refreshing the claim."
            )

        expires_at = existing.expires_at or (now + timedelta(hours=ttl_hours)).isoformat()
        progress_payload: dict[str, str | None] = {}
        if not any(field in refreshed_payload for field in coordination_claims.PROGRESS_FIELD_NAMES):
            initial_progress = coordination_claims.build_progress_event(
                progress_kind="claim_started",
                evidence_ref=plan_ref or scope,
                next_action=intent,
                progress_at=now,
            )
            progress_payload = coordination_claims._progress_event_payload(initial_progress)
        payload = {
            **refreshed_payload,
            "agent": agent,
            "project": project,
            "projects": [project],
            "scope": scope,
            "intent": intent,
            "plan_ref": plan_ref,
            "repo_root": repo_root,
            "worktree_path": worktree_path,
            "branch": branch,
            "session_id": session_id,
            "session_name": session_name,
            "broader_goal": broader_goal,
            "tracker_path": tracker_path,
            "status": "active",
            "heartbeat_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "claimed_at": existing.claimed_at or now.isoformat(),
            "expires_at": expires_at,
            "claim_type": effective_claim_type,
            "write_paths": effective_write_paths,
            "read_paths": effective_read_paths,
            "parent_scope": effective_parent_scope,
            "work_graph_path": effective_work_graph_path,
            "work_unit_id": effective_work_unit_id,
            "work_graph_sha256": work_graph_sha256,
            "approval_revisions": list(approval_revisions),
            "schema_version": candidate.schema_version,
            "parallel_root_authorized": candidate.parallel_root_authorized,
            **progress_payload,
        }
        if effective_start_revision is not None:
            payload["start_revision"] = effective_start_revision
        else:
            payload.pop("start_revision", None)
        _write_claim_payload(path, payload)
        _projection_path, projection_digest_after = coordination_claims.refresh_prewrite_authority_projection(
            coordination_claims.CLAIMS_DIR
        )
        coordination_claims.record_claim_mutation(
            operation="session_upsert",
            claims_dir=coordination_claims.CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=path,
            session_id=session_id,
            projection_digest_after=projection_digest_after,
        )
    return "updated"


def _iter_matching_live_claims(
    *,
    agent: str | None = None,
    project: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
) -> list[coordination_claims.ClaimRecord]:
    """Return live claims filtered to one bounded session scope."""

    claims = coordination_claims.check_claims(project)
    filtered: list[coordination_claims.ClaimRecord] = []
    for claim in claims:
        if agent and claim.agent != agent:
            continue
        if project and project not in claim.projects:
            continue
        if scope and claim.scope != scope:
            continue
        if branch and claim.branch != branch:
            continue
        filtered.append(claim)
    return filtered


def _single_matching_live_claim(
    *,
    agent: str,
    project: str,
    scope: str,
) -> coordination_claims.ClaimRecord:
    """Return one live claim for a bounded lane or fail loud."""

    claims = _iter_matching_live_claims(agent=agent, project=project, scope=scope)
    if not claims:
        raise ValueError(f"No live claim found for {agent} → {project}:{scope}")
    if len(claims) > 1:
        raise ValueError(f"Multiple live claims found for {agent} → {project}:{scope}")
    return claims[0]


def _record_required_outcome_admission(
    result: outcome_admission.OutcomeAdmissionResultV1,
    *,
    receipt_path: Path,
) -> dict[str, Any]:
    """Record one required admission and fail before lifecycle mutation on deny."""

    receipt = outcome_admission.record_outcome_admission(
        result,
        receipt_path=receipt_path,
    )
    if result.decision.disposition != "allow":
        detail = f": {result.resolution_error_message}" if result.resolution_error_message is not None else ""
        raise OutcomeAdmissionDeniedError(
            f"Outcome admission denied ({result.decision.reason_code}); receipt {receipt.receipt_id}{detail}"
        )
    return receipt.model_dump(mode="json")


def _record_selection_pending_activation(
    result: outcome_admission.SelectionPendingActivationResultV1,
    *,
    receipt_path: Path,
) -> dict[str, Any]:
    """Record the narrow pre-selection tracker bootstrap without calling it allow."""

    receipt = outcome_admission.record_selection_pending_activation(
        result,
        outcome_receipt_path=receipt_path,
    )
    if (
        result.disposition != "defer"
        or result.reason_code != "selection_pending"
        or result.evidence is None
    ):
        detail = f": {result.resolution_error_message}" if result.resolution_error_message is not None else ""
        raise OutcomeAdmissionDeniedError(
            f"Outcome admission denied ({result.reason_code}); receipt {receipt.receipt_id}{detail}"
        )
    return receipt.model_dump(mode="json")


def _require_staged_activation_arguments_match(
    claim: coordination_claims.ClaimRecord,
    *,
    agent: str,
    project: str,
    scope: str,
    intent: str,
    plan_ref: str | None,
    repo_root: str,
    worktree_path: str,
    branch: str,
    session_id: str,
    session_name: str | None,
    broader_goal: str,
    claim_type: str | None,
    write_paths: list[str] | None,
    read_paths: list[str] | None,
    parent_scope: str | None,
    work_graph_path: str | None,
    work_unit_id: str | None,
    start_revision: str | None,
    allow_parallel: bool,
) -> None:
    """Reject any attempt to turn tracker attachment into claim replacement."""

    requested = session_contracts.SessionContract.build(
        agent=agent,
        project=project,
        scope=scope,
        intent=intent,
        plan_ref=plan_ref,
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch=branch,
        session_id=session_id,
        broader_goal=broader_goal,
        session_name=session_name,
        start_revision=start_revision or claim.start_revision,
    )
    requested_write_paths = (
        claim.write_paths
        if write_paths is None
        else [coordination_claims._normalize_repo_path(path) for path in write_paths]
    )
    requested_read_paths = (
        claim.read_paths
        if read_paths is None
        else [coordination_claims._normalize_repo_path(path) for path in read_paths]
    )
    existing_session_name = session_contracts.validate_session_name(
        session_name=claim.session_name or "",
        broader_goal=claim.broader_goal or "",
    )
    requested_fields: dict[str, object] = {
        "agent": requested.agent,
        "project": requested.project,
        "scope": requested.scope,
        "intent": requested.intent,
        "plan_ref": requested.plan_ref,
        "repo_root": requested.repo_root,
        "worktree_path": requested.worktree_path,
        "branch": requested.branch,
        "session_id": requested.session_id,
        "session_name": requested.session_name,
        "broader_goal": requested.broader_goal,
        "claim_type": claim_type or claim.claim_type,
        "write_paths": requested_write_paths,
        "read_paths": requested_read_paths,
        "parent_scope": claim.parent_scope if parent_scope is None else parent_scope,
        "work_graph_path": claim.work_graph_path if work_graph_path is None else work_graph_path,
        "work_unit_id": claim.work_unit_id if work_unit_id is None else work_unit_id,
        "start_revision": requested.start_revision,
        "parallel_root_authorized": allow_parallel or claim.parallel_root_authorized,
    }
    existing_fields: dict[str, object] = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "intent": claim.intent,
        "plan_ref": claim.plan_ref,
        "repo_root": claim.repo_root,
        "worktree_path": claim.worktree_path,
        "branch": claim.branch,
        "session_id": claim.session_id,
        "session_name": existing_session_name,
        "broader_goal": claim.broader_goal,
        "claim_type": claim.claim_type,
        "write_paths": claim.write_paths,
        "read_paths": claim.read_paths,
        "parent_scope": claim.parent_scope,
        "work_graph_path": claim.work_graph_path,
        "work_unit_id": claim.work_unit_id,
        "start_revision": claim.start_revision,
        "parallel_root_authorized": claim.parallel_root_authorized,
    }
    mismatches = sorted(
        name for name, value in requested_fields.items() if existing_fields[name] != value
    )
    if mismatches:
        raise ValueError(
            "selection-pending activation may attach only a tracker; caller changed: "
            + ", ".join(mismatches)
        )


def _claim_status(claim: coordination_claims.ClaimRecord) -> str:
    """Return the current persisted status string for one claim."""

    return claim.status


def _recovery_action_for_claim(
    claim: coordination_claims.ClaimRecord,
    *,
    active_claims: list[coordination_claims.ClaimRecord] | None = None,
    now: datetime | None = None,
) -> str:
    """Return the operator action implied by one claim's lifecycle state."""

    health_status = coordination_claims.claim_runtime_status(
        claim,
        active_claims=active_claims,
        now=now,
    )
    if claim.status == "handoff":
        return "resume_or_finish_handoff"
    if claim.status == coordination_claims.SESSION_ENDED_STATUS:
        return "resume_take_over_or_close_preserved_lane"
    if health_status == "stale":
        return "resume_or_abandon_or_prune"
    if health_status == "stalled":
        return "record_progress_or_handoff"
    if health_status == "weak":
        progress_issues = coordination_claims.claim_progress_issues(claim, now=now)
        if any(issue != "stalled_progress_lease" for issue in progress_issues):
            return "repair_progress_contract"
        if active_claims and coordination_claims.claim_hierarchy_issues(
            claim,
            active_claims=active_claims,
        ):
            return "repair_claim_hierarchy"
        return "repair_session_contract"
    return "continue"


def _worktree_is_clean(worktree_path: str) -> tuple[bool, str]:
    """Return whether one worktree has a clean git status."""

    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=worktree_path,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return (not result.stdout.strip(), result.stdout.strip())


def _claim_record_any_status(
    *,
    agent: str,
    project: str,
    scope: str,
) -> tuple[coordination_claims.ClaimRecord, dict[str, Any], Path]:
    """Load one claim regardless of current lifecycle status."""

    claim_file = _claim_path(agent, project, scope)
    payload = _load_claim_payload(agent, project, scope)
    if payload is None:
        raise ValueError(f"Claim file missing for {agent} → {project}:{scope}")
    claim = coordination_claims.normalize_claim(payload, source_file=str(claim_file))
    if claim is None:
        raise ValueError(f"Claim file invalid for {agent} → {project}:{scope}")
    return claim, payload, claim_file


def _resolve_claim_repo_root(claim: coordination_claims.ClaimRecord) -> Path:
    """Return the canonical repo root for one claim."""

    if claim.repo_root:
        return resolve_canonical_repo_root(Path(claim.repo_root).expanduser())
    if claim.worktree_path:
        return resolve_canonical_repo_root(Path(claim.worktree_path).expanduser())
    raise ValueError(f"Claim {claim.scope} is missing repo_root and worktree_path")


def _cwd_inside(path: Path) -> bool:
    """Return whether the current shell cwd is inside the target path."""

    try:
        current_dir = Path(os.getcwd()).resolve()
    except OSError:
        return False
    try:
        current_dir.relative_to(path.resolve())
        return True
    except ValueError:
        return False


def _branch_exists(repo_root: Path, branch: str) -> bool:
    """Return whether one local branch ref exists."""

    result = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _ref_exists(repo_root: Path, ref: str) -> bool:
    """Return whether one Git ref resolves to a commit."""

    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _is_ancestor(repo_root: Path, ancestor_ref: str, descendant_ref: str) -> bool:
    """Return whether ``ancestor_ref`` is integrated into ``descendant_ref``."""

    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor_ref, descendant_ref],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


def _patch_without_blob_identity(patch: bytes) -> bytes:
    """Remove only full-index blob IDs while preserving the complete patch body."""

    return b"".join(line for line in patch.splitlines(keepends=True) if not line.startswith(b"index "))


def _squash_merge_matches_branch(
    repo_root: Path,
    *,
    branch_ref: str,
    merge_commit: str,
    default_ref: str,
) -> bool:
    """Prove a one-parent merge commit carries exactly the task branch patch."""

    if not _ref_exists(repo_root, merge_commit) or not _is_ancestor(repo_root, merge_commit, default_ref):
        return False
    parents = subprocess.run(
        ["git", "rev-list", "--parents", "-n", "1", merge_commit],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    parent_fields = parents.stdout.strip().split()
    if parents.returncode != 0 or len(parent_fields) != 2:
        return False
    merge_parent = parent_fields[1]
    merge_base = subprocess.run(
        ["git", "merge-base", branch_ref, merge_parent],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if merge_base.returncode != 0 or not merge_base.stdout.strip():
        return False

    def patch(left: str, right: str) -> bytes | None:
        result = subprocess.run(
            ["git", "diff", "--binary", "--full-index", "--no-renames", left, right],
            cwd=str(repo_root),
            capture_output=True,
            check=False,
        )
        return _patch_without_blob_identity(result.stdout) if result.returncode == 0 else None

    branch_patch = patch(merge_base.stdout.strip(), branch_ref)
    merged_patch = patch(merge_parent, merge_commit)
    return branch_patch is not None and branch_patch == merged_patch


def _validate_closeout_preflight(
    *,
    repo_root: Path,
    branch: str | None,
    disposition: str,
    disposition_reason: str | None,
    recovery_ref: str | None,
    merge_commit: str | None,
    allow_discard_unique: bool,
    delete_branch: bool,
) -> CloseoutPreflight:
    """Validate merge or explicit recovery evidence before any closeout mutation."""

    normalized_disposition = disposition.strip().lower()
    if normalized_disposition not in WORKTREE_DISPOSITIONS:
        supported = ", ".join(sorted(WORKTREE_DISPOSITIONS))
        raise ValueError(f"Unsupported worktree disposition '{disposition}'. Supported values: {supported}")
    if normalized_disposition in NON_CLOSEABLE_DISPOSITIONS:
        raise ValueError(
            f"Disposition '{normalized_disposition}' does not permit session-close; keep or hand off the lane instead."
        )
    if not branch:
        raise ValueError("session-close requires a branch for merge/disposition validation")

    branch_exists = _branch_exists(repo_root, branch)
    if not branch_exists:
        return CloseoutPreflight(
            disposition=normalized_disposition,
            branch_exists=False,
            default_branch=None,
            merged_to_default=None,
            default_remote_ref=None,
            default_branch_pushed=None,
            merge_commit=None,
            merge_evidence=None,
            recovery_ref=recovery_ref,
            force_delete_branch=False,
        )

    default_branch = push_safety.resolve_default_branch(repo_root)
    if not default_branch:
        raise ValueError(
            "Unable to resolve the canonical default branch; configure origin/HEAD "
            "or create a local main/master ref before closeout."
        )
    if branch == default_branch:
        raise ValueError(f"Refusing to close the canonical default branch '{default_branch}' as a task lane.")

    branch_ref = f"refs/heads/{branch}"
    default_ref = f"refs/heads/{default_branch}"
    default_remote_ref = f"refs/remotes/origin/{default_branch}"
    remote_default_exists = _ref_exists(repo_root, default_remote_ref)
    merged_to_local_default = _is_ancestor(repo_root, branch_ref, default_ref)
    merged_to_remote_default = (
        _is_ancestor(repo_root, branch_ref, default_remote_ref) if remote_default_exists else None
    )
    merged_to_default = merged_to_remote_default if merged_to_remote_default is not None else merged_to_local_default
    default_branch_pushed = _is_ancestor(repo_root, default_ref, default_remote_ref) if remote_default_exists else None
    if normalized_disposition == MERGED_DISPOSITION:
        normalized_merge_commit = merge_commit.strip() if merge_commit else None
        merge_evidence = "branch_ancestor" if merged_to_default else None
        if not merged_to_default and normalized_merge_commit:
            canonical_default_ref = default_remote_ref if remote_default_exists else default_ref
            if _squash_merge_matches_branch(
                repo_root,
                branch_ref=branch_ref,
                merge_commit=normalized_merge_commit,
                default_ref=canonical_default_ref,
            ):
                merged_to_default = True
                merge_evidence = "squash_patch_equivalent"
        if not merged_to_default:
            if merged_to_local_default and default_branch_pushed is False:
                raise ValueError(
                    f"Canonical default branch '{default_branch}' has commits not present in "
                    f"'{default_remote_ref}'. Push the default branch before closeout."
                )
            raise ValueError(
                f"Branch '{branch}' is clean but not integrated into canonical default "
                f"branch '{default_branch}'. Merge it first or supply an explicit "
                "non-merge disposition with required evidence."
            )
        if (
            default_branch_pushed is False
            and merged_to_remote_default is not True
            and merge_evidence != "squash_patch_equivalent"
        ):
            raise ValueError(
                f"Canonical default branch '{default_branch}' has commits not present in "
                f"'{default_remote_ref}'. Push the default branch before closeout."
            )
        return CloseoutPreflight(
            disposition=normalized_disposition,
            branch_exists=True,
            default_branch=default_branch,
            merged_to_default=True,
            default_remote_ref=default_remote_ref,
            default_branch_pushed=default_branch_pushed,
            merge_commit=normalized_merge_commit,
            merge_evidence=merge_evidence,
            recovery_ref=None,
            # Git's ordinary -d check substitutes a configured feature upstream
            # for HEAD. The explicit checks above already proved the stronger
            # authority: this tip is in the pushed canonical default branch.
            force_delete_branch=delete_branch,
        )

    if normalized_disposition not in (RECOVERY_REQUIRED_DISPOSITIONS | DISCARD_AUTHORIZATION_DISPOSITIONS):
        raise ValueError(f"Disposition '{normalized_disposition}' is not a terminal closeout state.")
    if merged_to_default:
        raise ValueError(
            f"Branch '{branch}' is already integrated into '{default_branch}'; use disposition '{MERGED_DISPOSITION}'."
        )
    if not disposition_reason or not disposition_reason.strip():
        raise ValueError(f"Disposition '{normalized_disposition}' requires --disposition-reason.")

    normalized_recovery_ref = recovery_ref.strip() if recovery_ref else None
    if normalized_disposition in DISCARD_AUTHORIZATION_DISPOSITIONS:
        if not allow_discard_unique:
            raise ValueError(
                f"Disposition '{normalized_disposition}' requires --allow-discard-unique because "
                "the branch is not integrated into the canonical default branch."
            )
    elif normalized_disposition in RECOVERY_REQUIRED_DISPOSITIONS:
        if not normalized_recovery_ref:
            raise ValueError(
                f"Disposition '{normalized_disposition}' requires --recovery-ref "
                "that durably contains the task branch tip."
            )
        if normalized_recovery_ref in {branch, branch_ref}:
            raise ValueError("Recovery ref must be independent of the local task branch.")
        if not _ref_exists(repo_root, normalized_recovery_ref):
            raise ValueError(f"Recovery ref '{normalized_recovery_ref}' does not resolve to a commit.")
        if not _is_ancestor(repo_root, branch_ref, normalized_recovery_ref):
            raise ValueError(f"Recovery ref '{normalized_recovery_ref}' does not contain branch '{branch}'.")

    return CloseoutPreflight(
        disposition=normalized_disposition,
        branch_exists=True,
        default_branch=default_branch,
        merged_to_default=False,
        default_remote_ref=default_remote_ref,
        default_branch_pushed=default_branch_pushed,
        merge_commit=None,
        merge_evidence=None,
        recovery_ref=normalized_recovery_ref,
        force_delete_branch=delete_branch,
    )


def _remove_worktree_path(repo_root: Path, worktree_path: Path) -> str:
    """Remove one worktree path from a safe root-anchored control session."""

    if not worktree_path.exists():
        return "already_missing"
    if _cwd_inside(worktree_path):
        raise ValueError(
            "Cannot close a session from a shell whose cwd is inside the target worktree. "
            "Run closeout from the canonical repo root session instead."
        )
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return "removed"


def _assert_worktree_removal_access(worktree_path: Path) -> None:
    """Fail before Git mutation when the current user cannot remove a tree.

    ``git worktree remove`` can unregister a worktree before recursive
    filesystem deletion encounters a read-only cache directory.  Check the
    directory permissions that govern unlinking first so a predictable access
    failure leaves both the Git registry and coordination claim untouched.
    """

    if not worktree_path.exists():
        return
    if _cwd_inside(worktree_path):
        raise ValueError(
            "Cannot close a session from a shell whose cwd is inside the target worktree. "
            "Run closeout from the canonical repo root session instead."
        )
    directories = [worktree_path.parent]
    directories.extend(Path(root) for root, _dirs, _files in os.walk(worktree_path))
    blocked = sorted(str(path) for path in directories if not os.access(path, os.W_OK | os.X_OK))
    if blocked:
        preview = ", ".join(blocked[:5])
        if len(blocked) > 5:
            preview += f", ... ({len(blocked)} total)"
        raise PermissionError(
            "Worktree removal blocked before Git registry mutation; "
            "the current user cannot recursively remove: "
            f"{preview}. Repair or preserve those paths, then retry session-close."
        )


def _delete_branch(repo_root: Path, branch: str | None, *, force: bool = False) -> str:
    """Delete one local branch after worktree cleanup."""

    if not branch:
        return "not_requested"
    if not _branch_exists(repo_root, branch):
        return "already_missing"
    delete_flag = "-D" if force else "-d"
    result = subprocess.run(
        ["git", "branch", delete_flag, branch],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    return "deleted"


def start_session(
    *,
    agent: str,
    project: str,
    scope: str,
    intent: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    broader_goal: str,
    current_phase: str,
    plan_ref: str | None = None,
    session_id: str | None = None,
    session_name: str | None = None,
    intended_next_phases: list[str] | None = None,
    depends_on_repos: list[str] | None = None,
    requires_shared_infra_changes: bool = False,
    stop_conditions: list[str] | None = None,
    notes: str | None = None,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    parent_scope: str | None = None,
    work_graph_path: str | None = None,
    work_unit_id: str | None = None,
    start_revision: str | None = None,
    tracker_dir: Path = session_contracts.DEFAULT_SESSION_TRACKERS_DIR,
    allow_unplanned: bool = False,
    allow_parallel: bool = False,
    outcome_selected: bool = False,
    outcome_bootstrap_plan: int | None = None,
    outcome_admission_receipt_path: Path = (outcome_admission.DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH),
) -> dict[str, Any]:
    """Create or refresh the session contract plus linked tracker artifact."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    configured_outcome_mode = outcome_admission.load_outcome_admission_mode(Path(worktree_path))
    explicit_unplanned_maintenance = (
        allow_unplanned and not plan_ref and outcome_bootstrap_plan is None and not outcome_selected
    )
    selected_admission_required = outcome_selected or (
        configured_outcome_mode == "enforce_selected" and not explicit_unplanned_maintenance
    )

    if outcome_selected and outcome_bootstrap_plan is not None:
        raise ValueError("session start cannot combine selected outcome admission with allocation bootstrap")
    outcome_admission_receipts: list[dict[str, Any]] = []
    staged_reservation: coordination_claims.ClaimRecord | None = None
    if outcome_bootstrap_plan is not None:
        bootstrap = outcome_admission.bootstrap_admission_result(
            outcome_admission.OutcomeAdmissionBootstrapV1(
                plan_number=outcome_bootstrap_plan,
                write_paths=tuple(write_paths or ()),
                ordinary_allowed=True,
            )
        )
        outcome_admission_receipts.append(
            _record_required_outcome_admission(
                bootstrap,
                receipt_path=outcome_admission_receipt_path,
            )
        )
    elif selected_admission_required:
        selected_claim = _single_matching_live_claim(
            agent=agent,
            project=project,
            scope=scope,
        )
        if selected_claim.session_id != resolved_session_id:
            raise ValueError(
                "Selected outcome admission claim belongs to session "
                f"{selected_claim.session_id}, not {resolved_session_id}"
            )
        selected = outcome_admission.evaluate_selected_claim_admission(
            selected_claim,
            boundary="session_start",
            ordinary_allowed=True,
            renewal=True,
        )
        if selected.resolution_error_code == "claim_not_healthy":
            staged = outcome_admission.evaluate_selection_pending_session_activation(
                selected_claim,
            )
            if staged.reason_code == "selection_pending":
                _require_staged_activation_arguments_match(
                    selected_claim,
                    agent=agent,
                    project=project,
                    scope=scope,
                    intent=intent,
                    plan_ref=plan_ref,
                    repo_root=repo_root,
                    worktree_path=worktree_path,
                    branch=branch,
                    session_id=resolved_session_id,
                    session_name=session_name,
                    broader_goal=broader_goal,
                    claim_type=claim_type,
                    write_paths=write_paths,
                    read_paths=read_paths,
                    parent_scope=parent_scope,
                    work_graph_path=work_graph_path,
                    work_unit_id=work_unit_id,
                    start_revision=start_revision,
                    allow_parallel=allow_parallel,
                )
                staged_reservation = selected_claim
                outcome_admission_receipts.append(
                    _record_selection_pending_activation(
                        staged,
                        receipt_path=outcome_admission_receipt_path,
                    )
                )
            else:
                receipt = outcome_admission.record_selection_pending_activation(
                    staged,
                    outcome_receipt_path=outcome_admission_receipt_path,
                )
                detail = (
                    f": {staged.resolution_error_message}"
                    if staged.resolution_error_message is not None
                    else ""
                )
                raise OutcomeAdmissionDeniedError(
                    f"Outcome admission denied ({staged.reason_code}); receipt {receipt.receipt_id}{detail}"
                )
        else:
            outcome_admission_receipts.append(
                _record_required_outcome_admission(
                    selected,
                    receipt_path=outcome_admission_receipt_path,
                )
            )

    exact_existing_claims = _iter_matching_live_claims(agent=agent, project=project, scope=scope)
    if len(exact_existing_claims) > 1:
        raise ValueError(f"Multiple live claims found for {agent} → {project}:{scope}")
    existing_claim = exact_existing_claims[0] if exact_existing_claims else None
    if start_revision is None and existing_claim is not None:
        start_revision = existing_claim.start_revision
    if (
        write_paths
        and coordination_claims.requires_work_graph(plan_ref)
        and existing_claim is None
        and start_revision is None
    ):
        raise ValueError("new plan-bound session start requires one full --start-revision")

    contract = session_contracts.SessionContract.build(
        agent=agent,
        project=project,
        scope=scope,
        intent=intent,
        plan_ref=plan_ref,
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch=branch,
        session_id=resolved_session_id,
        broader_goal=broader_goal,
        session_name=session_name,
        allow_unplanned=allow_unplanned,
        start_revision=start_revision,
    )
    matching_lane_claims = [
        claim
        for claim in _iter_matching_live_claims(project=project, scope=scope)
        if claim.plan_ref == contract.plan_ref and claim.branch != branch
    ]
    if matching_lane_claims and not allow_parallel:
        branches = ", ".join(sorted({claim.branch or "-" for claim in matching_lane_claims}))
        raise ValueError(
            "A live lane already exists for the same project + plan_ref + scope "
            f"on branch(es): {branches}. Use explicit parallelism if this is intentional."
        )
    tracker_path = session_contracts.session_tracker_path(contract, tracker_dir=tracker_dir)
    contract = contract.with_tracker_path(str(tracker_path))
    tracker = session_contracts.build_session_tracker(
        contract=contract,
        current_phase=current_phase,
        intended_next_phases=intended_next_phases,
        depends_on_repos=depends_on_repos,
        requires_shared_infra_changes=requires_shared_infra_changes,
        stop_conditions=stop_conditions,
        notes=notes,
    )
    claim_slot_path = _claim_path(agent, project, scope)
    claim_bytes_before = claim_slot_path.read_bytes() if claim_slot_path.is_file() else None
    tracker_preexisting = tracker_path.is_file()
    tracker_bytes_before = tracker_path.read_bytes() if tracker_preexisting else None
    session_contracts.write_session_tracker(tracker, tracker_dir=tracker_dir)
    tracker_bytes_written = tracker_path.read_bytes()
    try:
        action = _upsert_session_claim(
            agent=agent,
            project=project,
            scope=scope,
            intent=intent,
            plan_ref=contract.plan_ref,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            session_id=resolved_session_id,
            broader_goal=contract.broader_goal,
            session_name=contract.session_name,
            tracker_path=str(tracker_path),
            claim_type=claim_type,
            write_paths=write_paths,
            read_paths=read_paths,
            parent_scope=parent_scope,
            work_graph_path=work_graph_path,
            work_unit_id=work_unit_id,
            start_revision=contract.start_revision,
            allow_parallel=allow_parallel,
            staged_reservation=staged_reservation,
        )
    except Exception as claim_error:
        try:
            claim_bytes_after = claim_slot_path.read_bytes() if claim_slot_path.is_file() else None
        except OSError as inspection_error:
            raise RuntimeError(
                "session claim update failed and claim state could not be inspected before tracker rollback: "
                f"claim={claim_error}; inspection={inspection_error}"
            ) from claim_error
        if claim_bytes_after == claim_bytes_before:
            try:
                with session_contracts.session_tracker_lock(tracker_path):
                    if tracker_path.read_bytes() != tracker_bytes_written:
                        raise ValueError("session tracker changed after this start attempt; refusing unsafe rollback")
                    if tracker_preexisting:
                        assert tracker_bytes_before is not None
                        _atomic_restore_bytes(tracker_path, tracker_bytes_before)
                    else:
                        tracker_path.unlink(missing_ok=True)
            except Exception as rollback_error:
                raise RuntimeError(
                    "session claim update failed and exact tracker rollback was incomplete: "
                    f"claim={claim_error}; rollback={rollback_error}"
                ) from claim_error
        raise
    persisted_claim = _single_matching_live_claim(
        agent=agent,
        project=project,
        scope=scope,
    )
    return {
        "action": action,
        "session_id": resolved_session_id,
        "session_name": contract.session_name,
        "broader_goal": contract.broader_goal,
        "tracker_path": str(tracker_path),
        "plan_ref": contract.plan_ref,
        "claim_type": persisted_claim.claim_type,
        "parent_scope": persisted_claim.parent_scope,
        "start_revision": persisted_claim.start_revision,
        "outcome_admission_receipts": outcome_admission_receipts,
        "coordination_mailbox": _poll_mailbox(
            agent=agent,
            project=project,
            session_id=resolved_session_id,
        ),
    }


def heartbeat_session(
    *,
    agent: str,
    project: str,
    session_id: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
    current_phase: str | None = None,
    tracker_dir: Path = session_contracts.DEFAULT_SESSION_TRACKERS_DIR,
    outcome_selected: bool = False,
    outcome_admission_receipt_path: Path = (outcome_admission.DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH),
) -> dict[str, Any]:
    """Refresh claim heartbeat state and the linked tracker timestamp."""

    outcome_admission_receipts: list[dict[str, Any]] = []
    admitted_session_id = session_id
    selected_claims: list[coordination_claims.ClaimRecord] = []
    candidate_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if outcome_selected and not candidate_session_id:
        raise ValueError("Unable to resolve a session ID for selected outcome heartbeat admission")
    if candidate_session_id:
        matching_claims = [
            claim
            for claim in _iter_matching_live_claims(
                agent=agent,
                project=project,
                scope=scope,
                branch=branch,
            )
            if claim.session_id == candidate_session_id
        ]
        if outcome_selected:
            selected_claims = matching_claims
        else:
            selected_claims = [
                claim
                for claim in matching_claims
                if (claim.worktree_path or claim.repo_root)
                and outcome_admission.load_outcome_admission_mode(Path(str(claim.worktree_path or claim.repo_root)))
                == "enforce_selected"
            ]
    if selected_claims:
        admitted_session_id = candidate_session_id
        assert admitted_session_id is not None
        coordination_claims.validate_native_session_binding(agent, admitted_session_id)
        for claim in selected_claims:
            result = outcome_admission.evaluate_selected_claim_admission(
                claim,
                boundary="heartbeat",
                ordinary_allowed=True,
                renewal=True,
            )
            outcome_admission_receipts.append(
                _record_required_outcome_admission(
                    result,
                    receipt_path=outcome_admission_receipt_path,
                )
            )
    elif outcome_selected:
        assert candidate_session_id is not None
        admitted_session_id = candidate_session_id
        raise ValueError(
            "Selected outcome heartbeat admission matched no exact live claim for "
            f"agent={agent}, project={project}, scope={scope or '<any>'}, "
            f"branch={branch or '<any>'}, session_id={admitted_session_id}."
        )

    updated_count, updated_scopes, resolved_session_id, heartbeat_at = coordination_claims.heartbeat_claims(
        agent=agent,
        project=project,
        session_id=admitted_session_id,
        scope=scope,
        branch=branch,
    )
    if updated_count == 0:
        raise ValueError(
            "Heartbeat matched no live claim for "
            f"agent={agent}, project={project}, scope={scope or '<any>'}, "
            f"branch={branch or '<any>'}, session_id={resolved_session_id}."
        )
    tracker_paths_updated: list[str] = []
    for claim in _iter_matching_live_claims(
        agent=agent,
        project=project,
        scope=scope,
        branch=branch,
    ):
        if claim.session_id != resolved_session_id:
            continue
        if not claim.tracker_path:
            continue
        path = Path(claim.tracker_path).expanduser()
        if not path.exists():
            continue
        session_contracts.update_session_tracker(
            path,
            current_phase=current_phase,
            updated_at=heartbeat_at,
        )
        tracker_paths_updated.append(str(path))
    return {
        "updated_count": updated_count,
        "updated_scopes": updated_scopes,
        "session_id": resolved_session_id,
        "heartbeat_at": heartbeat_at,
        "tracker_paths_updated": sorted(tracker_paths_updated),
        "outcome_admission_receipts": outcome_admission_receipts,
        "coordination_mailbox": _poll_mailbox(
            agent=agent,
            project=project,
            session_id=resolved_session_id,
        ),
    }


def status_sessions(
    *,
    project: str | None = None,
    agent: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
    session_id: str | None = None,
    include_ended: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return session summaries derived from claims plus linked trackers."""

    sessions: list[dict[str, Any]] = []
    observed_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    all_claims = coordination_claims.list_claims(
        include_inactive=include_ended,
    )
    if include_ended:
        all_claims = [
            claim for claim in all_claims if claim.is_live() or claim.status == coordination_claims.SESSION_ENDED_STATUS
        ]
    project_claims = [claim for claim in all_claims if not project or project in claim.projects]
    matching_claims = [
        claim
        for claim in project_claims
        if (not agent or claim.agent == agent)
        and (not scope or claim.scope == scope)
        and (not branch or claim.branch == branch)
        and (not session_id or claim.session_id == session_id)
    ]
    for claim in matching_claims:
        session_roots = [
            item
            for item in all_claims
            if item.session_id == claim.session_id and item.claim_type == "program" and not item.parent_scope
        ]
        tracker_payload: dict[str, Any] | None = None
        if claim.tracker_path:
            path = Path(claim.tracker_path).expanduser()
            if path.exists():
                tracker_payload = session_contracts.read_session_tracker(path)
        tracker_section = tracker_payload.get("tracker") if isinstance(tracker_payload, dict) else {}
        timestamps = tracker_payload.get("timestamps") if isinstance(tracker_payload, dict) else {}
        health_issues = coordination_claims.coordination_health_issues(
            claim,
            active_claims=project_claims,
        )
        progress_issues = coordination_claims.claim_progress_issues(
            claim,
            now=observed_at,
        )
        sessions.append(
            {
                "project": claim.primary_project(),
                "scope": claim.scope,
                "agent": claim.agent,
                "branch": claim.branch,
                "worktree_path": claim.worktree_path,
                "plan_ref": claim.plan_ref,
                "plan_identity": coordination_claims.normalize_plan_identity(claim.plan_ref),
                "claim_type": claim.claim_type,
                "parent_scope": claim.parent_scope,
                "parallel_root_authorized": claim.parallel_root_authorized,
                "session_root_count": len(session_roots),
                "session_root_identities": [f"{item.primary_project()}:{item.scope}" for item in session_roots],
                "hierarchy_role": (
                    "child" if claim.parent_scope else "root" if claim.claim_type == "program" else "standalone"
                ),
                "session_id": claim.session_id,
                "session_name": claim.session_name,
                "broader_goal": claim.broader_goal,
                "tracker_path": claim.tracker_path,
                "claim_status": claim.status,
                "health_status": coordination_claims.claim_runtime_status(
                    claim,
                    active_claims=project_claims,
                    now=observed_at,
                ),
                "health_issues": health_issues,
                "progress_at": claim.progress_at,
                "progress_kind": claim.progress_kind,
                "evidence_ref": claim.evidence_ref,
                "next_action": claim.next_action,
                "expected_quiet_until": claim.expected_quiet_until,
                "quiet_reason": claim.quiet_reason,
                "progress_issues": progress_issues,
                "current_phase": tracker_section.get("current_phase") if isinstance(tracker_section, dict) else None,
                "intended_next_phases": tracker_section.get("intended_next_phases")
                if isinstance(tracker_section, dict)
                else [],
                "depends_on_repos": tracker_section.get("depends_on_repos")
                if isinstance(tracker_section, dict)
                else [],
                "requires_shared_infra_changes": tracker_section.get("requires_shared_infra_changes")
                if isinstance(tracker_section, dict)
                else False,
                "stop_conditions": tracker_section.get("stop_conditions") if isinstance(tracker_section, dict) else [],
                "notes": tracker_section.get("notes") if isinstance(tracker_section, dict) else None,
                "tracker_updated_at": timestamps.get("updated_at") if isinstance(timestamps, dict) else None,
                "recovery_action": _recovery_action_for_claim(
                    claim,
                    active_claims=project_claims,
                    now=observed_at,
                ),
            }
        )
    return {
        "observed_at": observed_at.isoformat(),
        "session_count": len(sessions),
        "sessions": sessions,
    }


def end_runtime_session(
    *,
    agent: str,
    session_id: str | None = None,
    reason: str = "session ended",
    claims_dir: Path | None = None,
) -> dict[str, Any]:
    """Detach a terminated runtime from every exact-session live claim."""

    count, identities, resolved_session_id, ended_at = coordination_claims.end_session_claims(
        agent=agent,
        session_id=session_id,
        reason=reason,
        claims_dir=claims_dir,
    )
    for claim in coordination_claims.list_claims(
        claims_dir=claims_dir,
        include_inactive=True,
    ):
        if (
            claim.agent != agent
            or claim.session_id != resolved_session_id
            or claim.status != coordination_claims.SESSION_ENDED_STATUS
            or not claim.tracker_path
        ):
            continue
        tracker_path = Path(claim.tracker_path).expanduser()
        if tracker_path.exists():
            session_contracts.update_session_tracker(
                tracker_path,
                current_phase="session ended; lane disposition required",
                notes=reason.strip() or "session ended",
                updated_at=ended_at,
            )
    return {
        "action": "session_ended",
        "ended_count": count,
        "claims": identities,
        "session_id": resolved_session_id,
        "session_ended_at": ended_at,
        "reason": reason.strip() or "session ended",
    }


def finish_session(
    *,
    agent: str,
    project: str,
    scope: str,
    worktree_path: str,
    note: str | None = None,
    release_claim: bool = False,
    allow_dirty_handoff: bool = False,
) -> dict[str, Any]:
    """Close out one session or fail loud if the worktree state is unsafe."""

    claim = _single_matching_live_claim(agent=agent, project=project, scope=scope)

    clean, dirty_details = _worktree_is_clean(worktree_path)
    updated_at = datetime.now(timezone.utc).isoformat()

    tracker_path_text = claim.tracker_path
    if tracker_path_text:
        path = Path(tracker_path_text).expanduser()
        if path.exists():
            finish_note = note or ("completed and cleaned up" if clean else "handoff required")
            session_contracts.update_session_tracker(
                path,
                current_phase="completed" if clean else "handoff required",
                notes=finish_note,
                updated_at=updated_at,
            )

    claim_file = _claim_path(agent, project, scope)
    payload = _load_claim_payload(agent, project, scope)
    if payload is None:
        raise ValueError(f"Claim file missing for {agent} → {project}:{scope}")

    if not clean:
        if not allow_dirty_handoff:
            raise ValueError(
                "Worktree is dirty; commit or stash before session-finish, "
                "or pass --allow-dirty-handoff with a handoff note."
            )
        payload = _apply_claim_payload_updates(
            claim=claim,
            claim_file=claim_file,
            updates={
                "status": "handoff",
                "updated_at": updated_at,
                "notes": note or "handoff required because the worktree still has uncommitted changes",
            },
        )
        return {
            "action": "handoff",
            "clean": False,
            "dirty_details": dirty_details,
            "tracker_path": tracker_path_text,
        }

    doc_authority.assert_no_unresolved_owned_obligations(claim)

    if release_claim:
        coordination_claims.release_claim(agent, project, scope)
        return {
            "action": "released",
            "clean": True,
            "tracker_path": tracker_path_text,
        }

    _apply_claim_payload_updates(
        claim=claim,
        claim_file=claim_file,
        operation="closeout",
        updates={
            "status": "completed",
            "updated_at": updated_at,
            "notes": note or "session finished cleanly",
        },
    )
    return {
        "action": "completed",
        "clean": True,
        "tracker_path": tracker_path_text,
    }


def close_session(
    *,
    agent: str,
    project: str,
    scope: str,
    worktree_path: str | None = None,
    branch: str | None = None,
    note: str | None = None,
    delete_branch: bool = True,
    disposition: str = MERGED_DISPOSITION,
    disposition_reason: str | None = None,
    recovery_ref: str | None = None,
    merge_commit: str | None = None,
    allow_discard_unique: bool = False,
    reconcile_missing_worktree: bool = False,
    expected_tracker_sha256: str | None = None,
    mailbox_disposition: str | None = None,
    mailbox_note: str | None = None,
) -> dict[str, Any]:
    """Finish, clean up, and release one claimed lane as a single sanctioned flow.

    This is the canonical closeout path for claimed worktrees. It is intentionally
    idempotent around already-missing worktree and branch state so that rerunning
    a partially completed closeout can still release the claim cleanly.
    """

    claim, payload, claim_file = _claim_record_any_status(agent=agent, project=project, scope=scope)
    mailbox_closeout = _resolve_active_mailbox_for_closeout(
        claim=claim,
        mailbox_disposition=mailbox_disposition,
        mailbox_note=mailbox_note,
    )
    resolved_worktree_path = Path(worktree_path or claim.worktree_path or "").expanduser()
    resolved_branch = branch or claim.branch
    repo_root = _resolve_claim_repo_root(claim)
    updated_at = datetime.now(timezone.utc).isoformat()

    reconciliation_receipt = (
        _validate_missing_worktree_reconciliation(
            claim=claim,
            expected_tracker_sha256=expected_tracker_sha256,
        )
        if reconcile_missing_worktree
        else None
    )

    if resolved_worktree_path:
        canonical_worktree_path = resolved_worktree_path.resolve()
        sibling_scopes = sorted(
            sibling.scope
            for sibling in coordination_claims.check_claims()
            if not (
                sibling.agent == claim.agent
                and sibling.primary_project() == claim.primary_project()
                and sibling.scope == claim.scope
            )
            and sibling.worktree_path
            and Path(sibling.worktree_path).expanduser().resolve() == canonical_worktree_path
        )
        if sibling_scopes:
            raise ValueError(
                "Cannot close a shared worktree while sibling live claims still reference it: "
                + ", ".join(sibling_scopes)
            )

    if claim.write_paths:
        doc_authority.assert_no_unresolved_owned_obligations(claim)

    if resolved_worktree_path and resolved_worktree_path.exists():
        surface_runtime.assert_no_live_leases_for_worktree(resolved_worktree_path)
        clean, dirty_details = _worktree_is_clean(str(resolved_worktree_path))
        if not clean:
            raise ValueError(
                f"Worktree is dirty; commit or stash before session-close. Uncommitted state:\n{dirty_details}"
            )
        _assert_worktree_removal_access(resolved_worktree_path)

    preflight = _validate_closeout_preflight(
        repo_root=repo_root,
        branch=resolved_branch,
        disposition=disposition,
        disposition_reason=disposition_reason,
        recovery_ref=recovery_ref,
        merge_commit=merge_commit,
        allow_discard_unique=allow_discard_unique,
        delete_branch=delete_branch,
    )

    payload["status"] = "closing"
    payload["repo_root"] = str(repo_root)
    payload["disposition"] = preflight.disposition
    payload["disposition_reason"] = (
        disposition_reason.strip() if disposition_reason and disposition_reason.strip() else None
    )
    payload["recovery_ref"] = preflight.recovery_ref
    payload["default_branch"] = preflight.default_branch
    payload["merged_to_default"] = preflight.merged_to_default
    payload["default_remote_ref"] = preflight.default_remote_ref
    payload["default_branch_pushed"] = preflight.default_branch_pushed
    payload["merge_commit"] = preflight.merge_commit
    payload["merge_evidence"] = preflight.merge_evidence
    if reconciliation_receipt is not None:
        reconciliation_receipt["merge_evidence"] = preflight.merge_evidence or "none"
        reconciliation_receipt["merge_commit"] = preflight.merge_commit or "none"
        payload["missing_worktree_reconciliation"] = reconciliation_receipt
    payload["updated_at"] = updated_at
    payload["notes"] = note or "closing claimed lane via canonical session-close flow"
    # Keep the projection current during physical cleanup, but do not emit a
    # terminal closeout receipt until the final completed state is durable.
    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        _write_claim_payload(claim_file, payload)
        coordination_claims.refresh_prewrite_authority_projection(coordination_claims.CLAIMS_DIR)

    tracker_path = session_contracts.find_session_tracker_path(
        agent=claim.agent,
        project=project,
        scope=claim.scope,
        session_id=claim.session_id,
        preferred_path=claim.tracker_path,
    )
    tracker_path_text = str(tracker_path) if tracker_path is not None else claim.tracker_path
    if tracker_path is not None:
        session_contracts.update_session_tracker(
            tracker_path,
            current_phase="closing",
            notes=payload["notes"],
            updated_at=updated_at,
        )

    worktree_action = "not_requested"
    branch_action = "kept"
    if reconciliation_receipt is not None:
        worktree_action = reconciliation_receipt["filesystem_action"]
    elif worktree_path or claim.worktree_path:
        worktree_action = _remove_worktree_path(repo_root, resolved_worktree_path)
    if delete_branch:
        branch_action = _delete_branch(
            repo_root,
            resolved_branch,
            force=preflight.force_delete_branch,
        )

    closed_at = datetime.now(timezone.utc).isoformat()
    payload["status"] = "completed"
    payload["closed_at"] = closed_at
    payload["updated_at"] = closed_at
    payload["notes"] = note or (
        f"closed claimed lane with disposition={preflight.disposition}"
        + (f"; reason={disposition_reason.strip()}" if disposition_reason and disposition_reason.strip() else "")
    )
    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        _write_claim_payload(claim_file, payload)
        _projection_path, projection_digest_after = coordination_claims.refresh_prewrite_authority_projection(
            coordination_claims.CLAIMS_DIR
        )
        coordination_claims.record_claim_mutation(
            operation="closeout",
            claims_dir=coordination_claims.CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=claim.primary_project(),
            target_scope=claim.scope,
            target_claim_path=claim_file,
            session_id=claim.session_id,
            projection_digest_after=projection_digest_after,
        )

    if tracker_path is not None:
        session_contracts.update_session_tracker(
            tracker_path,
            current_phase="closed",
            notes=payload["notes"],
            updated_at=closed_at,
        )

    return {
        "action": "closed",
        "worktree_action": worktree_action,
        "branch_action": branch_action,
        "released": True,
        **preflight.to_dict(),
        "tracker_path": tracker_path_text,
        "missing_worktree_reconciliation": reconciliation_receipt,
        **mailbox_closeout,
    }


def resume_session(
    *,
    agent: str,
    project: str,
    scope: str,
    worktree_path: str,
    branch: str,
    current_phase: str,
    session_id: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Reattach a new runtime session to an existing plan-bound lane."""

    claim, payload, claim_file = _claim_record_any_status(
        agent=agent,
        project=project,
        scope=scope,
    )
    if claim.status not in coordination_claims.CLOSEABLE_STATUSES:
        raise ValueError(f"Cannot resume lane from lifecycle status {claim.status!r}")
    if not claim.plan_ref:
        raise ValueError("Cannot resume a lane with no plan_ref")
    if claim.branch and claim.branch != branch:
        raise ValueError(f"Claim branch is {claim.branch}, not {branch}")
    if claim.worktree_path and claim.worktree_path != worktree_path:
        raise ValueError(f"Claim worktree is {claim.worktree_path}, not {worktree_path}")

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError("Unable to resolve a session ID for session-resume.")

    same_runtime = claim.session_id == resolved_session_id
    explicitly_transferable = claim.status in {
        "handoff",
        coordination_claims.SESSION_ENDED_STATUS,
    }
    stale_heartbeat = "stale_session_heartbeat" in coordination_claims.claim_liveness_issues(claim)
    if not (same_runtime or explicitly_transferable or stale_heartbeat):
        current_owner = claim.session_id or "an unbound runtime"
        raise ValueError(
            f"Cannot resume lane {project}:{scope} as {resolved_session_id}; it is still owned by "
            f"runtime session {current_owner} with status {claim.status!r}. Cross-session resume "
            "requires an explicit handoff, a true session end, or a stale session heartbeat."
        )

    updated_at = datetime.now(timezone.utc).isoformat()
    transfer_preflight: outcome_selection.PreparedOutcomeSessionTransfer | None = None
    claim_bytes_before: bytes | None = None
    tracker_bytes_before: bytes | None = None
    if not same_runtime:
        transfer_preflight = outcome_selection.prepare_outcome_session_transfer(
            claim=claim,
            successor_session_id=resolved_session_id,
            transferred_at=datetime.fromisoformat(updated_at),
        )
        if transfer_preflight is not None:
            claim_bytes_before = claim_file.read_bytes()
            tracker_bytes_before = transfer_preflight.tracker_path.read_bytes()

    expected_fields = (
        payload
        if transfer_preflight is not None
        else {
            "status": claim.status,
            "session_id": claim.session_id,
            "heartbeat_at": claim.heartbeat_at,
            "updated_at": claim.updated_at,
        }
    )
    tracker_path_text = claim.tracker_path
    transfer_receipt: outcome_selection.OutcomeSessionTransferV1 | None = None
    try:
        payload = _apply_claim_payload_updates(
            claim=claim,
            claim_file=claim_file,
            updates={
                "status": "active",
                "session_id": resolved_session_id,
                "heartbeat_at": updated_at,
                "updated_at": updated_at,
                "notes": note or "session resumed with a fresh runtime attachment",
            },
            expected_fields=expected_fields,
        )

        if transfer_preflight is not None:
            successor_claim = coordination_claims.normalize_claim(
                payload,
                source_file=str(claim_file.resolve()),
            )
            if successor_claim is None:
                raise ValueError("resumed claim could not be normalized before tracker transfer")
            transfer_receipt = outcome_selection.apply_prepared_outcome_session_transfer(
                transfer_preflight,
                predecessor_claim=claim,
                successor_claim=successor_claim,
                current_phase=current_phase,
                notes=payload["notes"],
                updated_at=updated_at,
            )
        elif tracker_path_text:
            path = Path(tracker_path_text).expanduser()
            if path.exists():
                session_contracts.update_session_tracker(
                    path,
                    current_phase=current_phase,
                    notes=payload["notes"],
                    updated_at=updated_at,
                )
    except Exception as transfer_error:
        if transfer_preflight is None:
            raise
        if claim_bytes_before is None or tracker_bytes_before is None:
            raise SessionTransferIncompleteError(
                f"selected outcome transfer failed without exact rollback evidence: transfer={transfer_error}"
            ) from transfer_error
        try:
            claim_changed = claim_file.read_bytes() != claim_bytes_before
            tracker_changed = transfer_preflight.tracker_path.read_bytes() != tracker_bytes_before
        except OSError as inspection_error:
            raise SessionTransferIncompleteError(
                "selected outcome transfer failed and current state could not be inspected for rollback: "
                f"transfer={transfer_error}; inspection={inspection_error}"
            ) from transfer_error
        if not claim_changed and not tracker_changed:
            raise
        try:
            _rollback_outcome_session_transfer(
                claim=claim,
                claim_file=claim_file,
                successor_session_id=resolved_session_id,
                claim_bytes=claim_bytes_before,
                tracker_path=transfer_preflight.tracker_path,
                tracker_bytes=tracker_bytes_before,
            )
        except Exception as rollback_error:  # noqa: BLE001 - every rollback failure is terminal evidence
            raise SessionTransferIncompleteError(
                "selected outcome transfer failed and exact rollback was incomplete: "
                f"transfer={transfer_error}; rollback={rollback_error}"
            ) from transfer_error
        raise

    return {
        "action": "resumed",
        "session_id": resolved_session_id,
        "tracker_path": tracker_path_text,
        "plan_ref": claim.plan_ref,
        "outcome_session_transfer": (
            transfer_receipt.model_dump(mode="json") if transfer_receipt is not None else None
        ),
        "coordination_mailbox": _poll_mailbox(
            agent=agent,
            project=project,
            session_id=resolved_session_id,
        ),
    }


def handoff_session(
    *,
    agent: str,
    project: str,
    scope: str,
    note: str,
    current_phase: str = "handoff required",
) -> dict[str, Any]:
    """Mark one live lane as intentionally handed off."""

    claim = _single_matching_live_claim(agent=agent, project=project, scope=scope)
    updated_at = datetime.now(timezone.utc).isoformat()
    claim_file = _claim_path(agent, project, scope)
    payload = _load_claim_payload(agent, project, scope)
    if payload is None:
        raise ValueError(f"Claim file missing for {agent} → {project}:{scope}")

    payload = _apply_claim_payload_updates(
        claim=claim,
        claim_file=claim_file,
        updates={
            "status": "handoff",
            "updated_at": updated_at,
            "notes": note.strip(),
        },
    )

    tracker_path_text = claim.tracker_path
    if tracker_path_text:
        path = Path(tracker_path_text).expanduser()
        if path.exists():
            session_contracts.update_session_tracker(
                path,
                current_phase=current_phase,
                notes=payload["notes"],
                updated_at=updated_at,
            )

    return {
        "action": "handoff",
        "tracker_path": tracker_path_text,
    }


def abandon_session(
    *,
    agent: str,
    project: str,
    scope: str,
    note: str,
) -> dict[str, Any]:
    """Mark one live lane as explicitly abandoned."""

    claim = _single_matching_live_claim(agent=agent, project=project, scope=scope)
    updated_at = datetime.now(timezone.utc).isoformat()
    claim_file = _claim_path(agent, project, scope)
    payload = _load_claim_payload(agent, project, scope)
    if payload is None:
        raise ValueError(f"Claim file missing for {agent} → {project}:{scope}")

    payload = _apply_claim_payload_updates(
        claim=claim,
        claim_file=claim_file,
        updates={
            "status": "abandoned",
            "updated_at": updated_at,
            "notes": note.strip(),
        },
    )

    tracker_path_text = claim.tracker_path
    if tracker_path_text:
        path = Path(tracker_path_text).expanduser()
        if path.exists():
            session_contracts.update_session_tracker(
                path,
                current_phase="abandoned",
                notes=payload["notes"],
                updated_at=updated_at,
            )

    return {
        "action": "abandoned",
        "tracker_path": tracker_path_text,
    }
