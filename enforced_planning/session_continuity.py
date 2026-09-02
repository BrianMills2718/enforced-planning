"""Classify session activity without turning silence into takeover authority."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field


class ContinuityClaim(Protocol):
    """Claim fields required by the observe-only continuity classifier."""

    status: str
    session_id: str | None
    progress_at: str | None
    next_action: str | None
    expected_quiet_until: str | None
    quiet_reason: str | None

    def is_live(self) -> bool: ...


class CodexActivityV1(BaseModel):
    """Last durable Codex task boundary observed in one exact transcript."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["codex_session_activity"] = "codex_session_activity"
    session_id: str = Field(min_length=1)
    transcript_path: str = Field(min_length=1)
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


def _aware_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def read_codex_activity(*, session_id: str, transcript_path: Path) -> CodexActivityV1:
    """Read the latest task boundary; malformed transcript records fail visibly."""

    latest_event: Literal["task_started", "task_complete", "turn_aborted"] | None = None
    latest_boundary_at: datetime | None = None
    latest_record_at: datetime | None = None
    latest_turn_id: str | None = None
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
                record_at = _aware_timestamp(record.get("timestamp")) if isinstance(record, dict) else None
                if record_at is not None:
                    latest_record_at = record_at
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
    transfer_observe_after: timedelta = timedelta(minutes=30),
) -> ContinuityAssessmentV1:
    """Classify custody while withholding transfer authority from passive signals."""

    observed_at = (now or datetime.now(UTC)).astimezone(UTC)
    if notify_after <= timedelta(0) or transfer_observe_after < notify_after:
        raise ValueError("continuity thresholds must be positive and ordered")
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
            activity_state="unknown",
            continuity_disposition="circuit_breaker",
            action="fail_visible",
            reason_code="open_task_activity_stale",
            observed_at=observed_at,
            last_client_activity_at=activity.observed_at,
            inactivity_seconds=inactivity_seconds,
            resume_condition="observe a fresh client event or a bounded quiet declaration",
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
        transfer_candidate_observe_only=inactivity >= transfer_observe_after,
        resume_condition="current owner resumes or an exact successor handshake is accepted",
    )


__all__ = [
    "CodexActivityV1",
    "ContinuityAssessmentV1",
    "assess_continuity",
    "read_codex_activity",
]
