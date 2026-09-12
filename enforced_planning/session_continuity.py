"""Classify session activity without turning silence into takeover authority."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enforced_planning import coordination_messages


class ContinuityClaim(Protocol):
    """Claim fields required by the observe-only continuity classifier."""

    status: str
    session_id: str | None
    progress_at: str | None
    next_action: str | None
    expected_quiet_until: str | None
    quiet_reason: str | None

    def is_live(self) -> bool: ...


class ResumeOfferStatus(Protocol):
    """Mailbox status fields required before a successor may be launched."""

    message: coordination_messages.CoordinationMessage
    runtime_accepted: bool
    observed: bool
    acknowledged: bool


class CodexActivityV1(BaseModel):
    """Last durable Codex task boundary observed in one exact transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["codex_session_activity"] = "codex_session_activity"
    session_id: str = Field(min_length=1)
    transcript_path: str = Field(min_length=1)
    thread_source: Literal["user", "subagent", "unknown"] = "unknown"
    parent_thread_id: str | None = None
    state: Literal["active_operation", "between_turns", "unknown"]
    observed_at: datetime | None = None
    boundary_at: datetime | None = None
    turn_id: str | None = None
    evidence_event: Literal["task_started", "task_complete", "turn_aborted"] | None = None


class ContinuityAssessmentV1(BaseModel):
    """Observe-only continuity result; transfer always needs a later handshake."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["session_continuity_assessment"] = "session_continuity_assessment"
    session_id: str | None
    activity_state: Literal[
        "active_operation",
        "intentional_quiet",
        "idle_owner",
        "terminal",
        "unknown",
    ]
    continuity_disposition: Literal[
        "active_continuing",
        "successor_accepted",
        "human_required",
        "circuit_breaker",
    ] | None
    action: Literal["none", "notify_owner", "fail_visible"]
    reason_code: str = Field(min_length=1)
    observed_at: datetime
    last_client_activity_at: datetime | None
    inactivity_seconds: int | None = Field(default=None, ge=0)
    transfer_candidate_observe_only: bool = False
    transfer_eligible: Literal[False] = False
    observe_only: Literal[True] = True
    resume_condition: str | None = None


class ResumeOfferReviewV1(BaseModel):
    """Decision after projecting one exact owner resume offer and its receipts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["resume_offer_review"] = "resume_offer_review"
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$")
    owner_session_id: str = Field(min_length=1)
    action: Literal["wait_for_owner", "owner_responded", "launch_successor", "fail_visible"]
    reason_code: str = Field(min_length=1)
    successor_launch_allowed: bool
    transfer_eligible: Literal[False] = False
    resume_condition: str = Field(min_length=1)


class SuccessorCustodyOfferV1(BaseModel):
    """Exact recoverable lane state offered to one future successor runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["successor_custody_offer"] = "successor_custody_offer"
    offer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    owner_resume_message_id: str | None = Field(
        default=None, pattern=r"^msg_[0-9a-f]{32}$"
    )
    owner_resume_correlation_id: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{24}$"
    )
    predecessor_session_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    claim_epoch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    head_revision: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    next_action: str = Field(min_length=1)
    created_at: datetime

    @model_validator(mode="after")
    def validate_owner_resume_reference(self) -> SuccessorCustodyOfferV1:
        if (self.owner_resume_message_id is None) == (
            self.owner_resume_correlation_id is None
        ):
            raise ValueError("successor offer requires exactly one owner resume reference")
        return self


class SuccessorCustodyAcceptanceV1(BaseModel):
    """Successor-authored acceptance of every exact offered custody field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["successor_custody_acceptance"] = (
        "successor_custody_acceptance"
    )
    disposition: Literal["successor_accepted"] = "successor_accepted"
    offer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    offer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_session_id: str = Field(min_length=1)
    successor_session_id: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    claim_epoch_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    head_revision: str = Field(pattern=r"^[0-9a-f]{40,64}$")
    next_action: str = Field(min_length=1)
    accepted_at: datetime


