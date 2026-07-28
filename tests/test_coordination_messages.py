"""End-to-end and both-sign tests for Plan 67's durable mailbox skeleton."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from enforced_planning import coordination_claims
from enforced_planning.coordination_messages import (
    AcknowledgeMessageRequest,
    AcknowledgementResult,
    AmbiguousRecipientError,
    ClaimRecipientSelector,
    CoordinationMessage,
    CoordinationMessageStore,
    CorruptRecordError,
    ExactSessionSelector,
    IdentityMismatchError,
    MessagePollResult,
    MessageReceipt,
    MessageStatusRequest,
    MessageStatusView,
    PollMessagesRequest,
    PersistedMessageResult,
    RecordCollisionError,
    SendMessageRequest,
    SessionInboxNotice,
    UnknownSessionError,
    WrongRecipientError,
)


NOW = datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
CODEX_SESSION = "codex:thread-123"
CLAUDE_SESSION = "claude-code:session-456"


def _write_claim(claims_dir: Path, *, agent: str, project: str, scope: str, session_id: str) -> None:
    """Persist one real v2 claim fixture consumed by the production resolver."""

    claims_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "agent": agent,
        "projects": [project],
        "scope": scope,
        "intent": f"Own {scope}",
        "claim_type": "program",
        "write_paths": [],
        "read_paths": [],
        "session_id": session_id,
        "heartbeat_at": NOW.isoformat(),
        "status": "active",
        "claimed_at": NOW.isoformat(),
        "expires_at": datetime(2099, 1, 1, tzinfo=UTC).isoformat(),
    }
    path = claims_dir / f"{agent}_{project}_{scope}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


@pytest.fixture
def mailbox(tmp_path: Path) -> tuple[CoordinationMessageStore, Path, Path]:
    """Create a real filesystem mailbox backed by two canonical session claims."""

    claims_dir = tmp_path / "coordination" / "claims"
    root = tmp_path / "coordination" / "messages-v1"
    _write_claim(
        claims_dir,
        agent="codex",
        project="enforced-planning",
        scope="sender-lane",
        session_id=CODEX_SESSION,
    )
    _write_claim(
        claims_dir,
        agent="claude-code",
        project="enforced-planning",
        scope="recipient-lane",
        session_id=CLAUDE_SESSION,
    )
    return CoordinationMessageStore(root=root, claims_dir=claims_dir), claims_dir, root


def _send_request(
    *,
    sender: str = CODEX_SESSION,
    recipient: str = CLAUDE_SESSION,
    idempotency_key: str | None = "request-1",
    subject: str = "Narrow the docs claim",
    ttl_seconds: int = 3600,
) -> SendMessageRequest:
    """Build one strict request while keeping system IDs outside caller input."""

    return SendMessageRequest(
        caller_session_id=sender,
        sender_session_id=sender,
        recipient=ExactSessionSelector(kind="session", session_id=recipient),
        project="enforced-planning",
        kind="coordination_request",
        subject=subject,
        body="Please narrow the broad docs claim before implementation.",
        ttl_seconds=ttl_seconds,
        idempotency_key=idempotency_key,
        plan_ref="Plan #67",
    )


def test_mailbox_supports_canonical_legacy_claim_registry_signature(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vendored repos may use the older canonical-dir-only claim reader."""

    store, claims_dir, _root = mailbox
    current_check_claims = coordination_claims.check_claims

    def legacy_check_claims(project: str | None = None) -> list[coordination_claims.ClaimRecord]:
        """Emulate the older claim reader while retaining production parsing."""

        return current_check_claims(project, claims_dir=claims_dir)

    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(coordination_claims, "check_claims", legacy_check_claims)

    assert {claim.session_id for claim in store._live_claims()} == {CODEX_SESSION, CLAUDE_SESSION}


