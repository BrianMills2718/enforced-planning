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
    CodexSuccessorLaunchReceiptV1,
    NativeCodexConsumptionReceiptV1,
    NativeCodexDeliveryJournalV1,
    SuccessorCustodyAcceptanceV1,
    SuccessorCustodyOfferV1,
    accept_successor_custody_offer,
    assess_continuity,
    assess_resume_offer,
    build_codex_successor_launch,
    build_native_codex_resume_offer,
    build_native_successor_custody_offer,
    build_resume_offer_request,
    build_successor_custody_offer,
    native_resume_progress_fingerprint,
    parse_native_codex_queue_receipt,
    read_codex_activity,
    read_native_codex_consumption,
    successor_custody_offer_sha256,
    validate_successor_custody_acceptance,
)
from enforced_planning.session_process_fencing import PredecessorProcessIdentityV1
from scripts import session_continuity as continuity_cli
from scripts import session_resume as resume_cli

NOW = datetime(2026, 9, 2, 4, 30, tzinfo=UTC)
PROGRESS_FINGERPRINT = "1" * 64


def predecessor_process(
    offer: SuccessorCustodyOfferV1,
) -> PredecessorProcessIdentityV1:
    return PredecessorProcessIdentityV1(
        predecessor_session_id=offer.predecessor_session_id,
        worktree_path=offer.worktree_path,
        pid=4242,
        process_start_ticks=123456,
        command_sha256="e" * 64,
    )


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
        progress_fingerprint=PROGRESS_FINGERPRINT,
    )
    second = build_native_codex_resume_offer(
        assessment=assessment,
        project="demo",
        scope="feature-lane",
        next_action="run the focused integration",
        progress_fingerprint=PROGRESS_FINGERPRINT,
    )

    assert first.thread_id == "01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    assert first.correlation_id == second.correlation_id
    assert f"continuity-resume:{first.correlation_id}" in first.prompt
    assert "Do not spawn or delegate to any new agents" in first.prompt
    assert "run the focused integration" in first.prompt


def test_native_resume_progress_fingerprint_changes_with_durable_evidence() -> None:
    baseline = native_resume_progress_fingerprint(
        progress_at="2026-09-02T04:00:00+00:00",
        head_revision="a" * 40,
        next_action="run the focused integration",
    )

    assert baseline != native_resume_progress_fingerprint(
        progress_at="2026-09-02T04:00:00+00:00",
        head_revision="b" * 40,
        next_action="run the focused integration",
    )
    assert baseline != native_resume_progress_fingerprint(
        progress_at="2026-09-02T04:01:00+00:00",
        head_revision="a" * 40,
        next_action="run the focused integration",
    )
    assert baseline != native_resume_progress_fingerprint(
        progress_at="2026-09-02T04:00:00+00:00",
        head_revision="a" * 40,
        next_action="inspect the new receipt",
    )


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
        progress_fingerprint=PROGRESS_FINGERPRINT,
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
        progress_fingerprint=PROGRESS_FINGERPRINT,
    )

    with pytest.raises(ValueError, match="different thread"):
        parse_native_codex_queue_receipt(
            offer=offer,
            stdout=(
                "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
                "00000000-0000-0000-0000-000000000001.\n"
            ),
        )


@pytest.mark.parametrize("record_shape", ["response_item", "completed_item"])
def test_native_consumption_requires_authentic_correlated_owner_user_turn(
    tmp_path: Path,
    record_shape: str,
) -> None:
    transcript = tmp_path / "session.jsonl"
    correlation_id = "a" * 24
    if record_shape == "response_item":
        consumed = {
            "timestamp": "2026-09-02T04:32:00Z",
            "type": "response_item",
            "payload": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": f"continuity-resume:{correlation_id}: continue",
                    }
                ],
            },
        }
    else:
        consumed = {
            "timestamp": "2026-09-02T04:32:00Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "thread_id": "01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
                "item": {
                    "type": "UserMessage",
                    "content": [
                        {
                            "type": "text",
                            "text": f"continuity-resume:{correlation_id}: continue",
                        }
                    ],
                },
            },
        }
    transcript.write_text(
        json.dumps(consumed) + "\n", encoding="utf-8"
    )

    receipt = read_native_codex_consumption(
        owner_session_id="codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
        correlation_id=correlation_id,
        queued_submission_id="01a0608f-1498-7413-b469-3e538a9bf171",
        transcript_path=transcript,
    )

    assert receipt is not None
    assert receipt.runtime_consumed is True
    assert receipt.consumed_at == datetime(2026, 9, 2, 4, 32, tzinfo=UTC)
    assert receipt.evidence_event == "correlated_user_message"


