"""Session lifecycle operations for sanctioned worktree flows.

The session contract lives partly on the canonical claim and partly in the
linked tracker artifact. This module keeps those surfaces in sync without
inventing a second coordination registry.
"""

from __future__ import annotations

import base64
import fcntl
import hashlib
import json
import os
import re
import subprocess
import tempfile
from contextlib import nullcontext
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    coordination_messages,
    doc_authority,
    outcome_admission,
    outcome_selection,
    push_safety,
    session_continuity,
    session_contracts,
    session_process_fencing,
    surface_runtime,
)
from enforced_planning.blocker_policy import (
    BlockerDecisionInputV1,
    BlockerDecisionResultV1,
    ClaimQueueSnapshotV1,
    evaluate_blocker_request,
)
from enforced_planning.worktree_paths import resolve_canonical_repo_root

WORKTREE_LIFECYCLE_CONFIG_PATH = Path(__file__).with_name("worktree_lifecycle.yaml")
SESSION_TRANSFER_JOURNAL_FIELD = "transfer_journal"


class SessionTransferIncompleteError(RuntimeError):
    """A cross-file session transfer failed and exact rollback was incomplete."""

    code = "session_transfer_incomplete"


class OutcomeAdmissionDeniedError(PermissionError):
    """One recorded outcome denial raised before lifecycle mutation."""

    code = "outcome_admission_denied"


_STATUS_OBSERVATION_ATTEMPTS = 3
DEFAULT_BLOCKER_DISPOSITION_RECEIPT_DIR = (
    Path.home() / ".claude" / "coordination" / "blocker-dispositions-v1"
)


class BlockerDispositionApplicationReceiptV1(BaseModel):
    """Immutable evidence that one accepted disposition was safely consumed."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.0"] = "1.0"
    application_id: str = Field(pattern=r"^blocker_application_[0-9a-f]{32}$")
    disposition_id: str = Field(pattern=r"^blocker_disposition_[0-9a-f]{32}$")
    ready_queue_evaluation_id: str = Field(pattern=r"^ready_queue_[0-9a-f]{32}$")
    decision: str = Field(min_length=1)
    claim_action: str = Field(min_length=1)
    agent: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    root_scope: str = Field(min_length=1)
    affected_scopes: tuple[str, ...]
    registry_digest_before: str = Field(pattern=r"^[0-9a-f]{64}$")
    registry_digest_after: str = Field(pattern=r"^[0-9a-f]{64}$")
    work_graph_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    result: Literal["recorded_no_mutation", "applied"]
    recorded_at: datetime


def _shared_lock_fd_if_present(lock_path: Path) -> int | None:
    """Acquire an existing lock for observation without creating or chmodding it."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(lock_path, flags)
    except FileNotFoundError:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_SH)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _release_shared_lock(fd: int) -> None:
    """Release one observation lock acquired by `_shared_lock_fd_if_present`."""

    try:
        fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _file_observation_fingerprint(path: Path) -> tuple[int, int, str] | None:
    """Return stable identity, size, and digest for an observed file."""

    try:
        stat_result = path.stat()
        content = path.read_bytes()
    except FileNotFoundError:
        return None
    return stat_result.st_ino, len(content), hashlib.sha256(content).hexdigest()


def _claim_registry_observation_fingerprint(claims_dir: Path) -> tuple[tuple[str, int, int, str], ...]:
    """Fingerprint authoritative claim YAML without touching staging artifacts."""

    if not claims_dir.is_dir():
        return ()
    rows: list[tuple[str, int, int, str]] = []
    for path in sorted(claims_dir.glob("*.yaml")):
        fingerprint = _file_observation_fingerprint(path)
        if fingerprint is not None:
            inode, size, digest = fingerprint
            rows.append((path.name, inode, size, digest))
    return tuple(rows)


def _read_session_tracker_for_status(path: Path) -> dict[str, Any] | None:
    """Read one tracker under an existing shared lock or a verified stable snapshot."""

    resolved = path.expanduser().resolve()
    # Must be the SAME function the writer uses. This reader constructed the
    # sibling path independently, so moving the lock out of the repository
    # without changing here would leave it looking where no lock is ever
    # written again -- it would find nothing, fall through to the fingerprint
    # path, and silently stop serialising against live writers.
    lock_path = session_contracts.tracker_lock_path(resolved)
    for _attempt in range(_STATUS_OBSERVATION_ATTEMPTS):
        lock_fd = _shared_lock_fd_if_present(lock_path)
        if lock_fd is not None:
            try:
                try:
                    return session_contracts.read_session_tracker(resolved)
                except FileNotFoundError:
                    return None
            finally:
                _release_shared_lock(lock_fd)
        before = _file_observation_fingerprint(resolved)
        if before is None:
            return None
        payload = session_contracts.read_session_tracker(resolved)
        after = _file_observation_fingerprint(resolved)
        if before == after and not lock_path.exists():
            return payload
    raise RuntimeError(f"session status could not establish a stable read-only tracker snapshot for {resolved}")


def _poll_mailbox(*, agent: str, project: str, session_id: str) -> dict[str, Any]:
    """Inject canonical mailbox state into a shared lifecycle response.

    A poll needs a live claim to resolve the session, and `session-resume` is
    the one caller that may legitimately run without one: the preserved-lane
    check refuses a new claim and names resume as the recovery, so a fresh
    runtime arrives holding nothing. Letting `UnknownSessionError` escape turned
    that recovery into an unhandled traceback and left closing the lane as the
    only route the refusal named that actually worked.

    The operator guide governs the fallback: an adapter failure "emits a visible
    warning but cannot truthfully assert mailbox debt or manufacture a block".
    Crashing manufactures the block, and reporting an empty inbox would fabricate
    the opposite. Record the limitation instead, and say a live-agent decision
    may still be pending.
    """

    try:
        notice = coordination_messages.poll_session_inbox(
            agent=agent,
            project=project,
            session_id=session_id,
            observe=True,
        )
    except coordination_messages.UnknownSessionError as exc:
        return {
            "session_id": session_id,
            "project": project,
            "active_count": 0,
            "message_ids": [],
            "acknowledgement_count": 0,
            "acknowledgement_message_ids": [],
            "polled": False,
            "degraded_reason": "no_live_claim_owns_session",
            "summary": (
                "coordination mailbox: NOT POLLED -- no live claim owns session "
                f"{session_id!r} ({exc}). This is not an empty inbox; a "
                "live-agent decision may be pending. Do not cross a coordination "
                "boundary until a claim is held and polling is restored."
            ),
        }
    return {**notice.model_dump(mode="json"), "polled": True, "degraded_reason": None}


def _poll_mailbox_after_committed_transition(
    *,
    agent: str,
    project: str,
    session_id: str,
) -> dict[str, Any]:
    """Expose post-commit poll failure without misreporting committed custody."""

    try:
        return _poll_mailbox(agent=agent, project=project, session_id=session_id)
    except Exception as exc:  # noqa: BLE001 - the committed transition is already authoritative
        return {
            "session_id": session_id,
            "project": project,
            "active_count": 0,
            "message_ids": [],
            "acknowledgement_count": 0,
            "acknowledgement_message_ids": [],
            "polled": False,
            "degraded_reason": "post_commit_mailbox_poll_failed",
            "error_type": type(exc).__name__,
            "summary": (
                "coordination mailbox: NOT POLLED after committed lifecycle transition; "
                f"custody is committed but mailbox state is unknown ({type(exc).__name__}: {exc})"
            ),
        }


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


def _claim_sha256(path: Path) -> str:
    """Return the exact byte digest used to bind legacy-claim reconciliation."""

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


def _session_ended_reconciliation_tracker(
    claim: coordination_claims.ClaimRecord,
) -> tuple[Path, dict[str, dict[str, str | None]]]:
    """Resolve a tracker while preserving evidence of stale mutable identity.

    A historical session-start bug could reuse a tracker for a later lane in the
    same native session, leaving the claim's tracker path valid and digest-bound
    but its scope, worktree, and branch fields stale. Requiring those mutable
    fields to match makes the only sanctioned terminal recovery impossible.

    The session-ended reconciliation path already requires exact claim and
    tracker digests plus a different native actor. Under those guards, accept
    the claim-named tracker only when its stable owner identity still matches,
    and carry every mutable mismatch into the closeout receipt.
    """

    trackers = _exact_tracker_candidates(claim)
    if len(trackers) == 1:
        tracker = trackers[0]
        if claim.tracker_path and Path(claim.tracker_path).expanduser() != tracker:
            raise ValueError("Claim tracker path does not match the exact reconciliation tracker")
        return tracker, {}
    if len(trackers) > 1:
        rendered = ", ".join(str(path) for path in trackers)
        raise ValueError(
            "Session-ended closeout reconciliation found ambiguous exact session trackers: "
            + rendered
        )

    if not claim.tracker_path:
        raise ValueError(
            "Session-ended closeout reconciliation requires one exact session tracker; "
            "the claim does not name a fallback tracker path."
        )
    tracker = Path(claim.tracker_path).expanduser()
    if not tracker.is_file():
        raise ValueError(
            "Session-ended closeout reconciliation requires one exact session tracker; "
            f"the claim-named fallback does not exist: {tracker}"
        )
    payload = session_contracts.read_session_tracker(tracker)
    contract = payload.get("claim")
    if not isinstance(contract, dict):
        raise ValueError(f"Session tracker at {tracker} is missing claim metadata")

    project = claim.primary_project()
    stable_expected = {
        "agent": claim.agent,
        "project": project,
        "session_id": claim.session_id,
    }
    stable_mismatches = {
        field: {"claim": value, "tracker": contract.get(field)}
        for field, value in stable_expected.items()
        if contract.get(field) != value
    }
    if stable_mismatches:
        fields = ", ".join(sorted(stable_mismatches))
        raise ValueError(
            "Session-ended closeout reconciliation rejected the claim-named tracker because "
            f"stable owner identity differs in: {fields}. Preserve the lane and repair the "
            "claim/tracker pair through an owned recovery."
        )

    mutable_expected = {
        "scope": claim.scope,
        "worktree_path": claim.worktree_path,
        "branch": claim.branch,
    }
    mutable_mismatches = {
        field: {"claim": value, "tracker": contract.get(field)}
        for field, value in mutable_expected.items()
        if contract.get(field) != value
    }
    return tracker, mutable_mismatches


def _validate_missing_worktree_reconciliation(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    expected_tracker_sha256: str | None,
    expected_claim_sha256: str | None = None,
) -> dict[str, Any]:
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
    if not claim.tracker_path and not expected_tracker_sha256 and not _exact_tracker_candidates(claim):
        # A lane created by a direct claim never had a tracker (tracker_path
        # state 1). Bind the exact claim bytes instead; the ordinary
        # merge/recovery preflight still runs before any mutation.
        expected_claim = (expected_claim_sha256 or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_claim):
            raise ValueError(
                "Tracker-less missing-worktree reconciliation requires --claim-sha256 as a SHA-256 digest."
            )
        if _claim_sha256(claim_file) != expected_claim:
            raise ValueError(
                "Missing-worktree reconciliation claim digest mismatch; preserve the lane and regenerate evidence."
            )
        return {
            "schema_version": "1.0",
            "claim_status_before": claim.status,
            "recorded_worktree_path": str(recorded_worktree),
            "tracker_path": None,
            "tracker_sha256": None,
            "claim_sha256": expected_claim,
            "filesystem_action": "not_attempted_absent_recorded_worktree",
        }
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


def _validate_session_ended_closeout_reconciliation(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    repo_root: Path,
    actor_session_id: str | None,
    expected_claim_sha256: str | None,
    expected_tracker_sha256: str | None,
    tracker_absent: bool = False,
) -> dict[str, Any]:
    """Authorize terminal closeout without transferring write custody.

    ``tracker_absent`` (issue #2010) replaces the tracker digest with verified
    absence: a claim whose tracker never existed has no tracker bytes to bind,
    so the exact claim digest is the only binding.

    The actor identity and native-runtime marker are resolved against the
    ACTING client -- parsed from ``actor_session_id``'s own ``<agent>:`` prefix
    -- never ``claim.agent``, the predecessor's client. ``close_session()``'s
    outer ``agent`` argument cannot serve this purpose: it selects which
    agent-keyed claim file to load and must stay bound to the claim's own
    owner (``claim.agent``) even during cross-client reconciliation. The actor
    may be either the runtime that explicitly ended its own claim or a later
    runtime reconciling stranded residue. In both cases the terminal status,
    exact claim/tracker bytes, Git state, and merge/recovery evidence remain
    mandatory. Binding the native-marker check to claim.agent previously made
    cross-client cleanup structurally impossible
    (lrn-20260902T182546895692Z-f56b908b6b); requiring a different actor later
    created the inverse deadlock by preventing an owner from cleaning up the
    claim it had just ended (lrn-20260916T050517958708Z-8b8b878dfe).
    """

    if not actor_session_id or ":" not in actor_session_id:
        raise ValueError(
            "Session-ended closeout reconciliation requires an exact actor_session_id "
            "in '<agent>:<value>' form"
        )
    acting_agent = actor_session_id.split(":", 1)[0]
    if acting_agent not in coordination_claims.SUPPORTED_AGENTS:
        raise ValueError(
            f"Session-ended closeout reconciliation actor_session_id names an unsupported "
            f"agent {acting_agent!r}"
        )
    resolved_actor = coordination_claims.resolve_session_id(acting_agent, actor_session_id)
    if not resolved_actor:
        raise ValueError("Session-ended closeout reconciliation requires an exact actor_session_id")
    coordination_claims.validate_native_session_binding(
        acting_agent,
        resolved_actor,
        require_native_marker=True,
    )
    if claim.status != coordination_claims.SESSION_ENDED_STATUS:
        raise ValueError(
            "Session-ended closeout reconciliation requires an exact session_ended claim; "
            f"found {claim.status!r}."
        )
    if not claim.session_id:
        raise ValueError("Session-ended closeout reconciliation requires a recorded owner session_id.")
    if not claim.worktree_path:
        raise ValueError("Session-ended closeout reconciliation requires a recorded worktree path")
    recorded_worktree = Path(claim.worktree_path).expanduser().resolve()
    if recorded_worktree.exists() and not recorded_worktree.is_dir():
        raise ValueError(
            "Session-ended closeout reconciliation requires the recorded worktree to be a directory."
        )
    if recorded_worktree == repo_root.expanduser().resolve():
        raise ValueError(
            "Session-ended closeout reconciliation rejects canonical-root custody; "
            "use canonical-root reconciliation instead."
        )

    expected_claim_digest = (expected_claim_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_claim_digest):
        raise ValueError(
            "Session-ended closeout reconciliation requires --claim-sha256 as a SHA-256 digest."
        )
    actual_claim_digest = _claim_sha256(claim_file)
    if actual_claim_digest != expected_claim_digest:
        raise ValueError(
            "Session-ended closeout reconciliation claim digest mismatch; preserve the lane and regenerate evidence."
        )

    if tracker_absent:
        if expected_tracker_sha256:
            raise ValueError(
                "--tracker-absent and --tracker-sha256 are mutually exclusive; a tracker digest "
                "means the tracker exists, so use ordinary --reconcile-session-ended."
            )
        absence = _verify_session_ended_tracker_absent(claim)
        return {
            "schema_version": "1.0",
            "claim_status_before": claim.status,
            "predecessor_session_id": claim.session_id,
            "reconciliation_actor_session_id": resolved_actor,
            "reconciliation_actor_relation": (
                "owner" if claim.session_id == resolved_actor else "successor"
            ),
            "recorded_worktree_path": str(recorded_worktree),
            "worktree_present_before": recorded_worktree.is_dir() and not _is_closed_lane_placeholder(recorded_worktree),
            "claim_sha256": actual_claim_digest,
            "tracker_path": None,
            "tracker_sha256": None,
            **absence,
        }

    expected_tracker_digest = (expected_tracker_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_tracker_digest):
        raise ValueError(
            "Session-ended closeout reconciliation requires --tracker-sha256 as a SHA-256 digest."
        )
    tracker, tracker_identity_mismatches = _session_ended_reconciliation_tracker(claim)
    actual_tracker_digest = _tracker_sha256(tracker)
    if actual_tracker_digest != expected_tracker_digest:
        raise ValueError(
            "Session-ended closeout reconciliation tracker digest mismatch; preserve the lane and regenerate evidence."
        )
    return {
        "schema_version": "1.0",
        "claim_status_before": claim.status,
        "predecessor_session_id": claim.session_id,
        "reconciliation_actor_session_id": resolved_actor,
        "reconciliation_actor_relation": (
            "owner" if claim.session_id == resolved_actor else "successor"
        ),
        "recorded_worktree_path": str(recorded_worktree),
        "worktree_present_before": recorded_worktree.is_dir() and not _is_closed_lane_placeholder(recorded_worktree),
        "claim_sha256": actual_claim_digest,
        "tracker_path": str(tracker),
        "tracker_sha256": actual_tracker_digest,
        "tracker_identity_mismatches": tracker_identity_mismatches,
    }


def _verify_session_ended_tracker_absent(claim: coordination_claims.ClaimRecord) -> dict[str, Any]:
    """Prove, not assume, that a session-ended claim has no tracker to bind (#2010)."""

    recorded = Path(claim.tracker_path).expanduser() if claim.tracker_path else None
    if recorded is not None and recorded.exists():
        raise ValueError(
            f"--tracker-absent refused: the recorded tracker exists at {recorded}; "
            "use ordinary --reconcile-session-ended with --tracker-sha256."
        )
    exact = _exact_tracker_candidates(claim)
    found = session_contracts.find_session_tracker_path(
        agent=claim.agent,
        project=claim.primary_project() or "",
        scope=claim.scope,
        session_id=claim.session_id,
        preferred_path=claim.tracker_path,
    )
    if exact or found is not None:
        rendered = ", ".join(str(path) for path in [*exact, *([found] if found else [])])
        raise ValueError(
            f"--tracker-absent refused: an identity-matched session tracker exists ({rendered}); "
            "use ordinary --reconcile-session-ended with --tracker-sha256."
        )
    return {"recorded_tracker_path": str(recorded) if recorded else None, "tracker_absent_verified": True}


def _git_capture(cwd: Path, *args: str) -> str:
    """Run one Git command for lane-state capture; any failure is a capture failure."""

    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise ValueError(
            f"Session-ended lane capture failed at 'git {' '.join(args)}': "
            + (result.stderr or result.stdout).strip()
        )
    return result.stdout


def _capture_session_ended_lane_state(
    *,
    claim: coordination_claims.ClaimRecord,
    worktree: Path,
    repo_root: Path,
    archive_dir: str | None,
) -> dict[str, Any]:
    """Capture an existing session-ended worktree before any lifecycle mutation (#2010).

    Records ``git status``, the branch head, and an independent recovery ref.
    When the worktree holds staged or unstaged changes, the exact state is also
    written under ``archive_dir`` as a verified Git bundle plus diffs. Capture
    only adds objects, one new ref, and new files; it never deletes anything.
    """

    if not archive_dir:
        raise ValueError("--tracker-absent on an existing worktree requires --recovery-archive-dir.")
    archive = Path(archive_dir).expanduser()
    if not archive.is_absolute():
        raise ValueError("--recovery-archive-dir must be an absolute path.")
    try:
        archive.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"Session-ended lane capture failed creating {archive}: {exc}") from exc
    if any(archive.iterdir()):
        raise ValueError(f"Session-ended lane capture requires an empty recovery archive dir: {archive}")

    status = _git_capture(worktree, "status", "--porcelain=v1", "--untracked-files=all")
    entries = [line for line in status.splitlines() if line.strip()]
    untracked = [line[3:] for line in entries if line.startswith("??")]
    if untracked:
        raise ValueError(
            "Session-ended lane capture refuses untracked files, which a recovery ref cannot hold: "
            + ", ".join(untracked[:10])
        )
    head = _git_capture(worktree, "rev-parse", "--verify", "HEAD^{commit}").strip()
    current_branch = _git_capture(worktree, "symbolic-ref", "--quiet", "--short", "HEAD").strip()
    if not claim.branch or current_branch != claim.branch:
        raise ValueError(
            f"Session-ended lane capture found branch {current_branch!r}, not the claimed {claim.branch!r}."
        )
    dirty = bool(entries)
    snapshot = _git_capture(worktree, "stash", "create").strip() if dirty else head
    if not snapshot:
        raise ValueError("Session-ended lane capture failed: git stash create returned no commit.")
    safe_branch = re.sub(r"[^a-zA-Z0-9._-]+", "-", claim.branch)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    recovery_ref = f"refs/recovery/session-ended/{safe_branch}-{stamp}"
    _git_capture(repo_root, "update-ref", recovery_ref, snapshot, "")
    if _git_capture(repo_root, "rev-parse", "--verify", f"{recovery_ref}^{{commit}}").strip() != snapshot:
        raise ValueError("Session-ended lane capture failed: recovery ref does not resolve to the snapshot.")
    if not _is_ancestor(repo_root, head, recovery_ref):
        raise ValueError("Session-ended lane capture failed: recovery ref does not contain the branch head.")

    (archive / "git_status.txt").write_text(status, encoding="utf-8")
    capture: dict[str, Any] = {
        "schema_version": "1.0",
        "worktree_path": str(worktree),
        "branch": current_branch,
        "branch_head": head,
        "git_status_porcelain": entries,
        "uncommitted_changes": dirty,
        "recovery_ref": recovery_ref,
        "recovery_commit": snapshot,
        "archive_dir": str(archive),
        "bundle_path": None,
        "bundle_sha256": None,
    }
    if dirty:
        # Non-vacuous verification: the snapshot must reproduce the exact index
        # and working tree, not merely exist.
        index_commit = _git_capture(repo_root, "rev-parse", "--verify", f"{snapshot}^2").strip()
        for args in (("diff", "--quiet", "--cached", index_commit), ("diff", "--quiet", snapshot)):
            _git_capture(worktree, *args)
        staged = _git_capture(worktree, "diff", "--cached", "--binary")
        unstaged = _git_capture(worktree, "diff", "--binary")
        (archive / "staged.diff").write_text(staged, encoding="utf-8")
        (archive / "unstaged.diff").write_text(unstaged, encoding="utf-8")
        bundle = archive / "lane-state.bundle"
        _git_capture(repo_root, "bundle", "create", str(bundle), recovery_ref, f"^{head}")
        _git_capture(repo_root, "bundle", "verify", str(bundle))
        if snapshot not in _git_capture(repo_root, "bundle", "list-heads", str(bundle)):
            raise ValueError("Session-ended lane capture failed: bundle does not carry the snapshot commit.")
        capture.update(
            {
                "bundle_path": str(bundle),
                "bundle_sha256": hashlib.sha256(bundle.read_bytes()).hexdigest(),
                "staged_diff_path": str(archive / "staged.diff"),
                "unstaged_diff_path": str(archive / "unstaged.diff"),
            }
        )
    (archive / "capture_receipt.json").write_text(json.dumps(capture, indent=2, sort_keys=True), encoding="utf-8")
    return capture