def test_codex_to_claude_persist_observe_acknowledge_round_trip(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """The same core path must preserve all evidence classes without status mutation."""

    store, _claims_dir, _root = mailbox
    persisted = store.send(_send_request(), now=NOW)
    before = store.status(MessageStatusRequest(message_id=persisted.message.message_id, as_of=NOW))
    assert before.state == "persisted"
    assert before.receipts == ()

    polled = store.poll(
        PollMessagesRequest(current_session_id=CLAUDE_SESSION, as_of=NOW, observe=True),
        now=NOW,
    )
    assert [view.state for view in polled.messages] == ["observed"]
    assert [receipt.event for receipt in polled.observation_receipts] == ["observed"]
    assert len(polled.observation_receipt_paths) == 1
    assert Path(polled.observation_receipt_paths[0]).is_file()

    acknowledged = store.acknowledge(
        AcknowledgeMessageRequest(
            current_session_id=CLAUDE_SESSION,
            message_id=persisted.message.message_id,
            disposition="accepted",
            note="Claim will be narrowed.",
        ),
        now=NOW + timedelta(seconds=1),
    )
    assert acknowledged.status.state == "acknowledged"
    assert acknowledged.status.observed is True
    assert acknowledged.status.acknowledged is True
    assert len(acknowledged.status.receipt_set_sha256) == 64
    assert Path(acknowledged.receipt_path).is_file()
    assert all(Path(path).is_file() for path in acknowledged.status.receipt_paths)


def test_claude_to_codex_uses_identical_core_operations(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Client identity changes must not select a second storage or lifecycle implementation."""

    store, _claims_dir, _root = mailbox
    message = store.send(
        _send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="reverse"),
        now=NOW,
    ).message
    result = store.poll(PollMessagesRequest(current_session_id=CODEX_SESSION, as_of=NOW, observe=True))
    assert [view.message.message_id for view in result.messages] == [message.message_id]
    assert result.messages[0].state == "observed"


@pytest.mark.parametrize("agent,recipient", [("codex", CODEX_SESSION), ("claude-code", CLAUDE_SESSION)])
def test_duplicate_adapters_show_one_notice_per_event_then_repeat_for_later_event(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
    agent: str,
    recipient: str,
) -> None:
    """Host and repository adapters share one display marker but never infer acknowledgement."""

    store, _claims_dir, _root = mailbox
    message = store.send(
        _send_request(sender=CLAUDE_SESSION if recipient == CODEX_SESSION else CODEX_SESSION, recipient=recipient)
    ).message
    event_one = f"event-{agent}-one"
    host = store.poll(
        PollMessagesRequest(
            current_session_id=recipient,
            observe=True,
            delivery_event_id=event_one,
        ),
        now=NOW,
        require_live_claim=False,
    )
    repository = store.poll(
        PollMessagesRequest(
            current_session_id=recipient,
            observe=True,
            delivery_event_id=event_one,
        ),
        now=NOW + timedelta(milliseconds=1),
        require_live_claim=False,
    )
    later = store.poll(
        PollMessagesRequest(
            current_session_id=recipient,
            observe=True,
            delivery_event_id=f"event-{agent}-two",
        ),
        now=NOW + timedelta(seconds=1),
        require_live_claim=False,
    )

    assert [view.message.message_id for view in host.messages] == [message.message_id]
    assert repository.messages == ()
    assert repository.suppressed_message_ids == (message.message_id,)
    assert len(host.observation_receipts) == 1
    assert repository.observation_receipts == ()
    assert [view.message.message_id for view in later.messages] == [message.message_id]
    assert later.observation_receipts == ()
    status = store.status(MessageStatusRequest(message_id=message.message_id))
    assert status.state == "observed"
    assert [receipt.event for receipt in status.receipts] == ["observed"]


def test_claim_selector_resolves_unique_session_and_rejects_ambiguity(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Claim routing must resolve one existing identity rather than invent an inbox name."""

    store, claims_dir, _root = mailbox
    selector = ClaimRecipientSelector(kind="claim", project="enforced-planning", scope="recipient-lane")
    assert store.resolve_recipient(selector) == CLAUDE_SESSION

    _write_claim(
        claims_dir,
        agent="openclaw",
        project="enforced-planning",
        scope="other-lane",
        session_id="openclaw:run-789",
    )
    with pytest.raises(AmbiguousRecipientError, match="matched 3 sessions"):
        store.resolve_recipient(ClaimRecipientSelector(kind="claim", project="enforced-planning"))
    with pytest.raises(UnknownSessionError):
        store.resolve_recipient(ExactSessionSelector(kind="session", session_id="codex:missing"))


def test_idempotency_reuses_identical_message_and_rejects_changed_content(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """One retry key may recover the original record but never overwrite its intent."""

    store, _claims_dir, _root = mailbox
    first = store.send(_send_request(), now=NOW)
    second = store.send(_send_request(), now=NOW + timedelta(minutes=5))
    assert second.idempotent_replay is True
    assert second.message == first.message
    with pytest.raises(RecordCollisionError, match="different content"):
        store.send(_send_request(subject="Changed request"), now=NOW + timedelta(minutes=6))


def test_idempotent_retry_recovers_original_resolution_after_recipient_claim_changes(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A lost send response must remain recoverable after the original recipient goes offline."""

    store, claims_dir, _root = mailbox
    first = store.send(_send_request(), now=NOW)
    for path in claims_dir.glob("claude-code_*.yaml"):
        path.unlink()
    recovered = store.send(_send_request(), now=NOW + timedelta(minutes=5))
    assert recovered.idempotent_replay is True
    assert recovered.message == first.message


def test_identity_and_wrong_recipient_fail_loud(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Caller assertions and acknowledgement ownership are checked before evidence is written."""

    store, _claims_dir, _root = mailbox
    invalid_sender = _send_request().model_copy(update={"caller_session_id": CLAUDE_SESSION})
    with pytest.raises(IdentityMismatchError):
        store.send(invalid_sender, now=NOW)

    message = store.send(_send_request(), now=NOW).message
    with pytest.raises(WrongRecipientError):
        store.acknowledge(
            AcknowledgeMessageRequest(
                current_session_id=CODEX_SESSION,
                message_id=message.message_id,
                disposition="declined",
            ),
            now=NOW,
        )


def test_acknowledgement_retry_is_idempotent_and_changed_disposition_conflicts(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A recipient may retry the same acknowledgement but cannot rewrite its decision."""

    store, _claims_dir, _root = mailbox
    message = store.send(_send_request(), now=NOW).message
    request = AcknowledgeMessageRequest(
        current_session_id=CLAUDE_SESSION,
        message_id=message.message_id,
        disposition="accepted",
    )
    first = store.acknowledge(request, now=NOW)
    second = store.acknowledge(request, now=NOW + timedelta(seconds=1))
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert second.receipt == first.receipt

    with pytest.raises(RecordCollisionError, match="different content"):
        store.acknowledge(
            request.model_copy(update={"disposition": "declined"}),
            now=NOW + timedelta(seconds=2),
        )

    after_ack_poll = store.poll(
        PollMessagesRequest(current_session_id=CLAUDE_SESSION, as_of=NOW + timedelta(seconds=3), observe=True)
    )
    assert after_ack_poll.observation_receipts == ()
    assert [receipt.event for receipt in after_ack_poll.messages[0].receipts] == ["acknowledged"]


def test_expired_message_remains_auditable_and_late_ack_does_not_reactivate(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Expiry hides inactive work by default while preserving late historical evidence."""

    store, _claims_dir, _root = mailbox
    message = store.send(_send_request(ttl_seconds=1), now=NOW).message
    later = NOW + timedelta(seconds=2)
    assert store.poll(PollMessagesRequest(current_session_id=CLAUDE_SESSION, as_of=later)).messages == ()
    included = store.poll(
        PollMessagesRequest(current_session_id=CLAUDE_SESSION, as_of=later, include_expired=True)
    )
    assert included.messages[0].state == "expired"

    late_ack = store.acknowledge(
        AcknowledgeMessageRequest(
            current_session_id=CLAUDE_SESSION,
            message_id=message.message_id,
            disposition="information_only",
        ),
        now=later,
    )
    assert late_ack.status.state == "expired"
    assert late_ack.status.acknowledged is True


def test_corrupt_message_is_quarantined_and_never_silently_skipped(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A digest mismatch must leave evidence and stop projection rather than disappear."""

    store, _claims_dir, _root = mailbox
    persisted = store.send(_send_request(), now=NOW)
    path = Path(persisted.message_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["payload"]["subject"] = "tampered"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(CorruptRecordError, match="Quarantined corrupt record"):
        store.status(MessageStatusRequest(message_id=persisted.message.message_id, as_of=NOW))
    assert not path.exists()
    assert len(list(store.quarantine_dir.glob("*.corrupt"))) == 1


def test_contract_rejects_unknown_fields_and_ambiguous_content() -> None:
    """Portable input contracts fail closed before any storage effect."""

    with pytest.raises(ValidationError, match="extra_forbidden"):
        SendMessageRequest.model_validate({**_send_request().model_dump(), "surprise": True})
    with pytest.raises(ValidationError, match="exactly one"):
        SendMessageRequest.model_validate({**_send_request().model_dump(), "content_ref": "artifact:123"})


def test_public_contract_fields_have_decode_time_descriptions() -> None:
    """Every public schema field must explain its semantic constraint to callers."""

    models = (
        ExactSessionSelector,
        ClaimRecipientSelector,
        SendMessageRequest,
        PollMessagesRequest,
        AcknowledgeMessageRequest,
        MessageStatusRequest,
        CoordinationMessage,
        MessageReceipt,
        MessageStatusView,
        PersistedMessageResult,
        MessagePollResult,
        AcknowledgementResult,
        SessionInboxNotice,
    )
    missing = [
        f"{model.__name__}.{name}"
        for model in models
        for name, field in model.model_fields.items()
        if not field.description
    ]
    assert missing == []


def test_legacy_markdown_inbox_is_not_consulted(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
    tmp_path: Path,
) -> None:
    """Legacy files cannot masquerade as canonical persisted or observed messages."""

    store, _claims_dir, _root = mailbox
    legacy = tmp_path / ".claude" / "messages" / "inbox" / "recipient-lane"
    legacy.mkdir(parents=True)
    (legacy / "fake.md").write_text("status: acknowledged\n", encoding="utf-8")
    result = store.poll(PollMessagesRequest(current_session_id=CLAUDE_SESSION, as_of=NOW))
    assert result.messages == ()


@pytest.mark.parametrize(
    "script_path",
    [
        "scripts/worktree-coordination/send_message.py",
        "scripts/worktree-coordination/check_messages.py",
    ],
)
def test_legacy_markdown_commands_are_fail_loud_tombstones(script_path: str) -> None:
    """No supported command may continue writing or mutating the retired authority."""

    result = subprocess.run(
        ["python", script_path],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert "Legacy Markdown" in result.stderr


def test_claude_hook_paths_never_scan_the_legacy_markdown_inbox() -> None:
    """Current and compatibility hooks must share the JSON mailbox authority."""

    repo_root = Path(__file__).resolve().parents[1]
    hook_paths = (
        repo_root / "hooks/claude/notify-coordination-messages.sh",
        repo_root / "hooks/claude/worktree-coordination/check-inbox.sh",
        repo_root / "hooks/claude/worktree-coordination/notify-inbox-startup.sh",
    )
    for path in hook_paths:
        content = path.read_text(encoding="utf-8")
        assert ".claude/messages" not in content
        assert "git worktree list --porcelain" in content
    assert "coordination_hook.py" in hook_paths[0].read_text(encoding="utf-8")
    for path in hook_paths[1:]:
        assert "coordination_inbox.py" in path.read_text(encoding="utf-8")


@pytest.mark.parametrize("script_path", ["scripts/coordination_messages.py", "scripts/meta/coordination_messages.py"])
def test_json_cli_runs_the_same_package_send_path(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
    script_path: str,
) -> None:
    """Source and installed wrappers must remain thin agent-drivable JSON boundaries."""

    _store, claims_dir, root = mailbox
    request_json = _send_request(idempotency_key="cli").model_dump_json()
    result = subprocess.run(
        [
            "python",
            script_path,
            "--root",
            str(root),
            "--claims-dir",
            str(claims_dir),
            "send",
            "--request-json",
            request_json,
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["message"]["recipient_session_id"] == CLAUDE_SESSION
    assert Path(payload["message_path"]).is_file()


def test_native_cli_message_lifecycle_survives_write_claim_completion(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Exact native identity should support message-only work after claims end."""

    store, claims_dir, root = mailbox
    for path in claims_dir.glob("codex_*.yaml"):
        path.unlink()
    send_request = _send_request(
        sender=CODEX_SESSION,
        recipient=CLAUDE_SESSION,
        idempotency_key="native-unclaimed-send",
    )
    codex_env = {**os.environ, "CODEX_THREAD_ID": "thread-123"}
    sent = subprocess.run(
        [
            "python",
            "scripts/coordination_messages.py",
            "--root",
            str(root),
            "--claims-dir",
            str(claims_dir),
            "send",
            "--request-json",
            send_request.model_dump_json(),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=codex_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert sent.returncode == 0, sent.stderr or sent.stdout
    message_id = json.loads(sent.stdout)["message"]["message_id"]

    for path in claims_dir.glob("claude-code_*.yaml"):
        path.unlink()
    claude_env = {**os.environ, "CLAUDE_SESSION_ID": "session-456"}
    polled = subprocess.run(
        [
            "python",
            "scripts/coordination_messages.py",
            "--root",
            str(root),
            "--claims-dir",
            str(claims_dir),
            "poll",
            "--request-json",
            PollMessagesRequest(
                current_session_id=CLAUDE_SESSION,
                observe=True,
            ).model_dump_json(),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=claude_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert polled.returncode == 0, polled.stderr or polled.stdout
    assert json.loads(polled.stdout)["messages"][0]["message"]["message_id"] == message_id

    acknowledged = subprocess.run(
        [
            "python",
            "scripts/coordination_messages.py",
            "--root",
            str(root),
            "--claims-dir",
            str(claims_dir),
            "acknowledge",
            "--request-json",
            AcknowledgeMessageRequest(
                current_session_id=CLAUDE_SESSION,
                message_id=message_id,
                disposition="information_only",
            ).model_dump_json(),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env=claude_env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert acknowledged.returncode == 0, acknowledged.stderr or acknowledged.stdout
    assert json.loads(acknowledged.stdout)["status"]["state"] == "acknowledged"
    assert store.status(MessageStatusRequest(message_id=message_id)).acknowledged is True


def test_native_cli_rejects_unclaimed_sender_when_ambient_session_differs(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Knowing a session ID must not let a different native session assert it."""

    _store, claims_dir, root = mailbox
    for path in claims_dir.glob("codex_*.yaml"):
        path.unlink()
    result = subprocess.run(
        [
            "python",
            "scripts/coordination_messages.py",
            "--root",
            str(root),
            "--claims-dir",
            str(claims_dir),
            "send",
            "--request-json",
            _send_request(idempotency_key="native-mismatch").model_dump_json(),
        ],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "CODEX_THREAD_ID": "different-thread"},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["error_type"] == "UnknownSessionError"
    assert list(root.glob("messages/*.json")) == []


def test_agent_inbox_cli_injects_notice_and_observation_evidence(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A client-facing poll must expose the message and append exact observation evidence."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(idempotency_key="notice"))
    result = subprocess.run(
        [
            "python",
            "scripts/coordination_inbox.py",
            "--agent",
            "claude-code",
            "--project",
            "enforced-planning",
            "--session-id",
            CLAUDE_SESSION,
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(root),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    payload = json.loads(result.stdout)
    assert payload["message_ids"] == [persisted.message.message_id]
    assert "Narrow the docs claim" in payload["summary"]
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert status.state == "observed"
    assert len(status.receipt_paths) == 1


def test_codex_lifecycle_hook_observes_repeats_until_ack_then_hides(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Native Codex delivery must persist until the exact recipient acknowledges it."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(
            sender=CLAUDE_SESSION,
            recipient=CODEX_SESSION,
            idempotency_key="codex-hook",
        )
    )
    hook_input = json.dumps(
        {
            "session_id": "thread-123",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "hook_event_name": "SessionStart",
            "event_id": "codex-lifecycle-one",
        }
    )
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]

    first = subprocess.run(
        command,
        input=hook_input,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0, first.stderr or first.stdout
    first_payload = json.loads(first.stdout)
    context = first_payload["hookSpecificOutput"]["additionalContext"]
    assert persisted.message.message_id in context
    assert "Narrow the docs claim" in context
    assert store.status(MessageStatusRequest(message_id=persisted.message.message_id)).state == "observed"
    refreshed_claim = yaml.safe_load(
        (claims_dir / "codex_enforced-planning_sender-lane.yaml").read_text(encoding="utf-8")
    )
    assert refreshed_claim["heartbeat_at"] != NOW.isoformat()

    duplicate = subprocess.run(
        command,
        input=hook_input,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert duplicate.returncode == 0
    assert duplicate.stdout == ""
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert len(status.receipt_paths) == 1

    later_hook_input = json.dumps(
        {
            "session_id": "thread-123",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "hook_event_name": "SessionStart",
            "event_id": "codex-lifecycle-two",
        }
    )
    later = subprocess.run(
        command,
        input=later_hook_input,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert persisted.message.message_id in later.stdout

    store.acknowledge(
        AcknowledgeMessageRequest(
            message_id=persisted.message.message_id,
            current_session_id=CODEX_SESSION,
            disposition="accepted",
        )
    )
    after_ack = subprocess.run(
        command,
        input=hook_input,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert after_ack.returncode == 0
    assert after_ack.stdout == ""


def test_claude_lifecycle_adapter_is_duplicate_safe_with_repository_project_override(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Claude host and repository adapters use the same event marker contract as Codex."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(sender=CODEX_SESSION, recipient=CLAUDE_SESSION, idempotency_key="claude-hook")
    )
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--agent",
        "claude-code",
        "--project",
        "enforced-planning",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]
    event = json.dumps(
        {
            "session_id": "session-456",
            "hook_event_name": "PostToolUse",
            "event_id": "claude-tool-use-1",
        }
    )
    host = subprocess.run(
        command,
        input=event,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    repository = subprocess.run(
        command,
        input=event,
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    later = subprocess.run(
        command,
        input=json.dumps(
            {
                "session_id": "session-456",
                "hook_event_name": "PostToolUse",
                "event_id": "claude-tool-use-2",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert host.returncode == 0, host.stderr or host.stdout
    assert persisted.message.message_id in host.stdout
    assert repository.returncode == 0
    assert repository.stdout == ""
    assert later.returncode == 0
    assert persisted.message.message_id in later.stdout
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert [receipt.event for receipt in status.receipts] == ["observed"]


def test_claude_prompt_lifecycle_uses_native_prompt_id_for_duplicate_safety(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Claude prompt callbacks use prompt_id, never a session-ID fallback."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(sender=CODEX_SESSION, recipient=CLAUDE_SESSION, idempotency_key="claude-prompt-id")
    )
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--agent",
        "claude-code",
        "--project",
        "enforced-planning",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]
    prompt = {
        "session_id": "session-456",
        "hook_event_name": "UserPromptSubmit",
        "prompt_id": "claude-prompt-one",
    }

    first = subprocess.run(
        command,
        input=json.dumps(prompt),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    duplicate = subprocess.run(
        command,
        input=json.dumps(prompt),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    later = subprocess.run(
        command,
        input=json.dumps({**prompt, "prompt_id": "claude-prompt-two"}),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr or first.stdout
    assert persisted.message.message_id in first.stdout
    assert duplicate.returncode == 0
    assert duplicate.stdout == ""
    assert later.returncode == 0
    assert persisted.message.message_id in later.stdout
    assert [receipt.event for receipt in store.status(MessageStatusRequest(message_id=persisted.message.message_id)).receipts] == [
        "observed"
    ]


def test_lifecycle_adapter_missing_event_identity_does_not_observe(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """An adapter without a native event identity cannot manufacture observation evidence."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="no-event"))
    result = subprocess.run(
        [
            "python",
            "scripts/coordination_hook.py",
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(root),
        ],
        input=json.dumps(
            {
                "session_id": "thread-123",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "SessionStart",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "requires a native event ID" in result.stdout
    assert store.status(MessageStatusRequest(message_id=persisted.message.message_id)).state == "persisted"


def test_codex_lifecycle_hook_does_not_adopt_a_different_session_claim(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Native activity must not manufacture liveness for a synthetic or obsolete session."""

    _store, claims_dir, root = mailbox
    claim_path = claims_dir / "codex_enforced-planning_sender-lane.yaml"
    before = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    result = subprocess.run(
        [
            "python",
            "scripts/coordination_hook.py",
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(root),
        ],
        input=json.dumps(
            {
                "session_id": "different-runtime",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "UserPromptSubmit",
                "event_id": "different-runtime-event",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    after = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert after["heartbeat_at"] == before["heartbeat_at"]


def test_codex_lifecycle_hook_polls_after_write_claim_completion(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Completing write ownership must not disable the still-running native inbox."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(
            sender=CLAUDE_SESSION,
            recipient=CODEX_SESSION,
            idempotency_key="completed-claim-native-poll",
        )
    )
    claim_path = claims_dir / "codex_enforced-planning_sender-lane.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["status"] = "completed"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")

    result = subprocess.run(
        [
            "python",
            "scripts/coordination_hook.py",
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(root),
        ],
        input=json.dumps(
            {
                "session_id": "thread-123",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "PostToolUse",
                "event_id": "completed-claim-event",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert persisted.message.message_id in json.loads(result.stdout)["systemMessage"]
    assert store.status(
        MessageStatusRequest(message_id=persisted.message.message_id)
    ).state == "observed"


def test_codex_lifecycle_hook_rejects_malformed_input_without_receipt(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Invalid lifecycle input must warn visibly without manufacturing observation evidence."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(
            sender=CLAUDE_SESSION,
            recipient=CODEX_SESSION,
            idempotency_key="malformed-hook",
        )
    )
    result = subprocess.run(
        [
            "python",
            "scripts/coordination_hook.py",
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(root),
        ],
        input='{"session_id":"thread-123"}',
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "coordination mailbox unavailable" in json.loads(result.stdout)["systemMessage"]
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert status.state == "persisted"
    assert status.receipt_paths == ()