class CodexSuccessorLaunchV1(BaseModel):
    """Exact disabled-by-default native launch request for one successor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["codex_successor_launch"] = "codex_successor_launch"
    offer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    offer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    predecessor_session_id: str = Field(min_length=1)
    predecessor_thread_id: str = Field(min_length=1)
    predecessor_process_pid: int = Field(gt=1)
    predecessor_process_start_ticks: int = Field(ge=1)
    offer_path: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    prompt: str = Field(min_length=1)
    prompt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    systemd_unit: str = Field(pattern=r"^[a-zA-Z0-9_.@-]+$")
    argv: list[str] = Field(min_length=1)
    transfer_eligible: Literal[False] = False


class CodexSuccessorLaunchReceiptV1(BaseModel):
    """Host acknowledgement that a successor unit started, not custody acceptance."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["codex_successor_launch_receipt"] = (
        "codex_successor_launch_receipt"
    )
    offer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    offer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    systemd_unit: str = Field(pattern=r"^[a-zA-Z0-9_.@-]+$")
    launch_started: Literal[True] = True
    successor_session_id: None = None
    successor_accepted: Literal[False] = False
    transfer_eligible: Literal[False] = False
    runtime_stdout: str


class NativeCodexSuccessorLaunchJournalV1(BaseModel):
    """Write-ahead state for one verified native successor launch."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_successor_launch"] = (
        "native_codex_successor_launch"
    )
    offer_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    offer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    systemd_unit: str = Field(pattern=r"^[a-zA-Z0-9_.@-]+$")
    state: Literal["intent", "started", "failed"]
    recorded_at: datetime
    launch_receipt: CodexSuccessorLaunchReceiptV1 | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> NativeCodexSuccessorLaunchJournalV1:
        if self.state == "intent" and (self.launch_receipt or self.error):
            raise ValueError("successor launch intent cannot contain a terminal result")
        if self.state == "started":
            if self.launch_receipt is None or self.error is not None:
                raise ValueError("started successor launch requires only its receipt")
            if (
                self.launch_receipt.offer_id != self.offer_id
                or self.launch_receipt.offer_sha256 != self.offer_sha256
                or self.launch_receipt.systemd_unit != self.systemd_unit
            ):
                raise ValueError("successor launch receipt does not match its journal")
        if self.state == "failed" and (
            not self.error or self.launch_receipt is not None
        ):
            raise ValueError("failed successor launch requires only an error")
        return self


class NativeCodexResumeOfferV1(BaseModel):
    """One exact, idempotently identifiable prompt for Codex's durable queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_resume_offer"] = "native_codex_resume_offer"
    owner_session_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    correlation_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    progress_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    prompt: str = Field(min_length=1)


class NativeCodexQueueReceiptV1(BaseModel):
    """Strictly parsed acceptance receipt from the installed Codex client."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_queue_receipt"] = "native_codex_queue_receipt"
    owner_session_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    correlation_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    queued_submission_id: str = Field(min_length=1)
    runtime_accepted: Literal[True] = True


class NativeCodexConsumptionReceiptV1(BaseModel):
    """Transcript proof that the exact queued prompt became an owner user turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_resume_consumption"] = (
        "native_codex_resume_consumption"
    )
    owner_session_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    correlation_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    queued_submission_id: str = Field(min_length=1)
    transcript_path: str = Field(min_length=1)
    consumed_at: datetime
    evidence_event: Literal["correlated_user_message"] = "correlated_user_message"
    runtime_consumed: Literal[True] = True