def _validate_canonical_root_reconciliation(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    repo_root: Path,
    expected_claim_sha256: str | None,
    expected_tracker_sha256: str | None,
) -> dict[str, Any]:
    """Bind ended owned custody to a retained root and digest-bound tracker."""

    if claim.status != coordination_claims.SESSION_ENDED_STATUS:
        raise ValueError(
            f"Canonical-root reconciliation requires an exact session_ended claim; found {claim.status!r}."
        )
    if not claim.worktree_path:
        raise ValueError("Canonical-root reconciliation requires a recorded worktree path")
    recorded_worktree = Path(claim.worktree_path).expanduser().resolve()
    canonical_root = repo_root.expanduser().resolve()
    if recorded_worktree != canonical_root or not recorded_worktree.is_dir():
        raise ValueError(
            "Canonical-root reconciliation requires the existing recorded worktree path "
            "to equal the canonical repository root."
        )
    expected_claim_digest = (expected_claim_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_claim_digest):
        raise ValueError("Canonical-root reconciliation requires --claim-sha256 as a SHA-256 digest.")
    actual_claim_digest = _claim_sha256(claim_file)
    if actual_claim_digest != expected_claim_digest:
        raise ValueError(
            "Canonical-root reconciliation claim digest mismatch; preserve the repository and regenerate evidence."
        )
    expected_tracker_digest = (expected_tracker_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_tracker_digest):
        raise ValueError("Canonical-root reconciliation requires --tracker-sha256 as a SHA-256 digest.")
    # The legacy tracker-name collision may leave a later scope in this file.
    # Reuse stable-owner validation; closeout never updates a non-matching tracker.
    tracker, tracker_identity_drift = _session_ended_reconciliation_tracker(claim)
    if claim.tracker_path and Path(claim.tracker_path).expanduser() != tracker:
        raise ValueError("Claim tracker path does not match the exact reconciliation tracker")
    actual_tracker_digest = _tracker_sha256(tracker)
    if actual_tracker_digest != expected_tracker_digest:
        raise ValueError(
            "Canonical-root reconciliation tracker digest mismatch; preserve the repository and regenerate evidence."
        )

    def git_output(*args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=str(recorded_worktree),
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            raise ValueError(
                "Canonical-root reconciliation could not prove canonical Git identity: "
                + (result.stderr or result.stdout).strip()
            )
        return result.stdout.strip()

    top_level = Path(git_output("rev-parse", "--show-toplevel")).resolve()
    common_dir_text = git_output("rev-parse", "--git-common-dir")
    common_dir = Path(common_dir_text)
    if not common_dir.is_absolute():
        common_dir = recorded_worktree / common_dir
    common_dir = common_dir.resolve()
    if top_level != recorded_worktree or common_dir != (recorded_worktree / ".git").resolve():
        raise ValueError("Canonical-root reconciliation rejects linked worktrees and non-canonical Git identities.")
    if not (recorded_worktree / ".git").is_dir():
        raise ValueError("Canonical-root reconciliation requires a main-worktree .git directory")
    clean, dirty_details = _worktree_is_clean(str(recorded_worktree))
    if not clean:
        raise ValueError(
            "Canonical-root reconciliation requires a clean canonical checkout. Uncommitted state:\n" + dirty_details
        )
    symbolic = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=recorded_worktree, capture_output=True, text=True, check=False,
    )
    if symbolic.returncode not in (0, 1):
        raise ValueError("Canonical-root reconciliation could not prove checked-out branch identity.")
    current_branch = symbolic.stdout.strip() if symbolic.returncode == 0 else "HEAD"
    head_commit = git_output("rev-parse", "--verify", "HEAD^{commit}")
    if not claim.branch or current_branch != claim.branch:
        raise ValueError(
            "Canonical-root reconciliation requires the checked-out branch to match the recorded claim branch."
        )
    return {
        "schema_version": "1.0",
        "claim_status_before": claim.status,
        "tracker_identity_drift": tracker_identity_drift,
        "recorded_worktree_path": str(recorded_worktree),
        "canonical_repo_root": str(canonical_root),
        "branch": current_branch,
        "head_commit": head_commit,
        "claim_path": str(claim_file),
        "claim_sha256": actual_claim_digest,
        "tracker_path": str(tracker),
        "tracker_sha256": actual_tracker_digest,
        "filesystem_action": "retained_canonical_root",
        "branch_action": "retained_detached_head" if current_branch == "HEAD" else "retained_canonical_branch",
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
    """Persist one normalized claim payload through the canonical atomic writer.

    WARNING: This function does NOT refresh the projection. Use
    _write_claim_and_refresh_projection() instead for mutations that require
    atomic projection updates. This function exists only for internal use where
    the caller handles projection refresh explicitly within a lock context.
    """

    coordination_claims._atomic_write_claim(path, payload)


def _write_claim_and_refresh_projection(
    path: Path,
    payload: dict[str, Any],
    claims_dir: Path = coordination_claims.CLAIMS_DIR,
) -> tuple[Path, str]:
    """Write claim and atomically refresh projection in one operation.

    This is the canonical mutation path for claim writes that must keep the
    projection in sync. It ensures the projection digest is always current
    with the claim registry state, eliminating the race condition where
    the projection could be stale between write and refresh.

    Delegates to coordination_claims._replace_claim_and_refresh_projection_fail_atomic,
    the module's own canonical fail-atomic primitive (already used by
    narrow_claim and covered by
    test_narrow_projection_failure_restores_exact_claim_and_projection_bytes),
    rather than a separate, weaker reimplementation. Before this change, this
    function wrote the claim first and only then refreshed the projection --
    matching neither its own docstring's atomicity claim nor the documented
    pattern elsewhere in this module ("the exact preflight claim and tracker
    bytes are restored; an unsuccessful rollback raises a visible error rather
    than reporting success" -- WORKTREE_COORDINATION_OPERATOR_GUIDE.md,
    restart-safe outcome custody). If refresh failed, the write stood: an
    unrelated claim's corruption could strand THIS claim mid-write (observed
    2026-09-14: a session-close call that had already written `status:
    closing` crashed here on a different, concurrently-live session's
    malformed claim file, leaving the caller's own claim permanently stuck in
    a non-terminal status with no sanctioned recovery command for that exact
    state). The caller still sees the same exception either way; only the
    claim (and now also the projection) file's on-disk state differs.

    Args:
        path: Path to the claim file
        payload: Normalized claim payload to write
        claims_dir: Parent directory for projection refresh (defaults to CLAIMS_DIR)

    Returns:
        Tuple of (projection_path, projection_digest) for mutation tracking
    """

    return coordination_claims._replace_claim_and_refresh_projection_fail_atomic(
        claim_path=path,
        payload=payload,
        claims_dir=claims_dir,
    )


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


def _renewed_lease_expiry(updated_at: str, current_expires_at: str | None) -> str:
    """Return the lease expiry a resume attaching at ``updated_at`` should carry.

    Resume takes a lane back into live ownership, so it must renew the lease and
    not only the heartbeat. Claims carry a 24-hour TTL, and the registry loader
    drops an expired claim *before* normalization -- so a lane resumed a day or
    more after it was created came back with ``status: active`` and the caller's
    own ``session_id``, and was still invisible to every consumer that reads the
    registry. The pre-push gate then reported ``missing_branch_claim``, naming
    the wrong problem: not "your claim is expired" but "no claim is attached to
    this branch", about a file sitting on disk saying otherwise
    (lrn-20260908T170436862573Z-d2c739d527).

    Renewal only ever extends. A claim may deliberately carry an expiry further
    out than the default TTL, and a liveness signal must never be the thing that
    shortens it -- clamping every heartbeat to ``now + TTL`` would quietly pull a
    long-lived lease back to a day.
    """

    parsed = datetime.fromisoformat(updated_at)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    renewed = parsed + timedelta(hours=coordination_claims.DEFAULT_TTL_HOURS)
    if current_expires_at:
        try:
            existing = datetime.fromisoformat(current_expires_at)
        except ValueError:
            return renewed.isoformat()
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
        if existing > renewed:
            return current_expires_at
    return renewed.isoformat()


def _apply_cross_agent_handoff_transaction(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    claim_bytes_before: bytes,
    successor_agent: str,
    successor_session_id: str,
    current_phase: str,
    note: str | None,
    updated_at: str,
    expected_fields: dict[str, Any],
    project: str,
    scope: str,
) -> dict[str, Any]:
    """Transfer a quiesced claim's identity to a different native agent.

    Reachable only for explicit ``handoff`` or ``session_ended`` claims: the
    predecessor already quiesced with no live process to fence, so there is
    nothing to verify beyond the successor's own proven native identity and the
    claim's exact unchanged bytes. This intentionally does not reuse the same-agent
    cross-session transfer machinery (process fencing, transfer journals):
    those exist to protect a *live* predecessor runtime, which a handoff
    claim by definition no longer has. The claim file itself is renamed
    because every other lookup (`_claim_path`, heartbeat, close) is keyed by
    ``<agent>_<project>_<scope>.yaml``; the session tracker keeps its
    original filename as accurate provenance of which agent created it.
    """

    new_claim_file = _claim_path(successor_agent, project, scope)
    if new_claim_file.exists():
        raise ValueError(
            f"Cannot transfer {project}:{scope} to agent {successor_agent!r}; "
            f"a claim already exists at {new_claim_file}"
        )
    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        if claim_file.read_bytes() != claim_bytes_before:
            raise ValueError("claim changed after cross-agent handoff preflight")
        current = yaml.safe_load(claim_bytes_before)
        if not isinstance(current, dict):
            raise TypeError("cross-agent handoff claim must be a YAML mapping")
        for field, expected in expected_fields.items():
            if current.get(field) != expected:
                raise ValueError(f"claim field {field} changed after cross-agent handoff preflight")
        predecessor_agent = current.get("agent")
        current.update(
            {
                "agent": successor_agent,
                "status": "active",
                "session_id": successor_session_id,
                "heartbeat_at": updated_at,
                "expires_at": _renewed_lease_expiry(updated_at, claim.expires_at),
                "updated_at": updated_at,
                "notes": note
                or f"session resumed under a different native agent ({predecessor_agent} -> {successor_agent})",
            }
        )
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        try:
            _write_claim_payload(new_claim_file, current)
            claim_file.unlink()
            _projection_path, projection_digest_after = coordination_claims.refresh_prewrite_authority_projection(
                coordination_claims.CLAIMS_DIR
            )
            coordination_claims.record_claim_mutation(
                operation="session_upsert",
                claims_dir=coordination_claims.CLAIMS_DIR,
                registry_digest_before=registry_digest_before,
                target_project=project,
                target_scope=scope,
                target_claim_path=new_claim_file,
                session_id=successor_session_id,
                projection_digest_after=projection_digest_after,
            )
        except Exception:
            rollback_registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
            if new_claim_file.exists():
                new_claim_file.unlink()
            _atomic_restore_bytes(claim_file, claim_bytes_before)
            _projection_path, rollback_projection_digest = coordination_claims.refresh_prewrite_authority_projection(
                coordination_claims.CLAIMS_DIR
            )
            coordination_claims.record_claim_mutation(
                operation="session_upsert",
                claims_dir=coordination_claims.CLAIMS_DIR,
                registry_digest_before=rollback_registry_digest_before,
                target_project=project,
                target_scope=scope,
                target_claim_path=claim_file,
                session_id=claim.session_id,
                projection_digest_after=rollback_projection_digest,
            )
            raise
    return current


def _apply_legacy_cross_session_resume_transaction(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    claim_bytes_before: bytes,
    tracker_path: Path,
    tracker_bytes_before: bytes,
    successor_session_id: str,
    current_phase: str,
    note: str | None,
    updated_at: str,
    expected_fields: dict[str, Any],
    transfer_preflight: outcome_selection.PreparedOutcomeSessionTransfer | None,
    project: str,
    scope: str,
    worktree_path: str,
    branch: str,
) -> tuple[
    dict[str, Any],
    outcome_selection.OutcomeSessionTransferV1 | None,
    dict[str, Any],
]:
    """Commit an unfenced non-Codex custody transfer with exact rollback."""

    with (
        coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR),
        session_contracts.session_tracker_lock(tracker_path),
    ):
        if claim_file.read_bytes() != claim_bytes_before:
            raise ValueError("claim changed after cross-session resume preflight")
        if tracker_path.read_bytes() != tracker_bytes_before:
            raise ValueError("session tracker changed after cross-session resume preflight")
        current = yaml.safe_load(claim_bytes_before)
        if not isinstance(current, dict):
            raise TypeError("cross-session resume claim must be a YAML mapping")
        for field, expected in expected_fields.items():
            if current.get(field) != expected:
                raise ValueError(f"claim field {field} changed after cross-session resume preflight")
        if claim.broad_scope_mode == "bootstrap" and claim.target_worktree_path:
            current["worktree_path"] = claim.target_worktree_path
        elif claim.worktree_path and claim.worktree_path != worktree_path:
            # Reaching this branch means resume_session()'s own
            # _validate_worktree_path_repair already confirmed the recorded
            # path is gone and the provided one is a real linked worktree on
            # the claimed branch -- the only way worktree_path could differ
            # here at all is a validated repair, never an unchecked caller
            # value.
            current["worktree_path"] = worktree_path
        current.update(
            {
                "status": "active",
                "session_id": successor_session_id,
                "heartbeat_at": updated_at,
                "expires_at": _renewed_lease_expiry(updated_at, claim.expires_at),
                "updated_at": updated_at,
                "notes": note or "session resumed with a fresh runtime attachment",
            }
        )
        successor_claim = coordination_claims.normalize_claim(
            current,
            source_file=str(claim_file.resolve()),
        )
        if successor_claim is None:
            raise ValueError("resumed claim could not be normalized before tracker transfer")
        tracker_payload = session_contracts.read_session_tracker(tracker_path)
        transfer_receipt: outcome_selection.OutcomeSessionTransferV1 | None = None
        if transfer_preflight is not None:
            tracker_payload = outcome_selection.build_prepared_outcome_session_transfer_payload(
                transfer_preflight,
                tracker_payload=tracker_payload,
                predecessor_claim=claim,
                successor_claim=successor_claim,
                current_phase=current_phase,
                notes=current["notes"],
                updated_at=updated_at,
            )
            transfer_receipt = transfer_preflight.transfer
        else:
            tracker_claim = tracker_payload.get("claim")
            tracker_section = tracker_payload.get("tracker")
            timestamps = tracker_payload.get("timestamps")
            if not isinstance(tracker_claim, dict) or tracker_claim.get("session_id") != claim.session_id:
                raise ValueError("session tracker predecessor identity does not match the claim")
            if not isinstance(tracker_section, dict) or not isinstance(timestamps, dict):
                raise ValueError("session tracker is missing tracker or timestamps state")
            tracker_claim["session_id"] = successor_session_id
            tracker_section["current_phase"] = current_phase
            tracker_section["notes"] = current["notes"]
            timestamps["updated_at"] = updated_at

        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        try:
            _write_claim_payload(claim_file, current)
            session_contracts._atomic_write_session_tracker(tracker_path, tracker_payload)
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
                session_id=successor_session_id,
                projection_digest_after=projection_digest_after,
            )
            claim_session_transfer = _persist_claim_session_transfer_receipt(
                claim=claim,
                project=project,
                scope=scope,
                worktree_path=worktree_path,
                branch=branch,
                successor_session_id=successor_session_id,
                transferred_at=updated_at,
                prior_claim_bytes=claim_bytes_before,
                successor_claim_bytes=claim_file.read_bytes(),
                process_fence=None,
                predecessor_process_pid=None,
                predecessor_process_start_ticks=None,
                process_fence_transfer_epoch_sha256=None,
            )
        except Exception:
            rollback_registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
            _atomic_restore_bytes(claim_file, claim_bytes_before)
            _atomic_restore_bytes(tracker_path, tracker_bytes_before)
            _projection_path, rollback_projection_digest = coordination_claims.refresh_prewrite_authority_projection(
                coordination_claims.CLAIMS_DIR
            )
            coordination_claims.record_claim_mutation(
                operation="session_upsert",
                claims_dir=coordination_claims.CLAIMS_DIR,
                registry_digest_before=rollback_registry_digest_before,
                target_project=claim.primary_project(),
                target_scope=claim.scope,
                target_claim_path=claim_file,
                session_id=claim.session_id,
                projection_digest_after=rollback_projection_digest,
            )
            raise
    return current, transfer_receipt, claim_session_transfer