def test_native_consumption_does_not_accept_agent_echo(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    correlation_id = "a" * 24
    transcript.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-02T04:31:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "assistant",
                    "content": [
                        {
                            "type": "output_text",
                            "text": f"continuity-resume:{correlation_id}: echoed",
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert read_native_codex_consumption(
        owner_session_id="codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
        correlation_id=correlation_id,
        queued_submission_id="01a0608f-1498-7413-b469-3e538a9bf171",
        transcript_path=transcript,
    ) is None


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
    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        stdout = (
            "a" * 40 + "\n"
            if command[0] == "git"
            else (
                "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
                "01a05b94-d5d8-7d82-8a9a-6c64c6979e96.\n"
            )
        )
        return subprocess.CompletedProcess(command, 0, stdout, "")

    monkeypatch.setattr(continuity_cli.subprocess, "run", fake_run)

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


def successor_custody_offer() -> SuccessorCustodyOfferV1:
    assessment = assess_continuity(
        claim=Claim(), activity=activity("between_turns", 31), now=NOW
    )
    review = assess_resume_offer(
        assessment=assessment,
        status=offer_status(delivered=True),
        now=NOW,
    )
    return build_successor_custody_offer(
        review=review,
        project="demo",
        scope="feature-lane",
        branch="feat/example",
        worktree_path="/tmp/demo/worktrees/feat/example",
        claim_epoch_sha256="c" * 64,
        head_revision="d" * 40,
        next_action="run the focused integration",
        created_at=NOW,
    )


def test_successor_offer_freezes_exact_recoverable_custody() -> None:
    offer = successor_custody_offer()

    assert offer.offer_id == "875e78a8ddd0890b386bc038"
    assert offer.predecessor_session_id == "codex:owner"
    assert offer.owner_resume_message_id == "msg_" + "a" * 32
    assert offer.project == "demo"
    assert offer.scope == "feature-lane"
    assert offer.branch == "feat/example"
    assert offer.worktree_path == "/tmp/demo/worktrees/feat/example"
    assert offer.claim_epoch_sha256 == "c" * 64
    assert offer.head_revision == "d" * 40
    assert offer.next_action == "run the focused integration"


def test_native_consumed_retry_builds_offer_without_mailbox_or_launch() -> None:
    owner = "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    thread = owner.removeprefix("codex:")
    correlation = "a" * 24
    submission = "01a0608f-1498-7413-b469-3e538a9bf171"
    delivery = NativeCodexDeliveryJournalV1(
        owner_session_id=owner,
        thread_id=thread,
        correlation_id=correlation,
        progress_fingerprint=PROGRESS_FINGERPRINT,
        state="accepted",
        recorded_at=NOW,
        queued_submission_id=submission,
    )
    consumption = NativeCodexConsumptionReceiptV1(
        owner_session_id=owner,
        thread_id=thread,
        correlation_id=correlation,
        queued_submission_id=submission,
        transcript_path="/tmp/session.jsonl",
        consumed_at=NOW,
    )

    offer = build_native_successor_custody_offer(
        delivery=delivery,
        consumption=consumption,
        consumed_attempt_count=2,
        project="demo",
        scope="feature-lane",
        branch="feat/example",
        worktree_path="/tmp/demo/worktrees/feat/example",
        claim_epoch_sha256="c" * 64,
        head_revision="d" * 40,
        next_action="run the focused integration",
        created_at=NOW,
    )

    assert offer.owner_resume_message_id is None
    assert offer.owner_resume_correlation_id == correlation
    assert offer.predecessor_session_id == owner


def test_native_successor_offer_rejects_unconsumed_or_unbounded_attempt() -> None:
    owner = "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    thread = owner.removeprefix("codex:")
    delivery = NativeCodexDeliveryJournalV1(
        owner_session_id=owner,
        thread_id=thread,
        correlation_id="a" * 24,
        progress_fingerprint=PROGRESS_FINGERPRINT,
        state="accepted",
        recorded_at=NOW,
        queued_submission_id="01a0608f-1498-7413-b469-3e538a9bf171",
    )
    consumption = NativeCodexConsumptionReceiptV1(
        owner_session_id=owner,
        thread_id=thread,
        correlation_id="b" * 24,
        queued_submission_id="01a0608f-1498-7413-b469-3e538a9bf171",
        transcript_path="/tmp/session.jsonl",
        consumed_at=NOW,
    )
    kwargs = {
        "delivery": delivery,
        "consumption": consumption,
        "project": "demo",
        "scope": "feature-lane",
        "branch": "feat/example",
        "worktree_path": "/tmp/demo/worktrees/feat/example",
        "claim_epoch_sha256": "c" * 64,
        "head_revision": "d" * 40,
        "next_action": "run the focused integration",
        "created_at": NOW,
    }

    with pytest.raises(ValueError, match="bounded retry"):
        build_native_successor_custody_offer(consumed_attempt_count=1, **kwargs)
    with pytest.raises(ValueError, match="matching delivery"):
        build_native_successor_custody_offer(consumed_attempt_count=2, **kwargs)


def test_codex_successor_launch_requires_acceptance_before_work(tmp_path: Path) -> None:
    offer = successor_custody_offer()
    offer_path = tmp_path / "offer.json"
    resume_script = tmp_path / "session_resume.py"

    launch = build_codex_successor_launch(
        offer=offer,
        offer_path=str(offer_path),
        resume_script=str(resume_script),
        predecessor_process_pid=4242,
        predecessor_process_start_ticks=123456,
    )

    assert launch.predecessor_thread_id == "owner"
    assert launch.offer_sha256 == successor_custody_offer_sha256(offer)
    assert launch.argv[:8] == [
        "systemd-run",
        "--user",
        "--collect",
        "--unit",
        f"enforced-planning-successor-{offer.offer_id}",
        "--property",
        f"WorkingDirectory={offer.worktree_path}",
        "--",
    ]
    assert launch.argv[8:13] == ["codex", "exec", "fork", "--json", "owner"]
    assert "--accept-successor-custody-offer" in launch.prompt
    assert "--predecessor-process-pid 4242" in launch.prompt
    assert "--predecessor-process-start-ticks 123456" in launch.prompt
    assert launch.predecessor_process_pid == 4242
    assert launch.predecessor_process_start_ticks == 123456
    assert str(offer_path) in launch.prompt
    assert offer.next_action in launch.prompt
    assert launch.transfer_eligible is False


def test_codex_successor_launch_rejects_relative_control_paths() -> None:
    with pytest.raises(ValueError, match="paths must be absolute"):
        build_codex_successor_launch(
            offer=successor_custody_offer(),
            offer_path="offer.json",
            resume_script="scripts/session_resume.py",
            predecessor_process_pid=4242,
            predecessor_process_start_ticks=123456,
        )


def test_successor_offer_persistence_and_transient_launch_receipt(tmp_path: Path) -> None:
    offer = successor_custody_offer()
    offer_path = continuity_cli.persist_successor_offer(offer, offer_dir=tmp_path)
    assert continuity_cli.persist_successor_offer(offer, offer_dir=tmp_path) == offer_path
    assert SuccessorCustodyOfferV1.model_validate_json(offer_path.read_text()) == offer
    assert offer_path.stat().st_mode & 0o777 == 0o600
    launch = build_codex_successor_launch(
        offer=offer,
        offer_path=str(offer_path),
        resume_script=str(tmp_path / "session_resume.py"),
        predecessor_process_pid=4242,
        predecessor_process_start_ticks=123456,
    )
    observed: list[str] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.extend(command)
        return subprocess.CompletedProcess(
            command,
            0,
            f"Running as unit: {launch.systemd_unit}.service\n",
            "",
        )

    receipt = continuity_cli.launch_codex_successor(launch, run=fake_run)

    assert observed == launch.argv
    assert isinstance(receipt, CodexSuccessorLaunchReceiptV1)
    assert receipt.launch_started is True
    assert receipt.successor_session_id is None
    assert receipt.successor_accepted is False
    assert receipt.transfer_eligible is False


def test_successor_launch_fails_visible_without_exact_unit_ack(tmp_path: Path) -> None:
    offer = successor_custody_offer()
    launch = build_codex_successor_launch(
        offer=offer,
        offer_path=str(tmp_path / "offer.json"),
        resume_script=str(tmp_path / "session_resume.py"),
        predecessor_process_pid=4242,
        predecessor_process_start_ticks=123456,
    )

    with pytest.raises(RuntimeError, match="exact transient unit"):
        continuity_cli.launch_codex_successor(
            launch,
            run=lambda command, **_kwargs: subprocess.CompletedProcess(
                command, 0, "Running as unit: different.service\n", ""
            ),
        )


def test_verified_native_successor_launch_is_journaled_exactly_once(
    tmp_path: Path,
) -> None:
    offer = successor_custody_offer()
    offer_path = continuity_cli.persist_successor_offer(
        offer, offer_dir=tmp_path / "offers"
    )
    prepared = [
        {
            "project": offer.project,
            "scope": offer.scope,
            "session_id": offer.predecessor_session_id,
            "offer_id": offer.offer_id,
            "offer_sha256": successor_custody_offer_sha256(offer),
            "offer_path": str(offer_path),
            "action": "successor_offer_prepared",
            "successor_offer_verified": True,
        }
    ]
    calls: list[tuple[str, ...]] = []

    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            f"Running as unit: enforced-planning-successor-{offer.offer_id}.service\n",
            "",
        )

    receipt_path = tmp_path / "receipts.jsonl"
    first = continuity_cli.launch_verified_native_successors(
        successor_offers=prepared,
        receipt_path=receipt_path,
        resume_script=tmp_path / "session_resume.py",
        run=fake_run,
        process_resolver=predecessor_process,
    )
    second = continuity_cli.launch_verified_native_successors(
        successor_offers=prepared,
        receipt_path=receipt_path,
        resume_script=tmp_path / "session_resume.py",
        run=fake_run,
        process_resolver=predecessor_process,
    )

    assert first[0]["action"] == "successor_launch_started"
    assert first[0]["successor_session_id"] is None
    assert first[0]["successor_accepted"] is False
    assert first[0]["transfer_eligible"] is False
    assert second[0]["action"] == "successor_launch_already_started"
    assert len(calls) == 1
    records = [
        json.loads(line)
        for line in receipt_path.read_text(encoding="utf-8").splitlines()
    ]
    assert [record["state"] for record in records] == ["intent", "started"]
    assert records[-1]["launch_receipt"]["successor_accepted"] is False


def test_failed_verified_native_successor_launch_is_not_retried(
    tmp_path: Path,
) -> None:
    offer = successor_custody_offer()
    offer_path = continuity_cli.persist_successor_offer(
        offer, offer_dir=tmp_path / "offers"
    )
    prepared = [
        {
            "project": offer.project,
            "scope": offer.scope,
            "session_id": offer.predecessor_session_id,
            "offer_id": offer.offer_id,
            "offer_sha256": successor_custody_offer_sha256(offer),
            "offer_path": str(offer_path),
            "action": "successor_offer_prepared",
            "successor_offer_verified": True,
        }
    ]
    calls = 0

    def reject(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 1, "", "launcher unavailable")

    receipt_path = tmp_path / "receipts.jsonl"
    first = continuity_cli.launch_verified_native_successors(
        successor_offers=prepared,
        receipt_path=receipt_path,
        resume_script=tmp_path / "session_resume.py",
        run=reject,
        process_resolver=predecessor_process,
    )
    second = continuity_cli.launch_verified_native_successors(
        successor_offers=prepared,
        receipt_path=receipt_path,
        resume_script=tmp_path / "session_resume.py",
        run=reject,
        process_resolver=predecessor_process,
    )

    assert first[0]["reason_code"] == "native_successor_launch_invalid"
    assert second[0]["reason_code"] == "prior_successor_launch_failed"
    assert calls == 1


def test_verified_native_successor_launch_rejects_process_for_other_custody(
    tmp_path: Path,
) -> None:
    offer = successor_custody_offer()
    offer_path = continuity_cli.persist_successor_offer(
        offer, offer_dir=tmp_path / "offers"
    )
    prepared = [
        {
            "project": offer.project,
            "scope": offer.scope,
            "session_id": offer.predecessor_session_id,
            "offer_id": offer.offer_id,
            "offer_sha256": successor_custody_offer_sha256(offer),
            "offer_path": str(offer_path),
            "action": "successor_offer_prepared",
            "successor_offer_verified": True,
        }
    ]
    wrong_process = predecessor_process(offer).model_copy(
        update={"predecessor_session_id": "codex:different-owner"}
    )
    calls = 0

    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 0, "", "")

    result = continuity_cli.launch_verified_native_successors(
        successor_offers=prepared,
        receipt_path=tmp_path / "receipts.jsonl",
        resume_script=tmp_path / "session_resume.py",
        run=fake_run,
        process_resolver=lambda _offer: wrong_process,
    )

    assert result[0]["action"] == "fail_visible"
    assert "different offered custody" in result[0]["error"]
    assert calls == 0


def test_verified_native_successor_launch_rejects_changed_offer_bytes(
    tmp_path: Path,
) -> None:
    offer = successor_custody_offer()
    offer_path = continuity_cli.persist_successor_offer(
        offer, offer_dir=tmp_path / "offers"
    )
    prepared = [
        {
            "project": offer.project,
            "scope": offer.scope,
            "session_id": offer.predecessor_session_id,
            "offer_id": offer.offer_id,
            "offer_sha256": successor_custody_offer_sha256(offer),
            "offer_path": str(offer_path),
            "action": "successor_offer_prepared",
            "successor_offer_verified": True,
        }
    ]
    changed = offer.model_copy(update={"next_action": "different next action"})
    offer_path.write_text(changed.model_dump_json(indent=2) + "\n", encoding="utf-8")
    calls = 0

    def fake_run(
        command: tuple[str, ...], **_kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        nonlocal calls
        calls += 1
        return subprocess.CompletedProcess(command, 0, "", "")

    result = continuity_cli.launch_verified_native_successors(
        successor_offers=prepared,
        receipt_path=tmp_path / "receipts.jsonl",
        resume_script=tmp_path / "session_resume.py",
        run=fake_run,
    )

    assert result[0]["action"] == "fail_visible"
    assert "changed before launch" in result[0]["error"]
    assert calls == 0


def test_cli_successor_launch_requires_exact_offer_review() -> None:
    with pytest.raises(SystemExit):
        continuity_cli.parse_args(
            [
                "--project",
                "demo",
                "--scope",
                "feature-lane",
                "--launch-successor",
            ]
        )


def test_cli_native_successor_launch_requires_shared_delivery_mode() -> None:
    args = continuity_cli.parse_args(
        [
            "--scan-all-live-claims",
            "--deliver-native-resume-offers",
            "--launch-native-successors",
        ]
    )
    assert args.launch_native_successors is True

    with pytest.raises(SystemExit):
        continuity_cli.parse_args(
            [
                "--project",
                "demo",
                "--scope",
                "feature-lane",
                "--launch-native-successors",
            ]
        )


def test_different_successor_accepts_every_exact_offer_field() -> None:
    offer = successor_custody_offer()

    acceptance = accept_successor_custody_offer(
        offer=offer,
        successor_session_id="codex:successor",
        project=offer.project,
        scope=offer.scope,
        branch=offer.branch,
        worktree_path=offer.worktree_path,
        claim_epoch_sha256=offer.claim_epoch_sha256,
        head_revision=offer.head_revision,
        next_action=offer.next_action,
        accepted_at=NOW + timedelta(minutes=1),
    )

    assert acceptance.disposition == "successor_accepted"
    assert acceptance.offer_id == offer.offer_id
    assert acceptance.offer_sha256 == successor_custody_offer_sha256(offer)
    assert acceptance.successor_session_id == "codex:successor"


@pytest.mark.parametrize(
    ("field", "wrong"),
    [
        ("project", "other"),
        ("scope", "other"),
        ("branch", "other"),
        ("worktree_path", "/tmp/other"),
        ("claim_epoch_sha256", "e" * 64),
        ("head_revision", "e" * 40),
        ("next_action", "do something else"),
    ],
)
def test_successor_acceptance_rejects_any_changed_custody_field(
    field: str,
    wrong: str,
) -> None:
    offer = successor_custody_offer()
    observed = {
        "project": offer.project,
        "scope": offer.scope,
        "branch": offer.branch,
        "worktree_path": offer.worktree_path,
        "claim_epoch_sha256": offer.claim_epoch_sha256,
        "head_revision": offer.head_revision,
        "next_action": offer.next_action,
    }
    observed[field] = wrong

    with pytest.raises(ValueError, match=field):
        accept_successor_custody_offer(
            offer=offer,
            successor_session_id="codex:successor",
            **observed,
        )


def test_predecessor_cannot_self_accept_successor_offer() -> None:
    offer = successor_custody_offer()

    with pytest.raises(ValueError, match="different exact session"):
        accept_successor_custody_offer(
            offer=offer,
            successor_session_id=offer.predecessor_session_id,
            project=offer.project,
            scope=offer.scope,
            branch=offer.branch,
            worktree_path=offer.worktree_path,
            claim_epoch_sha256=offer.claim_epoch_sha256,
            head_revision=offer.head_revision,
            next_action=offer.next_action,
        )


def test_acceptance_digest_tampering_is_rejected() -> None:
    offer = successor_custody_offer()
    acceptance = accept_successor_custody_offer(
        offer=offer,
        successor_session_id="codex:successor",
        project=offer.project,
        scope=offer.scope,
        branch=offer.branch,
        worktree_path=offer.worktree_path,
        claim_epoch_sha256=offer.claim_epoch_sha256,
        head_revision=offer.head_revision,
        next_action=offer.next_action,
    ).model_copy(update={"offer_sha256": "f" * 64})

    with pytest.raises(ValueError, match="offer_sha256"):
        validate_successor_custody_acceptance(offer=offer, acceptance=acceptance)


def test_session_resume_cli_passes_strict_offer_and_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    offer = successor_custody_offer()
    acceptance = accept_successor_custody_offer(
        offer=offer,
        successor_session_id="codex:successor",
        project=offer.project,
        scope=offer.scope,
        branch=offer.branch,
        worktree_path=offer.worktree_path,
        claim_epoch_sha256=offer.claim_epoch_sha256,
        head_revision=offer.head_revision,
        next_action=offer.next_action,
    )
    offer_path = tmp_path / "offer.json"
    acceptance_path = tmp_path / "acceptance.json"
    offer_path.write_text(offer.model_dump_json(), encoding="utf-8")
    acceptance_path.write_text(acceptance.model_dump_json(), encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_resume(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "action": "resumed",
            "plan_ref": "UNPLANNED",
            "session_id": "codex:successor",
            "coordination_mailbox": {"summary": "no active messages"},
        }

    monkeypatch.setattr(resume_cli.session_lifecycle, "resume_session", fake_resume)

    result = resume_cli.main(
        [
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
            "accepted successor custody",
            "--session-id",
            acceptance.successor_session_id,
            "--successor-custody-offer",
            str(offer_path),
            "--successor-custody-acceptance",
            str(acceptance_path),
            "--json",
        ]
    )

    assert result == 0
    assert observed["successor_custody_offer"] == offer
    assert observed["successor_custody_acceptance"] == acceptance
    assert json.loads(capsys.readouterr().out)["action"] == "resumed"


def test_session_resume_cli_current_successor_explicitly_accepts_offer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    offer = successor_custody_offer()
    offer_path = tmp_path / "offer.json"
    offer_path.write_text(offer.model_dump_json(), encoding="utf-8")
    observed: dict[str, object] = {}

    def fake_resume(**kwargs: object) -> dict[str, object]:
        observed.update(kwargs)
        return {
            "action": "resumed",
            "plan_ref": "UNPLANNED",
            "session_id": "codex:successor",
            "coordination_mailbox": {"summary": "no active messages"},
        }

    monkeypatch.setenv("CODEX_THREAD_ID", "successor")
    monkeypatch.setattr(resume_cli.session_lifecycle, "resume_session", fake_resume)

    result = resume_cli.main(
        [
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
            str(offer_path),
            "--accept-successor-custody-offer",
            "--json",
        ]
    )

    acceptance = observed["successor_custody_acceptance"]
    assert result == 0
    assert observed["session_id"] == "codex:successor"
    assert observed["successor_custody_offer"] == offer
    assert isinstance(acceptance, SuccessorCustodyAcceptanceV1)
    assert acceptance.successor_session_id == "codex:successor"
    assert acceptance.offer_sha256 == successor_custody_offer_sha256(offer)


def test_session_resume_cli_refuses_explicit_acceptance_without_offer() -> None:
    with pytest.raises(ValueError, match="offer and exactly one acceptance mode"):
        resume_cli.main(
            [
                "--agent",
                "codex",
                "--project",
                "demo",
                "--scope",
                "feature-lane",
                "--worktree-path",
                "/tmp/demo/worktrees/feature-lane",
                "--branch",
                "feature-lane",
                "--current-phase",
                "accept exact successor custody",
                "--accept-successor-custody-offer",
            ]
        )


def test_cli_offer_resolves_claim_epoch_and_exact_git_revision(tmp_path: Path) -> None:
    claim_file = tmp_path / "claim.yaml"
    claim_file.write_text("status: handoff\n", encoding="utf-8")
    claim = SweepClaim(
        session_id="codex:owner",
        scope="feature-lane",
    )
    claim.source_file = str(claim_file)
    claim.worktree_path = str(tmp_path / "worktree")
    claim.branch = "feat/example"
    review = assess_resume_offer(
        assessment=assess_continuity(
            claim=Claim(), activity=activity("between_turns", 31), now=NOW
        ),
        status=offer_status(delivered=True),
        now=NOW,
    )

    offer = continuity_cli.build_successor_offer_for_claim(
        review=review,
        claim=claim,
        run=lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, "d" * 40 + "\n", ""
        ),
    )

    assert offer.claim_epoch_sha256 == __import__("hashlib").sha256(
        claim_file.read_bytes()
    ).hexdigest()
    assert offer.head_revision == "d" * 40
    assert offer.worktree_path == str((tmp_path / "worktree").resolve())


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


def test_codex_transcript_identifies_top_level_owner(tmp_path: Path) -> None:
    transcript = tmp_path / "session.jsonl"
    records = [
        {
            "timestamp": "2026-09-02T04:00:00Z",
            "type": "session_meta",
            "payload": {"id": "owner", "thread_source": "user"},
        },
        {
            "timestamp": "2026-09-02T04:21:00Z",
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "turn-1"},
        },
    ]
    transcript.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    result = read_codex_activity(session_id="codex:owner", transcript_path=transcript)

    assert result.thread_source == "user"
    assert result.parent_thread_id is None


def test_codex_transcript_identifies_spawned_owner_and_exact_parent(
    tmp_path: Path,
) -> None:
    transcript = tmp_path / "session.jsonl"
    records = [
        {
            "timestamp": "2026-09-02T04:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "child",
                "thread_source": "subagent",
                "parent_thread_id": "01a05b30-4bdb-7051-86d0-f20575c46fdf",
            },
        },
        {
            "timestamp": "2026-09-02T04:00:01Z",
            "type": "session_meta",
            "payload": {
                "id": "01a05b30-4bdb-7051-86d0-f20575c46fdf",
                "thread_source": "user",
            },
        },
        {
            "timestamp": "2026-09-02T04:21:00Z",
            "type": "event_msg",
            "payload": {"type": "task_complete", "turn_id": "turn-1"},
        },
    ]
    transcript.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    result = read_codex_activity(session_id="codex:child", transcript_path=transcript)

    assert result.thread_source == "subagent"
    assert result.parent_thread_id == "01a05b30-4bdb-7051-86d0-f20575c46fdf"


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
    worktree_path: str = "/tmp"

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
                "agent": "codex",
                "scope": "feature-lane",
                "session_id": session_id,
                "next_action": "run the focused integration",
                "progress_fingerprint": PROGRESS_FINGERPRINT,
                "thread_source": "user",
                "parent_thread_id": None,
                "assessment": assessment.model_dump(mode="json"),
            }
        ]
    }


