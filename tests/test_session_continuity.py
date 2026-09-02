"""Tests for resume-first session continuity classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from enforced_planning import coordination_messages

from enforced_planning.session_continuity import (
    CodexActivityV1,
    assess_continuity,
    assess_resume_offer,
    build_resume_offer_request,
    read_codex_activity,
)


NOW = datetime(2026, 9, 2, 4, 30, tzinfo=UTC)


@dataclass
class Claim:
    status: str = "active"
    session_id: str | None = "codex:owner"
    progress_at: str | None = "2026-09-02T04:00:00+00:00"
    next_action: str | None = "continue the verified implementation"
    expected_quiet_until: str | None = None
    quiet_reason: str | None = None

    def is_live(self) -> bool:
        return self.status in {"active", "blocked", "handoff", "session_ended"}


def activity(state: str, minutes_ago: int) -> CodexActivityV1:
    event = "task_started" if state == "active_operation" else "task_complete"
    return CodexActivityV1(
        session_id="codex:owner",
        transcript_path="/tmp/fixture.jsonl",
        state=state,
        observed_at=NOW - timedelta(minutes=minutes_ago),
        evidence_event=event,
    )


def write_transcript(path: Path, events: list[tuple[str, str]]) -> None:
    records = [
        {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {"type": event, "turn_id": "turn-1"},
        }
        for timestamp, event in events
    ]
    path.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")


def test_active_task_retains_owner_even_when_started_long_ago() -> None:
    result = assess_continuity(claim=Claim(), activity=activity("active_operation", 1), now=NOW)

    assert result.activity_state == "active_operation"
    assert result.action == "none"
    assert result.continuity_disposition == "active_continuing"
    assert result.transfer_eligible is False


def test_silent_open_task_gets_owner_offer_without_licensing_takeover() -> None:
    result = assess_continuity(claim=Claim(), activity=activity("active_operation", 120), now=NOW)

    assert result.activity_state == "idle_owner"
    assert result.action == "notify_owner"
    assert result.reason_code == "open_task_resume_offer_due"
    assert result.transfer_candidate_observe_only is False
    assert result.transfer_eligible is False


def test_recent_between_turns_owner_remains_in_grace() -> None:
    result = assess_continuity(claim=Claim(), activity=activity("between_turns", 14), now=NOW)

    assert result.reason_code == "owner_within_resume_grace"
    assert result.action == "none"
    assert result.transfer_candidate_observe_only is False


def test_idle_owner_is_offered_resume_before_transfer() -> None:
    result = assess_continuity(claim=Claim(), activity=activity("between_turns", 15), now=NOW)

    assert result.action == "notify_owner"
    assert result.reason_code == "owner_resume_offer_due"
    assert result.transfer_candidate_observe_only is False
    assert result.transfer_eligible is False


def test_thirty_minutes_is_observe_only_not_transfer_authority() -> None:
    result = assess_continuity(claim=Claim(), activity=activity("between_turns", 30), now=NOW)

    assert result.action == "notify_owner"
    assert result.transfer_candidate_observe_only is False
    assert result.transfer_eligible is False
    assert result.continuity_disposition == "active_continuing"


def test_idle_assessment_builds_exact_idempotent_resume_offer() -> None:
    assessment = assess_continuity(
        claim=Claim(),
        activity=activity("between_turns", 30),
        now=NOW,
    )

    first = build_resume_offer_request(
        assessment=assessment,
        sender_session_id="codex:coordinator",
        project="demo",
        scope="feature-lane",
        next_action="run the focused integration",
    )
    second = build_resume_offer_request(
        assessment=assessment,
        sender_session_id="codex:coordinator",
        project="demo",
        scope="feature-lane",
        next_action="run the focused integration",
    )

    assert first.recipient.session_id == "codex:owner"
    assert first.idempotency_key == second.idempotency_key
    assert first.claim_ref == "feature-lane"
    assert "run the focused integration" in (first.body or "")
    assert first.ttl_seconds == 60 * 60


def test_active_owner_cannot_receive_idle_resume_offer() -> None:
    assessment = assess_continuity(
        claim=Claim(),
        activity=activity("active_operation", 1),
        now=NOW,
    )

    with pytest.raises(ValueError, match="idle-owner"):
        build_resume_offer_request(
            assessment=assessment,
            sender_session_id="codex:coordinator",
            project="demo",
            scope="feature-lane",
            next_action="continue",
        )


@dataclass
class OfferStatus:
    message: coordination_messages.CoordinationMessage
    runtime_accepted: bool = False
    observed: bool = False
    acknowledged: bool = False


def offer_status(*, delivered: bool, acknowledged: bool = False) -> OfferStatus:
    message = coordination_messages.CoordinationMessage(
        schema_version="1.0",
        message_id="msg_" + "a" * 32,
        sender_session_id="codex:coordinator",
        recipient_selector=coordination_messages.ExactSessionSelector(
            kind="session", session_id="codex:owner"
        ),
        recipient_session_id="codex:owner",
        project="demo",
        kind="coordination_request",
        subject="Resume",
        body="Resume exact custody",
        created_at=NOW - timedelta(minutes=31),
        expires_at=NOW + timedelta(minutes=29),
        request_sha256="b" * 64,
        claim_ref="feature-lane",
    )
    return OfferStatus(
        message=message,
        runtime_accepted=delivered,
        observed=delivered,
        acknowledged=acknowledged,
    )


def test_persisted_only_offer_fails_visible_and_cannot_launch_successor() -> None:
    assessment = assess_continuity(
        claim=Claim(), activity=activity("between_turns", 31), now=NOW
    )

    review = assess_resume_offer(
        assessment=assessment,
        status=offer_status(delivered=False),
        now=NOW,
    )

    assert review.action == "fail_visible"
    assert review.successor_launch_allowed is False
    assert review.transfer_eligible is False


def test_delivered_unanswered_offer_allows_successor_launch_not_transfer() -> None:
    assessment = assess_continuity(
        claim=Claim(), activity=activity("between_turns", 31), now=NOW
    )

    review = assess_resume_offer(
        assessment=assessment,
        status=offer_status(delivered=True),
        now=NOW,
    )

    assert review.action == "launch_successor"
    assert review.successor_launch_allowed is True
    assert review.transfer_eligible is False
    assert "must accept exact claim" in review.resume_condition


def test_owner_acknowledgement_retains_current_custody() -> None:
    assessment = assess_continuity(
        claim=Claim(), activity=activity("between_turns", 31), now=NOW
    )

    review = assess_resume_offer(
        assessment=assessment,
        status=offer_status(delivered=True, acknowledged=True),
        now=NOW,
    )

    assert review.action == "owner_responded"
    assert review.successor_launch_allowed is False
    assert review.transfer_eligible is False


def test_fresh_owner_activity_after_offer_cancels_successor_launch() -> None:
    assessment = assess_continuity(
        claim=Claim(), activity=activity("active_operation", 1), now=NOW
    )
    status = offer_status(delivered=True)

    review = assess_resume_offer(assessment=assessment, status=status, now=NOW)

    assert review.action == "owner_responded"
    assert review.reason_code == "owner_activity_after_resume_offer"
    assert review.successor_launch_allowed is False
    assert review.transfer_eligible is False


def test_bounded_quiet_suppresses_idle_recovery() -> None:
    claim = Claim(
        expected_quiet_until="2026-09-02T05:00:00+00:00",
        quiet_reason="bounded integration test",
    )

    result = assess_continuity(claim=claim, activity=activity("between_turns", 60), now=NOW)

    assert result.activity_state == "intentional_quiet"
    assert result.action == "none"
    assert result.transfer_eligible is False


def test_unknown_activity_fails_visible_without_takeover() -> None:
    result = assess_continuity(claim=Claim(), activity=None, now=NOW)

    assert result.activity_state == "unknown"
    assert result.action == "fail_visible"
    assert result.continuity_disposition == "circuit_breaker"
    assert result.transfer_eligible is False


def test_terminal_claim_needs_no_continuity_action() -> None:
    result = assess_continuity(
        claim=Claim(status="completed", next_action=None),
        activity=activity("between_turns", 60),
        now=NOW,
    )

    assert result.activity_state == "terminal"
    assert result.continuity_disposition is None
    assert result.action == "none"


def test_activity_identity_must_match_claim() -> None:
    wrong = activity("between_turns", 30).model_copy(update={"session_id": "codex:other"})

    with pytest.raises(ValueError, match="different claim session"):
        assess_continuity(claim=Claim(), activity=wrong, now=NOW)


def test_codex_transcript_tracks_unmatched_task_start(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    records = [
        {
            "timestamp": "2026-09-02T04:00:00Z",
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "turn-1"},
        },
        {
            "timestamp": "2026-09-02T04:20:00Z",
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-2"},
        },
        {
            "timestamp": "2026-09-02T04:29:00Z",
            "type": "response_item",
            "payload": {"type": "reasoning"},
        },
    ]
    transcript.write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )

    result = read_codex_activity(session_id="codex:owner", transcript_path=transcript)

    assert result.state == "active_operation"
    assert result.boundary_at == datetime(2026, 9, 2, 4, 20, tzinfo=UTC)
    assert result.observed_at == datetime(2026, 9, 2, 4, 29, tzinfo=UTC)


def test_codex_transcript_tracks_completed_turn(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    write_transcript(
        transcript,
        [
            ("2026-09-02T04:20:00Z", "task_started"),
            ("2026-09-02T04:21:00Z", "task_complete"),
        ],
    )

    result = read_codex_activity(session_id="codex:owner", transcript_path=transcript)

    assert result.state == "between_turns"
    assert result.evidence_event == "task_complete"


def test_malformed_transcript_fails_visible(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    transcript.write_text("{not-json}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="malformed JSON"):
        read_codex_activity(session_id="codex:owner", transcript_path=transcript)