class NativeCodexDeliveryJournalV1(BaseModel):
    """Write-ahead state for one correlation-bound native queue attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_resume_delivery"] = "native_codex_resume_delivery"
    owner_session_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    correlation_id: str = Field(pattern=r"^[0-9a-f]{24}$")
    progress_fingerprint: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    state: Literal["intent", "accepted", "failed"]
    recorded_at: datetime
    queued_submission_id: str | None = None
    error: str | None = None

    @model_validator(mode="after")
    def validate_state_payload(self) -> NativeCodexDeliveryJournalV1:
        if self.state == "intent" and (self.queued_submission_id or self.error):
            raise ValueError("delivery intent cannot contain a terminal result")
        if self.state == "accepted" and (
            not self.queued_submission_id or self.error is not None
        ):
            raise ValueError("accepted delivery requires only a queued submission id")
        if self.state == "failed" and (
            not self.error or self.queued_submission_id is not None
        ):
            raise ValueError("failed delivery requires only an error")
        return self


_CODEX_QUEUE_RECEIPT = re.compile(
    r"Queued message ([0-9a-f-]{36}) for thread ([0-9a-f-]{36})\.\s*"
)


def _aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def read_codex_activity(*, session_id: str, transcript_path: Path) -> CodexActivityV1:
    """Read the latest task boundary; malformed transcript records fail visibly."""

    expected_thread_id = session_id.removeprefix("codex:")
    latest_event: Literal["task_started", "task_complete", "turn_aborted"] | None = None
    latest_boundary_at: datetime | None = None
    latest_record_at: datetime | None = None
    latest_turn_id: str | None = None
    thread_source: Literal["user", "subagent", "unknown"] = "unknown"
    parent_thread_id: str | None = None
    with transcript_path.expanduser().open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Codex transcript has malformed JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict) or record.get("type") != "event_msg":
                record_at = (
                    _aware_timestamp(record.get("timestamp"))
                    if isinstance(record, dict)
                    else None
                )
                if record_at is not None:
                    latest_record_at = record_at
                if isinstance(record, dict) and record.get("type") == "session_meta":
                    payload = record.get("payload")
                    if not isinstance(payload, dict):
                        raise ValueError(
                            f"Codex session metadata is invalid at line {line_number}"
                        )
                    if payload.get("id") != expected_thread_id:
                        continue
                    source = payload.get("thread_source")
                    thread_source = (
                        source if source in {"user", "subagent"} else "unknown"
                    )
                    parent = payload.get("parent_thread_id")
                    parent_thread_id = (
                        parent if isinstance(parent, str) and parent.strip() else None
                    )
                    if thread_source == "subagent" and parent_thread_id is None:
                        raise ValueError(
                            "Codex spawned-agent session metadata lacks parent_thread_id "
                            f"at line {line_number}"
                        )
                continue
            record_at = _aware_timestamp(record.get("timestamp"))
            if record_at is not None:
                latest_record_at = record_at
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            event = payload.get("type")
            if event not in {"task_started", "task_complete", "turn_aborted"}:
                continue
            observed_at = record_at
            if observed_at is None:
                raise ValueError(
                    f"Codex task boundary has invalid timestamp at line {line_number}"
                )
            latest_event = event
            latest_boundary_at = observed_at
            turn_id = payload.get("turn_id")
            latest_turn_id = turn_id if isinstance(turn_id, str) and turn_id else None

    state: Literal["active_operation", "between_turns", "unknown"]
    if latest_event == "task_started":
        state = "active_operation"
    elif latest_event in {"task_complete", "turn_aborted"}:
        state = "between_turns"
    else:
        state = "unknown"
    return CodexActivityV1(
        session_id=session_id,
        transcript_path=str(transcript_path.expanduser().resolve()),
        thread_source=thread_source,
        parent_thread_id=parent_thread_id,
        state=state,
        observed_at=latest_record_at,
        boundary_at=latest_boundary_at,
        turn_id=latest_turn_id,
        evidence_event=latest_event,
    )


def read_native_codex_consumption(
    *,
    owner_session_id: str,
    correlation_id: str,
    queued_submission_id: str,
    transcript_path: Path,
) -> NativeCodexConsumptionReceiptV1 | None:
    """Find the exact continuity marker only in a native owner user-message event."""

    thread_id = owner_session_id.removeprefix("codex:")
    try:
        thread_id = str(uuid.UUID(thread_id))
    except ValueError as exc:
        raise ValueError("native consumption requires a UUID Codex owner session") from exc
    marker = f"continuity-resume:{correlation_id}:"

    def contains_marker(value: object) -> bool:
        if isinstance(value, str):
            return marker in value
        if isinstance(value, list):
            return any(contains_marker(item) for item in value)
        if isinstance(value, dict):
            return any(contains_marker(item) for item in value.values())
        return False

    resolved = transcript_path.expanduser().resolve()
    with resolved.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Codex transcript has malformed JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                continue
            payload = record.get("payload")
            if not isinstance(payload, dict):
                continue
            response_user_message = (
                record.get("type") == "response_item"
                and payload.get("type") == "message"
                and payload.get("role") == "user"
            )
            item = payload.get("item")
            completed_user_message = (
                record.get("type") == "event_msg"
                and payload.get("type") == "item_completed"
                and isinstance(item, dict)
                and item.get("type") == "UserMessage"
                and payload.get("thread_id") == thread_id
            )
            if not (response_user_message or completed_user_message) or not contains_marker(
                payload
            ):
                continue
            consumed_at = _aware_timestamp(record.get("timestamp"))
            if consumed_at is None:
                raise ValueError(
                    f"correlated native user message has invalid timestamp at line {line_number}"
                )
            return NativeCodexConsumptionReceiptV1(
                owner_session_id=owner_session_id,
                thread_id=thread_id,
                correlation_id=correlation_id,
                queued_submission_id=queued_submission_id,
                transcript_path=str(resolved),
                consumed_at=consumed_at,
            )
    return None


def assess_continuity(
    *,
    claim: ContinuityClaim,
    activity: CodexActivityV1 | None,
    now: datetime | None = None,
    notify_after: timedelta = timedelta(minutes=15),
) -> ContinuityAssessmentV1:
    """Classify custody while withholding transfer authority from passive signals."""

    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    if notify_after <= timedelta(0):
        raise ValueError("continuity notification threshold must be positive")
    if not claim.is_live() or not claim.next_action:
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="terminal",
            continuity_disposition=None,
            action="none",
            reason_code="no_unfinished_live_custody",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at if activity else None,
        )
    if claim.status == "handoff":
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="idle_owner",
            continuity_disposition="human_required",
            action="none",
            reason_code="explicit_handoff_requires_successor",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at if activity else None,
            resume_condition="an explicit successor accepts the handed-off custody",
        )
    if claim.status == "blocked":
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="idle_owner",
            continuity_disposition="human_required",
            action="none",
            reason_code="blocked_claim_requires_explicit_progress",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at if activity else None,
            resume_condition="the blocker is resolved and the claim returns to active",
        )
    if claim.status != "active":
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="unknown",
            continuity_disposition="circuit_breaker",
            action="fail_visible",
            reason_code="unsupported_auto_resume_claim_status",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at if activity else None,
            resume_condition="record an active claim before automatic owner resume",
        )

    quiet_until = _aware_timestamp(claim.expected_quiet_until)
    if (claim.expected_quiet_until is None) != (claim.quiet_reason is None) or (
        claim.expected_quiet_until is not None and quiet_until is None
    ):
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="unknown",
            continuity_disposition="circuit_breaker",
            action="fail_visible",
            reason_code="invalid_quiet_declaration",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at if activity else None,
            resume_condition="repair the bounded quiet deadline and reason",
        )
    if quiet_until is not None and quiet_until > observed_at and claim.quiet_reason:
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="intentional_quiet",
            continuity_disposition="active_continuing",
            action="none",
            reason_code="bounded_quiet_active",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at if activity else None,
            resume_condition=f"quiet interval ends at {quiet_until.isoformat()}",
        )

    if activity is None or activity.state == "unknown" or activity.observed_at is None:
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="unknown",
            continuity_disposition="circuit_breaker",
            action="fail_visible",
            reason_code="client_activity_unknown",
            observed_at=observed_at,
            last_client_activity_at=None,
            resume_condition="obtain authentic client task-boundary evidence",
        )
    if activity.session_id != claim.session_id:
        raise ValueError("client activity belongs to a different claim session")
    if activity.observed_at > observed_at:
        raise ValueError("client activity timestamp is in the future")
    inactivity = observed_at - activity.observed_at
    inactivity_seconds = int(inactivity.total_seconds())
    if activity.state == "active_operation" and inactivity < notify_after:
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="active_operation",
            continuity_disposition="active_continuing",
            action="none",
            reason_code="client_task_active",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at,
            inactivity_seconds=inactivity_seconds,
        )
    if activity.state == "active_operation":
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="idle_owner",
            continuity_disposition="active_continuing",
            action="notify_owner",
            reason_code="open_task_resume_offer_due",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at,
            inactivity_seconds=inactivity_seconds,
            resume_condition="current owner resumes or declares a bounded quiet interval",
        )
    if inactivity < notify_after:
        return ContinuityAssessmentV1(
            session_id=claim.session_id,
            activity_state="idle_owner",
            continuity_disposition="active_continuing",
            action="none",
            reason_code="owner_within_resume_grace",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at,
            inactivity_seconds=inactivity_seconds,
        )
    return ContinuityAssessmentV1(
        session_id=claim.session_id,
        activity_state="idle_owner",
        continuity_disposition="active_continuing",
        action="notify_owner",
        reason_code="owner_resume_offer_due",
        observed_at=observed_at,
        last_client_activity_at=activity.observed_at,
        inactivity_seconds=inactivity_seconds,
        transfer_candidate_observe_only=False,
        resume_condition="current owner resumes or an exact successor handshake is accepted",
    )


def native_resume_progress_fingerprint(
    *, progress_at: str | None, head_revision: str, next_action: str
) -> str:
    """Bind retry accounting to durable outcome evidence, not liveness telemetry."""

    normalized_progress = ""
    if progress_at is not None:
        parsed_progress = _aware_timestamp(progress_at)
        if parsed_progress is None:
            raise ValueError("native resume progress_at must be an aware timestamp")
        normalized_progress = parsed_progress.isoformat()
    normalized_head = head_revision.strip().lower()
    if re.fullmatch(r"[0-9a-f]{40,64}", normalized_head) is None:
        raise ValueError("native resume progress requires an exact Git revision")
    normalized_action = next_action.strip()
    if not normalized_action:
        raise ValueError("native resume progress requires an exact next action")
    fingerprint = (
        f"{normalized_progress}\0{normalized_head}\0{normalized_action}"
    ).encode()
    return hashlib.sha256(fingerprint).hexdigest()


def build_resume_offer_request(
    *,
    assessment: ContinuityAssessmentV1,
    sender_session_id: str,
    project: str,
    scope: str,
    next_action: str,
) -> coordination_messages.SendMessageRequest:
    """Build one idempotent owner-first resume offer from an idle assessment."""

    if assessment.action != "notify_owner" or assessment.session_id is None:
        raise ValueError("resume offers require one exact idle-owner notification assessment")
    if assessment.last_client_activity_at is None:
        raise ValueError("resume offer lacks exact client activity evidence")
    correlation_source = (
        f"{assessment.session_id}\0{assessment.last_client_activity_at.isoformat()}"
        f"\0{project}\0{scope}"
    )
    correlation = hashlib.sha256(correlation_source.encode("utf-8")).hexdigest()[:24]
    return coordination_messages.SendMessageRequest(
        caller_session_id=sender_session_id,
        sender_session_id=sender_session_id,
        recipient=coordination_messages.ExactSessionSelector(
            kind="session",
            session_id=assessment.session_id,
        ),
        project=project,
        kind="coordination_request",
        subject="Resume authorized work toward the next verified checkpoint",
        body=(
            "Your exact Codex session is between turns with authorized work remaining. "
            f"Resume current custody and continue this next action: {next_action}"
        ),
        ttl_seconds=60 * 60,
        idempotency_key=f"continuity-resume-offer-{correlation}",
        claim_ref=scope,
    )


def build_native_codex_resume_offer(
    *,
    assessment: ContinuityAssessmentV1,
    project: str,
    scope: str,
    next_action: str,
    progress_fingerprint: str,
) -> NativeCodexResumeOfferV1:
    """Build one exact-thread prompt accepted by the native Codex queue CLI."""

    if assessment.action != "notify_owner" or assessment.session_id is None:
        raise ValueError("native resume offers require one exact idle-owner assessment")
    if assessment.last_client_activity_at is None:
        raise ValueError("native resume offer lacks exact client activity evidence")
    prefix = "codex:"
    if not assessment.session_id.startswith(prefix):
        raise ValueError("native Codex resume offer requires a codex-prefixed session")
    raw_thread_id = assessment.session_id.removeprefix(prefix)
    try:
        thread_id = str(uuid.UUID(raw_thread_id))
    except ValueError as exc:
        raise ValueError("native Codex resume offer requires a UUID thread id") from exc
    if not project.strip() or not scope.strip() or not next_action.strip():
        raise ValueError("native Codex resume offer requires project, scope, and next action")
    correlation_source = (
        f"{assessment.session_id}\0{assessment.last_client_activity_at.isoformat()}"
        f"\0{project}\0{scope}\0{progress_fingerprint}"
    )
    correlation_id = hashlib.sha256(correlation_source.encode("utf-8")).hexdigest()[:24]
    prompt = (
        f"continuity-resume:{correlation_id}: Authorized work remains in {project}/{scope}. "
        "Continue in this exact thread yourself toward the next verified checkpoint. "
        "Do not spawn or delegate to any new agents as part of this automatic resume. "
        f"Next action: {next_action}"
    )
    return NativeCodexResumeOfferV1(
        owner_session_id=assessment.session_id,
        thread_id=thread_id,
        correlation_id=correlation_id,
        progress_fingerprint=progress_fingerprint,
        prompt=prompt,
    )


def parse_native_codex_queue_receipt(
    *, offer: NativeCodexResumeOfferV1, stdout: str
) -> NativeCodexQueueReceiptV1:
    """Accept only Codex's exact queue acknowledgement for the requested thread."""

    matched = _CODEX_QUEUE_RECEIPT.fullmatch(stdout)
    if matched is None:
        raise ValueError("Codex queue returned an invalid acceptance receipt")
    submission_id, thread_id = matched.groups()
    try:
        submission_id = str(uuid.UUID(submission_id))
        thread_id = str(uuid.UUID(thread_id))
    except ValueError as exc:
        raise ValueError("Codex queue receipt contains an invalid UUID") from exc
    if thread_id != offer.thread_id:
        raise ValueError("Codex queue receipt belongs to a different thread")
    return NativeCodexQueueReceiptV1(
        owner_session_id=offer.owner_session_id,
        thread_id=thread_id,
        correlation_id=offer.correlation_id,
        queued_submission_id=submission_id,
    )