def test_spawned_owner_reaches_typed_circuit_breaker_without_queue(
    tmp_path: Path,
) -> None:
    sweep = native_delivery_sweep_fixture()
    item = sweep["items"][0]  # type: ignore[index]
    item["thread_source"] = "subagent"
    item["parent_thread_id"] = "01a05b30-4bdb-7051-86d0-f20575c46fdf"

    result = continuity_cli.deliver_native_resume_offers(
        sweep=sweep,
        receipt_path=tmp_path / "receipts.jsonl",
        run=lambda *_args, **_kwargs: pytest.fail("spawned owner must not be queued"),
    )

    assert result == [
        {
            "project": "demo",
            "scope": "feature-lane",
            "session_id": "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
            "action": "circuit_breaker",
            "reason_code": "spawned_agent_native_queue_unsupported",
            "parent_thread_id": "01a05b30-4bdb-7051-86d0-f20575c46fdf",
            "resume_condition": (
                "resume from the exact parent when the active resource boundary "
                "permits sub-agent execution"
            ),
        }
    ]
    assert not (tmp_path / "receipts.jsonl").exists()


def test_unknown_thread_origin_reaches_circuit_breaker_without_queue(
    tmp_path: Path,
) -> None:
    sweep = native_delivery_sweep_fixture()
    item = sweep["items"][0]  # type: ignore[index]
    item["thread_source"] = "unknown"

    result = continuity_cli.deliver_native_resume_offers(
        sweep=sweep,
        receipt_path=tmp_path / "receipts.jsonl",
        run=lambda *_args, **_kwargs: pytest.fail("unknown owner must not be queued"),
    )

    assert result[0]["action"] == "circuit_breaker"
    assert result[0]["reason_code"] == "thread_origin_not_verified_top_level"
    assert result[0]["resume_condition"] == (
        "record valid top-level Codex session metadata before delivery"
    )
    assert not (tmp_path / "receipts.jsonl").exists()


