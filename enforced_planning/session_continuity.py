"""Classify session activity without turning silence into takeover authority."""

from __future__ import annotations

import hashlib
import json
import re
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


class NativeCodexResumeOfferV1(BaseModel):
    """One exact, idempotently identifiable prompt for Codex's durable queue."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_resume_offer"] = "native_codex_resume_offer"
    owner_session_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    correlation_id: str = Field(pattern=r"^[0-9a-f]{24}$")
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


class NativeCodexDeliveryJournalV1(BaseModel):
    """Write-ahead state for one correlation-bound native queue attempt."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["native_codex_resume_delivery"] = "native_codex_resume_delivery"
    owner_session_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    correlation_id: str = Field(pattern=r"^[0-9a-f]{24}$")
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
        f"\0{project}\0{scope}"
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


__all__ = [
    "CodexActivityV1",
    "ContinuityAssessmentV1",
    "NativeCodexDeliveryJournalV1",
    "NativeCodexQueueReceiptV1",
    "NativeCodexResumeOfferV1",
    "ResumeOfferReviewV1",
    "assess_continuity",
    "assess_resume_offer",
    "build_native_codex_resume_offer",
    "build_resume_offer_request",
    "parse_native_codex_queue_receipt",
    "read_codex_activity",
]