def assess_resume_offer(
    *,
    assessment: ContinuityAssessmentV1,
    status: ResumeOfferStatus,
    now: datetime | None = None,
    successor_after: timedelta = timedelta(minutes=30),
) -> ResumeOfferReviewV1:
    """Allow successor launch only after the exact owner offer reached its runtime."""

    if successor_after <= timedelta(0):
        raise ValueError("successor threshold must be positive")
    if assessment.session_id is None or status.message.recipient_session_id != assessment.session_id:
        raise ValueError("resume offer status belongs to a different owner session")
    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    age = observed_at - status.message.created_at.astimezone(UTC)
    base = {
        "message_id": status.message.message_id,
        "owner_session_id": assessment.session_id,
        "transfer_eligible": False,
    }
    if (
        assessment.action != "notify_owner"
        or assessment.activity_state != "idle_owner"
        or (
            assessment.last_client_activity_at is not None
            and assessment.last_client_activity_at > status.message.created_at
        )
    ):
        return ResumeOfferReviewV1(
            **base,
            action="owner_responded",
            reason_code="owner_activity_after_resume_offer",
            successor_launch_allowed=False,
            resume_condition="current owner retains custody while client activity continues",
        )
    if status.acknowledged:
        return ResumeOfferReviewV1(
            **base,
            action="owner_responded",
            reason_code="owner_acknowledged_resume_offer",
            successor_launch_allowed=False,
            resume_condition="current owner retains custody unless it explicitly hands off",
        )
    if not (status.runtime_accepted or status.observed):
        return ResumeOfferReviewV1(
            **base,
            action="fail_visible",
            reason_code="resume_offer_not_delivered",
            successor_launch_allowed=False,
            resume_condition="obtain runtime acceptance evidence for the exact owner offer",
        )
    if age < successor_after:
        return ResumeOfferReviewV1(
            **base,
            action="wait_for_owner",
            reason_code="owner_response_window_active",
            successor_launch_allowed=False,
            resume_condition=(
                f"owner response window reaches {successor_after.total_seconds():.0f} seconds"
            ),
        )
    return ResumeOfferReviewV1(
        **base,
        action="launch_successor",
        reason_code="delivered_resume_offer_unanswered",
        successor_launch_allowed=True,
        resume_condition="successor must accept exact claim, revision, branch, worktree, and next action",
    )