def test_delivery_sweep_counts_spawned_circuit_breaker_as_expected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sweep = native_delivery_sweep_fixture()
    item = sweep["items"][0]  # type: ignore[index]
    item["thread_source"] = "subagent"
    item["parent_thread_id"] = "01a05b30-4bdb-7051-86d0-f20575c46fdf"
    monkeypatch.setattr(continuity_cli, "build_observe_sweep", lambda **_kwargs: sweep)

    result = continuity_cli.run_native_delivery_sweep(
        notify_minutes=15,
        receipt_path=tmp_path / "receipts.jsonl",
    )

    assert result["native_resume_circuit_breaker_count"] == 1
    assert result["native_resume_fail_visible_count"] == 0
    assert result["native_resume_queued_count"] == 0


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


def test_accepted_native_delivery_promotes_once_after_transcript_consumption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = tmp_path / "receipts.jsonl"
    queued = continuity_cli.deliver_native_resume_offers(
        sweep=native_delivery_sweep_fixture(),
        receipt_path=receipt_path,
        run=lambda command, **_kwargs: subprocess.CompletedProcess(
            command,
            0,
            (
                "Queued message 01a0608f-1498-7413-b469-3e538a9bf171 for thread "
                "01a05b94-d5d8-7d82-8a9a-6c64c6979e96.\n"
            ),
            "",
        ),
    )
    correlation_id = queued[0]["correlation_id"]
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "timestamp": "2026-09-02T04:32:00Z",
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"continuity-resume:{correlation_id}: continue",
                        }
                    ],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        continuity_cli.coordination_claims,
        "session_transcript_path",
        lambda _session_id: transcript,
    )

    first = continuity_cli.reconcile_native_resume_consumption(
        receipt_path=receipt_path
    )
    second = continuity_cli.reconcile_native_resume_consumption(
        receipt_path=receipt_path
    )

    assert first[0]["action"] == "owner_resume_consumed"
    assert first[0]["queued_submission_id"] == (
        "01a0608f-1498-7413-b469-3e538a9bf171"
    )
    assert second == []
    records = [json.loads(line) for line in receipt_path.read_text().splitlines()]
    assert records[-1]["record_type"] == "native_codex_resume_consumption"
    assert records[-1]["runtime_consumed"] is True


