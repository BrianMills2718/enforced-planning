"""Tests for resume-first session continuity classification."""

from __future__ import annotations

import fcntl
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from enforced_planning import coordination_messages
from enforced_planning.session_continuity import (
    CodexActivityV1,
    assess_continuity,
    assess_resume_offer,
    build_native_codex_resume_offer,
    build_resume_offer_request,
    parse_native_codex_queue_receipt,
    read_codex_activity,
)
from scripts import session_continuity as continuity_cli

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


def test_idle_assessment_builds_exact_native_codex_queue_offer() -> None:
    assessment = assess_continuity(
        claim=Claim(session_id="codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"),
        activity=activity("between_turns", 30).model_copy(
            update={"session_id": "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"}
        ),
        now=NOW,
    )

    first = build_native_codex_resume_offer(
        assessment=assessment,
        project="demo",
        scope="feature-lane",
        next_action="run the focused integration",
    )
    second = build_native_codex_resume_offer(
        assessment=assessment,
        project="demo",
        scope="feature-lane",
        next_action="run the focused integration",
    )

    assert first.thread_id == "01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    assert first.correlation_id == second.correlation_id
    assert f"continuity-resume:{first.correlation_id}" in first.prompt
    assert "run the focused integration" in first.prompt


def test_native_codex_queue_receipt_requires_exact_thread() -> None:
    assessment = assess_continuity(
        claim=Claim(session_id="codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"),
        activity=activity("between_turns", 30).model_copy(
            update={"session_id": "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"}
        ),
        now=NOW,
    )
    offer = build_native_codex_resume_offer(
        assessment=assessment,
        project="demo",
        scope="feature-lane",
        next_action="continue",
    )

    receipt = parse_native_codex_queue_receipt(
        offer=offer,
        stdout=(
            "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
            "01a05b94-d5d8-7d82-8a9a-6c64c6979e96.\n"
        ),
    )

    assert receipt.runtime_accepted is True
    assert receipt.correlation_id == offer.correlation_id


def test_native_codex_queue_receipt_rejects_wrong_thread() -> None:
    assessment = assess_continuity(
        claim=Claim(session_id="codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"),
        activity=activity("between_turns", 30).model_copy(
            update={"session_id": "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"}
        ),
        now=NOW,
    )
    offer = build_native_codex_resume_offer(
        assessment=assessment,
        project="demo",
        scope="feature-lane",
        next_action="continue",
    )

    with pytest.raises(ValueError, match="different thread"):
        parse_native_codex_queue_receipt(
            offer=offer,
            stdout=(
                "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
                "00000000-0000-0000-0000-000000000001.\n"
            ),
        )