def build_successor_custody_offer(
    *,
    review: ResumeOfferReviewV1,
    project: str,
    scope: str,
    branch: str,
    worktree_path: str,
    claim_epoch_sha256: str,
    head_revision: str,
    next_action: str,
    created_at: datetime | None = None,
) -> SuccessorCustodyOfferV1:
    """Freeze the exact lane state a later successor may explicitly accept."""

    if review.action != "launch_successor" or not review.successor_launch_allowed:
        raise ValueError("successor custody offer requires an allowed successor launch")
    offered_at = (created_at or datetime.now(UTC)).astimezone(UTC)
    exact = {
        "owner_resume_message_id": review.message_id,
        "predecessor_session_id": review.owner_session_id,
        "project": project.strip(),
        "scope": scope.strip(),
        "branch": branch.strip(),
        "worktree_path": str(Path(worktree_path).expanduser().resolve()),
        "claim_epoch_sha256": claim_epoch_sha256,
        "head_revision": head_revision,
        "next_action": next_action.strip(),
        "created_at": offered_at.isoformat(),
    }
    if any(not exact[field] for field in ("project", "scope", "branch", "next_action")):
        raise ValueError("successor custody offer requires complete exact lane state")
    correlation = hashlib.sha256(
        json.dumps(exact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return SuccessorCustodyOfferV1(offer_id=correlation, **exact)


def build_native_successor_custody_offer(
    *,
    delivery: NativeCodexDeliveryJournalV1,
    consumption: NativeCodexConsumptionReceiptV1,
    consumed_attempt_count: int,
    project: str,
    scope: str,
    branch: str,
    worktree_path: str,
    claim_epoch_sha256: str,
    head_revision: str,
    next_action: str,
    created_at: datetime | None = None,
) -> SuccessorCustodyOfferV1:
    """Freeze custody after bounded, consumed native retries without launching it."""

    if consumed_attempt_count < 2:
        raise ValueError("native successor offer requires the bounded retry circuit breaker")
    if delivery.state != "accepted" or delivery.progress_fingerprint is None:
        raise ValueError("native successor offer requires an accepted progress-bound delivery")
    matching = (
        delivery.owner_session_id == consumption.owner_session_id
        and delivery.thread_id == consumption.thread_id
        and delivery.correlation_id == consumption.correlation_id
        and delivery.queued_submission_id == consumption.queued_submission_id
    )
    if not matching:
        raise ValueError("native successor offer requires matching delivery and consumption")
    offered_at = (created_at or datetime.now(UTC)).astimezone(UTC)
    exact = {
        "owner_resume_correlation_id": delivery.correlation_id,
        "predecessor_session_id": delivery.owner_session_id,
        "project": project.strip(),
        "scope": scope.strip(),
        "branch": branch.strip(),
        "worktree_path": str(Path(worktree_path).expanduser().resolve()),
        "claim_epoch_sha256": claim_epoch_sha256,
        "head_revision": head_revision,
        "next_action": next_action.strip(),
        "created_at": offered_at.isoformat(),
    }
    if any(not exact[field] for field in ("project", "scope", "branch", "next_action")):
        raise ValueError("native successor offer requires complete exact lane state")
    correlation = hashlib.sha256(
        json.dumps(exact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return SuccessorCustodyOfferV1(offer_id=correlation, **exact)


def successor_custody_offer_sha256(offer: SuccessorCustodyOfferV1) -> str:
    """Return the canonical digest bound into a successor acceptance receipt."""

    canonical = json.dumps(
        offer.model_dump(mode="json", exclude_none=True),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def build_codex_successor_launch(
    *,
    offer: SuccessorCustodyOfferV1,
    offer_path: str,
    resume_script: str,
    predecessor_process_pid: int,
    predecessor_process_start_ticks: int,
    codex: str = "codex",
    systemd_run: str = "systemd-run",
) -> CodexSuccessorLaunchV1:
    """Build one transient fork whose first authorized mutation is acceptance."""

    if not offer.predecessor_session_id.startswith("codex:"):
        raise ValueError("Codex successor launch requires a Codex predecessor session")
    if predecessor_process_pid <= 1 or predecessor_process_start_ticks < 1:
        raise ValueError("Codex successor launch requires exact predecessor process identity")
    predecessor_thread_id = offer.predecessor_session_id.removeprefix("codex:")
    resolved_offer = Path(offer_path).expanduser()
    resolved_resume = Path(resume_script).expanduser()
    if not resolved_offer.is_absolute() or not resolved_resume.is_absolute():
        raise ValueError("successor offer and resume script paths must be absolute")
    resolved_offer = resolved_offer.resolve()
    resolved_resume = resolved_resume.resolve()
    accept_command = shlex.join(
        [
            "/usr/bin/python3",
            str(resolved_resume),
            "--agent",
            "codex",
            "--project",
            offer.project,
            "--scope",
            offer.scope,
            "--worktree-path",
            offer.worktree_path,
            "--branch",
            offer.branch,
            "--current-phase",
            "accept exact successor custody",
            "--successor-custody-offer",
            str(resolved_offer),
            "--accept-successor-custody-offer",
            "--predecessor-process-pid",
            str(predecessor_process_pid),
            "--predecessor-process-start-ticks",
            str(predecessor_process_start_ticks),
            "--json",
        ]
    )
    prompt = (
        f"Automatic successor custody offer {offer.offer_id}. Before any mutation, run exactly:\n"
        f"{accept_command}\n"
        "If exact acceptance fails, stop and report the failure without changing custody. "
        f"After acceptance, continue this authorized next action: {offer.next_action}"
    )
    unit = f"enforced-planning-successor-{offer.offer_id}"
    argv = [
        systemd_run,
        "--user",
        "--collect",
        "--unit",
        unit,
        "--property",
        f"WorkingDirectory={offer.worktree_path}",
        "--",
        codex,
        "exec",
        "fork",
        "--json",
        predecessor_thread_id,
        prompt,
    ]
    return CodexSuccessorLaunchV1(
        offer_id=offer.offer_id,
        offer_sha256=successor_custody_offer_sha256(offer),
        predecessor_session_id=offer.predecessor_session_id,
        predecessor_thread_id=predecessor_thread_id,
        predecessor_process_pid=predecessor_process_pid,
        predecessor_process_start_ticks=predecessor_process_start_ticks,
        offer_path=str(resolved_offer),
        worktree_path=offer.worktree_path,
        prompt=prompt,
        prompt_sha256=hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        systemd_unit=unit,
        argv=argv,
    )


def accept_successor_custody_offer(
    *,
    offer: SuccessorCustodyOfferV1,
    successor_session_id: str,
    project: str,
    scope: str,
    branch: str,
    worktree_path: str,
    claim_epoch_sha256: str,
    head_revision: str,
    next_action: str,
    accepted_at: datetime | None = None,
) -> SuccessorCustodyAcceptanceV1:
    """Accept only an exact offer; this receipt does not itself mutate custody."""

    if not successor_session_id.strip() or successor_session_id == offer.predecessor_session_id:
        raise ValueError("successor acceptance requires a different exact session")
    observed = {
        "project": project.strip(),
        "scope": scope.strip(),
        "branch": branch.strip(),
        "worktree_path": str(Path(worktree_path).expanduser().resolve()),
        "claim_epoch_sha256": claim_epoch_sha256,
        "head_revision": head_revision,
        "next_action": next_action.strip(),
    }
    mismatched = [field for field, value in observed.items() if value != getattr(offer, field)]
    if mismatched:
        raise ValueError(
            "successor acceptance does not match offered custody fields: "
            + ", ".join(mismatched)
        )
    return SuccessorCustodyAcceptanceV1(
        offer_id=offer.offer_id,
        offer_sha256=successor_custody_offer_sha256(offer),
        predecessor_session_id=offer.predecessor_session_id,
        successor_session_id=successor_session_id,
        accepted_at=(accepted_at or datetime.now(UTC)).astimezone(UTC),
        **observed,
    )


def validate_successor_custody_acceptance(
    *,
    offer: SuccessorCustodyOfferV1,
    acceptance: SuccessorCustodyAcceptanceV1,
) -> SuccessorCustodyAcceptanceV1:
    """Verify a successor receipt is bound to the exact immutable offer."""

    expected = {
        "offer_id": offer.offer_id,
        "offer_sha256": successor_custody_offer_sha256(offer),
        "predecessor_session_id": offer.predecessor_session_id,
        "project": offer.project,
        "scope": offer.scope,
        "branch": offer.branch,
        "worktree_path": offer.worktree_path,
        "claim_epoch_sha256": offer.claim_epoch_sha256,
        "head_revision": offer.head_revision,
        "next_action": offer.next_action,
    }
    mismatched = [
        field for field, value in expected.items() if getattr(acceptance, field) != value
    ]
    if acceptance.successor_session_id == offer.predecessor_session_id:
        mismatched.append("successor_session_id")
    if mismatched:
        raise ValueError(
            "successor custody acceptance is not bound to exact offer fields: "
            + ", ".join(mismatched)
        )
    return acceptance


__all__ = [
    "CodexActivityV1",
    "CodexSuccessorLaunchReceiptV1",
    "CodexSuccessorLaunchV1",
    "ContinuityAssessmentV1",
    "NativeCodexConsumptionReceiptV1",
    "NativeCodexDeliveryJournalV1",
    "NativeCodexQueueReceiptV1",
    "NativeCodexResumeOfferV1",
    "NativeCodexSuccessorLaunchJournalV1",
    "ResumeOfferReviewV1",
    "SuccessorCustodyAcceptanceV1",
    "SuccessorCustodyOfferV1",
    "accept_successor_custody_offer",
    "assess_continuity",
    "assess_resume_offer",
    "build_codex_successor_launch",
    "build_native_codex_resume_offer",
    "build_native_successor_custody_offer",
    "build_resume_offer_request",
    "build_successor_custody_offer",
    "native_resume_progress_fingerprint",
    "parse_native_codex_queue_receipt",
    "read_codex_activity",
    "read_native_codex_consumption",
    "successor_custody_offer_sha256",
    "validate_successor_custody_acceptance",
]