def _apply_codex_cross_session_resume_transaction(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    claim_bytes_before: bytes,
    tracker_path: Path,
    tracker_bytes_before: bytes,
    successor_session_id: str,
    current_phase: str,
    note: str | None,
    updated_at: str,
    expected_fields: dict[str, Any],
    transfer_preflight: outcome_selection.PreparedOutcomeSessionTransfer | None,
    project: str,
    scope: str,
    worktree_path: str,
    branch: str,
    process_fence: dict[str, Any] | None,
    predecessor_process_pid: int | None,
    predecessor_process_start_ticks: int | None,
    takeover_reservation: dict[str, Any] | None,
) -> tuple[
    dict[str, Any],
    outcome_selection.OutcomeSessionTransferV1 | None,
    dict[str, Any],
]:
    """Commit custody through a reservation journal with the claim written last."""

    def yaml_bytes(payload: dict[str, Any]) -> bytes:
        return yaml.safe_dump(payload, default_flow_style=False, sort_keys=False).encode("utf-8")

    def decode_journal_bytes(
        journal: dict[str, Any],
        *,
        prefix: str,
    ) -> bytes:
        encoded = journal.get(f"{prefix}_bytes_base64")
        expected_sha256 = journal.get(f"{prefix}_sha256")
        if not isinstance(encoded, str) or not isinstance(expected_sha256, str):
            raise TypeError(f"session transfer journal lacks exact {prefix} bytes")
        try:
            decoded = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError(f"session transfer journal has invalid {prefix} bytes") from exc
        if hashlib.sha256(decoded).hexdigest() != expected_sha256:
            raise ValueError(f"session transfer journal {prefix} digest mismatch")
        return decoded

    def validate_journal(
        journal: dict[str, Any],
        *,
        reservation: dict[str, Any],
    ) -> tuple[bytes, bytes, bytes]:
        expected = {
            "record_type": "claim_session_transfer_journal",
            "predecessor_session_id": claim.session_id,
            "successor_session_id": successor_session_id,
            "worktree_path": str(Path(worktree_path).expanduser().resolve()),
            "branch": branch,
            "claim_epoch_sha256": reservation.get("claim_epoch_sha256"),
            "process_fence_receipt_path": process_fence.get("receipt_path") if process_fence else None,
            "process_fence_receipt_sha256": process_fence.get("receipt_sha256") if process_fence else None,
        }
        if any(journal.get(field) != value for field, value in expected.items()):
            raise ValueError("session transfer journal does not match exact custody inputs")
        predecessor_tracker_bytes = decode_journal_bytes(
            journal,
            prefix="predecessor_tracker",
        )
        successor_claim_bytes = decode_journal_bytes(journal, prefix="successor_claim")
        successor_tracker_bytes = decode_journal_bytes(
            journal,
            prefix="successor_tracker",
        )
        successor_claim_payload = yaml.safe_load(successor_claim_bytes)
        successor_tracker_payload = yaml.safe_load(successor_tracker_bytes)
        if not isinstance(successor_claim_payload, dict) or not isinstance(successor_tracker_payload, dict):
            raise TypeError("session transfer journal successor state must contain YAML mappings")
        if (
            successor_claim_payload.get("session_id") != successor_session_id
            or coordination_claims.SESSION_TAKEOVER_RESERVATION_FIELD in successor_claim_payload
        ):
            raise ValueError("session transfer journal has invalid successor claim custody")
        tracker_claim = successor_tracker_payload.get("claim")
        if not isinstance(tracker_claim, dict) or tracker_claim.get("session_id") != successor_session_id:
            raise ValueError("session transfer journal has invalid successor tracker custody")
        return predecessor_tracker_bytes, successor_claim_bytes, successor_tracker_bytes

    with (
        coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR),
        session_contracts.session_tracker_lock(tracker_path),
    ):
        current_claim_bytes = claim_file.read_bytes()
        current = yaml.safe_load(current_claim_bytes)
        if not isinstance(current, dict):
            raise TypeError("cross-session resume claim must be a YAML mapping")
        reservation = coordination_claims.active_session_takeover_reservation(current)
        if reservation is None or takeover_reservation is None:
            raise ValueError("cross-session Codex transfer requires one active takeover reservation")
        for field in (
            "predecessor_session_id",
            "successor_session_id",
            "worktree_path",
            "pid",
            "process_start_ticks",
            "claim_epoch_sha256",
        ):
            if reservation.get(field) != takeover_reservation.get(field):
                raise ValueError("takeover reservation changed before custody commit")

        raw_journal = reservation.get(SESSION_TRANSFER_JOURNAL_FIELD)
        transfer_receipt: outcome_selection.OutcomeSessionTransferV1 | None = None
        if raw_journal is None:
            if current_claim_bytes != claim_bytes_before:
                raise ValueError("claim changed after cross-session resume preflight")
            if tracker_path.read_bytes() != tracker_bytes_before:
                raise ValueError("session tracker changed after cross-session resume preflight")
            for field, expected in expected_fields.items():
                if current.get(field) != expected:
                    raise ValueError(f"claim field {field} changed after cross-session resume preflight")

            successor_payload = dict(current)
            if claim.broad_scope_mode == "bootstrap" and claim.target_worktree_path:
                successor_payload["worktree_path"] = claim.target_worktree_path
            successor_payload.pop(coordination_claims.SESSION_TAKEOVER_RESERVATION_FIELD, None)
            successor_payload.update(
                {
                    "status": "active",
                    "session_id": successor_session_id,
                    "heartbeat_at": updated_at,
                    "expires_at": _renewed_lease_expiry(updated_at, claim.expires_at),
                    "updated_at": updated_at,
                    "notes": note or "session resumed with a fresh runtime attachment",
                }
            )
            successor_claim = coordination_claims.normalize_claim(
                successor_payload,
                source_file=str(claim_file.resolve()),
            )
            if successor_claim is None:
                raise ValueError("resumed claim could not be normalized before tracker transfer")
            tracker_payload = yaml.safe_load(tracker_bytes_before)
            if not isinstance(tracker_payload, dict):
                raise TypeError("session tracker predecessor state must be a YAML mapping")
            if transfer_preflight is not None:
                tracker_payload = outcome_selection.build_prepared_outcome_session_transfer_payload(
                    transfer_preflight,
                    tracker_payload=tracker_payload,
                    predecessor_claim=claim,
                    successor_claim=successor_claim,
                    current_phase=current_phase,
                    notes=successor_payload["notes"],
                    updated_at=updated_at,
                )
                transfer_receipt = transfer_preflight.transfer
            else:
                tracker_claim = tracker_payload.get("claim")
                tracker_section = tracker_payload.get("tracker")
                timestamps = tracker_payload.get("timestamps")
                if not isinstance(tracker_claim, dict) or tracker_claim.get("session_id") != claim.session_id:
                    raise ValueError("session tracker predecessor identity does not match the claim")
                if not isinstance(tracker_section, dict) or not isinstance(timestamps, dict):
                    raise ValueError("session tracker is missing tracker or timestamps state")
                tracker_claim["session_id"] = successor_session_id
                tracker_section["current_phase"] = current_phase
                tracker_section["notes"] = successor_payload["notes"]
                timestamps["updated_at"] = updated_at

            successor_claim_bytes = yaml_bytes(successor_payload)
            successor_tracker_bytes = yaml_bytes(tracker_payload)
            if process_fence is None:
                raise ValueError("Codex transfer journal requires typed process-fence evidence")
            journal = {
                "record_type": "claim_session_transfer_journal",
                "predecessor_session_id": claim.session_id,
                "successor_session_id": successor_session_id,
                "worktree_path": str(Path(worktree_path).expanduser().resolve()),
                "branch": branch,
                "claim_epoch_sha256": reservation["claim_epoch_sha256"],
                "transferred_at": updated_at,
                "process_fence_receipt_path": process_fence.get("receipt_path"),
                "process_fence_receipt_sha256": process_fence.get("receipt_sha256"),
                "predecessor_tracker_sha256": hashlib.sha256(tracker_bytes_before).hexdigest(),
                "predecessor_tracker_bytes_base64": base64.b64encode(tracker_bytes_before).decode("ascii"),
                "successor_claim_sha256": hashlib.sha256(successor_claim_bytes).hexdigest(),
                "successor_claim_bytes_base64": base64.b64encode(successor_claim_bytes).decode("ascii"),
                "successor_tracker_sha256": hashlib.sha256(successor_tracker_bytes).hexdigest(),
                "successor_tracker_bytes_base64": base64.b64encode(successor_tracker_bytes).decode("ascii"),
            }
            journalized_reservation = dict(reservation)
            journalized_reservation[SESSION_TRANSFER_JOURNAL_FIELD] = journal
            journalized_claim = dict(current)
            journalized_claim[coordination_claims.SESSION_TAKEOVER_RESERVATION_FIELD] = journalized_reservation
            registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
            _write_claim_payload(claim_file, journalized_claim)
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
            current_claim_bytes = claim_file.read_bytes()
            current = journalized_claim
            reservation = journalized_reservation
            raw_journal = journal
        elif not isinstance(raw_journal, dict):
            raise TypeError("session takeover reservation has malformed transfer journal state")

        assert isinstance(raw_journal, dict)
        predecessor_tracker_bytes, successor_claim_bytes, successor_tracker_bytes = validate_journal(
            raw_journal, reservation=reservation
        )
        current_tracker_bytes = tracker_path.read_bytes()
        if current_tracker_bytes not in {predecessor_tracker_bytes, successor_tracker_bytes}:
            raise ValueError("session tracker changed outside the durable custody journal")

        transferred_at = raw_journal.get("transferred_at")
        if not isinstance(transferred_at, str) or not transferred_at:
            raise ValueError("session transfer journal lacks its transfer timestamp")
        claim_session_transfer = _persist_claim_session_transfer_receipt(
            claim=claim,
            project=project,
            scope=scope,
            worktree_path=worktree_path,
            branch=branch,
            successor_session_id=successor_session_id,
            transferred_at=transferred_at,
            prior_claim_bytes=current_claim_bytes,
            successor_claim_bytes=successor_claim_bytes,
            process_fence=process_fence,
            predecessor_process_pid=predecessor_process_pid,
            predecessor_process_start_ticks=predecessor_process_start_ticks,
            process_fence_transfer_epoch_sha256=reservation.get("claim_epoch_sha256"),
        )
        if current_tracker_bytes != successor_tracker_bytes:
            _atomic_restore_bytes(tracker_path, successor_tracker_bytes)

        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        _atomic_restore_bytes(claim_file, successor_claim_bytes)
        successor_payload = yaml.safe_load(successor_claim_bytes)
        if not isinstance(successor_payload, dict):
            raise TypeError("session transfer journal successor claim must be a YAML mapping")
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
            session_id=successor_session_id,
            projection_digest_after=projection_digest_after,
        )
    return successor_payload, transfer_receipt, claim_session_transfer


def _validate_same_runtime_tracker_identity(
    *,
    claim: coordination_claims.ClaimRecord,
    tracker_path: Path,
    tracker_payload: dict[str, Any],
) -> None:
    """Require exact claim and tracker custody before reattaching a lost path."""

    tracker_claim = tracker_payload.get("claim")
    if not isinstance(tracker_claim, dict):
        raise TypeError(f"Session tracker at {tracker_path} is missing claim metadata")

    expected = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "branch": claim.branch,
    }
    mismatches = [field for field, value in expected.items() if tracker_claim.get(field) != value]
    for field in ("repo_root", "worktree_path"):
        claim_value = getattr(claim, field)
        tracker_value = tracker_claim.get(field)
        if (
            not isinstance(claim_value, str)
            or not isinstance(tracker_value, str)
            or Path(claim_value).expanduser().resolve() != Path(tracker_value).expanduser().resolve()
        ):
            mismatches.append(field)
    tracker_custody = tracker_claim.get("tracker_path")
    if (
        not isinstance(tracker_custody, str)
        or Path(tracker_custody).expanduser().resolve() != tracker_path.expanduser().resolve()
    ):
        mismatches.append("tracker_path")
    if mismatches:
        raise ValueError("Exact session tracker does not match claim custody: " + ", ".join(sorted(set(mismatches))))


def _reattach_same_runtime_tracker(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_file: Path,
    tracker_path: Path,
    current_phase: str,
    note: str | None,
    updated_at: str,
    expected_fields: dict[str, Any],
) -> dict[str, Any]:
    """Atomically restore a uniquely identified tracker path and resume its lane."""

    claim_bytes_before = claim_file.read_bytes()
    tracker_bytes_before = tracker_path.read_bytes()
    with (
        coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR),
        session_contracts.session_tracker_lock(tracker_path),
    ):
        if claim_file.read_bytes() != claim_bytes_before:
            raise ValueError("claim changed after same-runtime tracker reattachment preflight")
        if tracker_path.read_bytes() != tracker_bytes_before:
            raise ValueError("session tracker changed after same-runtime reattachment preflight")
        current = yaml.safe_load(claim_bytes_before)
        if not isinstance(current, dict):
            raise ValueError("same-runtime reattachment claim must be a YAML mapping")
        for field, expected in expected_fields.items():
            if current.get(field) != expected:
                raise ValueError(f"claim field {field} changed after same-runtime reattachment preflight")
        tracker_payload = session_contracts.read_session_tracker(tracker_path)
        _validate_same_runtime_tracker_identity(
            claim=claim,
            tracker_path=tracker_path,
            tracker_payload=tracker_payload,
        )
        tracker_section = tracker_payload.get("tracker")
        timestamps = tracker_payload.get("timestamps")
        if not isinstance(tracker_section, dict) or not isinstance(timestamps, dict):
            raise ValueError("session tracker is missing tracker or timestamps state")
        current.update(
            {
                "status": "active",
                "session_id": claim.session_id,
                "tracker_path": str(tracker_path),
                "heartbeat_at": updated_at,
                "expires_at": _renewed_lease_expiry(updated_at, claim.expires_at),
                "updated_at": updated_at,
                "notes": note or "session resumed with its exact tracker reattached",
            }
        )
        tracker_section["current_phase"] = current_phase
        tracker_section["notes"] = current["notes"]
        timestamps["updated_at"] = updated_at
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        try:
            _write_claim_payload(claim_file, current)
            session_contracts._atomic_write_session_tracker(tracker_path, tracker_payload)
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
        except Exception:
            rollback_registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
            _atomic_restore_bytes(claim_file, claim_bytes_before)
            _atomic_restore_bytes(tracker_path, tracker_bytes_before)
            _projection_path, rollback_projection_digest = coordination_claims.refresh_prewrite_authority_projection(
                coordination_claims.CLAIMS_DIR
            )
            coordination_claims.record_claim_mutation(
                operation="session_upsert",
                claims_dir=coordination_claims.CLAIMS_DIR,
                registry_digest_before=rollback_registry_digest_before,
                target_project=claim.primary_project(),
                target_scope=claim.scope,
                target_claim_path=claim_file,
                session_id=claim.session_id,
                projection_digest_after=rollback_projection_digest,
            )
            raise
    return current


def _persist_claim_session_transfer_receipt(
    *,
    claim: coordination_claims.ClaimRecord,
    project: str,
    scope: str,
    worktree_path: str,
    branch: str,
    successor_session_id: str,
    transferred_at: str,
    prior_claim_bytes: bytes,
    successor_claim_bytes: bytes,
    process_fence: dict[str, Any] | None,
    predecessor_process_pid: int | None,
    predecessor_process_start_ticks: int | None,
    process_fence_transfer_epoch_sha256: str | None,
) -> dict[str, Any]:
    """Persist one immutable, digest-bound receipt for cross-session claim custody."""

    prior_session_id = claim.session_id
    if not prior_session_id or prior_session_id == successor_session_id:
        raise ValueError("Claim custody transfer requires distinct predecessor and successor sessions")
    if not claim.repo_root:
        raise ValueError("Claim custody transfer requires the canonical repository root")
    if (
        claim.agent == "codex"
        and claim.status != coordination_claims.SESSION_ENDED_STATUS
        and process_fence is None
    ):
        raise ValueError("Codex custody transfer requires exact predecessor process-fence evidence")
    process_fence_binding: dict[str, object] | None = None
    if process_fence is not None:
        if predecessor_process_pid is None or predecessor_process_start_ticks is None:
            raise ValueError("process-fence evidence requires the exact requested predecessor PID generation")
        receipt_path_raw = process_fence.get("receipt_path")
        receipt_sha256 = process_fence.get("receipt_sha256")
        if not isinstance(receipt_path_raw, str) or not isinstance(receipt_sha256, str):
            raise ValueError("process-fence evidence lacks an exact receipt path and digest")
        process_receipt_path = Path(receipt_path_raw).expanduser().resolve()
        process_receipt_bytes = process_receipt_path.read_bytes()
        if hashlib.sha256(process_receipt_bytes).hexdigest() != receipt_sha256:
            raise ValueError("process-fence receipt digest does not match its exact bytes")
        parsed_fence = session_process_fencing.ProcessFenceReceiptV1.model_validate_json(process_receipt_bytes)
        if process_fence_transfer_epoch_sha256 is None:
            raise ValueError("process-fence evidence lacks its reserved predecessor claim epoch")
        expected_transfer_epoch = process_fence_transfer_epoch_sha256
        expected_worktree = str(Path(worktree_path).expanduser().resolve())
        expected_fields = {
            "predecessor_session_id": prior_session_id,
            "successor_session_id": successor_session_id,
            "worktree_path": expected_worktree,
            "pid": predecessor_process_pid,
            "process_start_ticks": predecessor_process_start_ticks,
            "transfer_epoch_sha256": expected_transfer_epoch,
        }
        parsed_fields = {
            "predecessor_session_id": parsed_fence.predecessor_session_id,
            "successor_session_id": parsed_fence.successor_session_id,
            "worktree_path": parsed_fence.worktree_path,
            "pid": parsed_fence.pid,
            "process_start_ticks": parsed_fence.process_start_ticks,
            "transfer_epoch_sha256": parsed_fence.transfer_epoch_sha256,
        }
        returned_fields = {
            key: process_fence.get(key)
            for key in (
                "predecessor_session_id",
                "successor_session_id",
                "worktree_path",
                "pid",
                "process_start_ticks",
                "transfer_epoch_sha256",
            )
        }
        if parsed_fields != expected_fields or parsed_fields != returned_fields:
            raise ValueError("typed process-fence receipt does not match the exact transfer inputs and result")
        process_fence_binding = {
            "receipt_path": str(process_receipt_path),
            "receipt_sha256": receipt_sha256,
            "pid": parsed_fence.pid,
            "transfer_epoch_sha256": parsed_fence.transfer_epoch_sha256,
            "process_start_ticks": parsed_fence.process_start_ticks,
        }
    payload = {
        "schema_version": "1.0",
        "record_type": "claim_session_custody_transfer",
        "action": "session_resume",
        "project": project,
        "scope": scope,
        "repo_root": str(Path(claim.repo_root).expanduser().resolve()),
        "worktree_path": str(Path(worktree_path).expanduser().resolve()),
        "branch": branch,
        "prior_session_id": prior_session_id,
        "successor_session_id": successor_session_id,
        "transferred_at": transferred_at,
        "prior_claim_sha256": hashlib.sha256(prior_claim_bytes).hexdigest(),
        "successor_claim_sha256": hashlib.sha256(successor_claim_bytes).hexdigest(),
        "predecessor_process_fence": process_fence_binding,
    }
    canonical = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    receipt_sha256 = hashlib.sha256(canonical).hexdigest()
    receipt_root = coordination_claims.CLAIMS_DIR.expanduser().resolve().parent / "session-custody-transfers-v1"
    receipt_path = receipt_root / f"{receipt_sha256[:32]}.json"
    if receipt_path.exists():
        if receipt_path.read_bytes() != canonical:
            raise ValueError(f"Claim custody receipt collision at {receipt_path}")
    else:
        receipt_root.mkdir(parents=True, exist_ok=True, mode=0o700)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "wb",
                dir=receipt_root,
                prefix=f".{receipt_path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                handle.write(canonical)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, receipt_path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
    return {
        "receipt": payload,
        "receipt_path": str(receipt_path),
        "receipt_sha256": receipt_sha256,
    }


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
        coordination_claims.reject_mutation_during_session_takeover(
            current,
            operation=str(operation),
        )
        for field, expected in (expected_fields or {}).items():
            if current.get(field) != expected:
                raise ValueError(
                    f"Claim at {claim_file} changed while preparing {operation}; retry from current ownership state"
                )
        if claim.broad_scope_mode == "bootstrap" and claim.target_worktree_path:
            # Legacy bootstrap records stored the authorization sentinel as
            # canonical identity. Any sanctioned mutation migrates that raw
            # record to the physical identity already exposed by normalization.
            current["worktree_path"] = claim.target_worktree_path
        current.update(updates)
        _projection_path, projection_digest_after = _write_claim_and_refresh_projection(
            claim_file, current, coordination_claims.CLAIMS_DIR
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
    plan_repo_root: str | None = None,
    plan_start_point: str | None = None,
    ttl_hours: float = coordination_claims.DEFAULT_TTL_HOURS,
    allow_parallel: bool = False,
    broad_scope_mode: str | None = None,
    broad_scope_reason: str | None = None,
    target_worktree_path: str | None = None,
    new_files: list[str] | None = None,
    staged_reservation: coordination_claims.ClaimRecord | None = None,
    maintenance_snapshot: _MaintenanceRefreshSnapshot | None = None,
    registry_lock_held: bool = False,
    verified_goal_default_revision: str | None = None,
    verified_maintenance_default_revision: str | None = None,
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
            plan_repo_root=plan_repo_root,
            plan_start_point=plan_start_point,
            ttl_hours=ttl_hours,
            allow_parallel=allow_parallel,
            broad_scope_mode=broad_scope_mode,
            broad_scope_reason=broad_scope_reason,
            target_worktree_path=target_worktree_path,
            new_files=new_files,
            require_native_session_binding=True,
            verified_goal_default_revision=verified_goal_default_revision,
            verified_maintenance_default_revision=verified_maintenance_default_revision,
        )
        if not ok:
            raise ValueError(message)
        return "created"

    registry_context = nullcontext() if registry_lock_held else coordination_claims.claim_registry_lock()
    with registry_context:
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
        if maintenance_snapshot is not None and path.read_bytes() != maintenance_snapshot.claim_bytes:
            raise ValueError(
                "sanctioned maintenance provenance changed during session refresh; retry from current state"
            )

        effective_claim_type = claim_type or existing.claim_type
        effective_write_paths = existing.write_paths if write_paths is None else write_paths
        effective_read_paths = existing.read_paths if read_paths is None else read_paths
        effective_parent_scope = existing.parent_scope if parent_scope is None else parent_scope
        effective_work_graph_path = existing.work_graph_path if work_graph_path is None else work_graph_path
        effective_work_unit_id = existing.work_unit_id if work_unit_id is None else work_unit_id
        effective_plan_repo_root = existing.plan_repo_root if plan_repo_root is None else plan_repo_root
        effective_plan_start_point = existing.plan_revision if plan_start_point is None else plan_start_point
        effective_broad_scope_mode = existing.broad_scope_mode if broad_scope_mode is None else broad_scope_mode
        effective_broad_scope_reason = existing.broad_scope_reason if broad_scope_reason is None else broad_scope_reason
        effective_target_worktree_path = (
            existing.target_worktree_path if target_worktree_path is None else target_worktree_path
        )
        effective_new_files = list(existing.new_files) if new_files is None else new_files
        if start_revision is not None and existing.start_revision not in {None, start_revision}:
            raise ValueError(f"Claim at {path} retains start revision {existing.start_revision}, not {start_revision}")
        effective_start_revision = existing.start_revision or start_revision
        work_graph_sha256 = existing.work_graph_sha256
        approval_revisions = existing.approval_revisions
        plan_sha256 = existing.plan_sha256
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
            binding = coordination_claims.coerce_canonical_work_unit_binding(
                coordination_claims.resolve_canonical_work_unit_binding(
                    repo_root=repo_root,
                    plan_ref=plan_ref,
                    work_graph_path=effective_work_graph_path,
                    work_unit_id=effective_work_unit_id,
                    start_point=effective_start_revision or "HEAD",
                    plan_repo_root=effective_plan_repo_root,
                    plan_start_point=effective_plan_start_point,
                    target_repository_id=project,
                )
            )
            work_graph_sha256 = binding.work_graph_sha256
            approval_revisions = binding.approval_revisions
            resolved_start_revision = binding.start_revision
            if effective_start_revision is not None and resolved_start_revision != effective_start_revision:
                raise ValueError("session upsert resolved a different start revision than the existing claim")
            effective_start_revision = resolved_start_revision
            if existing.plan_repo_root not in {None, binding.plan_repo_root}:
                raise ValueError("session upsert resolved a different plan repository than the existing claim")
            if existing.plan_revision not in {None, binding.plan_revision}:
                raise ValueError("session upsert resolved a different plan revision than the existing claim")
            if existing.plan_sha256 not in {None, binding.plan_sha256}:
                raise ValueError("session upsert resolved a different plan digest than the existing claim")
            effective_plan_repo_root = binding.plan_repo_root
            effective_plan_start_point = binding.plan_revision
            plan_sha256 = binding.plan_sha256
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
            plan_repo_root=effective_plan_repo_root,
            plan_revision=effective_plan_start_point,
            plan_sha256=plan_sha256 if effective_plan_repo_root is not None else None,
            parallel_root_authorized=(allow_parallel or existing.parallel_root_authorized),
            broad_scope_mode=effective_broad_scope_mode,
            broad_scope_reason=effective_broad_scope_reason,
            target_worktree_path=effective_target_worktree_path,
            new_files=effective_new_files,
            # Ordinary refreshes preserve an existing legacy schema until the
            # caller supplies v6-only metadata.  This keeps a tracker attach or
            # heartbeat-equivalent upsert from becoming an implicit migration.
            schema_version=(
                6
                if any((effective_broad_scope_mode, effective_broad_scope_reason, effective_target_worktree_path))
                else existing.schema_version
            ),
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
            "projects": [project],
            "scope": scope,
            "intent": intent,
            "plan_ref": plan_ref,
            "repo_root": repo_root,
            "worktree_path": candidate.worktree_path,
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
        if candidate.new_files:
            payload["new_files"] = list(candidate.new_files)
        else:
            payload.pop("new_files", None)
        if "project" in refreshed_payload:
            payload["project"] = project
        for field, value in (
            ("broad_scope_mode", candidate.broad_scope_mode),
            ("broad_scope_reason", candidate.broad_scope_reason),
            ("target_worktree_path", candidate.target_worktree_path),
        ):
            if value is None:
                payload.pop(field, None)
            else:
                payload[field] = value
        if effective_start_revision is not None:
            payload["start_revision"] = effective_start_revision
        else:
            payload.pop("start_revision", None)
        if effective_plan_repo_root is not None:
            payload["plan_repo_root"] = effective_plan_repo_root
            payload["plan_revision"] = effective_plan_start_point
            payload["plan_sha256"] = plan_sha256
        else:
            for field in ("plan_repo_root", "plan_revision", "plan_sha256"):
                payload.pop(field, None)
        _projection_path, projection_digest_after = _write_claim_and_refresh_projection(
            path, payload, coordination_claims.CLAIMS_DIR
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
    if result.disposition != "defer" or result.reason_code != "selection_pending" or result.evidence is None:
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
    plan_repo_root: str | None,
    plan_start_point: str | None,
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
        plan_repo_root=claim.plan_repo_root,
        plan_revision=claim.plan_revision,
        plan_sha256=claim.plan_sha256,
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
        "plan_repo_root": claim.plan_repo_root
        if plan_repo_root is None
        else str(Path(plan_repo_root).expanduser().resolve()),
        "plan_revision": claim.plan_revision if plan_start_point is None else plan_start_point,
        "plan_sha256": claim.plan_sha256,
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
        "plan_repo_root": claim.plan_repo_root,
        "plan_revision": claim.plan_revision,
        "plan_sha256": claim.plan_sha256,
        "parallel_root_authorized": claim.parallel_root_authorized,
    }
    mismatches = sorted(name for name, value in requested_fields.items() if existing_fields[name] != value)
    if mismatches:
        raise ValueError(
            "selection-pending activation may attach only a tracker; caller changed: " + ", ".join(mismatches)
        )