def test_exact_cli_queues_native_offer_and_returns_typed_receipt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    claim = SweepClaim(
        session_id="codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    )
    idle = activity("between_turns", 30).model_copy(
        update={"session_id": claim.session_id}
    )
    monkeypatch.setattr(continuity_cli.coordination_claims, "check_claims", lambda: [claim])
    monkeypatch.setattr(
        continuity_cli.coordination_claims,
        "session_transcript_path",
        lambda _session_id: Path("/tmp/unused.jsonl"),
    )
    monkeypatch.setattr(
        continuity_cli.session_continuity,
        "read_codex_activity",
        lambda **_kwargs: idle,
    )
    monkeypatch.setattr(
        continuity_cli.subprocess,
        "run",
        lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            (
                "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
                "01a05b94-d5d8-7d82-8a9a-6c64c6979e96.\n"
            ),
            "",
        ),
    )

    assert continuity_cli.main(
        [
            "--project",
            "demo",
            "--scope",
            "feature-lane",
            "--queue-native-resume-offer",
            "--json",
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["native_resume_offer"] == {
        "schema_version": "1.0",
        "record_type": "native_codex_queue_receipt",
        "owner_session_id": "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
        "thread_id": "01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
        "correlation_id": payload["native_resume_offer"]["correlation_id"],
        "queued_submission_id": "01a0608f-1498-7413-b469-3e538a9bf171",
        "runtime_accepted": True,
    }


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


def test_malformed_quiet_declaration_fails_visible() -> None:
    claim = Claim(
        expected_quiet_until="not-a-timestamp",
        quiet_reason="bounded integration test",
    )

    result = assess_continuity(
        claim=claim, activity=activity("between_turns", 60), now=NOW
    )

    assert result.activity_state == "unknown"
    assert result.action == "fail_visible"
    assert result.reason_code == "invalid_quiet_declaration"
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


@dataclass
class SweepClaim(Claim):
    agent: str = "codex"
    scope: str = "feature-lane"
    project: str = "demo"

    @property
    def projects(self) -> list[str]:
        return [self.project]

    def primary_project(self) -> str:
        return self.project


def native_delivery_sweep_fixture() -> dict[str, object]:
    session_id = "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    assessment = assess_continuity(
        claim=Claim(session_id=session_id),
        activity=activity("between_turns", 30).model_copy(
            update={"session_id": session_id}
        ),
        now=NOW,
    )
    return {
        "items": [
            {
                "project": "demo",
                "scope": "feature-lane",
                "session_id": session_id,
                "next_action": "run the focused integration",
                "assessment": assessment.model_dump(mode="json"),
            }
        ]
    }


def test_native_delivery_journal_prevents_duplicate_queue_for_same_boundary(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "receipts.jsonl"
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            (
                "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
                "01a05b94-d5d8-7d82-8a9a-6c64c6979e96.\n"
            ),
            "",
        )

    first = continuity_cli.deliver_native_resume_offers(
        sweep=native_delivery_sweep_fixture(),
        receipt_path=receipt_path,
        run=fake_run,
    )
    second = continuity_cli.deliver_native_resume_offers(
        sweep=native_delivery_sweep_fixture(),
        receipt_path=receipt_path,
        run=fake_run,
    )

    assert first[0]["action"] == "queued_owner_resume"
    assert second[0]["reason_code"] == "already_accepted_for_activity_boundary"
    assert len(calls) == 1
    records = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    assert [record["state"] for record in records] == ["intent", "accepted"]


def test_unresolved_delivery_intent_fails_visible_without_retry(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "receipts.jsonl"
    sweep = native_delivery_sweep_fixture()
    assessment = continuity_cli.session_continuity.ContinuityAssessmentV1.model_validate(
        sweep["items"][0]["assessment"]  # type: ignore[index]
    )
    offer = build_native_codex_resume_offer(
        assessment=assessment,
        project="demo",
        scope="feature-lane",
        next_action="run the focused integration",
    )
    continuity_cli._append_delivery_state(
        receipt_path=receipt_path,
        offer=offer,
        state="intent",
    )

    result = continuity_cli.deliver_native_resume_offers(
        sweep=sweep,
        receipt_path=receipt_path,
        run=lambda *_args, **_kwargs: pytest.fail("indeterminate intent must not retry"),
    )

    assert result[0]["action"] == "fail_visible"
    assert result[0]["reason_code"] == "prior_delivery_outcome_indeterminate"


def test_delivery_timer_uses_one_shared_process_with_native_queue_enabled(
    tmp_path: Path,
) -> None:
    service, _timer = continuity_cli.render_observe_timer(
        script_path=tmp_path / "session_continuity.py",
        python_path=Path("/usr/bin/python3"),
        receipt_path=tmp_path / "receipts.jsonl",
        timer_minutes=10,
        notify_minutes=15,
        delivery_enabled=True,
        codex_path=Path("/opt/codex/bin/codex"),
    )

    assert "Type=oneshot" in service
    assert service.count("--deliver-native-resume-offers") == 1
    assert "--codex /opt/codex/bin/codex" in service


def test_shared_sweep_observes_all_codex_claims_without_transfer_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recent = tmp_path / "recent.jsonl"
    idle = tmp_path / "idle.jsonl"
    now = datetime.now(UTC)
    write_transcript(
        recent,
        [((now - timedelta(minutes=1)).isoformat(), "task_started")],
    )
    write_transcript(
        idle,
        [((now - timedelta(minutes=30)).isoformat(), "task_complete")],
    )
    claims = [
        SweepClaim(session_id="codex:recent", scope="recent"),
        SweepClaim(session_id="codex:idle", scope="idle"),
    ]
    transcripts = {"codex:recent": recent, "codex:idle": idle}
    monkeypatch.setattr(continuity_cli.coordination_claims, "check_claims", lambda: claims)
    monkeypatch.setattr(
        continuity_cli.coordination_claims,
        "session_transcript_path",
        lambda session_id: transcripts.get(session_id),
    )

    result = continuity_cli.build_observe_sweep(notify_minutes=15)

    assert result["claim_count"] == 2
    assert result["notify_owner_count"] == 1
    assert result["fail_visible_count"] == 0
    assert result["transfer_eligible"] is False
    assert result["successor_launch_allowed"] is False
    assert {item["scope"] for item in result["items"]} == {"recent", "idle"}


def test_shared_sweep_keeps_malformed_transcript_visible(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transcript = tmp_path / "malformed.jsonl"
    transcript.write_text("{bad-json}\n", encoding="utf-8")
    claim = SweepClaim()
    monkeypatch.setattr(continuity_cli.coordination_claims, "check_claims", lambda: [claim])
    monkeypatch.setattr(
        continuity_cli.coordination_claims,
        "session_transcript_path",
        lambda _session_id: transcript,
    )

    result = continuity_cli.build_observe_sweep(notify_minutes=15)

    assert result["fail_visible_count"] == 1
    assert result["items"][0]["assessment"] is None
    assert result["items"][0]["error"]["type"] == "ValueError"
    assert result["transfer_eligible"] is False


def test_observe_timer_is_one_shared_oneshot_process(tmp_path: Path) -> None:
    service, timer = continuity_cli.render_observe_timer(
        script_path=tmp_path / "session_continuity.py",
        python_path=Path("/usr/bin/python3"),
        receipt_path=tmp_path / "receipts.jsonl",
        timer_minutes=10,
        notify_minutes=15,
    )

    assert "Type=oneshot" in service
    assert "--scan-all-live-claims" in service
    assert "--send-resume-offer" not in service
    assert "OnUnitActiveSec=10m" in timer
    assert timer.count("Unit=enforced-planning-session-continuity.service") == 1


def test_install_observe_timer_records_owner_review_and_retirement(
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(command, 0, "", "")

    result = continuity_cli.install_observe_timer(
        unit_dir=tmp_path / "units",
        receipt_path=tmp_path / "state/receipts.jsonl",
        timer_minutes=10,
        notify_minutes=15,
        run=fake_run,
    )

    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    assert metadata["mode"] == "observe"
    assert metadata["owner"] == "enforced-planning"
    assert metadata["review_after"]
    assert "retire" in metadata["retirement_condition"]
    assert calls == [
        ("systemctl", "--user", "show-environment"),
        ("systemctl", "--user", "daemon-reload"),
        (
            "systemctl",
            "--user",
            "enable",
            "--now",
            "enforced-planning-session-continuity.timer",
        ),
        (
            "systemctl",
            "--user",
            "is-enabled",
            "enforced-planning-session-continuity.timer",
        ),
        (
            "systemctl",
            "--user",
            "is-active",
            "enforced-planning-session-continuity.timer",
        ),
    ]


def test_install_native_delivery_timer_records_mode_and_exact_codex(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        continuity_cli.shutil,
        "which",
        lambda _name: "/opt/codex/bin/codex",
    )

    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 0, "", "")

    result = continuity_cli.install_observe_timer(
        unit_dir=tmp_path / "units",
        receipt_path=tmp_path / "state/receipts.jsonl",
        timer_minutes=10,
        notify_minutes=15,
        delivery_enabled=True,
        run=fake_run,
    )

    metadata = json.loads(Path(result["metadata_path"]).read_text(encoding="utf-8"))
    service = Path(result["service_path"]).read_text(encoding="utf-8")
    assert metadata["mode"] == "native_resume_delivery"
    assert metadata["codex_path"] == "/opt/codex/bin/codex"
    assert "--deliver-native-resume-offers" in service
    assert "--codex /opt/codex/bin/codex" in service


def test_install_observe_timer_rejects_unowned_unit_collision(tmp_path: Path) -> None:
    unit_dir = tmp_path / "units"
    unit_dir.mkdir()
    (unit_dir / "enforced-planning-session-continuity.service").write_text(
        "unrelated service\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="occupied without owner metadata"):
        continuity_cli.install_observe_timer(
            unit_dir=unit_dir,
            receipt_path=tmp_path / "receipts.jsonl",
            timer_minutes=10,
            notify_minutes=15,
        )


def test_sweep_receipt_is_one_json_line(tmp_path: Path) -> None:
    receipt = tmp_path / "receipts.jsonl"
    payload = {"schema_version": "1.0", "mode": "observe"}

    continuity_cli._append_receipt(receipt, payload)

    assert json.loads(receipt.read_text(encoding="utf-8")) == payload
    assert receipt.stat().st_mode & 0o777 == 0o600


def test_full_sweep_rejects_overlapping_invocation(tmp_path: Path) -> None:
    receipt = tmp_path / "receipts.jsonl"
    lock_path = receipt.with_suffix(receipt.suffix + ".sweep.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a+", encoding="utf-8") as held:
        fcntl.flock(held.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RuntimeError, match="still active"):
            continuity_cli.run_observe_sweep(
                notify_minutes=15,
                receipt_path=receipt,
            )