def test_reconciliation_only_cli_reports_receipts_without_delivery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    receipt_path = tmp_path / "receipts.jsonl"
    correlation = "a" * 24
    receipt_path.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "record_type": "native_codex_resume_consumption",
                "owner_session_id": "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
                "thread_id": "01a05b94-d5d8-7d82-8a9a-6c64c6979e96",
                "correlation_id": correlation,
                "queued_submission_id": "01a0608f-1498-7413-b469-3e538a9bf171",
                "transcript_path": "/tmp/session.jsonl",
                "consumed_at": NOW.isoformat(),
                "evidence_event": "correlated_user_message",
                "runtime_consumed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        continuity_cli,
        "deliver_native_resume_offers",
        lambda **_kwargs: pytest.fail("reconciliation-only mode must not deliver"),
    )

    assert continuity_cli.main(
        [
            "--reconcile-native-resume-consumption",
            "--receipt-jsonl",
            str(receipt_path),
            "--json",
        ]
    ) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["record_type"] == "native_resume_consumption_reconciliation"
    assert payload["consumed_count"] == 1
    assert payload["consumed_correlations"] == [correlation]
    assert payload["native_queue_invoked"] is False
    assert payload["successor_launch_allowed"] is False


def test_two_consumed_attempts_without_progress_reach_typed_circuit_breaker(
    tmp_path: Path,
) -> None:
    receipt_path = tmp_path / "receipts.jsonl"
    owner = "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    thread = owner.removeprefix("codex:")
    records: list[dict[str, object]] = []
    for correlation, submission in (
        ("a" * 24, "01a0608f-1498-7413-b469-3e538a9bf171"),
        ("b" * 24, "01a0615e-330c-7680-8547-ef1850675131"),
    ):
        records.extend(
            [
                {
                    "schema_version": "1.0",
                    "record_type": "native_codex_resume_delivery",
                    "owner_session_id": owner,
                    "thread_id": thread,
                    "correlation_id": correlation,
                    "progress_fingerprint": PROGRESS_FINGERPRINT,
                    "state": "accepted",
                    "recorded_at": NOW.isoformat(),
                    "queued_submission_id": submission,
                    "error": None,
                },
                {
                    "schema_version": "1.0",
                    "record_type": "native_codex_resume_consumption",
                    "owner_session_id": owner,
                    "thread_id": thread,
                    "correlation_id": correlation,
                    "queued_submission_id": submission,
                    "transcript_path": "/tmp/session.jsonl",
                    "consumed_at": NOW.isoformat(),
                    "evidence_event": "correlated_user_message",
                    "runtime_consumed": True,
                },
            ]
        )
    receipt_path.write_text(
        "".join(json.dumps(record) + "\n" for record in records), encoding="utf-8"
    )

    result = continuity_cli.deliver_native_resume_offers(
        sweep=native_delivery_sweep_fixture(),
        receipt_path=receipt_path,
        run=lambda *_args, **_kwargs: pytest.fail("circuit breaker must not queue"),
    )

    assert result == [
        {
            "project": "demo",
            "scope": "feature-lane",
            "session_id": owner,
            "progress_fingerprint": PROGRESS_FINGERPRINT,
            "consumed_attempt_count": 2,
            "consumed_correlation_ids": ["a" * 24, "b" * 24],
            "latest_consumed_correlation_id": "b" * 24,
            "action": "circuit_breaker",
            "reason_code": "native_resume_progress_not_observed",
            "resume_condition": (
                "record a changed Git revision, claim progress timestamp, or exact "
                "next action before another automatic owner resume"
            ),
        }
    ]