def _claim_status(claim: coordination_claims.ClaimRecord) -> str:
    """Return the current persisted status string for one claim."""

    return claim.status


def _require_claim_actor(
    claim: coordination_claims.ClaimRecord,
    *,
    actor_session_id: str | None,
) -> str:
    """Require the exact native actor before a lane lifecycle mutation."""

    resolved = coordination_claims.resolve_session_id(claim.agent, actor_session_id)
    if not resolved:
        raise ValueError("lifecycle mutation requires an exact actor_session_id")
    coordination_claims.validate_native_session_binding(
        claim.agent,
        resolved,
        require_native_marker=True,
    )
    if claim.session_id != resolved:
        raise ValueError(
            f"claim {claim.primary_project()}:{claim.scope} belongs to session "
            f"{claim.session_id or '<missing>'}, not actor {resolved}; use sanctioned "
            "session-resume before mutating another runtime's lane"
        )
    return resolved


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


def _claim_snapshot_any_status(
    *,
    agent: str,
    project: str,
    scope: str,
) -> tuple[coordination_claims.ClaimRecord, dict[str, Any], Path, bytes]:
    """Load one exact claim-byte snapshot regardless of lifecycle status."""

    claim_file = _claim_path(agent, project, scope)
    try:
        claim_bytes = claim_file.read_bytes()
    except FileNotFoundError:
        raise ValueError(f"Claim file missing for {agent} → {project}:{scope}")
    payload = yaml.safe_load(claim_bytes)
    if not isinstance(payload, dict):
        raise TypeError(f"Claim file invalid for {agent} → {project}:{scope}")
    claim = coordination_claims.normalize_claim(payload, source_file=str(claim_file))
    if claim is None:
        raise ValueError(f"Claim file invalid for {agent} → {project}:{scope}")
    return claim, payload, claim_file, claim_bytes


def _claim_record_any_status(
    *,
    agent: str,
    project: str,
    scope: str,
) -> tuple[coordination_claims.ClaimRecord, dict[str, Any], Path]:
    """Load one claim regardless of current lifecycle status."""

    claim, payload, claim_file, _claim_bytes = _claim_snapshot_any_status(
        agent=agent,
        project=project,
        scope=scope,
    )
    return claim, payload, claim_file


def _resolve_claim_repo_root(claim: coordination_claims.ClaimRecord) -> Path:
    """Return the canonical repo root for one claim."""

    if claim.worktree_path:
        worktree_repo_root = resolve_canonical_repo_root(Path(claim.worktree_path).expanduser())
        if (worktree_repo_root / ".git").is_dir():
            return worktree_repo_root
    if claim.repo_root:
        return resolve_canonical_repo_root(Path(claim.repo_root).expanduser())
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


def _validate_worktree_path_repair(
    *,
    recorded_worktree_path: str,
    provided_worktree_path: str,
    branch: str,
) -> None:
    """Fail closed before accepting a corrected ``worktree_path`` on resume.

    A worktree legitimately relocated from a non-standard path to the
    sanctioned ``<repo>/worktrees/<branch>/`` convention leaves its claim's
    recorded ``worktree_path`` stale. Nothing before this could repair that
    pointer: a fresh claim on the same scope refuses because the existing one
    is not overwritable while non-live, ``session-close`` requires the exact
    owning runtime, and plain resume requires the caller's path to match the
    stale record exactly. Observed 2026-09-08:
    ``open_web_retrieval:case001/tool-adoption`` ended with worktree_path
    recorded at a non-standard location that no longer existed, while the
    real worktree -- with the real committed work -- already lived at the
    correct convention path.

    This mirrors ``session_archive_tracker.py``'s own safety contract rather
    than inventing a new one: the recorded path must be genuinely gone (not
    merely different), and the provided replacement must be a real linked
    worktree actually checked out on the exact claimed branch. Neither
    condition trusts the caller's say-so.
    """

    recorded_path = Path(recorded_worktree_path).expanduser()
    if recorded_path.exists():
        raise ValueError(
            f"Refusing to repair worktree_path: the recorded path {recorded_worktree_path} "
            "still exists on disk. Repair only applies when the recorded worktree is "
            "genuinely gone; if two worktrees exist, resolve that first."
        )

    provided_path = Path(provided_worktree_path).expanduser()
    git_marker = provided_path / ".git"
    if not git_marker.is_file():
        raise ValueError(
            f"Refusing to repair worktree_path: {provided_worktree_path} is not a linked "
            "git worktree (expected a '.git' file, not a directory or nothing at all)."
        )
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=str(provided_path),
        capture_output=True,
        text=True,
        check=False,
    )
    actual_branch = result.stdout.strip()
    if result.returncode != 0 or actual_branch != branch:
        raise ValueError(
            f"Refusing to repair worktree_path: {provided_worktree_path} is checked out on "
            f"{actual_branch or 'an unresolvable ref'!r}, not the claimed branch {branch!r}."
        )


_HUNK_HEADER_OFFSETS_RE = re.compile(rb"^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@")


def _patch_without_blob_identity(patch: bytes) -> bytes:
    """Remove full-index blob IDs and hunk-header line offsets while preserving
    the complete patch body.

    Both are position metadata, not content: a squash merge that lands on a
    main tip already advanced by an unrelated earlier change to the same file
    reproduces the identical added/removed lines, but git's own diff embeds
    the surrounding line numbers in the `@@ -a,b +c,d @@` header, and those
    numbers legitimately differ between the task branch's own diff (against
    its own base) and the merge commit's diff (against the new base) even
    though nothing about the actual change is different. Comparing raw diff
    bytes without normalizing this shift makes a genuinely exact squash merge
    look unproven whenever anything else landed on the same file first --
    observed directly the same day this normalization was added, on this
    exact function's own file after an unrelated PR landed just ahead of it.
    """

    normalized: list[bytes] = []
    for line in patch.splitlines(keepends=True):
        if line.startswith(b"index "):
            continue
        if line.startswith(b"@@ "):
            line = _HUNK_HEADER_OFFSETS_RE.sub(b"@@ -N,N +N,N @@", line, count=1)
        normalized.append(line)
    return b"".join(normalized)


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


def _discover_squash_merge_commit(
    repo_root: Path,
    *,
    branch_ref: str,
    default_ref: str,
    candidate_cap: int = 100,
) -> str | None:
    """Find the squash-merge commit for a branch, or None.

    The proof in _squash_merge_matches_branch was always here, but it only ran
    when the operator hand-supplied --merge-commit, and nobody knows a squash SHA
    offhand. So in practice a squash-merged lane could not be closed by the
    sanctioned route at all, and both project-meta and enforced-planning squash by
    default. Their lanes accumulated until the claim bootstrap refused to open any
    new lane -- "requires the native session to own zero existing claim roots" --
    naming two lanes whose work was already merged and which this same preflight
    would not let anyone close. Enforcement whose remedy is unreachable.

    This supplies the input only. Every candidate must still pass the existing
    patch-equality proof, so discovery cannot approve anything a hand-supplied SHA
    would not have. Candidates are bounded to commits on the canonical default
    branch that are absent from the task branch and that touch the paths the branch
    changed, so an unmerged branch finds nothing rather than matching by accident.
    """

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", *args], cwd=str(repo_root), capture_output=True, text=True, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    merge_base = git("merge-base", branch_ref, default_ref)
    if not merge_base:
        return None
    changed_paths = [
        line for line in git("diff", "--name-only", f"{merge_base}..{branch_ref}").splitlines() if line
    ]
    if not changed_paths:
        return None
    candidates = git(
        "rev-list", f"--max-count={candidate_cap}", default_ref, f"^{branch_ref}", "--", *changed_paths
    ).splitlines()
    for candidate in candidates:
        if candidate and _squash_merge_matches_branch(
            repo_root, branch_ref=branch_ref, merge_commit=candidate, default_ref=default_ref
        ):
            return candidate
    return None


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
    retain_canonical_default_branch: bool = False,
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
        if normalized_disposition == MERGED_DISPOSITION:
            raise ValueError(
                f"Cannot record disposition '{MERGED_DISPOSITION}' because branch '{branch}' "
                "is missing and its integration into the canonical default branch cannot be proven. "
                "Restore the branch from durable evidence, or use an explicit non-merge disposition "
                "with its required recovery or discard authorization."
            )
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
    if branch == default_branch and not retain_canonical_default_branch:
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
        canonical_default_ref = default_remote_ref if remote_default_exists else default_ref
        discovered_merge_commit = False
        if not merged_to_default and not normalized_merge_commit:
            normalized_merge_commit = _discover_squash_merge_commit(
                repo_root, branch_ref=branch_ref, default_ref=canonical_default_ref
            )
            discovered_merge_commit = normalized_merge_commit is not None
        if not merged_to_default and normalized_merge_commit:
            if _squash_merge_matches_branch(
                repo_root,
                branch_ref=branch_ref,
                merge_commit=normalized_merge_commit,
                default_ref=canonical_default_ref,
            ):
                merged_to_default = True
                merge_evidence = (
                    "squash_patch_equivalent_discovered"
                    if discovered_merge_commit
                    else "squash_patch_equivalent"
                )
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


def _detached_canonical_preflight(
    *, repo_root: Path, disposition: str, disposition_reason: str | None,
    recovery_ref: str | None, head_commit: str,
) -> CloseoutPreflight:
    """Archive metadata for a retained pin only with independent remote history."""
    if disposition != "archived" or not disposition_reason or not disposition_reason.strip():
        raise ValueError("Detached canonical closeout requires disposition=archived and a reason.")
    if not recovery_ref or not recovery_ref.startswith("refs/remotes/"):
        raise ValueError("Detached canonical closeout requires an independent remote recovery ref.")
    if not _ref_exists(repo_root, recovery_ref) or not _is_ancestor(repo_root, head_commit, recovery_ref):
        raise ValueError("Detached canonical recovery ref does not contain the retained HEAD commit.")
    if _git_capture(repo_root, "rev-parse", "--verify", "HEAD^{commit}").strip() != head_commit:
        raise ValueError("Detached canonical HEAD changed during closeout preflight.")
    return CloseoutPreflight(
        disposition=disposition, branch_exists=False,
        default_branch=push_safety.resolve_default_branch(repo_root),
        merged_to_default=None, default_remote_ref=None, default_branch_pushed=None,
        merge_commit=None, merge_evidence=None, recovery_ref=recovery_ref,
        force_delete_branch=False,
    )


def _captured_lane_preflight(
    *,
    repo_root: Path,
    branch: str | None,
    disposition: str,
    disposition_reason: str | None,
    capture: dict[str, Any],
) -> CloseoutPreflight:
    """Preflight for a tracker-absent lane whose uncommitted state was captured (#2010).

    The worktree and branch are retained, so nothing is deleted; the operator
    must still name a recovery-required disposition and reason, and the
    verified capture ref must contain the exact branch tip.
    """

    normalized = disposition.strip().lower()
    if normalized not in RECOVERY_REQUIRED_DISPOSITIONS:
        supported = ", ".join(sorted(RECOVERY_REQUIRED_DISPOSITIONS))
        raise ValueError(
            "A session-ended lane with captured uncommitted changes requires a recovery-required "
            f"disposition ({supported}); found {disposition!r}."
        )
    if not disposition_reason or not disposition_reason.strip():
        raise ValueError(f"Disposition '{normalized}' requires --disposition-reason.")
    if not branch or not _branch_exists(repo_root, branch):
        raise ValueError("Captured-lane closeout requires the claimed branch to exist.")
    branch_ref = f"refs/heads/{branch}"
    head = _git_capture(repo_root, "rev-parse", "--verify", f"{branch_ref}^{{commit}}").strip()
    if head != capture["branch_head"] or not _is_ancestor(repo_root, branch_ref, capture["recovery_ref"]):
        raise ValueError("Captured recovery ref no longer contains the exact branch tip; recapture the lane.")
    default_branch = push_safety.resolve_default_branch(repo_root)
    default_remote_ref = f"refs/remotes/origin/{default_branch}" if default_branch else None
    merged = (
        _is_ancestor(repo_root, branch_ref, default_remote_ref)
        if default_remote_ref and _ref_exists(repo_root, default_remote_ref)
        else None
    )
    return CloseoutPreflight(
        disposition=normalized,
        branch_exists=True,
        default_branch=default_branch,
        merged_to_default=merged,
        default_remote_ref=default_remote_ref,
        default_branch_pushed=None,
        merge_commit=None,
        merge_evidence=None,
        recovery_ref=capture["recovery_ref"],
        force_delete_branch=False,
    )


def _is_closed_lane_placeholder(path: Path) -> bool:
    """Return whether ``path`` is the empty directory a closed lane leaves behind."""

    try:
        return path.is_dir() and not any(path.iterdir())
    except OSError:
        return False