def test_bounded_native_retry_persists_offer_without_launch_or_transfer(
    tmp_path: Path,
) -> None:
    owner = "codex:01a05b94-d5d8-7d82-8a9a-6c64c6979e96"
    thread = owner.removeprefix("codex:")
    correlation = "b" * 24
    submission = "01a0615e-330c-7680-8547-ef1850675131"
    head_revision = "d" * 40
    next_action = "run the focused integration"
    progress_at = "2026-09-02T04:00:00+00:00"
    progress_fingerprint = native_resume_progress_fingerprint(
        progress_at=progress_at,
        head_revision=head_revision,
        next_action=next_action,
    )
    receipt_path = tmp_path / "receipts.jsonl"
    receipt_path.write_text(
        "".join(
            json.dumps(record) + "\n"
            for record in (
                {
                    "schema_version": "1.0",
                    "record_type": "native_codex_resume_delivery",
                    "owner_session_id": owner,
                    "thread_id": thread,
                    "correlation_id": correlation,
                    "progress_fingerprint": progress_fingerprint,
                    "state": "accepted",
                    "recorded_at": NOW.isoformat(),
                    "queued_submission_id": submission,
                    "error": None,
                },
                {
                    "schema_version": "1.0",
                    "record_type": "native_codex_resume_consumption",
                    "owner_session_id": owner,
                    "thread_id": thread,
                    "correlation_id": correlation,
                    "queued_submission_id": submission,
                    "transcript_path": "/tmp/session.jsonl",
                    "consumed_at": NOW.isoformat(),
                    "evidence_event": "correlated_user_message",
                    "runtime_consumed": True,
                },
            )
        ),
        encoding="utf-8",
    )
    claim_source = tmp_path / "claim.yaml"
    claim_source.write_text("scope: feature-lane\n", encoding="utf-8")
    sweep = {
        "items": [
            {
                "agent": "codex",
                "project": "demo",
                "scope": "feature-lane",
                "session_id": owner,
                "next_action": next_action,
                "progress_at": progress_at,
                "worktree_path": str(tmp_path),
                "branch": "feat/example",
                "claim_source_file": str(claim_source),
            }
        ]
    }
    deliveries = [
        {
            "project": "demo",
            "scope": "feature-lane",
            "session_id": owner,
            "progress_fingerprint": progress_fingerprint,
            "consumed_attempt_count": 2,
            "latest_consumed_correlation_id": correlation,
            "action": "circuit_breaker",
            "reason_code": "native_resume_progress_not_observed",
        }
    ]

    verified: list[dict[str, object]] = []

    def verify_offer(**kwargs: object) -> dict[str, object]:
        verified.append(kwargs)
        return {
            "record_type": "successor_custody_offer_verification",
            "action": "successor_custody_offer_verified",
            "head_revision": head_revision,
            "successor_acceptance_required": True,
            "successor_launch_allowed": False,
            "custody_mutation_performed": False,
            "transfer_eligible": False,
        }

    result = continuity_cli.prepare_native_successor_offers(
        sweep=sweep,
        deliveries=deliveries,
        receipt_path=receipt_path,
        offer_dir=tmp_path / "offers",
        git_run=lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, head_revision + "\n", ""
        ),
        offer_verifier=verify_offer,
    )

    assert result[0]["action"] == "successor_offer_prepared"
    assert result[0]["owner_resume_correlation_id"] == correlation
    assert result[0]["successor_offer_verified"] is True
    assert result[0]["successor_acceptance_required"] is True
    assert result[0]["successor_launch_allowed"] is False
    assert result[0]["custody_mutation_performed"] is False
    assert result[0]["transfer_eligible"] is False
    assert verified[0]["agent"] == "codex"
    assert verified[0]["successor_custody_offer"] == SuccessorCustodyOfferV1.model_validate_json(
        Path(result[0]["offer_path"]).read_text()
    )
    offer_path = Path(result[0]["offer_path"])
    offer = SuccessorCustodyOfferV1.model_validate_json(offer_path.read_text())
    assert offer.owner_resume_correlation_id == correlation
    assert offer_path.stat().st_mode & 0o777 == 0o600

    unsafe = continuity_cli.prepare_native_successor_offers(
        sweep=sweep,
        deliveries=deliveries,
        receipt_path=receipt_path,
        offer_dir=tmp_path / "unsafe-offers",
        git_run=lambda command, **_kwargs: subprocess.CompletedProcess(
            command, 0, head_revision + "\n", ""
        ),
        offer_verifier=lambda **_kwargs: {
            "record_type": "successor_custody_offer_verification",
            "action": "successor_custody_offer_verified",
            "successor_acceptance_required": True,
            "successor_launch_allowed": False,
            "custody_mutation_performed": True,
            "transfer_eligible": False,
        },
    )
    assert unsafe[0]["action"] == "fail_visible"
    assert unsafe[0]["reason_code"] == "native_successor_offer_invalid"
    assert "unsafe or invalid" in unsafe[0]["error"]
    assert len(list((tmp_path / "unsafe-offers").glob("*.json"))) == 1


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
        progress_fingerprint=PROGRESS_FINGERPRINT,
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
    assert "--launch-native-successors" not in service

    launch_service, _timer = continuity_cli.render_observe_timer(
        script_path=tmp_path / "session_continuity.py",
        python_path=Path("/usr/bin/python3"),
        receipt_path=tmp_path / "receipts.jsonl",
        timer_minutes=10,
        notify_minutes=15,
        delivery_enabled=True,
        successor_launch_enabled=True,
        codex_path=Path("/opt/codex/bin/codex"),
    )
    assert launch_service.count("--launch-native-successors") == 1


def test_delivery_sweep_cli_exits_nonzero_for_fail_visible_delivery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "schema_version": "1.0",
        "record_type": "session_continuity_sweep",
        "mode": "native_resume_delivery",
        "native_resume_fail_visible_count": 1,
    }
    monkeypatch.setattr(
        continuity_cli,
        "run_native_delivery_sweep",
        lambda **_kwargs: payload,
    )

    result = continuity_cli.main(
        ["--scan-all-live-claims", "--deliver-native-resume-offers", "--json"]
    )

    assert result == 1
    assert json.loads(capsys.readouterr().out) == payload


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