def _leave_closed_lane_placeholder(worktree_path: Path) -> None:
    """Recreate the removed lane path as an empty directory.

    Another live agent session (a parent of the closing subagent, or a sibling)
    can still record the lane as its working directory; that location is held
    inside the agent client, not in any OS process this closeout can see or
    move. When the path vanished, the CC Safety Net hook refused every tool
    call in those sessions until a human restarted them (process_tracing,
    2026-10-05; project-meta policy friction session-close-deletes-active-cwd).
    An empty directory keeps their working directory valid, and ``git worktree
    add`` accepts an empty target, so the lane name stays reusable.
    """

    try:
        worktree_path.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _remove_worktree_path(repo_root: Path, worktree_path: Path) -> str:
    """Remove one worktree path from a safe root-anchored control session."""

    if not worktree_path.exists() or _is_closed_lane_placeholder(worktree_path):
        return "already_missing"
    if _cwd_inside(worktree_path):
        os.chdir(repo_root)
    result = subprocess.run(
        ["git", "worktree", "remove", str(worktree_path)],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 and "working trees containing submodules" in (
        result.stderr or result.stdout
    ):
        # Git requires --force even for a clean linked worktree merely because
        # it has initialized submodules. Closeout has already proved the tree
        # clean, the branch integrated (or durably disposed), and filesystem
        # access safe, so this retry does not weaken the data-loss boundary.
        result = subprocess.run(
            ["git", "worktree", "remove", "--force", str(worktree_path)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    if result.returncode != 0:
        raise RuntimeError((result.stderr or result.stdout).strip())
    _leave_closed_lane_placeholder(worktree_path)
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


@dataclass(frozen=True)
class _MaintenanceRefreshSnapshot:
    """Immutable maintenance-bootstrap state observed before session refresh."""

    claim: coordination_claims.ClaimRecord
    claim_path: Path
    claim_bytes: bytes
    tracker_path: Path
    tracker_bytes: bytes


def _validate_locked_sanctioned_maintenance_refresh(
    existing_claim: coordination_claims.ClaimRecord,
    *,
    claim_path: Path,
    claim_bytes: bytes,
    tracker_path: Path,
    tracker_bytes: bytes,
    existing_tracker: dict[str, Any],
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
    current_phase: str,
    intended_next_phases: list[str] | None,
    depends_on_repos: list[str] | None,
    requires_shared_infra_changes: bool | None,
    stop_conditions: list[str] | None,
    notes: str | None,
    claim_type: str | None,
    write_paths: list[str] | None,
    read_paths: list[str] | None,
    parent_scope: str | None,
    work_graph_path: str | None,
    work_unit_id: str | None,
    start_revision: str | None,
    plan_repo_root: str | None,
    plan_start_point: str | None,
    allow_unplanned: bool,
    allow_parallel: bool,
    broad_scope_mode: str | None,
    broad_scope_reason: str | None,
    target_worktree_path: str | None,
    tracker_dir: Path,
) -> _MaintenanceRefreshSnapshot | None:
    """Validate immutable refresh inputs against one locked claim/tracker snapshot."""

    effective_start_revision = existing_claim.start_revision if start_revision is None else start_revision
    attaching_bootstrap_start_revision = (
        existing_claim.start_revision is None
        and start_revision is not None
        and existing_claim.plan_ref == "UNPLANNED"
        and current_phase == "maintenance-bootstrap"
    )
    if attaching_bootstrap_start_revision:
        coordination_claims.validate_start_revision_targets(
            repo_root=repo_root,
            start_revision=start_revision,
            branch=branch,
            worktree_path=worktree_path,
            require_branch=True,
            require_worktree=True,
        )
    effective_plan_repo_root = existing_claim.plan_repo_root if plan_repo_root is None else plan_repo_root
    effective_plan_revision = existing_claim.plan_revision if plan_start_point is None else plan_start_point
    effective_broad_scope_mode = existing_claim.broad_scope_mode if broad_scope_mode is None else broad_scope_mode
    effective_broad_scope_reason = (
        existing_claim.broad_scope_reason if broad_scope_reason is None else broad_scope_reason
    )
    effective_target_worktree_path = (
        existing_claim.target_worktree_path if target_worktree_path is None else target_worktree_path
    )
    contract = session_contracts.SessionContract.build(
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
        start_revision=effective_start_revision,
        plan_repo_root=effective_plan_repo_root,
        plan_revision=effective_plan_revision,
        plan_sha256=existing_claim.plan_sha256 if effective_plan_repo_root is not None else None,
        allow_unplanned=allow_unplanned,
    )
    candidate_tracker_path = (
        session_contracts.session_tracker_path(
            contract,
            tracker_dir=tracker_dir,
        )
        .expanduser()
        .resolve()
    )
    expected_tracker_path = tracker_path.expanduser().resolve()
    existing_tracker_fields = existing_tracker.get("tracker")
    if not isinstance(existing_tracker_fields, dict):
        raise ValueError("sanctioned maintenance tracker is missing execution metadata")
    effective_intended_next_phases = (
        existing_tracker_fields.get("intended_next_phases") if intended_next_phases is None else intended_next_phases
    )
    effective_depends_on_repos = (
        existing_tracker_fields.get("depends_on_repos") if depends_on_repos is None else depends_on_repos
    )
    effective_requires_shared_infra_changes = (
        existing_tracker_fields.get("requires_shared_infra_changes")
        if requires_shared_infra_changes is None
        else requires_shared_infra_changes
    )
    effective_stop_conditions = (
        existing_tracker_fields.get("stop_conditions") if stop_conditions is None else stop_conditions
    )
    effective_notes = existing_tracker_fields.get("notes") if notes is None else notes
    candidate_tracker = session_contracts.build_session_tracker(
        contract=contract.with_tracker_path(str(candidate_tracker_path)),
        current_phase=current_phase,
        intended_next_phases=effective_intended_next_phases,
        depends_on_repos=effective_depends_on_repos,
        requires_shared_infra_changes=effective_requires_shared_infra_changes,
        stop_conditions=effective_stop_conditions,
        notes=effective_notes,
    )

    immutable_inputs: dict[str, tuple[Any, Any]] = {
        "agent": (agent, existing_claim.agent),
        "project": (project, existing_claim.primary_project()),
        "scope": (scope, existing_claim.scope),
        "intent": (intent, existing_claim.intent),
        "plan_ref": (contract.plan_ref, existing_claim.plan_ref),
        "repo_root": (repo_root, existing_claim.repo_root),
        "worktree_path": (worktree_path, existing_claim.worktree_path),
        "branch": (branch, existing_claim.branch),
        "session_id": (session_id, existing_claim.session_id),
        "session_name": (contract.session_name, existing_claim.session_name),
        "broader_goal": (broader_goal, existing_claim.broader_goal),
        "tracker_path": (str(candidate_tracker_path), str(expected_tracker_path)),
        "claim_type": (claim_type or existing_claim.claim_type, existing_claim.claim_type),
        "write_paths": (existing_claim.write_paths if write_paths is None else write_paths, existing_claim.write_paths),
        "read_paths": (existing_claim.read_paths if read_paths is None else read_paths, existing_claim.read_paths),
        "parent_scope": (parent_scope, existing_claim.parent_scope),
        "work_graph_path": (work_graph_path, existing_claim.work_graph_path),
        "work_unit_id": (work_unit_id, existing_claim.work_unit_id),
        "start_revision": (
            existing_claim.start_revision
            if attaching_bootstrap_start_revision
            else effective_start_revision,
            existing_claim.start_revision,
        ),
        "plan_repo_root": (contract.plan_repo_root, existing_claim.plan_repo_root),
        "plan_revision": (contract.plan_revision, existing_claim.plan_revision),
        "allow_parallel": (allow_parallel, existing_claim.parallel_root_authorized),
        "broad_scope_mode": (effective_broad_scope_mode, existing_claim.broad_scope_mode),
        "broad_scope_reason": (effective_broad_scope_reason, existing_claim.broad_scope_reason),
        "target_worktree_path": (effective_target_worktree_path, existing_claim.target_worktree_path),
    }
    candidate_tracker_fields = candidate_tracker.tracker_fields()
    for field in session_contracts.TRACKER_ONLY_FIELD_NAMES:
        if field != "current_phase":
            immutable_inputs[f"tracker.{field}"] = (
                candidate_tracker_fields[field],
                existing_tracker_fields.get(field),
            )
    mismatches = sorted(field for field, (candidate, existing) in immutable_inputs.items() if candidate != existing)
    if mismatches:
        raise ValueError("sanctioned maintenance refresh cannot change immutable provenance: " + ", ".join(mismatches))

    return _MaintenanceRefreshSnapshot(
        claim=existing_claim,
        claim_path=claim_path,
        claim_bytes=claim_bytes,
        tracker_path=expected_tracker_path,
        tracker_bytes=tracker_bytes,
    )


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
    requires_shared_infra_changes: bool | None = None,
    stop_conditions: list[str] | None = None,
    notes: str | None = None,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    parent_scope: str | None = None,
    work_graph_path: str | None = None,
    work_unit_id: str | None = None,
    start_revision: str | None = None,
    plan_repo_root: str | None = None,
    plan_start_point: str | None = None,
    tracker_dir: Path = session_contracts.DEFAULT_SESSION_TRACKERS_DIR,
    allow_unplanned: bool = False,
    allow_parallel: bool = False,
    broad_scope_mode: str | None = None,
    broad_scope_reason: str | None = None,
    target_worktree_path: str | None = None,
    new_files: list[str] | None = None,
    outcome_selected: bool = False,
    outcome_bootstrap_plan: int | None = None,
    outcome_admission_receipt_path: Path = (outcome_admission.DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH),
    verified_goal_default_revision: str | None = None,
    verified_maintenance_default_revision: str | None = None,
) -> dict[str, Any]:
    """Create or refresh the session contract plus linked tracker artifact."""

    # Claim creation has always enforced SUPPORTED_AGENTS; tracker creation
    # never did. That asymmetry is what produced 23 permanently stranded
    # trackers between 2026-07-24 and 2026-08-21, written with legacy per-lane
    # identities such as 'codex-evidence-reader-wiki' and 'codex-root'. A
    # tracker naming an agent the claim registry will not accept can never have
    # a matching claim, so session-close cannot reach it -- it loads the claim
    # first -- and it becomes residue the moment its worktree is removed.
    #
    # Validating here closes the write path. `validate_native_session_binding`
    # below does not catch this: STRICT_NATIVE_SESSION_ENV_KEYS.get(agent)
    # returns None for an unknown agent, so it silently no-ops rather than
    # rejecting the name.
    if agent not in coordination_claims.SUPPORTED_AGENTS:
        supported = ", ".join(coordination_claims.SUPPORTED_AGENTS)
        raise ValueError(
            f"start_session refuses an unsupported agent {agent!r}: a tracker naming an "
            f"agent the claim registry will not accept can never be closed through "
            f"session-close, because that path loads the claim first. Use one of: {supported}. "
            "A per-lane or per-task identity belongs in scope or session_name, not agent."
        )

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    exact_existing_claims = _iter_matching_live_claims(agent=agent, project=project, scope=scope)
    if len(exact_existing_claims) > 1:
        raise ValueError(f"Multiple live claims found for {agent} → {project}:{scope}")
    existing_claim = exact_existing_claims[0] if exact_existing_claims else None
    configured_outcome_mode = outcome_admission.load_outcome_admission_mode(Path(worktree_path))
    explicit_unplanned_maintenance = (
        allow_unplanned
        and plan_ref in {None, session_contracts.UNPLANNED_PLAN_REF}
        and outcome_bootstrap_plan is None
        and not outcome_selected
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
                    plan_repo_root=plan_repo_root,
                    plan_start_point=plan_start_point,
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
                detail = f": {staged.resolution_error_message}" if staged.resolution_error_message is not None else ""
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

    if start_revision is None and existing_claim is not None:
        start_revision = existing_claim.start_revision
    if (
        write_paths
        and coordination_claims.requires_work_graph(plan_ref)
        and existing_claim is None
        and start_revision is None
    ):
        raise ValueError("new plan-bound session start requires one full --start-revision")

    contract_plan_repo_root = existing_claim.plan_repo_root if existing_claim is not None else None
    contract_plan_revision = existing_claim.plan_revision if existing_claim is not None else None
    contract_plan_sha256 = existing_claim.plan_sha256 if existing_claim is not None else None
    if (
        existing_claim is None
        and write_paths
        and coordination_claims.requires_work_graph(plan_ref)
        and plan_repo_root is not None
    ):
        if not work_graph_path or not work_unit_id:
            raise ValueError("Plan-bound write ownership requires --work-graph and --work-unit-id")
        binding = coordination_claims.coerce_canonical_work_unit_binding(
            coordination_claims.resolve_canonical_work_unit_binding(
                repo_root=repo_root,
                plan_ref=plan_ref or "",
                work_graph_path=work_graph_path,
                work_unit_id=work_unit_id,
                start_point=start_revision or "HEAD",
                plan_repo_root=plan_repo_root,
                plan_start_point=plan_start_point,
                target_repository_id=project,
            )
        )
        contract_plan_repo_root = binding.plan_repo_root
        contract_plan_revision = binding.plan_revision
        contract_plan_sha256 = binding.plan_sha256

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
        plan_repo_root=contract_plan_repo_root,
        plan_revision=contract_plan_revision,
        plan_sha256=contract_plan_sha256,
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
        requires_shared_infra_changes=bool(requires_shared_infra_changes),
        stop_conditions=stop_conditions,
        notes=notes,
    )
    claim_slot_path = _claim_path(agent, project, scope)
    maintenance_snapshot: _MaintenanceRefreshSnapshot | None = None

    def upsert_claim(*, registry_lock_held: bool = False) -> str:
        return _upsert_session_claim(
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
            plan_repo_root=plan_repo_root,
            plan_start_point=plan_start_point,
            allow_parallel=allow_parallel,
            broad_scope_mode=broad_scope_mode,
            broad_scope_reason=broad_scope_reason,
            target_worktree_path=target_worktree_path,
            new_files=new_files,
            staged_reservation=staged_reservation,
            maintenance_snapshot=maintenance_snapshot,
            registry_lock_held=registry_lock_held,
            verified_goal_default_revision=verified_goal_default_revision,
            verified_maintenance_default_revision=verified_maintenance_default_revision,
        )

    existing_action: str | None = None
    if existing_claim is not None:
        with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
            if not claim_slot_path.is_file():
                raise ValueError(
                    "session refresh lost the initially live claim before locked reload; refusing recreation"
                )
            locked_claim_bytes = claim_slot_path.read_bytes()
            locked_claim_payload = yaml.safe_load(locked_claim_bytes)
            locked_claim = (
                coordination_claims.normalize_claim(
                    locked_claim_payload,
                    source_file=str(claim_slot_path),
                )
                if isinstance(locked_claim_payload, dict)
                else None
            )
            if locked_claim is None:
                raise ValueError("session refresh could not reload the initially live claim; refusing recreation")
            initial_owner = (
                existing_claim.agent,
                tuple(existing_claim.projects),
                existing_claim.scope,
                existing_claim.session_id,
            )
            locked_owner = (
                locked_claim.agent,
                tuple(locked_claim.projects),
                locked_claim.scope,
                locked_claim.session_id,
            )
            if locked_owner != initial_owner:
                raise ValueError(
                    "session refresh observed a different claim owner during locked reload; refusing replacement"
                )
            if not locked_claim.is_live():
                raise ValueError(
                    "session refresh observed that the initially live claim ended before locked reload; "
                    "refusing reactivation"
                )
            if locked_claim.tracker_path:
                # A truthy tracker_path here means "a real tracker file
                # already exists" -- never "a path reserved for one about to
                # be written." A caller that pre-sets tracker_path on a fresh
                # claim before writing the file hits FileNotFoundError below.
                # See "tracker_path's three lifecycle states" in
                # docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md.
                locked_tracker_path = Path(locked_claim.tracker_path).expanduser().resolve()
                with session_contracts.session_tracker_lock(locked_tracker_path):
                    locked_tracker_bytes = locked_tracker_path.read_bytes()
                    locked_tracker_payload = yaml.safe_load(locked_tracker_bytes)
                    if outcome_admission.is_sanctioned_maintenance_claim_payload(
                        locked_claim,
                        locked_tracker_payload,
                        tracker_path=locked_tracker_path,
                    ):
                        assert isinstance(locked_tracker_payload, dict)
                        maintenance_snapshot = _validate_locked_sanctioned_maintenance_refresh(
                            locked_claim,
                            claim_path=claim_slot_path,
                            claim_bytes=locked_claim_bytes,
                            tracker_path=locked_tracker_path,
                            tracker_bytes=locked_tracker_bytes,
                            existing_tracker=locked_tracker_payload,
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
                            current_phase=current_phase,
                            intended_next_phases=intended_next_phases,
                            depends_on_repos=depends_on_repos,
                            requires_shared_infra_changes=requires_shared_infra_changes,
                            stop_conditions=stop_conditions,
                            notes=notes,
                            claim_type=claim_type,
                            write_paths=write_paths,
                            read_paths=read_paths,
                            parent_scope=parent_scope,
                            work_graph_path=work_graph_path,
                            work_unit_id=work_unit_id,
                            start_revision=start_revision,
                            plan_repo_root=plan_repo_root,
                            plan_start_point=plan_start_point,
                            allow_unplanned=allow_unplanned,
                            allow_parallel=allow_parallel,
                            broad_scope_mode=broad_scope_mode,
                            broad_scope_reason=broad_scope_reason,
                            target_worktree_path=target_worktree_path,
                            tracker_dir=tracker_dir,
                        )
                        tracker_section = locked_tracker_payload.get("tracker")
                        tracker_claim_section = locked_tracker_payload.get("claim")
                        timestamps = locked_tracker_payload.get("timestamps")
                        if (
                            not isinstance(tracker_claim_section, dict)
                            or not isinstance(tracker_section, dict)
                            or not isinstance(timestamps, dict)
                        ):
                            raise ValueError(
                                "sanctioned maintenance tracker is missing claim, execution, or timestamp metadata"
                            )
                        if locked_claim.start_revision is None and contract.start_revision is not None:
                            tracker_claim_section["start_revision"] = contract.start_revision
                        tracker_section["current_phase"] = tracker.current_phase
                        timestamps["updated_at"] = tracker.updated_at
                        session_contracts._atomic_write_session_tracker(
                            locked_tracker_path,
                            locked_tracker_payload,
                        )
                        tracker_bytes_written = locked_tracker_path.read_bytes()
                        try:
                            existing_action = upsert_claim(registry_lock_held=True)
                        except Exception as claim_error:
                            claim_bytes_after = claim_slot_path.read_bytes() if claim_slot_path.is_file() else None
                            if claim_bytes_after == locked_claim_bytes:
                                if locked_tracker_path.read_bytes() != tracker_bytes_written:
                                    raise RuntimeError(
                                        "session claim update failed and exact tracker rollback was incomplete: "
                                        f"claim={claim_error}; rollback=session tracker changed inside locked refresh"
                                    ) from claim_error
                                _atomic_restore_bytes(locked_tracker_path, locked_tracker_bytes)
                            raise
                    elif outcome_admission.has_sanctioned_maintenance_claim_identity(locked_claim):
                        raise ValueError(
                            "explicit UNPLANNED maintenance claim has malformed locked tracker provenance; "
                            "refusing generic refresh"
                        )
            if existing_action is None:
                generic_claim_bytes = locked_claim_bytes
                generic_tracker_preexisting = tracker_path.is_file()
                generic_tracker_bytes = tracker_path.read_bytes() if generic_tracker_preexisting else None
                session_contracts.write_session_tracker(tracker, tracker_dir=tracker_dir)
                generic_tracker_written = tracker_path.read_bytes()
                try:
                    existing_action = upsert_claim(registry_lock_held=True)
                except Exception as claim_error:
                    claim_bytes_after = claim_slot_path.read_bytes() if claim_slot_path.is_file() else None
                    if claim_bytes_after == generic_claim_bytes:
                        try:
                            with session_contracts.session_tracker_lock(tracker_path):
                                if tracker_path.read_bytes() != generic_tracker_written:
                                    raise ValueError(
                                        "session tracker changed inside locked existing-claim refresh; "
                                        "refusing unsafe rollback"
                                    )
                                if generic_tracker_preexisting:
                                    assert generic_tracker_bytes is not None
                                    _atomic_restore_bytes(tracker_path, generic_tracker_bytes)
                                else:
                                    tracker_path.unlink(missing_ok=True)
                        except Exception as rollback_error:
                            raise RuntimeError(
                                "session claim update failed and exact tracker rollback was incomplete: "
                                f"claim={claim_error}; rollback={rollback_error}"
                            ) from claim_error
                    raise
    if existing_action is not None:
        action = existing_action
    else:
        claim_bytes_before = claim_slot_path.read_bytes() if claim_slot_path.is_file() else None
        tracker_preexisting = tracker_path.is_file()
        tracker_bytes_before = tracker_path.read_bytes() if tracker_preexisting else None
        session_contracts.write_session_tracker(tracker, tracker_dir=tracker_dir)
        tracker_bytes_written = tracker_path.read_bytes()
        try:
            action = upsert_claim()
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
                            raise ValueError(
                                "session tracker changed after this start attempt; refusing unsafe rollback"
                            )
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


def _require_delegation_session_id(agent: str, session_id: str, *, field: str) -> str:
    """Require one exact native-client identity without accepting nested prefixes."""

    if re.fullmatch(rf"{re.escape(agent)}:[^:]+", session_id) is None:
        raise ValueError(f"{field} must be one canonical {agent}:<native-id> identity")
    return session_id


def _locked_delegation_parent(
    *,
    agent: str,
    project: str,
    parent_scope: str,
    parent_session_id: str,
    repo_root: str,
    active_claims: list[coordination_claims.ClaimRecord],
) -> coordination_claims.ClaimRecord:
    """Return the exact healthy program root that may delegate one child lane."""

    matches = [
        claim
        for claim in active_claims
        if claim.agent == agent
        and claim.primary_project() == project
        and claim.scope == parent_scope
        and claim.session_id == parent_session_id
    ]
    if len(matches) != 1:
        raise ValueError("delegation requires exactly one live parent claim owned by the native parent session")
    parent = matches[0]
    if parent.claim_type != "program" or parent.parent_scope is not None:
        raise ValueError("delegation parent must be one unparented program claim")
    if not parent.repo_root or Path(parent.repo_root).expanduser().resolve() != Path(repo_root).expanduser().resolve():
        raise ValueError("delegation parent and child must use the same canonical repository")
    if coordination_claims.claim_runtime_status(parent, active_claims=active_claims) != "healthy":
        raise ValueError("delegation parent claim is not healthy")
    return parent


def start_delegated_session(
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
    parent_scope: str,
    parent_session_id: str,
    child_session_id: str,
    start_revision: str,
    write_paths: list[str],
    session_name: str | None = None,
    tracker_dir: Path = session_contracts.DEFAULT_SESSION_TRACKERS_DIR,
    notes: str | None = None,
    **legacy_fixed_fields: Any,
) -> dict[str, Any]:
    """Create one narrow child claim using its authenticated parent as actor."""

    compatible_fixed_fields = {
        "plan_ref": {None, session_contracts.UNPLANNED_PLAN_REF},
        "claim_type": {None, "write"},
        "allow_unplanned": {True},
        "allow_parallel": {False, None},
        "broad_scope_mode": {None},
        "broad_scope_reason": {None},
        "target_worktree_path": {None},
        "work_graph_path": {None},
        "work_unit_id": {None},
        "plan_repo_root": {None},
        "plan_start_point": {None},
        "read_paths": {None, ()},
    }
    forbidden: dict[str, Any] = {}
    for key, value in legacy_fixed_fields.items():
        comparable = tuple(value) if isinstance(value, list) else value
        if key not in compatible_fixed_fields or comparable not in compatible_fixed_fields[key]:
            forbidden[key] = value
    if forbidden:
        raise ValueError("delegated session received unsupported authority fields: " + ", ".join(sorted(forbidden)))
    parent_session_id = _require_delegation_session_id(agent, parent_session_id, field="parent_session_id")
    child_session_id = _require_delegation_session_id(agent, child_session_id, field="child_session_id")
    if parent_session_id == child_session_id:
        raise ValueError("delegated child session must differ from its parent session")
    coordination_claims.validate_native_session_binding(
        agent,
        parent_session_id,
        require_native_marker=True,
    )
    if scope != branch:
        raise ValueError("delegated scope must equal its task branch")
    delegated_goal = f"Delegated maintenance: {branch.replace('-', ' ').replace('/', ' ')}"
    if intent != delegated_goal or broader_goal != delegated_goal:
        raise ValueError(f"delegated intent and broader_goal must equal {delegated_goal!r}")
    normalized_paths = list(dict.fromkeys(coordination_claims._normalize_repo_path(path) for path in write_paths))
    if not normalized_paths or "." in normalized_paths:
        raise ValueError("delegated write ownership must be non-empty and narrower than the repository root")
    if coordination_claims.classify_broad_write_paths(repo_root, normalized_paths):
        raise ValueError("delegated write ownership must use narrow file or nested-directory paths")
    coordination_claims.validate_start_revision_targets(
        repo_root=repo_root,
        start_revision=start_revision,
        branch=branch,
        worktree_path=worktree_path,
        require_branch=True,
        require_worktree=True,
    )
    contract = session_contracts.SessionContract.build(
        agent=agent,
        project=project,
        scope=scope,
        intent=intent,
        plan_ref=session_contracts.UNPLANNED_PLAN_REF,
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch=branch,
        session_id=child_session_id,
        broader_goal=broader_goal,
        session_name=session_name,
        start_revision=start_revision,
        allow_unplanned=True,
    )
    tracker_path = session_contracts.session_tracker_path(contract, tracker_dir=tracker_dir).expanduser().resolve()
    contract = contract.with_tracker_path(str(tracker_path))
    now = datetime.now(timezone.utc)
    tracker = session_contracts.build_session_tracker(
        contract=contract,
        current_phase=current_phase,
        notes=notes,
        now=now,
    )
    event = coordination_claims.build_progress_event(
        progress_kind="claim_started",
        evidence_ref=scope,
        next_action=intent,
        progress_at=now,
    )
    claim_path = _claim_path(agent, project, scope)
    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        active_claims = coordination_claims.check_claims()
        _locked_delegation_parent(
            agent=agent,
            project=project,
            parent_scope=parent_scope,
            parent_session_id=parent_session_id,
            repo_root=repo_root,
            active_claims=active_claims,
        )
        if any(claim.session_id == child_session_id for claim in active_claims):
            raise ValueError("delegated child session already owns a live claim")
        if claim_path.exists():
            raise ValueError(f"delegated child claim slot already exists: {project}:{scope}")
        if tracker_path.exists():
            raise ValueError("delegated child tracker path already exists")
        coordination_claims.validate_start_revision_targets(
            repo_root=repo_root,
            start_revision=start_revision,
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
            plan_ref=session_contracts.UNPLANNED_PLAN_REF,
            claim_type="write",
            write_paths=normalized_paths,
            read_paths=[],
            worktree_path=worktree_path,
            repo_root=repo_root,
            branch=branch,
            session_name=contract.session_name,
            broader_goal=broader_goal,
            tracker_path=str(tracker_path),
            session_id=child_session_id,
            heartbeat_at=now.isoformat(),
            parent_scope=parent_scope,
            notes=notes,
            claimed_at=now.isoformat(),
            expires_at=(now + timedelta(hours=coordination_claims.DEFAULT_TTL_HOURS)).isoformat(),
            updated_at=now.isoformat(),
            start_revision=start_revision,
            schema_version=6,
            **coordination_claims._progress_event_payload(event),
        )
        coordination_claims.validate_claim_for_creation(candidate)
        coordination_claims.validate_no_preserved_lane_conflict(
            candidate,
            claims=coordination_claims.list_claims(include_inactive=True),
        )
        coordination_claims.validate_claim_hierarchy_for_creation(candidate, active_claims=active_claims)
        coordination_claims.validate_session_root_for_creation(candidate, active_claims=active_claims)
        conflicts = coordination_claims.evaluate_claim(candidate, active_claims=active_claims)
        if conflicts.hard_conflicts:
            owners = ", ".join(f"{item.other_agent}:{item.other_scope}" for item in conflicts.hard_conflicts)
            raise ValueError(f"delegated write ownership conflicts with {owners}")
        claim_payload = candidate.to_dict()
        claim_payload.pop("source_file", None)
        claim_payload.pop("project", None)
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        from enforced_planning.prewrite_claim_fast import projection_path_for

        projection_path = projection_path_for(coordination_claims.CLAIMS_DIR)
        projection_before = projection_path.read_bytes() if projection_path.exists() else None
        tracker_preexisting = tracker_path.is_file()
        tracker_before = tracker_path.read_bytes() if tracker_preexisting else None
        session_contracts.write_session_tracker(tracker, tracker_dir=tracker_dir)
        tracker_written = tracker_path.read_bytes()
        try:
            _projection_path, projection_digest = coordination_claims._replace_claim_and_refresh_projection_fail_atomic(
                claim_path=claim_path,
                payload=claim_payload,
                claims_dir=coordination_claims.CLAIMS_DIR,
            )
            coordination_claims.record_claim_mutation(
                operation="create",
                claims_dir=coordination_claims.CLAIMS_DIR,
                registry_digest_before=registry_digest_before,
                target_project=project,
                target_scope=scope,
                target_claim_path=claim_path,
                session_id=child_session_id,
                projection_digest_after=projection_digest,
            )
        except Exception as claim_error:
            try:
                claim_after = claim_path.read_bytes() if claim_path.exists() else None
                projection_after = projection_path.read_bytes() if projection_path.exists() else None
                if claim_after is not None:
                    coordination_claims._atomic_restore_file(claim_path, None)
                if projection_after != projection_before:
                    coordination_claims._atomic_restore_file(projection_path, projection_before)
                with session_contracts.session_tracker_lock(tracker_path):
                    if tracker_path.read_bytes() != tracker_written:
                        raise ValueError("delegated tracker changed after creation; refusing unsafe rollback")
                    if tracker_preexisting:
                        assert tracker_before is not None
                        _atomic_restore_bytes(tracker_path, tracker_before)
                    else:
                        tracker_path.unlink(missing_ok=True)
            except Exception as rollback_error:
                raise RuntimeError(
                    "delegated claim creation failed and tracker rollback was incomplete: "
                    f"claim={claim_error}; rollback={rollback_error}"
                ) from claim_error
            raise
    persisted = _single_matching_live_claim(agent=agent, project=project, scope=scope)
    if not outcome_admission.is_sanctioned_delegated_maintenance_claim(persisted):
        raise RuntimeError("delegated child persisted without its exact sanctioned provenance")
    return {
        "action": "delegated_created",
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "scope": scope,
        "tracker_path": str(tracker_path),
        "start_revision": start_revision,
    }


def revoke_delegated_session(
    *,
    agent: str,
    project: str,
    scope: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    parent_scope: str,
    parent_session_id: str,
    child_session_id: str,
    expected_start_revision: str,
    tracker_path: str,
    note: str | None = None,
) -> dict[str, Any]:
    """Cancel one pristine delegated child using its authenticated parent."""

    parent_session_id = _require_delegation_session_id(agent, parent_session_id, field="parent_session_id")
    child_session_id = _require_delegation_session_id(agent, child_session_id, field="child_session_id")
    if parent_session_id == child_session_id:
        raise ValueError("delegated child session must differ from its parent session")
    coordination_claims.validate_native_session_binding(
        agent,
        parent_session_id,
        require_native_marker=True,
    )
    claim_path = _claim_path(agent, project, scope)
    resolved_tracker_path = Path(tracker_path).expanduser().resolve()
    resolved_worktree = Path(worktree_path).expanduser().resolve()
    resolved_repo = Path(repo_root).expanduser().resolve()
    cancelled_note = note or "unused delegated child cancelled by its authenticated parent"
    with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
        active_claims = coordination_claims.check_claims()
        _locked_delegation_parent(
            agent=agent,
            project=project,
            parent_scope=parent_scope,
            parent_session_id=parent_session_id,
            repo_root=repo_root,
            active_claims=active_claims,
        )
        if not claim_path.is_file():
            raise ValueError(f"delegated child claim does not exist: {project}:{scope}")
        raw = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        child = coordination_claims.normalize_claim(raw, source_file=str(claim_path)) if isinstance(raw, dict) else None
        if child is None:
            raise ValueError("delegated child claim is invalid")
        expected = {
            "agent": agent,
            "project": project,
            "scope": scope,
            "session_id": child_session_id,
            "parent_scope": parent_scope,
            "repo_root": str(resolved_repo),
            "worktree_path": str(resolved_worktree),
            "branch": branch,
            "start_revision": expected_start_revision,
        }
        observed = {
            "agent": child.agent,
            "project": child.primary_project(),
            "scope": child.scope,
            "session_id": child.session_id,
            "parent_scope": child.parent_scope,
            "repo_root": str(Path(child.repo_root).expanduser().resolve()) if child.repo_root else None,
            "worktree_path": str(Path(child.worktree_path).expanduser().resolve()) if child.worktree_path else None,
            "branch": child.branch,
            "start_revision": child.start_revision,
        }
        mismatches = sorted(field for field, value in expected.items() if observed[field] != value)
        if mismatches:
            raise ValueError("delegated child identity changed before revoke: " + ", ".join(mismatches))
        if child.status not in {"active", "closing", "completed"}:
            raise ValueError(f"delegated child cannot be revoked from status {child.status!r}")
        if child.status in {"closing", "completed"} and (
            raw.get("disposition") != "superseded"
            or raw.get("disposition_reason") != "unused delegated child cancelled"
        ):
            raise ValueError("delegated child has a different in-progress closeout disposition")
        if not resolved_tracker_path.is_file():
            raise ValueError("delegated child tracker is missing")
        tracker_payload = yaml.safe_load(resolved_tracker_path.read_bytes())
        if not outcome_admission.is_sanctioned_delegated_maintenance_claim_payload(
            child,
            tracker_payload,
            tracker_path=resolved_tracker_path,
        ):
            raise ValueError("delegated child tracker or claim provenance is malformed")
        if child.status == "completed":
            _archived_claim, archive_receipt = coordination_claims._archive_completed_claim_locked(
                claim_path,
                claims_dir=coordination_claims.CLAIMS_DIR,
            )
            return {
                "action": "delegated_revoked",
                "parent_session_id": parent_session_id,
                "child_session_id": child_session_id,
                "worktree_action": "already_missing",
                "branch_action": "already_missing",
                "claim_archive_id": archive_receipt.archive_id,
                "tracker_path": str(resolved_tracker_path),
                "canonical_lock_reconciliation_required": True,
            }
        branch_exists = _branch_exists(resolved_repo, branch)
        worktree_exists = resolved_worktree.exists()
        if child.status == "active" and (not branch_exists or not worktree_exists):
            raise ValueError("active delegated child must retain both its branch and worktree")
        if branch_exists or worktree_exists:
            coordination_claims.validate_start_revision_targets(
                repo_root=resolved_repo,
                start_revision=expected_start_revision,
                branch=branch,
                worktree_path=str(resolved_worktree),
                require_branch=branch_exists,
                require_worktree=worktree_exists,
            )
        if worktree_exists:
            surface_runtime.assert_no_live_leases_for_worktree(resolved_worktree)
            clean, details = _worktree_is_clean(str(resolved_worktree))
            if not clean:
                raise ValueError(f"delegated child worktree is dirty; refusing revoke:\n{details}")
            _assert_worktree_removal_access(resolved_worktree)
        if child.write_paths:
            doc_authority.assert_no_unresolved_owned_obligations(child)

        closing_payload = dict(raw)
        closing_payload.update(
            {
                "status": "closing",
                "disposition": "superseded",
                "disposition_reason": "unused delegated child cancelled",
                "merged_to_default": None,
                "merge_evidence": None,
                "notes": cancelled_note,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        _projection_path, projection_digest = coordination_claims._replace_claim_and_refresh_projection_fail_atomic(
            claim_path=claim_path,
            payload=closing_payload,
            claims_dir=coordination_claims.CLAIMS_DIR,
        )
        coordination_claims.record_claim_mutation(
            operation="session_upsert",
            claims_dir=coordination_claims.CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=claim_path,
            session_id=child_session_id,
            projection_digest_after=projection_digest,
        )
        session_contracts.update_session_tracker(
            resolved_tracker_path,
            current_phase="cancelled",
            notes=cancelled_note,
            updated_at=closing_payload["updated_at"],
        )
        worktree_action = _remove_worktree_path(resolved_repo, resolved_worktree)
        branch_action = _delete_branch(resolved_repo, branch, force=True)
        closed_at = datetime.now(timezone.utc).isoformat()
        completed_payload = dict(closing_payload)
        completed_payload.update({"status": "completed", "closed_at": closed_at, "updated_at": closed_at})
        registry_digest_before = coordination_claims._registry_digest(coordination_claims.CLAIMS_DIR)
        _projection_path, projection_digest = coordination_claims._replace_claim_and_refresh_projection_fail_atomic(
            claim_path=claim_path,
            payload=completed_payload,
            claims_dir=coordination_claims.CLAIMS_DIR,
        )
        coordination_claims.record_claim_mutation(
            operation="closeout",
            claims_dir=coordination_claims.CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=claim_path,
            session_id=child_session_id,
            projection_digest_after=projection_digest,
        )
        _archived_claim, archive_receipt = coordination_claims._archive_completed_claim_locked(
            claim_path,
            claims_dir=coordination_claims.CLAIMS_DIR,
        )
    return {
        "action": "delegated_revoked",
        "parent_session_id": parent_session_id,
        "child_session_id": child_session_id,
        "worktree_action": worktree_action,
        "branch_action": branch_action,
        "claim_archive_id": archive_receipt.archive_id,
        "tracker_path": str(resolved_tracker_path),
        "canonical_lock_reconciliation_required": True,
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
    if not candidate_session_id:
        raise ValueError("Unable to resolve a session ID for heartbeat ownership")
    coordination_claims.validate_native_session_binding(
        agent,
        candidate_session_id,
        require_native_marker=True,
    )
    if outcome_selected:
        selected_claims = [
            claim
            for claim in _iter_matching_live_claims(
                agent=agent,
                project=project,
                scope=scope,
                branch=branch,
            )
            if claim.session_id == candidate_session_id
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


def narrow_session_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    write_paths: list[str],
    session_id: str | None = None,
) -> dict[str, Any]:
    """Narrow one live claim without renewing its heartbeat or expiry."""

    result = coordination_claims.narrow_claim(
        agent=agent,
        project=project,
        scope=scope,
        session_id=session_id,
        write_paths=write_paths,
        require_native_session_binding=True,
    )
    return {
        "action": "narrowed",
        **result.to_dict(),
        "coordination_mailbox": _poll_mailbox(
            agent=agent,
            project=project,
            session_id=result.session_id,
        ),
    }


def _blocker_claim_snapshots(
    *, project: str, goal_scope: str, claims_dir: Path
) -> tuple[ClaimQueueSnapshotV1, ...]:
    """Project the locked canonical registry into the accepted evaluator contract."""

    claims = coordination_claims.list_claims(project, claims_dir=claims_dir)
    snapshots: list[ClaimQueueSnapshotV1] = []
    for claim in claims:
        if claim.session_id is None:
            raise ValueError(f"live canonical claim {claim.scope} has no session identity")
        issues = [
            *coordination_claims.coordination_health_issues(claim, active_claims=claims),
            *coordination_claims.claim_liveness_issues(claim),
        ]
        if issues:
            raise ValueError(
                f"live canonical claim {claim.scope} is not current and healthy: "
                + ", ".join(issues)
            )
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
    if "#" not in goal_scope or goal_scope.split("#", 1)[0] != project:
        raise ValueError("blocker application requires a project-qualified goal scope")
    return tuple(snapshots)


def _blocker_application_id(
    *, expected: BlockerDecisionResultV1, agent: str, project: str, root_scope: str
) -> str:
    payload = {
        "disposition_id": expected.disposition.disposition_id,
        "ready_queue_evaluation_id": expected.ready_queue.evaluation_id,
        "agent": agent,
        "session_id": expected.ready_queue.session_id,
        "project": project,
        "root_scope": root_scope,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"blocker_application_{hashlib.sha256(canonical).hexdigest()[:32]}"


def _write_immutable_blocker_receipt(
    receipt: BlockerDispositionApplicationReceiptV1, *, receipt_dir: Path
) -> Path:
    """Publish one receipt without permitting replacement or conflicting replay."""

    resolved_dir = receipt_dir.expanduser().resolve()
    resolved_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = resolved_dir / f"{receipt.application_id}.json"
    canonical = (receipt.model_dump_json(indent=2) + "\n").encode("utf-8")
    if target.exists():
        existing = BlockerDispositionApplicationReceiptV1.model_validate_json(target.read_text())
        if existing != receipt:
            raise ValueError(f"blocker application receipt collision at {target}")
        return target
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb", dir=resolved_dir, prefix=f".{target.name}.", suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(canonical)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp_path, target)
        except FileExistsError:
            existing = BlockerDispositionApplicationReceiptV1.model_validate_json(target.read_text())
            if existing != receipt:
                raise ValueError(f"blocker application receipt collision at {target}")
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
    return target


def apply_blocker_disposition(
    *,
    decision_input: BlockerDecisionInputV1,
    expected_result: BlockerDecisionResultV1,
    repository_root: Path,
    agent: str,
    project: str,
    root_scope: str,
    actor_session_id: str | None = None,
    claims_dir: Path | None = None,
    receipt_dir: Path | None = None,
) -> dict[str, Any]:
    """Re-evaluate and consume one disposition against current canonical custody.

    Replay is idempotent.  New applications serialize graph/claim validation,
    scoped mutation, projection refresh, and immutable receipt publication under
    the canonical registry lock.  No branch, worktree, or dirty file is touched.
    """

    if decision_input.claim_snapshots:
        raise ValueError("blocker application rejects caller-supplied claim snapshots")
    if decision_input.mailbox_evidence or decision_input.request.mailbox_dependency:
        raise ValueError("blocker application rejects caller-supplied mailbox state")
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    resolved_receipt_dir = receipt_dir or DEFAULT_BLOCKER_DISPOSITION_RECEIPT_DIR
    session_id = coordination_claims.resolve_session_id(agent, actor_session_id)
    if session_id is None:
        raise ValueError("blocker application requires an exact native session identity")
    coordination_claims.validate_native_session_binding(agent, session_id, require_native_marker=True)
    if session_id != decision_input.request.session_id:
        raise ValueError("blocker request belongs to a different runtime session")

    application_id = _blocker_application_id(
        expected=expected_result, agent=agent, project=project, root_scope=root_scope
    )
    receipt_path = resolved_receipt_dir.expanduser().resolve() / f"{application_id}.json"
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        if receipt_path.exists():
            receipt = BlockerDispositionApplicationReceiptV1.model_validate_json(receipt_path.read_text())
            identity = (receipt.agent, receipt.session_id, receipt.project, receipt.root_scope)
            if identity != (agent, session_id, project, root_scope):
                raise ValueError(f"blocker application receipt collision at {receipt_path}")
            if (
                receipt.disposition_id != expected_result.disposition.disposition_id
                or receipt.ready_queue_evaluation_id != expected_result.ready_queue.evaluation_id
            ):
                raise ValueError("existing blocker application receipt does not match expected decision")
            return {
                **receipt.model_dump(mode="json"),
                "receipt_path": str(receipt_path),
                "receipt_sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                "idempotent_replay": True,
            }

        claims = coordination_claims.list_claims(project, claims_dir=resolved_claims_dir)
        roots = [claim for claim in claims if claim.agent == agent and claim.scope == root_scope]
        if len(roots) != 1:
            raise ValueError(f"blocker application requires one live root claim for {project}:{root_scope}")
        root = roots[0]
        _require_claim_actor(root, actor_session_id=session_id)
        if root.plan_ref != decision_input.request.claim_scope:
            raise ValueError("root claim is not bound to the blocker request goal scope")
        if (
            root.work_graph_path != decision_input.work_graph_ref_path
            or root.work_graph_sha256 != decision_input.expected_work_graph_sha256
        ):
            raise ValueError("root claim is not bound to the blocker request graph bytes")

        snapshots = _blocker_claim_snapshots(
            project=project,
            goal_scope=decision_input.request.claim_scope,
            claims_dir=resolved_claims_dir,
        )
        canonical_input = decision_input.model_copy(update={"claim_snapshots": snapshots})
        actual = evaluate_blocker_request(canonical_input, repository_root=repository_root)
        expected_queue = expected_result.ready_queue.model_dump(mode="json", exclude={"evaluated_at"})
        actual_queue = actual.ready_queue.model_dump(mode="json", exclude={"evaluated_at"})
        expected_disposition = expected_result.disposition.model_dump(
            mode="json", exclude={"recorded_at"}
        )
        actual_disposition = actual.disposition.model_dump(mode="json", exclude={"recorded_at"})
        if expected_queue != actual_queue or expected_disposition != actual_disposition:
            raise ValueError("accepted blocker disposition is stale against current graph or claims")

        affected: list[coordination_claims.ClaimRecord] = [root]
        pending = {root.scope}
        while pending:
            parents = set(pending)
            pending.clear()
            for claim in claims:
                if (
                    claim not in affected
                    and claim.agent == agent
                    and claim.session_id == session_id
                    and claim.parent_scope in parents
                ):
                    affected.append(claim)
                    pending.add(claim.scope)

        action = actual.disposition.claim_action
        status = "handoff" if action == "handoff_scope" else coordination_claims.SESSION_ENDED_STATUS
        replacements: dict[Path, dict[str, Any]] = {}
        original_payloads: dict[Path, dict[str, Any]] = {}
        original_trackers: dict[Path, bytes] = {}
        recorded_at = datetime.now(UTC)
        registry_before = coordination_claims._registry_digest(resolved_claims_dir)
        projection_digest_after: str | None = None
        if action in {"handoff_scope", "retire_goal_scope"}:
            for claim in affected:
                if claim.source_file is None:
                    raise ValueError(f"claim {claim.scope} has no canonical source path")
                path = Path(claim.source_file).expanduser().resolve()
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                if not isinstance(raw, dict):
                    raise TypeError(f"claim {claim.scope} is not a YAML mapping")
                coordination_claims.reject_mutation_during_session_takeover(
                    raw, operation="blocker_disposition"
                )
                original_payloads[path] = dict(raw)
                raw.update(
                    {
                        "status": status,
                        "updated_at": recorded_at.isoformat(),
                        "notes": (
                            f"blocker disposition {actual.disposition.disposition_id}: "
                            f"{actual.disposition.resume_event}"
                        ),
                    }
                )
                replacements[path] = raw
            _projection_path, projection_digest_after = (
                coordination_claims.replace_claim_payloads_and_refresh_projection_fail_atomic(
                replacements=replacements, claims_dir=resolved_claims_dir
                )
            )
            try:
                for claim in affected:
                    if not claim.tracker_path:
                        continue
                    tracker_path = Path(claim.tracker_path).expanduser().resolve()
                    if not tracker_path.is_file():
                        continue
                    original_trackers[tracker_path] = tracker_path.read_bytes()
                    session_contracts.update_session_tracker(
                        tracker_path,
                        current_phase=(
                            "handoff required" if action == "handoff_scope"
                            else "session ended; goal-scope disposition recorded"
                        ),
                        notes=(
                            f"blocker disposition {actual.disposition.disposition_id}: "
                            f"{actual.disposition.resume_event}"
                        ),
                        updated_at=recorded_at.isoformat(),
                    )
            except Exception:  # noqa: BLE001 - every tracker failure rolls back authority
                for tracker_path, content in original_trackers.items():
                    _atomic_restore_bytes(tracker_path, content)
                coordination_claims.replace_claim_payloads_and_refresh_projection_fail_atomic(
                    replacements=original_payloads, claims_dir=resolved_claims_dir
                )
                raise

        registry_after = coordination_claims._registry_digest(resolved_claims_dir)
        receipt = BlockerDispositionApplicationReceiptV1(
            application_id=application_id,
            disposition_id=actual.disposition.disposition_id,
            ready_queue_evaluation_id=actual.ready_queue.evaluation_id,
            decision=actual.disposition.decision,
            claim_action=action,
            agent=agent,
            session_id=session_id,
            project=project,
            root_scope=root_scope,
            affected_scopes=tuple(sorted(claim.scope for claim in affected)) if replacements else (),
            registry_digest_before=registry_before,
            registry_digest_after=registry_after,
            work_graph_sha256=decision_input.expected_work_graph_sha256,
            result="applied" if replacements else "recorded_no_mutation",
            recorded_at=recorded_at,
        )
        try:
            stored_path = _write_immutable_blocker_receipt(receipt, receipt_dir=resolved_receipt_dir)
        except Exception:  # noqa: BLE001 - receipt publication failure rolls back authority
            for tracker_path, content in original_trackers.items():
                _atomic_restore_bytes(tracker_path, content)
            if original_payloads:
                coordination_claims.replace_claim_payloads_and_refresh_projection_fail_atomic(
                    replacements=original_payloads, claims_dir=resolved_claims_dir
                )
            raise

        if replacements:
            assert projection_digest_after is not None
            operation: claim_mutation_receipts.MutationOperation = (
                "session_upsert" if action == "handoff_scope" else "session_end"
            )
            for claim in affected:
                assert claim.source_file is not None
                coordination_claims.record_claim_mutation(
                    operation=operation,
                    claims_dir=resolved_claims_dir,
                    registry_digest_before=registry_before,
                    target_project=project,
                    target_scope=claim.scope,
                    target_claim_path=Path(claim.source_file),
                    session_id=session_id,
                    projection_digest_after=projection_digest_after,
                )
        return {
            **receipt.model_dump(mode="json"),
            "receipt_path": str(stored_path),
            "receipt_sha256": hashlib.sha256(stored_path.read_bytes()).hexdigest(),
            "idempotent_replay": False,
        }


def _status_sessions_locked(
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
        missing_tracker_file = False
        if claim.tracker_path:
            path = Path(claim.tracker_path).expanduser()
            tracker_payload = _read_session_tracker_for_status(path)
            missing_tracker_file = tracker_payload is None
        tracker_section = tracker_payload.get("tracker") if isinstance(tracker_payload, dict) else {}
        timestamps = tracker_payload.get("timestamps") if isinstance(tracker_payload, dict) else {}
        health_issues = coordination_claims.coordination_health_issues(
            claim,
            active_claims=project_claims,
        )
        if missing_tracker_file and "missing_tracker_file" not in health_issues:
            health_issues = [*health_issues, "missing_tracker_file"]
        claim_health_status = coordination_claims.claim_runtime_status(
            claim,
            active_claims=project_claims,
            now=observed_at,
        )
        if missing_tracker_file and claim_health_status != "stale":
            claim_health_status = "weak"
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
                "health_status": claim_health_status,
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
    """Observe claims and trackers without creating or pruning coordination artifacts."""

    claims_dir = coordination_claims.CLAIMS_DIR.expanduser().resolve()
    lock_path = claims_dir.parent / f".{claims_dir.name}.lock"
    for _attempt in range(_STATUS_OBSERVATION_ATTEMPTS):
        lock_fd = _shared_lock_fd_if_present(lock_path)
        if lock_fd is not None:
            try:
                return _status_sessions_locked(
                    project=project,
                    agent=agent,
                    scope=scope,
                    branch=branch,
                    session_id=session_id,
                    include_ended=include_ended,
                    now=now,
                )
            finally:
                _release_shared_lock(lock_fd)
        before = _claim_registry_observation_fingerprint(claims_dir)
        result = _status_sessions_locked(
            project=project,
            agent=agent,
            scope=scope,
            branch=branch,
            session_id=session_id,
            include_ended=include_ended,
            now=now,
        )
        after = _claim_registry_observation_fingerprint(claims_dir)
        if before == after and not lock_path.exists():
            return result
    raise RuntimeError("session status could not establish a stable read-only claim-registry snapshot")


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
    actor_session_id: str | None = None,
) -> dict[str, Any]:
    """Close out one session or fail loud if the worktree state is unsafe."""

    claim = _single_matching_live_claim(agent=agent, project=project, scope=scope)
    _require_claim_actor(claim, actor_session_id=actor_session_id)

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

    raise ValueError(
        "A clean claimed worktree cannot be terminally finished independently of its lane. "
        "Merge or explicitly disposition the branch, then use session-close so worktree, "
        "local branch, live claim, and terminal audit state close together."
    )


def _resolve_closeout_worktree_path(
    claim: coordination_claims.ClaimRecord,
    requested_worktree_path: str | None,
) -> Path:
    """Resolve physical cleanup to the real bootstrap target, never its sentinel."""

    return Path(requested_worktree_path or claim.target_worktree_path or claim.worktree_path or "").expanduser()


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
    reconcile_canonical_root: bool = False,
    reconcile_session_ended: bool = False,
    expected_claim_sha256: str | None = None,
    mailbox_disposition: str | None = None,
    mailbox_note: str | None = None,
    actor_session_id: str | None = None,
    terminalize_shared_child: bool = False,
    tracker_absent: bool = False,
    recovery_archive_dir: str | None = None,
) -> dict[str, Any]:
    """Finish, clean up, and release one claimed lane as a single sanctioned flow.

    This is the canonical closeout path for claimed worktrees. It is intentionally
    idempotent around already-missing worktree and branch state so that rerunning
    a partially completed closeout can still release the claim cleanly.
    """

    claim, payload, claim_file = _claim_record_any_status(agent=agent, project=project, scope=scope)
    reconciliation_modes = sum(
        bool(value)
        for value in (
            reconcile_missing_worktree,
            reconcile_canonical_root,
            reconcile_session_ended,
        )
    )
    if reconciliation_modes > 1:
        raise ValueError("Choose only one reconciliation mode per session-close invocation.")
    if tracker_absent and not reconcile_session_ended:
        raise ValueError("--tracker-absent is only valid with --reconcile-session-ended.")
    if recovery_archive_dir and not tracker_absent:
        raise ValueError("--recovery-archive-dir is only valid with --tracker-absent.")
    if not reconcile_session_ended:
        _require_claim_actor(claim, actor_session_id=actor_session_id)
    resolved_worktree_path = _resolve_closeout_worktree_path(claim, worktree_path)
    resolved_branch = branch or claim.branch
    repo_root = _resolve_claim_repo_root(claim)
    updated_at = datetime.now(timezone.utc).isoformat()

    session_ended_reconciliation = (
        _validate_session_ended_closeout_reconciliation(
            claim=claim,
            claim_file=claim_file,
            repo_root=repo_root,
            actor_session_id=actor_session_id,
            expected_claim_sha256=expected_claim_sha256,
            expected_tracker_sha256=expected_tracker_sha256,
            tracker_absent=tracker_absent,
        )
        if reconcile_session_ended
        else None
    )

    reconciliation_receipt = (
        _validate_missing_worktree_reconciliation(
            claim=claim,
            claim_file=claim_file,
            expected_tracker_sha256=expected_tracker_sha256,
            expected_claim_sha256=expected_claim_sha256,
        )
        if reconcile_missing_worktree
        else None
    )
    canonical_root_reconciliation = (
        _validate_canonical_root_reconciliation(
            claim=claim,
            claim_file=claim_file,
            repo_root=repo_root,
            expected_claim_sha256=expected_claim_sha256,
            expected_tracker_sha256=expected_tracker_sha256,
        )
        if reconcile_canonical_root
        else None
    )
    retained_parent_scope: str | None = None
    if terminalize_shared_child:
        if disposition != MERGED_DISPOSITION:
            raise ValueError("Shared child terminalization requires disposition=merged.")
        if not claim.parent_scope:
            raise ValueError("Shared child terminalization requires an exact parent_scope.")
        if not claim.worktree_path or not claim.branch:
            raise ValueError("Shared child terminalization requires exact worktree and branch custody.")
        recorded_worktree_path = Path(claim.worktree_path).expanduser().resolve()
        if worktree_path and Path(worktree_path).expanduser().resolve() != recorded_worktree_path:
            raise ValueError("Shared child worktree override does not match recorded custody.")
        if branch and branch != claim.branch:
            raise ValueError("Shared child branch override does not match recorded custody.")
        resolved_worktree_path = recorded_worktree_path
        resolved_branch = claim.branch
        canonical_worktree_path = recorded_worktree_path
        parent_matches = [
            sibling
            for sibling in coordination_claims.check_claims()
            if sibling.primary_project() == claim.primary_project()
            and sibling.scope == claim.parent_scope
            and sibling.worktree_path
            and Path(sibling.worktree_path).expanduser().resolve() == canonical_worktree_path
            and sibling.branch == resolved_branch
            and sibling.repo_root
            and Path(sibling.repo_root).expanduser().resolve() == repo_root
        ]
        if len(parent_matches) != 1:
            raise ValueError(
                "Shared child terminalization requires exactly one live parent with the same "
                "repository, worktree, and branch custody."
            )
        retained_parent_scope = parent_matches[0].scope
    elif resolved_worktree_path and canonical_root_reconciliation is None:
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

    lane_state_capture: dict[str, Any] | None = None
    retain_captured_lane = False
    if resolved_worktree_path and resolved_worktree_path.exists():
        surface_runtime.assert_no_live_leases_for_worktree(resolved_worktree_path)
        if tracker_absent:
            lane_state_capture = _capture_session_ended_lane_state(
                claim=claim,
                worktree=resolved_worktree_path,
                repo_root=repo_root,
                archive_dir=recovery_archive_dir,
            )
            retain_captured_lane = bool(lane_state_capture["uncommitted_changes"])
        clean, dirty_details = _worktree_is_clean(str(resolved_worktree_path))
        if not clean and not retain_captured_lane:
            raise ValueError(
                f"Worktree is dirty; commit or stash before session-close. Uncommitted state:\n{dirty_details}"
            )
        if canonical_root_reconciliation is None and not retain_captured_lane:
            _assert_worktree_removal_access(resolved_worktree_path)

    if retain_captured_lane and lane_state_capture is not None:
        # Uncommitted work is never removed on this path: the worktree and
        # branch are retained, and the verified capture is the recovery
        # evidence for the recovery-required disposition.
        preflight = _captured_lane_preflight(
            repo_root=repo_root,
            branch=resolved_branch,
            disposition=disposition,
            disposition_reason=disposition_reason,
            capture=lane_state_capture,
        )
    elif canonical_root_reconciliation is not None and canonical_root_reconciliation["branch"] == "HEAD":
        preflight = _detached_canonical_preflight(
            repo_root=repo_root, disposition=disposition,
            disposition_reason=disposition_reason, recovery_ref=recovery_ref,
            head_commit=canonical_root_reconciliation["head_commit"],
        )
    else:
        preflight = _validate_closeout_preflight(
            repo_root=repo_root,
            branch=resolved_branch,
            disposition=disposition,
            disposition_reason=disposition_reason,
            recovery_ref=recovery_ref
            or (lane_state_capture["recovery_ref"] if lane_state_capture is not None else None),
            merge_commit=merge_commit,
            allow_discard_unique=allow_discard_unique,
            delete_branch=delete_branch,
            retain_canonical_default_branch=canonical_root_reconciliation is not None,
        )
    mailbox_closeout = _resolve_active_mailbox_for_closeout(
        claim=claim,
        mailbox_disposition=mailbox_disposition,
        mailbox_note=mailbox_note,
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
    if canonical_root_reconciliation is not None:
        canonical_root_reconciliation["merge_evidence"] = preflight.merge_evidence or "none"
        canonical_root_reconciliation["merge_commit"] = preflight.merge_commit or "none"
        payload["canonical_root_reconciliation"] = canonical_root_reconciliation
    if session_ended_reconciliation is not None:
        session_ended_reconciliation["merge_evidence"] = preflight.merge_evidence or "none"
        session_ended_reconciliation["merge_commit"] = preflight.merge_commit or "none"
        session_ended_reconciliation["lane_state_capture"] = lane_state_capture
        payload["session_ended_closeout_reconciliation"] = session_ended_reconciliation
        if _claim_sha256(claim_file) != session_ended_reconciliation["claim_sha256"]:
            raise ValueError("Session-ended closeout reconciliation claim changed before mutation.")
        if tracker_absent:
            _verify_session_ended_tracker_absent(claim)
        elif _tracker_sha256(Path(session_ended_reconciliation["tracker_path"])) != session_ended_reconciliation[
            "tracker_sha256"
        ]:
            raise ValueError("Session-ended closeout reconciliation tracker changed before mutation.")
    payload["updated_at"] = updated_at
    payload["notes"] = note or "closing claimed lane via canonical session-close flow"
    # Keep the projection current during physical cleanup, but do not emit a
    # terminal closeout receipt until the final completed state is durable.
    if session_ended_reconciliation is None:
        with coordination_claims.claim_registry_lock(coordination_claims.CLAIMS_DIR):
            _write_claim_and_refresh_projection(claim_file, payload, coordination_claims.CLAIMS_DIR)

    tracker_path = session_contracts.find_session_tracker_path(
        agent=claim.agent,
        project=project,
        scope=claim.scope,
        session_id=claim.session_id,
        preferred_path=claim.tracker_path,
    )
    tracker_path_text = str(tracker_path) if tracker_path is not None else claim.tracker_path
    preserve_stale_tracker = canonical_root_reconciliation is not None and bool(
        canonical_root_reconciliation["tracker_identity_drift"]
    )
    if tracker_path is not None and session_ended_reconciliation is None and not preserve_stale_tracker:
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
    elif canonical_root_reconciliation is not None:
        worktree_action = canonical_root_reconciliation["filesystem_action"]
    elif terminalize_shared_child:
        worktree_action = "retained_for_parent"
    elif retain_captured_lane:
        worktree_action = "retained_uncommitted_state_captured"
    elif worktree_path or claim.worktree_path:
        worktree_action = _remove_worktree_path(repo_root, resolved_worktree_path)
    if canonical_root_reconciliation is not None:
        branch_action = canonical_root_reconciliation["branch_action"]
    elif terminalize_shared_child:
        branch_action = "retained_for_parent"
    elif retain_captured_lane:
        branch_action = "retained_uncommitted_state_captured"
    elif delete_branch:
        branch_action = _delete_branch(
            repo_root,
            resolved_branch,
            force=preflight.force_delete_branch,
        )

    if session_ended_reconciliation is not None:
        session_ended_reconciliation["filesystem_action"] = worktree_action
        session_ended_reconciliation["branch_action"] = branch_action

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
        _projection_path, projection_digest_after = _write_claim_and_refresh_projection(
            claim_file, payload, coordination_claims.CLAIMS_DIR
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
        _archived_claim, archive_receipt = coordination_claims._archive_completed_claim_locked(
            claim_file,
            claims_dir=coordination_claims.CLAIMS_DIR,
        )

    if tracker_path is not None and not preserve_stale_tracker:
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
        "claim_archive_id": archive_receipt.archive_id,
        **preflight.to_dict(),
        "tracker_path": tracker_path_text,
        "missing_worktree_reconciliation": reconciliation_receipt,
        "canonical_root_reconciliation": canonical_root_reconciliation,
        "retained_parent_scope": retained_parent_scope,
        "lane_state_capture": lane_state_capture,
        **mailbox_closeout,
    }


def _verify_successor_custody_offer_state(
    *,
    claim: coordination_claims.ClaimRecord,
    claim_snapshot_bytes: bytes,
    project: str,
    scope: str,
    worktree_path: str,
    branch: str,
    successor_custody_offer: session_continuity.SuccessorCustodyOfferV1,
    git_run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    """Bind one immutable offer to the current lane without changing custody."""

    current_head = git_run(
        ("git", "-C", worktree_path, "rev-parse", "--verify", "HEAD^{commit}"),
        capture_output=True,
        text=True,
        check=False,
    )
    exact_runtime = {
        "predecessor_session_id": claim.session_id,
        "project": project,
        "scope": scope,
        "branch": branch,
        "worktree_path": str(Path(worktree_path).expanduser().resolve()),
        "claim_epoch_sha256": hashlib.sha256(claim_snapshot_bytes).hexdigest(),
        "head_revision": current_head.stdout.strip() if current_head.returncode == 0 else None,
        "next_action": claim.next_action,
    }
    mismatched = [
        field
        for field, value in exact_runtime.items()
        if value != getattr(successor_custody_offer, field)
    ]
    if mismatched:
        raise ValueError(
            "successor offer no longer matches current custody state: "
            + ", ".join(mismatched)
        )
    return {
        "schema_version": "1.0",
        "record_type": "successor_custody_offer_verification",
        "action": "successor_custody_offer_verified",
        "offer_id": successor_custody_offer.offer_id,
        "predecessor_session_id": successor_custody_offer.predecessor_session_id,
        "project": project,
        "scope": scope,
        "branch": branch,
        "worktree_path": exact_runtime["worktree_path"],
        "head_revision": exact_runtime["head_revision"],
        "successor_acceptance_required": True,
        "successor_launch_allowed": False,
        "custody_mutation_performed": False,
        "transfer_eligible": False,
    }


def verify_successor_custody_offer_state(
    *,
    agent: str,
    project: str,
    scope: str,
    worktree_path: str,
    branch: str,
    successor_custody_offer: session_continuity.SuccessorCustodyOfferV1,
) -> dict[str, Any]:
    """Verify a prepared offer against live state without reserving custody."""

    claim, _payload, _claim_file, claim_snapshot_bytes = _claim_snapshot_any_status(
        agent=agent,
        project=project,
        scope=scope,
    )
    if claim.status not in coordination_claims.CLOSEABLE_STATUSES:
        raise ValueError(f"Cannot verify lane from lifecycle status {claim.status!r}")
    if not claim.plan_ref:
        raise ValueError("Cannot verify a lane with no plan_ref")
    if claim.branch and claim.branch != branch:
        raise ValueError(f"Claim branch is {claim.branch}, not {branch}")
    if claim.worktree_path and claim.worktree_path != worktree_path:
        raise ValueError(f"Claim worktree is {claim.worktree_path}, not {worktree_path}")
    return _verify_successor_custody_offer_state(
        claim=claim,
        claim_snapshot_bytes=claim_snapshot_bytes,
        project=project,
        scope=scope,
        worktree_path=worktree_path,
        branch=branch,
        successor_custody_offer=successor_custody_offer,
    )


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
    predecessor_process_pid: int | None = None,
    predecessor_process_start_ticks: int | None = None,
    successor_custody_offer: session_continuity.SuccessorCustodyOfferV1 | None = None,
    successor_custody_acceptance: session_continuity.SuccessorCustodyAcceptanceV1 | None = None,
    repair_worktree_path: bool = False,
    repair_missing_plan_ref: bool = False,
    successor_agent: str | None = None,
) -> dict[str, Any]:
    """Reattach a new runtime session to an existing plan-bound lane.

    ``agent`` always selects which claim file to open (``<agent>_<project>_
    <scope>.yaml``) -- that is the claim's recorded, and by default required,
    native identity. Pass ``successor_agent`` only when a *different*
    supported agent is legitimately taking over a claim the recorded agent
    explicitly left in ``handoff`` or ``session_ended`` status: this proves the successor's own
    native identity (never the departed agent's) and transfers the claim's
    recorded identity, including renaming its file, to ``successor_agent``.
    It is refused for any other lifecycle status. Live or stale-heartbeat claims
    still need the existing fenced transfer paths below because their predecessor
    may still be running. Explicit handoff and session end are both terminal
    process boundaries, so neither requires predecessor fencing.
    """

    claim, payload, claim_file, claim_snapshot_bytes = _claim_snapshot_any_status(
        agent=agent,
        project=project,
        scope=scope,
    )
    if claim.status not in coordination_claims.CLOSEABLE_STATUSES:
        raise ValueError(f"Cannot resume lane from lifecycle status {claim.status!r}")
    if claim.plan_ref and repair_missing_plan_ref:
        raise ValueError(
            f"repair_missing_plan_ref refuses a lane that already records plan_ref "
            f"{claim.plan_ref!r}; it exists only to stamp the explicit UNPLANNED marker "
            "onto a claim whose plan_ref is absent, never to overwrite a real authority."
        )
    if not claim.plan_ref:
        if not repair_missing_plan_ref:
            raise ValueError(
                "Cannot resume a lane with no plan_ref. The guide's mandatory rule is that no "
                "live session lacks one, and bounded maintenance satisfies it with the explicit "
                "UNPLANNED marker -- but a Makefile call site that passed --allow-unplanned "
                "without falling back to --plan UNPLANNED wrote a literal null instead, and "
                "claims created before that fallback landed still carry it. Refusing here left "
                "such a lane no sanctioned exit at all: it could not be resumed, therefore not "
                "pushed (the pre-push gate wants a live claim) and therefore not closed (closeout "
                "wants merge evidence the push would have produced) "
                "-- lrn-20260825T051949695806Z-29b10f7045. Pass repair_missing_plan_ref "
                "(--repair-missing-plan-ref) to stamp UNPLANNED first, then resume normally."
            )
        # One explicit locked mutation before the resume transaction, rather than
        # threading a repaired value through all four of its update branches. It
        # is deliberately durable on its own: if resume then fails for an
        # unrelated reason, the claim is still compliant with the mandatory rule
        # and the next attempt no longer needs the flag.
        _apply_claim_payload_updates(
            claim=claim,
            claim_file=claim_file,
            updates={"plan_ref": session_contracts.UNPLANNED_PLAN_REF},
            expected_fields={
                "plan_ref": payload.get("plan_ref"),
                "session_id": payload.get("session_id"),
                "status": payload.get("status"),
            },
        )
        claim, payload, claim_file, claim_snapshot_bytes = _claim_snapshot_any_status(
            agent=agent,
            project=project,
            scope=scope,
        )
        if not claim.plan_ref:
            raise ValueError("plan_ref repair did not take effect; refusing to resume")
    if claim.branch and claim.branch != branch:
        raise ValueError(f"Claim branch is {claim.branch}, not {branch}")
    if claim.worktree_path and claim.worktree_path != worktree_path:
        if not repair_worktree_path:
            raise ValueError(f"Claim worktree is {claim.worktree_path}, not {worktree_path}")
        _validate_worktree_path_repair(
            recorded_worktree_path=claim.worktree_path,
            provided_worktree_path=worktree_path,
            branch=branch,
        )

    if successor_agent is not None and successor_agent != agent:
        if claim.status not in {"handoff", coordination_claims.SESSION_ENDED_STATUS}:
            raise ValueError(
                "Cross-agent resume requires an explicit 'handoff' or "
                f"'session_ended' claim status, not {claim.status!r}. A live or "
                "stale-heartbeat claim must be fenced through its existing transfer path."
            )
        if successor_agent not in coordination_claims.SUPPORTED_AGENTS:
            raise ValueError(f"Unsupported successor agent {successor_agent!r}")
        resolved_successor_session_id = coordination_claims.resolve_session_id(successor_agent, session_id)
        if not resolved_successor_session_id:
            raise ValueError("Unable to resolve a native session ID for the successor agent.")
        coordination_claims.validate_native_session_binding(
            successor_agent,
            resolved_successor_session_id,
            require_native_marker=True,
        )
        transfer_updated_at = datetime.now(timezone.utc).isoformat()
        transferred_claim = _apply_cross_agent_handoff_transaction(
            claim=claim,
            claim_file=claim_file,
            claim_bytes_before=claim_snapshot_bytes,
            successor_agent=successor_agent,
            successor_session_id=resolved_successor_session_id,
            current_phase=current_phase,
            note=note,
            updated_at=transfer_updated_at,
            expected_fields={
                "status": claim.status,
                "session_id": claim.session_id,
                "heartbeat_at": claim.heartbeat_at,
                "updated_at": claim.updated_at,
                "agent": claim.agent,
            },
            project=project,
            scope=scope,
        )
        if claim.tracker_path:
            tracker_path_obj = Path(claim.tracker_path).expanduser()
            if tracker_path_obj.is_file():
                session_contracts.update_session_tracker(
                    tracker_path_obj,
                    current_phase=current_phase,
                    notes=transferred_claim["notes"],
                    updated_at=transferred_claim["updated_at"],
                )
        return {
            "action": "resumed",
            "session_id": resolved_successor_session_id,
            "tracker_path": claim.tracker_path,
            "plan_ref": claim.plan_ref,
            "outcome_session_transfer": None,
            "claim_session_transfer": None,
            "successor_custody_acceptance": None,
            "predecessor_process_fence": None,
            "predecessor_agent": claim.agent,
            "successor_agent": successor_agent,
            "coordination_mailbox": _poll_mailbox_after_committed_transition(
                agent=successor_agent,
                project=project,
                session_id=resolved_successor_session_id,
            ),
        }

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError("Unable to resolve a session ID for session-resume.")
    coordination_claims.validate_native_session_binding(
        agent,
        resolved_session_id,
        require_native_marker=True,
    )

    same_runtime = claim.session_id == resolved_session_id
    if (successor_custody_offer is None) != (successor_custody_acceptance is None):
        raise ValueError("automatic successor transfer requires both offer and acceptance")
    if successor_custody_offer is not None and successor_custody_acceptance is not None:
        _verify_successor_custody_offer_state(
            claim=claim,
            claim_snapshot_bytes=claim_snapshot_bytes,
            project=project,
            scope=scope,
            worktree_path=worktree_path,
            branch=branch,
            successor_custody_offer=successor_custody_offer,
        )
        session_continuity.validate_successor_custody_acceptance(
            offer=successor_custody_offer,
            acceptance=successor_custody_acceptance,
        )
        if successor_custody_acceptance.successor_session_id != resolved_session_id:
            raise ValueError(
                "successor acceptance no longer matches current custody state: "
                "successor_session_id"
            )
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
    process_fence: dict[str, Any] | None = None
    claim_bytes_before: bytes | None = None
    tracker_bytes_before: bytes | None = None
    takeover_reservation: dict[str, Any] | None = None
    tracker_path_text = claim.tracker_path
    tracker_path = Path(tracker_path_text).expanduser() if tracker_path_text else None
    if same_runtime and tracker_path is None:
        tracker_path = session_contracts.find_session_tracker_path(
            agent=claim.agent,
            project=project,
            scope=claim.scope,
            session_id=claim.session_id,
        )
        if tracker_path is None:
            raise ValueError("same-runtime resume could not find one unique exact session tracker")
        tracker_path = tracker_path.expanduser().resolve()
        tracker_path_text = str(tracker_path)
    if not same_runtime:
        if tracker_path is None or not tracker_path.is_file():
            raise ValueError("cross-session resume requires one existing exact session tracker")
        # A recorded session end is the terminal custody signal.  Its process
        # may still be an idle Codex UI rooted at the workspace rather than the
        # linked worktree, so fencing it would reject a lane that the registry
        # has already declared safe for successor custody.  Live/handoff
        # transfers still require the exact process fence below.
        if agent == "codex" and claim.status != coordination_claims.SESSION_ENDED_STATUS:
            if predecessor_process_pid is None:
                raise ValueError(
                    "Cross-session Codex resume requires --predecessor-process-pid so the exact "
                    "prior runtime is fenced before custody transfer."
                )
            if predecessor_process_start_ticks is None:
                raise ValueError(
                    "Cross-session Codex resume requires --predecessor-process-start-ticks "
                    "to bind one exact process generation."
                )
            if not claim.session_id:
                raise ValueError("Cross-session Codex resume cannot fence an unbound predecessor session.")
            claim, payload, claim_bytes_before, takeover_reservation = coordination_claims.reserve_session_takeover(
                claim_file=claim_file,
                agent=agent,
                project=project,
                scope=scope,
                predecessor_session_id=claim.session_id,
                successor_session_id=resolved_session_id,
                worktree_path=worktree_path,
                predecessor_pid=predecessor_process_pid,
                predecessor_process_start_ticks=predecessor_process_start_ticks,
                reserved_at=updated_at,
                pre_reservation_claim_bytes=claim_snapshot_bytes,
            )
        else:
            claim_bytes_before = claim_file.read_bytes()
        tracker_bytes_before = tracker_path.read_bytes()
        existing_transfer_journal = (
            takeover_reservation.get(SESSION_TRANSFER_JOURNAL_FIELD) if takeover_reservation is not None else None
        )
        if existing_transfer_journal is None:
            transfer_preflight = outcome_selection.prepare_outcome_session_transfer(
                claim=claim,
                successor_session_id=resolved_session_id,
                transferred_at=datetime.fromisoformat(updated_at),
            )
            if transfer_preflight is not None and transfer_preflight.tracker_path != tracker_path.resolve():
                raise ValueError("selected outcome transfer resolved a different tracker path")
        elif not isinstance(existing_transfer_journal, dict):
            raise TypeError("session takeover reservation has malformed transfer journal state")
        if agent == "codex" and claim.status != coordination_claims.SESSION_ENDED_STATUS:
            assert takeover_reservation is not None
            assert predecessor_process_pid is not None
            assert predecessor_process_start_ticks is not None
            assert claim.session_id is not None
            process_fence = session_process_fencing.fence_predecessor_process(
                predecessor_session_id=claim.session_id,
                successor_session_id=resolved_session_id,
                worktree_path=worktree_path,
                predecessor_pid=predecessor_process_pid,
                transfer_epoch_sha256=takeover_reservation["claim_epoch_sha256"],
                predecessor_process_start_ticks=predecessor_process_start_ticks,
            )

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
    transfer_receipt: outcome_selection.OutcomeSessionTransferV1 | None = None
    claim_session_transfer: dict[str, Any] | None = None
    try:
        if same_runtime:
            if claim.tracker_path is None:
                assert tracker_path is not None
                payload = _reattach_same_runtime_tracker(
                    claim=claim,
                    claim_file=claim_file,
                    tracker_path=tracker_path,
                    current_phase=current_phase,
                    note=note,
                    updated_at=updated_at,
                    expected_fields=expected_fields,
                )
            else:
                payload = _apply_claim_payload_updates(
                    claim=claim,
                    claim_file=claim_file,
                    updates={
                        "status": "active",
                        "session_id": resolved_session_id,
                        "heartbeat_at": updated_at,
                        "expires_at": _renewed_lease_expiry(updated_at, claim.expires_at),
                        "updated_at": updated_at,
                        "notes": note or "session resumed with a fresh runtime attachment",
                    },
                    expected_fields=expected_fields,
                )
                assert tracker_path is not None
                session_contracts.update_session_tracker(
                    tracker_path,
                    current_phase=current_phase,
                    notes=payload["notes"],
                    updated_at=updated_at,
                )
        else:
            if claim_bytes_before is None or tracker_bytes_before is None or tracker_path is None:
                raise SessionTransferIncompleteError("cross-session resume lacks exact predecessor bytes")
            if takeover_reservation is not None:
                payload, transfer_receipt, claim_session_transfer = _apply_codex_cross_session_resume_transaction(
                    claim=claim,
                    claim_file=claim_file,
                    claim_bytes_before=claim_bytes_before,
                    tracker_path=tracker_path,
                    tracker_bytes_before=tracker_bytes_before,
                    successor_session_id=resolved_session_id,
                    current_phase=current_phase,
                    note=note,
                    updated_at=updated_at,
                    expected_fields=expected_fields,
                    transfer_preflight=transfer_preflight,
                    project=project,
                    scope=scope,
                    worktree_path=worktree_path,
                    branch=branch,
                    process_fence=process_fence,
                    predecessor_process_pid=predecessor_process_pid,
                    predecessor_process_start_ticks=predecessor_process_start_ticks,
                    takeover_reservation=takeover_reservation,
                )
            else:
                payload, transfer_receipt, claim_session_transfer = _apply_legacy_cross_session_resume_transaction(
                    claim=claim,
                    claim_file=claim_file,
                    claim_bytes_before=claim_bytes_before,
                    tracker_path=tracker_path,
                    tracker_bytes_before=tracker_bytes_before,
                    successor_session_id=resolved_session_id,
                    current_phase=current_phase,
                    note=note,
                    updated_at=updated_at,
                    expected_fields=expected_fields,
                    transfer_preflight=transfer_preflight,
                    project=project,
                    scope=scope,
                    worktree_path=worktree_path,
                    branch=branch,
                )
    except Exception as transfer_error:
        if same_runtime:
            raise
        if takeover_reservation is not None:
            # A fenced Codex transfer is recoverable only by replaying its durable
            # reservation journal. Restoring predecessor bytes would erase the
            # proof needed to finish custody without refencing a gone process.
            raise
        if claim_bytes_before is None or tracker_bytes_before is None:
            raise SessionTransferIncompleteError(
                f"session transfer failed without exact rollback evidence: transfer={transfer_error}"
            ) from transfer_error
        try:
            claim_changed = claim_file.read_bytes() != claim_bytes_before
            assert tracker_path is not None
            tracker_changed = tracker_path.read_bytes() != tracker_bytes_before
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
                tracker_path=tracker_path,
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
        "claim_session_transfer": claim_session_transfer,
        "successor_custody_acceptance": (
            successor_custody_acceptance.model_dump(mode="json")
            if successor_custody_acceptance is not None
            else None
        ),
        "predecessor_process_fence": process_fence,
        "coordination_mailbox": _poll_mailbox_after_committed_transition(
            agent=agent,
            project=project,
            session_id=resolved_session_id,
        ),
    }


def abort_unfenced_session_takeover(
    *,
    agent: str,
    project: str,
    scope: str,
    worktree_path: str,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Recover a successor-owned reservation left before process fencing."""

    _claim, _payload, claim_file, _claim_bytes = _claim_snapshot_any_status(
        agent=agent, project=project, scope=scope
    )
    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError("Unable to resolve a session ID for takeover-reservation recovery.")
    coordination_claims.validate_native_session_binding(
        agent, resolved_session_id, require_native_marker=True
    )
    result = coordination_claims.abort_unfenced_session_takeover_reservation(
        claim_file=claim_file,
        agent=agent,
        project=project,
        scope=scope,
        successor_session_id=resolved_session_id,
        worktree_path=worktree_path,
    )
    return {
        "action": "unfenced_takeover_aborted",
        "session_id": resolved_session_id,
        **result,
        "coordination_mailbox": _poll_mailbox_after_committed_transition(
            agent=agent, project=project, session_id=resolved_session_id
        ),
    }


def handoff_session(
    *,
    agent: str,
    project: str,
    scope: str,
    note: str,
    current_phase: str = "handoff required",
    actor_session_id: str | None = None,
) -> dict[str, Any]:
    """Mark one live lane as intentionally handed off."""

    claim = _single_matching_live_claim(agent=agent, project=project, scope=scope)
    _require_claim_actor(claim, actor_session_id=actor_session_id)
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
    actor_session_id: str | None = None,
) -> dict[str, Any]:
    """Mark one live, or preserved session-ended, lane as explicitly abandoned.

    A session-ended lane blocks any replacement lane on the same paths until it
    is disposed of (``validate_no_preserved_lane_conflict``). A lane without a
    session tracker cannot be resumed or closed, so abandonment by its own
    session is its only disposition (issue #548).
    """

    if _iter_matching_live_claims(agent=agent, project=project, scope=scope):
        claim = _single_matching_live_claim(agent=agent, project=project, scope=scope)
    else:
        try:
            claim, _payload, _path = _claim_record_any_status(agent=agent, project=project, scope=scope)
        except (ValueError, FileNotFoundError) as exc:
            raise ValueError(f"No live or session-ended claim found for {agent} → {project}:{scope}") from exc
        if claim.status != coordination_claims.SESSION_ENDED_STATUS:
            raise ValueError(
                f"No live or session-ended claim found for {agent} → {project}:{scope} (status {claim.status})"
            )
    _require_claim_actor(claim, actor_session_id=actor_session_id)
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


ORPHANED_TRACKER_ARCHIVE_DIRNAME = "sessions-archive"


def _session_tracker_archive_root() -> Path:
    """Return the canonical archive root beside the live session-tracker tree."""

    return session_contracts.DEFAULT_SESSION_TRACKERS_DIR.expanduser().parent / ORPHANED_TRACKER_ARCHIVE_DIRNAME


def _branch_unique_commits(repo_root: Path, *, branch: str, upstream_ref: str) -> list[str]:
    """Return branch commits with no patch-equivalent already on ``upstream_ref``.

    ``git cherry`` is patch-based on purpose. These repositories squash-merge,
    so ``git merge-base --is-ancestor`` reports a fully integrated branch as
    unmerged and would make every archival look like it discards work.
    """

    result = subprocess.run(
        ["git", "cherry", upstream_ref, branch],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise ValueError(
            f"Orphaned-tracker archival could not compare '{branch}' with '{upstream_ref}': "
            + (result.stderr or result.stdout).strip()
        )
    return [line[2:].strip() for line in result.stdout.splitlines() if line.startswith("+ ")]


def _validate_orphaned_tracker_archival(
    *,
    tracker_path: Path,
    expected_tracker_sha256: str | None,
    allow_unique_branch_commits: bool,
) -> dict[str, Any]:
    """Fail closed before archiving one claim-less tracker with no worktree.

    ``close_session()`` cannot reach these: it loads the claim first and raises
    "Claim file missing" because the claim was already released. What remains is
    coordination residue, so archival is metadata-only -- it never removes a
    worktree, never deletes a branch, and never touches a repository working
    tree.
    """

    sessions_root = session_contracts.DEFAULT_SESSION_TRACKERS_DIR.expanduser().resolve()
    resolved_tracker = tracker_path.expanduser().resolve()
    if not resolved_tracker.is_file():
        raise ValueError(f"Orphaned-tracker archival requires an existing tracker file at {resolved_tracker}")
    try:
        relative_tracker = resolved_tracker.relative_to(sessions_root)
    except ValueError:
        raise ValueError(
            "Orphaned-tracker archival only accepts a tracker inside the canonical session-tracker tree "
            f"{sessions_root}"
        ) from None

    expected_digest = (expected_tracker_sha256 or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("Orphaned-tracker archival requires --tracker-sha256 as a SHA-256 digest.")
    actual_digest = _tracker_sha256(resolved_tracker)
    if actual_digest != expected_digest:
        raise ValueError(
            "Orphaned-tracker archival tracker digest mismatch; preserve the tracker and regenerate evidence."
        )

    payload = session_contracts.read_session_tracker(resolved_tracker)
    contract = payload.get("claim")
    if not isinstance(contract, dict):
        raise ValueError(f"Session tracker at {resolved_tracker} is missing claim metadata")
    agent = contract.get("agent")
    project = contract.get("project")
    scope = contract.get("scope")
    if not agent or not project or not scope:
        raise ValueError(
            f"Session tracker at {resolved_tracker} is missing the agent/project/scope identity archival requires"
        )
    # Deliberately NOT refused on an unsupported agent name.
    #
    # SUPPORTED_AGENTS gates who may *act* -- claim a repository, close another
    # runtime's session. Archiving an orphaned tracker is neither: it moves a
    # dead bookkeeping file into the archive tree and leaves the branch, the
    # worktree, and every claim untouched. Asking "is this agent allowed to act
    # here?" where nobody acts blocked the cleanup and protected nothing.
    #
    # The operator guide's own contract for this operation lists the conditions
    # that make it safe -- the recorded worktree absent from disk, the claim file
    # gone, the tracker bytes matching the supplied digest, the tracker inside
    # the canonical tree. All four are enforced above and below. The agent name
    # is not among them, and never was.
    #
    # Measured 2026-09-08: 23 of 74 orphaned trackers were unarchivable for this
    # reason alone -- legacy per-lane identities such as
    # 'codex-evidence-reader-wiki' and 'codex-root' written between 2026-07-24
    # and 2026-08-21. Because claim creation DID enforce SUPPORTED_AGENTS while
    # start_session did not, these trackers could never have a matching claim,
    # so session-close could never reach them and archival refused them too.
    # They were permanent residue by construction. start_session now validates
    # the agent, so no new tracker can enter that state.
    #
    # The name is still reported in the receipt: an unexpected identity stays
    # visible rather than being silently normalised away.
    agent_supported = agent in coordination_claims.SUPPORTED_AGENTS

    recorded_worktree_text = contract.get("worktree_path")
    if not recorded_worktree_text:
        raise ValueError("Orphaned-tracker archival requires a recorded worktree path")
    recorded_worktree = Path(str(recorded_worktree_text)).expanduser()
    # Refuse only a genuine LINKED worktree -- a real lane checkout that is
    # still physically present. A linked worktree has a `.git` FILE containing
    # a `gitdir:` pointer; a canonical repository root has a `.git` DIRECTORY;
    # a shared or umbrella directory has no `.git` at all.
    #
    # The old check refused on mere existence and told the caller to use
    # session-close instead. For an orphaned tracker that advice is impossible:
    # session-close loads the claim first and the claim is, by definition here,
    # already gone. So every such tracker was unretireable by any path.
    #
    # Measured 2026-09-08 across the live residue, of the trackers blocked this
    # way: 16 recorded a real linked worktree (still correctly refused below),
    # 11 recorded a canonical repository root, and 12 recorded a directory with
    # no `.git` at all -- most of them the shared umbrella `~/projects/
    # inside-success`, which is not a lane checkout and will never be removed.
    # Those 23 could never satisfy the old condition.
    #
    # Refusing a canonical root is also wrong on the operator guide's own terms:
    # its "Legacy canonical-root claim reconciliation" section states that
    # ordinary session-close "must never process that record as a removable
    # linked worktree" and provides a metadata-only path for exactly that shape.
    # This is the claimless equivalent of that exception.
    #
    # Nothing here is removed, and the four conditions that make archival safe
    # are unchanged: claim gone, tracker digest matching, tracker inside the
    # canonical tree, and -- for a real lane -- its worktree absent.
    recorded_worktree_kind = "absent"
    if recorded_worktree.exists():
        git_marker = recorded_worktree / ".git"
        if git_marker.is_file():
            recorded_worktree_kind = "linked_worktree"
        elif git_marker.is_dir():
            recorded_worktree_kind = "canonical_repository_root"
        else:
            recorded_worktree_kind = "not_a_git_worktree"
    if recorded_worktree_kind == "linked_worktree":
        raise ValueError(
            f"Orphaned-tracker archival rejects {recorded_worktree}: it is still a linked "
            "worktree on disk, so the lane is physically present. Remove it through the "
            "sanctioned worktree-removal path first, then archive the tracker."
        )

    claim_file = _claim_path(str(agent), str(project), str(scope))
    if claim_file.exists():
        raise ValueError(
            f"Orphaned-tracker archival rejects a tracker whose claim {claim_file} still exists; "
            "that is a live lane, not residue. Close it through session-close."
        )

    repo_root_text = contract.get("repo_root")
    branch = contract.get("branch")
    branch_state = "not_recorded"
    default_branch: str | None = None
    comparison_ref: str | None = None
    unique_commits: list[str] = []
    repo_root: Path | None = None
    if repo_root_text:
        repo_root = Path(str(repo_root_text)).expanduser()
    if branch:
        if repo_root is None:
            branch_state = "repo_root_not_recorded"
        elif not (repo_root / ".git").exists():
            branch_state = "repo_root_absent"
        elif not _branch_exists(repo_root, str(branch)):
            branch_state = "branch_absent"
        else:
            default_branch = push_safety.resolve_default_branch(repo_root)
            if not default_branch:
                raise ValueError(
                    f"Orphaned-tracker archival cannot resolve the canonical default branch in {repo_root}, "
                    f"so unique work on '{branch}' cannot be ruled out."
                )
            remote_ref = f"refs/remotes/origin/{default_branch}"
            comparison_ref = remote_ref if _ref_exists(repo_root, remote_ref) else f"refs/heads/{default_branch}"
            unique_commits = _branch_unique_commits(
                repo_root,
                branch=str(branch),
                upstream_ref=comparison_ref,
            )
            branch_state = "branch_present_with_unique_commits" if unique_commits else "branch_present_integrated"
            if unique_commits and not allow_unique_branch_commits:
                preview = ", ".join(unique_commits[:5])
                raise ValueError(
                    f"Branch '{branch}' in {repo_root} still holds {len(unique_commits)} commit(s) with no "
                    f"patch-equivalent on '{comparison_ref}': {preview}. Archiving would hide unique work; "
                    "integrate or preserve the branch first, or pass allow_unique_branch_commits to record "
                    "the retained branch explicitly."
                )

    return {
        "schema_version": "1.0",
        "agent": str(agent),
        "agent_supported": agent_supported,
        "project": str(project),
        "scope": str(scope),
        "session_id": contract.get("session_id"),
        "tracker_path": str(resolved_tracker),
        "tracker_relative_path": str(relative_tracker),
        "tracker_sha256": actual_digest,
        "current_phase_before": (payload.get("tracker") or {}).get("current_phase")
        if isinstance(payload.get("tracker"), dict)
        else None,
        "claim_path": str(claim_file),
        "claim_present": False,
        "recorded_worktree_path": str(recorded_worktree),
        "repo_root": str(repo_root) if repo_root is not None else None,
        "branch": str(branch) if branch else None,
        "branch_state": branch_state,
        "default_branch": default_branch,
        "branch_comparison_ref": comparison_ref,
        "unique_commits": unique_commits,
        "unique_commits_authorized": bool(unique_commits) and allow_unique_branch_commits,
        # What the recorded worktree_path actually was. `absent` is the ordinary
        # orphan; `canonical_repository_root` and `not_a_git_worktree` are paths
        # that were never a removable lane checkout and are retained untouched.
        # A `linked_worktree` never reaches here -- it is refused above.
        "recorded_worktree_kind": recorded_worktree_kind,
        "filesystem_action": (
            "not_attempted_absent_recorded_worktree"
            if recorded_worktree_kind == "absent"
            else f"retained_untouched_{recorded_worktree_kind}"
        ),
        "branch_action": "untouched",
    }


def archive_orphaned_session_tracker(
    *,
    tracker_path: str | Path,
    expected_tracker_sha256: str | None,
    note: str | None = None,
    allow_unique_branch_commits: bool = False,
    archive_root: str | Path | None = None,
) -> dict[str, Any]:
    """Archive one claim-less session tracker whose worktree is already gone.

    This is the missing terminal path for coordination residue. The claim was
    released long ago, so there is nothing to release and nothing to clean up;
    the tracker alone keeps reporting a lane that no longer exists. It is moved
    into the sibling archive tree rather than deleted, because the tracker is
    the only durable account of who held that write lane.
    """

    resolved_tracker = Path(tracker_path).expanduser().resolve()
    receipt = _validate_orphaned_tracker_archival(
        tracker_path=resolved_tracker,
        expected_tracker_sha256=expected_tracker_sha256,
        allow_unique_branch_commits=allow_unique_branch_commits,
    )

    archived_at = datetime.now(timezone.utc)
    root = Path(archive_root).expanduser() if archive_root is not None else _session_tracker_archive_root()
    destination = root / archived_at.strftime("%Y-%m-%d") / receipt["tracker_relative_path"]
    notes = note or (
        "archived orphaned session tracker: recorded worktree absent and claim already released"
    )

    with session_contracts.session_tracker_lock(resolved_tracker):
        if _tracker_sha256(resolved_tracker) != receipt["tracker_sha256"]:
            raise ValueError("Orphaned-tracker archival tracker changed before mutation.")
        if _claim_path(receipt["agent"], receipt["project"], receipt["scope"]).exists():
            raise ValueError("Orphaned-tracker archival claim reappeared before mutation.")
        if destination.exists():
            raise ValueError(f"Orphaned-tracker archival refuses to overwrite an existing archive entry {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.replace(resolved_tracker, destination)

    def record_archival(payload: dict[str, Any]) -> None:
        tracker_section = payload.get("tracker")
        if not isinstance(tracker_section, dict):
            raise TypeError(f"Archived session tracker at {destination} is missing its tracker section")
        tracker_section["current_phase"] = "closed"
        tracker_section["notes"] = notes
        payload["archive"] = {
            "schema_version": "1.0",
            "reason": "orphaned_tracker_no_claim_no_worktree",
            "archived_at": archived_at.isoformat(),
            "archived_from": receipt["tracker_path"],
            "tracker_sha256_before_archive": receipt["tracker_sha256"],
            "recorded_worktree_path": receipt["recorded_worktree_path"],
            "claim_path": receipt["claim_path"],
            "repo_root": receipt["repo_root"],
            "branch": receipt["branch"],
            "branch_state": receipt["branch_state"],
            "branch_comparison_ref": receipt["branch_comparison_ref"],
            "unique_commits": receipt["unique_commits"],
            "unique_commits_authorized": receipt["unique_commits_authorized"],
            "branch_action": "untouched",
            "notes": notes,
        }

    session_contracts.mutate_session_tracker(
        destination,
        record_archival,
        updated_at=archived_at.isoformat(),
    )

    return {
        "action": "archived_orphaned_tracker",
        "archived_tracker_path": str(destination),
        "archived_at": archived_at.isoformat(),
        "released": False,
        "notes": notes,
        **receipt,
    }
