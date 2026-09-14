"""End-to-end and both-sign tests for Plan 67's durable mailbox skeleton."""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from enforced_planning import coordination_claims
from enforced_planning.coordination_messages import (
    AcknowledgementResult,
    AcknowledgeMessageRequest,
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
    PersistedMessageResult,
    PersistedMessageResultV2,
    PollMessagesRequest,
    RecordCollisionError,
    SendMessageRequest,
    SessionInboxNotice,
    UnknownSessionError,
    WrongRecipientError,
    inspect_host_delivery_capability,
    poll_session_inbox,
)

NOW = datetime(2026, 7, 15, 20, 0, tzinfo=UTC)
CODEX_SESSION = "codex:thread-123"
CLAUDE_SESSION = "claude-code:session-456"


def _write_claim(
    claims_dir: Path,
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    status: str = "active",
    updated_at: datetime | None = None,
) -> None:
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
        "status": status,
        "claimed_at": NOW.isoformat(),
        "expires_at": datetime(2099, 1, 1, tzinfo=UTC).isoformat(),
        "updated_at": (updated_at or NOW).isoformat(),
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
    project: str = "enforced-planning",
) -> SendMessageRequest:
    """Build one strict request while keeping system IDs outside caller input."""

    return SendMessageRequest(
        caller_session_id=sender,
        sender_session_id=sender,
        recipient=ExactSessionSelector(kind="session", session_id=recipient),
        project=project,
        kind="coordination_request",
        subject=subject,
        body="Please narrow the broad docs claim before implementation.",
        ttl_seconds=ttl_seconds,
        idempotency_key=idempotency_key,
        plan_ref="Plan #67",
    )


def test_sender_status_reports_advisory_only_when_local_pretooluse_is_disabled(
    tmp_path: Path,
) -> None:
    """Sender-visible status must not translate configured delivery into a stop claim."""

    config = tmp_path / "config.toml"
    adapter = tmp_path / "coordination_hook.py"
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts" / adapter.name, adapter)
    command = f"python3 {adapter} --agent codex"
    config.write_text(
        f'''[[hooks.SessionStart]]
matcher = "startup|resume|clear|compact"
[[hooks.SessionStart.hooks]]
type = "command"
command = "{command}"

[[hooks.PostToolUse]]
matcher = "*"
[[hooks.PostToolUse.hooks]]
type = "command"
command = "{command}"

[[hooks.PreToolUse]]
matcher = "Bash|apply_patch"
[[hooks.PreToolUse.hooks]]
type = "command"
command = "{command}"

[[hooks.Stop]]
matcher = ""
[[hooks.Stop.hooks]]
type = "command"
command = "{command}"

[hooks.state."{config.resolve()}:pre_tool_use:0:0"]
enabled = false
''',
        encoding="utf-8",
    )

    status = inspect_host_delivery_capability("codex:recipient", codex_config_path=config)

    assert status.delivery_mode == "advisory_only"
    assert status.mutation_enforcement_available is False
    assert status.stop_enforcement_available is True
    assert status.observed_proves_exposure_only is True
    assert status.observed_proves_stopped is False
    assert status.observed_proves_acknowledged is False
    assert "mutation enforcement is unavailable" in status.operator_message


def test_send_result_carries_advisory_only_local_host_status(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A persisted send reports the configured delivery boundary without upgrading observation."""

    store, _claims_dir, _root = mailbox
    monkeypatch.setenv("HOME", str(tmp_path))
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    adapter = tmp_path / "coordination_hook.py"
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts" / adapter.name, adapter)
    command = f"python3 {adapter} --agent claude-code"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "SessionStart": [
                        {
                            "matcher": "startup|resume|clear|compact",
                            "hooks": [{"type": "command", "command": command}],
                        }
                    ],
                    "PostToolUse": [
                        {
                            "matcher": "*",
                            "hooks": [{"type": "command", "command": command}],
                        }
                    ],
                    "Stop": [
                        {
                            "matcher": "",
                            "hooks": [{"type": "command", "command": command}],
                        }
                    ],
                }
            }
        ),
        encoding="utf-8",
    )

    result = store.send(_send_request(), now=NOW)

    assert result.local_host_delivery_capability.delivery_mode == "advisory_only"
    assert result.local_host_delivery_capability.mutation_enforcement_available is False
    assert result.local_host_delivery_capability.observed_proves_stopped is False
    assert result.local_host_delivery_capability.observed_proves_acknowledged is False


@pytest.mark.parametrize(
    ("adapter_state", "expected_issue"),
    [("missing", "adapter_missing"), ("digest_drift", "adapter_digest_mismatch")],
)
def test_send_result_fails_closed_for_untrusted_configured_adapter(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    adapter_state: str,
    expected_issue: str,
) -> None:
    """A configured command is not enforcement when its adapter bytes are unavailable or drifted."""

    store, _claims_dir, _root = mailbox
    monkeypatch.setenv("HOME", str(tmp_path))
    adapter = tmp_path / "coordination_hook.py"
    if adapter_state == "digest_drift":
        adapter.write_text("# drifted adapter\n", encoding="utf-8")
    command = f"python3 {adapter} --agent claude-code"
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    event: [{"matcher": matcher, "hooks": [{"type": "command", "command": command}]}]
                    for event, matcher in (
                        ("SessionStart", "startup|resume|clear|compact"),
                        ("UserPromptSubmit", ""),
                        ("PostToolUse", "*"),
                        ("PreToolUse", "Bash|Edit|Write"),
                        ("Stop", ""),
                    )
                }
            }
        ),
        encoding="utf-8",
    )

    capability = store.send(_send_request(), now=NOW).local_host_delivery_capability

    assert capability.delivery_mode == "unavailable"
    assert capability.mutation_enforcement_available is False
    assert capability.stop_enforcement_available is False
    assert expected_issue in capability.issues


@pytest.mark.parametrize(
    "command_template",
    (
        "exit 0; python3 {adapter} --agent codex",
        "python3 {adapter} --agent claude-code",
        "/usr/bin/env python3 {adapter} --agent codex",
        "/definitely/missing/python3 {adapter} --agent codex",
    ),
)
def test_host_delivery_rejects_composed_wrapped_or_wrong_client_commands(
    tmp_path: Path,
    command_template: str,
) -> None:
    """Byte-equal adapters count only when the configured argv invokes them directly."""

    config = tmp_path / "config.toml"
    adapter = tmp_path / "coordination_hook.py"
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts" / adapter.name, adapter)
    command = command_template.format(adapter=adapter)
    blocks = []
    for event, matcher in (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|apply_patch"),
        ("Stop", ""),
    ):
        blocks.append(
            f'[[hooks.{event}]]\nmatcher = "{matcher}"\n'
            f'[[hooks.{event}.hooks]]\ntype = "command"\ncommand = "{command}"\n'
        )
    config.write_text("\n".join(blocks), encoding="utf-8")

    capability = inspect_host_delivery_capability("codex:recipient", codex_config_path=config)

    assert capability.delivery_mode == "unavailable"
    assert capability.mutation_enforcement_available is False
    assert capability.stop_enforcement_available is False
    assert "adapter_command_invalid" in capability.issues


def test_host_delivery_rejects_untrusted_executable_named_python3(tmp_path: Path) -> None:
    """An executable basename cannot substitute for the interpreter running the classifier."""

    config = tmp_path / "config.toml"
    adapter = tmp_path / "coordination_hook.py"
    shutil.copy2(Path(__file__).resolve().parents[1] / "scripts" / adapter.name, adapter)
    no_op_python = tmp_path / "python3"
    no_op_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    no_op_python.chmod(0o755)
    command = f"{no_op_python} {adapter} --agent codex"
    blocks = []
    for event, matcher in (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|apply_patch"),
        ("Stop", ""),
    ):
        blocks.append(
            f'[[hooks.{event}]]\nmatcher = "{matcher}"\n'
            f'[[hooks.{event}.hooks]]\ntype = "command"\ncommand = "{command}"\n'
        )
    config.write_text("\n".join(blocks), encoding="utf-8")

    capability = inspect_host_delivery_capability("codex:recipient", codex_config_path=config)

    assert capability.delivery_mode == "unavailable"
    assert capability.mutation_enforcement_available is False
    assert capability.stop_enforcement_available is False
    assert "adapter_command_invalid" in capability.issues


def test_host_delivery_rejects_non_executable_direct_shell_adapter(tmp_path: Path) -> None:
    """A direct script command is runnable only when its executable bit is present."""

    config = tmp_path / "config.toml"
    adapter = tmp_path / "notify-coordination-messages.sh"
    shutil.copy2(
        Path(__file__).resolve().parents[1] / "hooks" / "codex" / adapter.name,
        adapter,
    )
    adapter.chmod(0o644)
    blocks = []
    for event, matcher in (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|apply_patch"),
        ("Stop", ""),
    ):
        blocks.append(
            f'[[hooks.{event}]]\nmatcher = "{matcher}"\n'
            f'[[hooks.{event}.hooks]]\ntype = "command"\ncommand = "{adapter}"\n'
        )
    config.write_text("\n".join(blocks), encoding="utf-8")

    capability = inspect_host_delivery_capability("codex:recipient", codex_config_path=config)

    assert capability.delivery_mode == "unavailable"
    assert capability.mutation_enforcement_available is False
    assert capability.stop_enforcement_available is False
    assert "adapter_command_invalid" in capability.issues


def test_v2_send_result_has_explicit_legacy_migration_boundary(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """The delivery-capability addition is a named successor, not a silent V1 shape change."""

    store, _claims_dir, _root = mailbox
    current = store.send(_send_request(), now=NOW)
    current_payload = current.model_dump(mode="json")
    legacy_payload = {
        key: value
        for key, value in current_payload.items()
        if key not in {"schema_version", "local_host_delivery_capability"}
    }

    assert (
        PersistedMessageResult.model_validate_json(json.dumps(legacy_payload)).model_dump(mode="json")
        == legacy_payload
    )
    assert PersistedMessageResultV2.model_validate_json(json.dumps(current_payload)).schema_version == "2.0.0"
    with pytest.raises(ValidationError):
        PersistedMessageResult.model_validate_json(json.dumps(current_payload))
    with pytest.raises(ValidationError):
        PersistedMessageResultV2.model_validate_json(json.dumps(legacy_payload))


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


def test_concurrent_truncated_notices_observe_and_claim_only_the_displayed_prefix(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Truncation must occur before delivery reservation or observation side effects."""

    store, claims_dir, root = mailbox
    current_time = datetime.now(UTC)
    messages = [
        store.send(
            _send_request(
                idempotency_key=f"truncated-{index}",
                subject=f"Message {index}",
            ),
            now=current_time + timedelta(seconds=index),
        ).message
        for index in range(3)
    ]

    def poll_once() -> SessionInboxNotice:
        return poll_session_inbox(
            agent="claude-code",
            project="enforced-planning",
            session_id=CLAUDE_SESSION,
            observe=True,
            claims_dir=claims_dir,
            root=root,
            max_messages=1,
            delivery_event_id="same-native-event",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        notices = tuple(executor.map(lambda _index: poll_once(), range(2)))

    displayed_ids = [message_id for notice in notices for message_id in notice.message_ids]
    assert displayed_ids == [messages[0].message_id]
    winner = next(notice for notice in notices if notice.message_ids)
    assert winner.active_count == 3
    assert "2 more not shown" in winner.summary
    assert store.status(MessageStatusRequest(message_id=messages[0].message_id)).state == "observed"
    assert [
        store.status(MessageStatusRequest(message_id=message.message_id)).state
        for message in messages[1:]
    ] == ["persisted", "persisted"]
    assert len(tuple((root / "deliveries").glob("*.json"))) == 1


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


def test_exact_selector_resolves_a_recently_ended_claim(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A recipient whose claim ended minutes ago is still reachable.

    Regression target: policy_friction.md cluster
    coordination-mailbox-session-resolution -- "the mailbox rejected a message
    to the registry's active Plan 136 session... the active owner cannot be
    notified through the prescribed channel" because the claim had just ended.
    """
    store, claims_dir, _root = mailbox
    _write_claim(
        claims_dir,
        agent="claude-code",
        project="enforced-planning",
        scope="recipient-lane",
        session_id=CLAUDE_SESSION,
        status="session_ended",
        updated_at=NOW - timedelta(hours=1),
    )

    assert (
        store.resolve_recipient(ExactSessionSelector(kind="session", session_id=CLAUDE_SESSION), now=NOW)
        == CLAUDE_SESSION
    )


def test_exact_selector_rejects_a_claim_ended_too_long_ago(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A claim that ended days ago is not a live process anymore -- must still fail."""
    store, claims_dir, _root = mailbox
    _write_claim(
        claims_dir,
        agent="claude-code",
        project="enforced-planning",
        scope="recipient-lane",
        session_id=CLAUDE_SESSION,
        status="session_ended",
        updated_at=NOW - timedelta(hours=48),
    )

    with pytest.raises(UnknownSessionError):
        store.resolve_recipient(ExactSessionSelector(kind="session", session_id=CLAUDE_SESSION), now=NOW)


def test_claim_selector_resolves_a_recently_ended_claim_by_scope(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Project/scope routing also reaches a claim that ended minutes ago."""
    store, claims_dir, _root = mailbox
    _write_claim(
        claims_dir,
        agent="claude-code",
        project="enforced-planning",
        scope="recipient-lane",
        session_id=CLAUDE_SESSION,
        status="session_ended",
        updated_at=NOW - timedelta(hours=1),
    )

    selector = ClaimRecipientSelector(kind="claim", project="enforced-planning", scope="recipient-lane")
    assert store.resolve_recipient(selector, now=NOW) == CLAUDE_SESSION


def test_caller_authorization_is_unaffected_by_recently_ended_recipient_fallback(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """_require_live_session (caller/write-authority checks) must not loosen.

    Recipient reachability and caller authorization are deliberately different
    questions -- see the module docstring. A session whose own claim recently
    ended must still fail the strict caller check even though it would now
    resolve as a message RECIPIENT.
    """
    store, claims_dir, _root = mailbox
    _write_claim(
        claims_dir,
        agent="claude-code",
        project="enforced-planning",
        scope="recipient-lane",
        session_id=CLAUDE_SESSION,
        status="session_ended",
        updated_at=NOW - timedelta(hours=1),
    )

    with pytest.raises(UnknownSessionError):
        store._require_live_session(CLAUDE_SESSION)
    assert (
        store.resolve_recipient(ExactSessionSelector(kind="session", session_id=CLAUDE_SESSION), now=NOW)
        == CLAUDE_SESSION
    )


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
    claude_env.pop("CLAUDE_CODE_SESSION_ID", None)
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
    assert payload["summary"].startswith(
        "coordination mailbox: ACKNOWLEDGEMENT REQUIRED"
    )
    assert "DO NOT pass the next natural work boundary" in payload["summary"]
    acknowledgement_script = Path(__file__).resolve().parents[1] / "scripts" / "coordination_messages.py"
    assert f"/usr/bin/python3 {acknowledgement_script} acknowledge" in payload["summary"]
    assert f'"current_session_id":"{CLAUDE_SESSION}"' in payload["summary"]
    assert f'"message_id":"{persisted.message.message_id}"' in payload["summary"]
    assert '"disposition":"<accepted|declined|deferred|information_only>"' in payload["summary"]
    assert "This notice will repeat until acknowledgement is recorded." in payload["summary"]
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert status.state == "observed"
    assert len(status.receipt_paths) == 1


def test_sender_lifecycle_hook_surfaces_acknowledgement_once_without_reply_loop(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """The sender sees one derived acknowledgement notice without a new message."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(idempotency_key="sender-ack-notice"))
    store.acknowledge(
        AcknowledgeMessageRequest(
            current_session_id=CLAUDE_SESSION,
            message_id=persisted.message.message_id,
            disposition="accepted",
            note="The overlapping guide claim was released.",
        )
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
        input=json.dumps(
            {
                "session_id": "thread-123",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "UserPromptSubmit",
                "event_id": "sender-ack-one",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    second = subprocess.run(
        command,
        input=json.dumps(
            {
                "session_id": "thread-123",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "UserPromptSubmit",
                "event_id": "sender-ack-two",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert first.returncode == 0, first.stderr or first.stdout
    notice = json.loads(first.stdout)["systemMessage"]
    assert persisted.message.message_id in notice
    assert "new acknowledgement" in notice
    assert "accepted" in notice
    assert "The overlapping guide claim was released." in notice
    assert second.returncode == 0
    assert second.stdout == ""
    assert len(list((root / "messages").glob("*.json"))) == 1
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert [receipt.event for receipt in status.receipts] == ["acknowledged"]


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
    assert "ACKNOWLEDGEMENT REQUIRED" in context
    acknowledgement_script = Path(__file__).resolve().parents[1] / "scripts" / "coordination_messages.py"
    assert f"/usr/bin/python3 {acknowledgement_script} acknowledge" in context
    assert store.status(MessageStatusRequest(message_id=persisted.message.message_id)).state == "observed"
    refreshed_claim = yaml.safe_load(
        (claims_dir / "codex_enforced-planning_sender-lane.yaml").read_text(encoding="utf-8")
    )
    # SessionStart is advisory and read-only with respect to claim authority;
    # the first real prompt/tool lifecycle event owns heartbeat refresh.
    assert refreshed_claim["heartbeat_at"] == NOW.isoformat()

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


def test_mailbox_obligation_gate_blocks_mutation_allows_exact_ack_then_passes(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A displayed active message blocks mutation but never blocks its own disposition."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="mutation-gate")
    )
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]
    base = {
        "session_id": "thread-123",
        "cwd": str(Path(__file__).resolve().parents[1]),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
    }
    blocked = subprocess.run(
        command,
        input=json.dumps(
            {**base, "tool_use_id": "mutation-one", "tool_input": {"command": "git commit -am blocked"}}
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert blocked.returncode == 0, blocked.stderr or blocked.stdout
    denial = json.loads(blocked.stdout)["hookSpecificOutput"]
    assert denial["permissionDecision"] == "deny"
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert [receipt.event for receipt in status.receipts] == ["observed"]
    boundary = store.boundary_blocks(persisted.message.message_id)[0]
    assert boundary.hook_event_name == "PreToolUse"
    assert boundary.tool_name == "Bash"

    request = {
        "current_session_id": CODEX_SESSION,
        "message_id": persisted.message.message_id,
        "disposition": "information_only",
        "note": "Recorded the completed sibling closeout; no follow-up action is needed.",
    }
    acknowledgement_command = (
        f"/usr/bin/python3 {Path(__file__).resolve().parents[1] / 'scripts' / 'coordination_messages.py'} "
        "acknowledge --request-json "
        + shlex.quote(json.dumps(request, separators=(",", ":")))
    )
    allowed_ack = subprocess.run(
        command,
        input=json.dumps(
            {
                **base,
                "tool_use_id": "ack-one",
                "tool_input": {"command": acknowledgement_command},
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert allowed_ack.returncode == 0, allowed_ack.stderr or allowed_ack.stdout
    assert "permissionDecision" not in allowed_ack.stdout

    acknowledged = store.acknowledge(AcknowledgeMessageRequest(**request))
    assert acknowledged.acknowledgement_latency_seconds >= 0
    after_ack = subprocess.run(
        command,
        input=json.dumps(
            {**base, "tool_use_id": "mutation-two", "tool_input": {"command": "git commit -am allowed"}}
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert after_ack.returncode == 0
    assert after_ack.stdout == ""


def test_mailbox_obligation_gate_blocks_stop_until_acknowledged(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """An active message blocks once, then a re-fired Stop must be allowed."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="stop-gate")
    )
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]
    hook_input = {
        "session_id": "thread-123",
        "cwd": str(Path(__file__).resolve().parents[1]),
        "hook_event_name": "Stop",
        "turn_id": "turn-stop-one",
        "stop_hook_active": False,
    }
    first = subprocess.run(
        command,
        input=json.dumps(hook_input),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    repeated = subprocess.run(
        command,
        input=json.dumps({**hook_input, "stop_hook_active": True}),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert json.loads(first.stdout)["decision"] == "block"
    repeated_payload = json.loads(repeated.stdout)
    assert "decision" not in repeated_payload
    assert repeated.returncode == 0
    boundary_records = store.boundary_blocks(persisted.message.message_id)
    assert len(boundary_records) == 1
    assert boundary_records[0].hook_event_name == "Stop"

    store.acknowledge(
        AcknowledgeMessageRequest(
            current_session_id=CODEX_SESSION,
            message_id=persisted.message.message_id,
            disposition="accepted",
            note="Handled before final response.",
        )
    )
    after_ack = subprocess.run(
        command,
        input=json.dumps({**hook_input, "turn_id": "turn-stop-two"}),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    assert after_ack.returncode == 0
    assert after_ack.stdout == ""


def test_claude_stop_gate_uses_native_last_message_when_event_id_is_absent(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Claude's Stop payload can block without inventing a session-scoped event ID."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(sender=CODEX_SESSION, recipient=CLAUDE_SESSION, idempotency_key="claude-stop-gate")
    )
    result = subprocess.run(
        [
            "python",
            "scripts/coordination_hook.py",
            "--agent",
            "claude-code",
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(root),
        ],
        input=json.dumps(
            {
                "session_id": "session-456",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "Stop",
                "stop_hook_active": False,
                "last_assistant_message": "I am done.",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout)["decision"] == "block"
    assert store.boundary_blocks(persisted.message.message_id)[0].hook_event_name == "Stop"


def test_codex_lifecycle_hook_workspace_root_without_claim_or_message_is_silent(
    mailbox: tuple[CoordinationMessageStore, Path, Path], tmp_path: Path
) -> None:
    """A non-Git workspace path is not a mailbox outage when no claim is live."""

    _store, claims_dir, root = mailbox
    for claim_path in claims_dir.glob("*.yaml"):
        claim_path.unlink()
    result = subprocess.run(
        ["python", "scripts/coordination_hook.py", "--claims-dir", str(claims_dir), "--root", str(root)],
        input=json.dumps({"session_id": "thread-123", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit", "event_id": "workspace-root-no-claim"}),
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert result.stdout == ""


def test_codex_lifecycle_hook_workspace_root_heartbeats_one_claim_and_delivers(
    mailbox: tuple[CoordinationMessageStore, Path, Path], tmp_path: Path
) -> None:
    """A non-Git workspace path routes through one exact-session live claim."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="workspace-one"))
    claim_path = claims_dir / "codex_enforced-planning_sender-lane.yaml"
    before = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    result = subprocess.run(
        ["python", "scripts/coordination_hook.py", "--claims-dir", str(claims_dir), "--root", str(root)],
        input=json.dumps({"session_id": "thread-123", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit", "event_id": "workspace-root-one-claim"}),
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert persisted.message.message_id in result.stdout
    assert yaml.safe_load(claim_path.read_text(encoding="utf-8"))["heartbeat_at"] != before["heartbeat_at"]


def test_codex_lifecycle_hook_workspace_root_heartbeats_multiple_claims_and_polls_all_projects(
    mailbox: tuple[CoordinationMessageStore, Path, Path], tmp_path: Path
) -> None:
    """Workspace-root polling reaches exact-session messages across live projects."""

    store, claims_dir, root = mailbox
    _write_claim(claims_dir, agent="codex", project="project-meta", scope="second-lane", session_id=CODEX_SESSION)
    persisted = store.send(_send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, project="project-meta", idempotency_key="workspace-multiple"))
    result = subprocess.run(
        ["python", "scripts/coordination_hook.py", "--claims-dir", str(claims_dir), "--root", str(root)],
        input=json.dumps({"session_id": "thread-123", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit", "event_id": "workspace-root-multiple-claims"}),
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert persisted.message.message_id in result.stdout
    for claim_path in claims_dir.glob("codex_*.yaml"):
        assert yaml.safe_load(claim_path.read_text(encoding="utf-8"))["heartbeat_at"] != NOW.isoformat()


def test_codex_lifecycle_hook_workspace_root_delivers_closed_lane_message(
    mailbox: tuple[CoordinationMessageStore, Path, Path], tmp_path: Path
) -> None:
    """Exact native identity still receives retained mail after its claim closes."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="workspace-closed"))
    for claim_path in claims_dir.glob("*.yaml"):
        claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        claim["status"] = "completed"
        claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    result = subprocess.run(
        ["python", "scripts/coordination_hook.py", "--claims-dir", str(claims_dir), "--root", str(root)],
        input=json.dumps({"session_id": "thread-123", "cwd": str(tmp_path), "hook_event_name": "UserPromptSubmit", "event_id": "workspace-root-closed-lane"}),
        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert persisted.message.message_id in result.stdout


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
    assert status.state == "persisted"
    assert [receipt.event for receipt in status.receipts] == []


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


def test_non_sessionstart_lifecycle_adapter_missing_event_identity_does_not_observe(
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
                "hook_event_name": "UserPromptSubmit",
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


def test_stop_gate_mailbox_failure_warns_without_fabricating_a_block_receipt(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A degraded adapter reports uncertainty instead of inventing mailbox state."""

    store, claims_dir, root = mailbox
    persisted = store.send(
        _send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="degraded-stop")
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
        input=json.dumps(
            {
                "session_id": "thread-123",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "Stop",
            }
        ),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )

    payload = json.loads(result.stdout)
    assert "coordination mailbox unavailable" in payload["systemMessage"]
    assert "decision" not in payload
    assert store.status(MessageStatusRequest(message_id=persisted.message.message_id)).receipts == ()
    assert store.boundary_blocks(persisted.message.message_id) == ()


def test_claude_session_start_without_event_identity_uses_bounded_duplicate_key(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Claude's documented SessionStart shape can deliver without inventing an event ID."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(sender=CODEX_SESSION, recipient=CLAUDE_SESSION, idempotency_key="claude-start"))
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--agent",
        "claude-code",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]
    hook_input = json.dumps(
        {
            "session_id": "session-456",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "hook_event_name": "SessionStart",
        }
    )

    first = subprocess.run(command, input=hook_input, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
    duplicate = subprocess.run(command, input=hook_input, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)

    assert first.returncode == 0, first.stderr or first.stdout
    assert persisted.message.message_id in first.stdout
    assert duplicate.returncode == 0
    assert duplicate.stdout == ""
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert [receipt.event for receipt in status.receipts] == ["observed"]


def test_codex_session_start_without_event_identity_uses_bounded_duplicate_key(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Codex's documented SessionStart shape can deliver without inventing an event ID."""

    store, claims_dir, root = mailbox
    persisted = store.send(_send_request(sender=CLAUDE_SESSION, recipient=CODEX_SESSION, idempotency_key="codex-start"))
    command = [
        "python",
        "scripts/coordination_hook.py",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(root),
    ]
    hook_input = json.dumps(
        {
            "session_id": "thread-123",
            "cwd": str(Path(__file__).resolve().parents[1]),
            "hook_event_name": "SessionStart",
        }
    )

    first = subprocess.run(command, input=hook_input, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)
    duplicate = subprocess.run(command, input=hook_input, cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, check=False)

    assert first.returncode == 0, first.stderr or first.stdout
    assert persisted.message.message_id in first.stdout
    assert duplicate.returncode == 0
    assert duplicate.stdout == ""
    status = store.status(MessageStatusRequest(message_id=persisted.message.message_id))
    assert [receipt.event for receipt in status.receipts] == ["observed"]


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
    ).state == "persisted"


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


def _initialize_git_repository(path: Path) -> None:
    """Create one clean linked worktree for native closeout-hook tests."""

    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = path.with_name(f".{path.name}-canonical")
    subprocess.run(["git", "init", "-q", str(canonical)], check=True)
    subprocess.run(["git", "-C", str(canonical), "config", "user.name", "Test Agent"], check=True)
    subprocess.run(
        ["git", "-C", str(canonical), "config", "user.email", "agent@example.test"],
        check=True,
    )
    (canonical / "tracked.txt").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(canonical), "add", "tracked.txt"], check=True)
    subprocess.run(["git", "-C", str(canonical), "commit", "-qm", "baseline"], check=True)
    subprocess.run(
        ["git", "-C", str(canonical), "worktree", "add", "-qb", "session-worktree", str(path)],
        check=True,
    )


def _run_repository_closeout_hook(
    *,
    workspace: Path,
    claims_dir: Path,
    message_root: Path,
    ledger_dir: Path,
    event_name: str,
    event_id: str,
    event_cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one native-shaped lifecycle event through repository closeout."""

    payload: dict[str, object] = {
        "session_id": "repository-closeout-test",
        "cwd": str(event_cwd or workspace),
        "hook_event_name": event_name,
        "event_id": event_id,
    }
    if event_name == "PreToolUse":
        payload.update({"tool_name": "Bash", "tool_input": {"command": "true"}})
    return subprocess.run(
        [
            "python",
            "scripts/coordination_hook.py",
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(message_root),
            "--closeout-ledger-dir",
            str(ledger_dir),
        ],
        input=json.dumps(payload),
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
        # Never read the host's real closeout-gate-disabled marker.
        env={
            **os.environ,
            "ENFORCED_PLANNING_CLOSEOUT_GATE_DISABLE_MARKER": str(ledger_dir.parent / "no-gate-disable-marker"),
        },
    )


def test_stop_blocks_dirty_sibling_then_passes_after_cleanup(tmp_path: Path) -> None:
    """A shared-root session must close every repository state it changed."""

    workspace = tmp_path / "workspace"
    first = workspace / "first"
    sibling = workspace / "sibling"
    _initialize_git_repository(first)
    _initialize_git_repository(sibling)
    claims_dir = tmp_path / "coordination" / "claims"
    message_root = tmp_path / "coordination" / "messages-v1"
    ledger_dir = tmp_path / "coordination" / "repository-closeout-ledgers"

    started = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="SessionStart",
        event_id="closeout-start",
    )
    assert started.returncode == 0, started.stderr or started.stdout
    assert started.stdout == ""

    touched = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="PreToolUse",
        event_id="closeout-touch-sibling",
        event_cwd=sibling,
    )
    assert touched.returncode == 0, touched.stderr or touched.stdout

    (sibling / "stranded.txt").write_text("uncommitted\n", encoding="utf-8")
    blocked = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="Stop",
        event_id="closeout-stop-dirty",
    )
    assert blocked.returncode == 0, blocked.stderr or blocked.stdout
    denial = json.loads(blocked.stdout)
    assert denial["decision"] == "block"
    assert str(sibling) in denial["reason"]
    assert "1 change" in denial["reason"]

    (sibling / "stranded.txt").unlink()
    clean = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="Stop",
        event_id="closeout-stop-clean",
    )
    assert clean.returncode == 0, clean.stderr or clean.stdout
    assert clean.stdout == ""


def test_stop_ignores_unchanged_preexisting_dirt_but_blocks_session_delta(tmp_path: Path) -> None:
    """Closeout owns session deltas without adopting another writer's baseline dirt."""

    workspace = tmp_path / "workspace"
    repository = workspace / "preexisting"
    _initialize_git_repository(repository)
    dirty_path = repository / "preexisting.txt"
    dirty_path.write_text("other writer\n", encoding="utf-8")
    claims_dir = tmp_path / "coordination" / "claims"
    message_root = tmp_path / "coordination" / "messages-v1"
    ledger_dir = tmp_path / "coordination" / "repository-closeout-ledgers"

    _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="PreToolUse",
        event_id="preexisting-baseline",
        event_cwd=repository,
    )
    unchanged = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="Stop",
        event_id="preexisting-unchanged",
    )
    assert unchanged.stdout == ""

    dirty_path.write_text("session changed it\n", encoding="utf-8")
    changed = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="Stop",
        event_id="preexisting-changed",
    )
    assert json.loads(changed.stdout)["decision"] == "block"


def test_stop_does_not_adopt_an_unobserved_sibling_change(tmp_path: Path) -> None:
    """A workspace fingerprint cannot attribute an unclaimed sibling writer."""

    workspace = tmp_path / "workspace"
    owned = workspace / "owned"
    sibling = workspace / "sibling"
    _initialize_git_repository(owned)
    _initialize_git_repository(sibling)
    claims_dir = tmp_path / "coordination" / "claims"
    message_root = tmp_path / "coordination" / "messages-v1"
    ledger_dir = tmp_path / "coordination" / "repository-closeout-ledgers"

    started = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="SessionStart",
        event_id="unobserved-start",
    )
    assert started.stdout == ""

    (sibling / "other-writer.txt").write_text("not this session\n", encoding="utf-8")
    stopped = _run_repository_closeout_hook(
        workspace=workspace,
        claims_dir=claims_dir,
        message_root=message_root,
        ledger_dir=ledger_dir,
        event_name="Stop",
        event_id="unobserved-stop",
    )

    assert stopped.returncode == 0
    assert stopped.stdout == ""


def test_send_flags_a_recipient_that_never_observes_its_mail(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """An aged, never-observed backlog means the next send will not be read either."""

    store, _claims_dir, _root = mailbox
    first_sent_at = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
    store.send(_send_request(idempotency_key="backlog-1"), now=first_sent_at)

    # Ten minutes later nobody has looked at it, which is the deaf-recipient signature.
    second = store.send(
        _send_request(idempotency_key="backlog-2", subject="Second attempt"),
        now=first_sent_at + timedelta(minutes=10),
    )

    assert second.recipient_unobserved_backlog == 1
    assert second.recipient_oldest_unobserved_seconds == 600.0
    assert second.recipient_may_be_unreachable is True


def test_send_stays_quiet_when_the_recipient_is_reading(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A recipient that polls its inbox must not be reported as unreachable."""

    store, _claims_dir, _root = mailbox
    first_sent_at = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
    store.send(_send_request(idempotency_key="read-1"), now=first_sent_at)
    store.poll(
        PollMessagesRequest(current_session_id=CLAUDE_SESSION, observe=True),
        now=first_sent_at + timedelta(minutes=1),
    )

    second = store.send(
        _send_request(idempotency_key="read-2", subject="Second attempt"),
        now=first_sent_at + timedelta(minutes=10),
    )

    assert second.recipient_unobserved_backlog == 0
    assert second.recipient_oldest_unobserved_seconds is None
    assert second.recipient_may_be_unreachable is False


def test_a_fresh_unobserved_message_is_not_yet_evidence(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A recipient gets a grace window before an unread message counts against it."""

    store, _claims_dir, _root = mailbox
    first_sent_at = datetime(2026, 8, 26, 18, 0, tzinfo=UTC)
    store.send(_send_request(idempotency_key="fresh-1"), now=first_sent_at)

    second = store.send(
        _send_request(idempotency_key="fresh-2", subject="Second attempt"),
        now=first_sent_at + timedelta(minutes=1),
    )

    assert second.recipient_unobserved_backlog == 1
    assert second.recipient_may_be_unreachable is False


def _unrelated_traffic(store: CoordinationMessageStore, count: int) -> None:
    """Fill the store with acknowledged traffic addressed to other sessions."""

    for index in range(count):
        sent = store.send(
            _send_request(idempotency_key=f"noise-{index}", subject=f"Noise {index}"),
            now=NOW,
        )
        store.acknowledge(
            AcknowledgeMessageRequest(
                current_session_id=CLAUDE_SESSION,
                message_id=sent.message.message_id,
                disposition="information_only",
                note="noise",
            ),
            now=NOW + timedelta(seconds=1),
        )


def test_receipt_lookup_reads_only_the_receipts_of_the_requested_message(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """Status projection must not cost one full receipt-store scan per message.

    Reading every receipt to answer one message made a single inbox poll cost
    ``messages x receipts`` and pushed the lifecycle hook past its budget.
    """

    store, _claims_dir, _root = mailbox
    _unrelated_traffic(store, 12)
    target = store.send(_send_request(idempotency_key="target-1"), now=NOW)
    store.acknowledge(
        AcknowledgeMessageRequest(
            current_session_id=CLAUDE_SESSION,
            message_id=target.message.message_id,
            disposition="accepted",
            note="done",
        ),
        now=NOW + timedelta(seconds=2),
    )

    reads: list[Path] = []
    original = CoordinationMessageStore._read_receipt_path

    def _counting_read(self: CoordinationMessageStore, path: Path) -> MessageReceipt:
        reads.append(path)
        return original(self, path)

    fresh = CoordinationMessageStore(root=store.root, claims_dir=store.claims_dir)
    fresh._refresh_receipt_index()
    CoordinationMessageStore._read_receipt_path = _counting_read  # type: ignore[method-assign]
    try:
        receipts = fresh._receipts_for(target.message.message_id)
    finally:
        CoordinationMessageStore._read_receipt_path = original  # type: ignore[method-assign]

    assert {receipt.message_id for receipt in receipts} == {target.message.message_id}
    assert len(reads) == len(receipts)
    assert len(list(store.receipts_dir.glob("*.json"))) > len(receipts)


def test_inbox_poll_reads_only_the_recipient_messages(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """An inbox poll must not parse every message the store has ever held."""

    store, claims_dir, _root = mailbox
    _write_claim(
        claims_dir,
        agent="claude-code",
        project="enforced-planning",
        scope="other-lane",
        session_id="claude-code:other-999",
    )
    _unrelated_traffic(store, 10)
    mine = store.send(
        _send_request(idempotency_key="mine-1", recipient="claude-code:other-999"),
        now=NOW,
    )

    reads: list[Path] = []
    original = CoordinationMessageStore._read_message_path

    def _counting_read(self: CoordinationMessageStore, path: Path) -> CoordinationMessage:
        reads.append(path)
        return original(self, path)

    fresh = CoordinationMessageStore(root=store.root, claims_dir=store.claims_dir)
    fresh._refresh_message_index()
    CoordinationMessageStore._read_message_path = _counting_read  # type: ignore[method-assign]
    try:
        selected = fresh._messages_for_recipient("claude-code:other-999")
    finally:
        CoordinationMessageStore._read_message_path = original  # type: ignore[method-assign]

    assert [message.message_id for message, _path in selected] == [mine.message.message_id]
    assert len(reads) == 1
    assert len(list(store.messages_dir.glob("*.json"))) > 1


def test_derived_index_is_rebuilt_from_the_canonical_records(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """A discarded or never-written index must reproduce full-scan results exactly."""

    store, _claims_dir, _root = mailbox
    _unrelated_traffic(store, 6)
    sent = store.send(_send_request(idempotency_key="rebuild-1"), now=NOW)

    expected_messages = {
        message.message_id
        for message, _path in store._all_messages()
        if message.recipient_session_id == CLAUDE_SESSION
    }
    expected_receipts = {receipt.receipt_id for receipt in store._receipts_for(sent.message.message_id)}

    shutil.rmtree(store.index_dir)
    assert not store.index_dir.exists()

    rebuilt = CoordinationMessageStore(root=store.root, claims_dir=store.claims_dir)
    assert {
        message.message_id for message, _path in rebuilt._messages_for_recipient(CLAUDE_SESSION)
    } == expected_messages
    assert {
        receipt.receipt_id for receipt in rebuilt._receipts_for(sent.message.message_id)
    } == expected_receipts
    assert store.index_dir.is_dir()


def test_quarantined_record_does_not_leave_a_broken_index_entry(
    mailbox: tuple[CoordinationMessageStore, Path, Path],
) -> None:
    """The canonical record set stays authoritative when a record is quarantined."""

    store, _claims_dir, _root = mailbox
    kept = store.send(_send_request(idempotency_key="kept-1"), now=NOW)
    doomed = store.send(_send_request(idempotency_key="doomed-1", subject="Doomed"), now=NOW)

    doomed_path = store.messages_dir / f"{doomed.message.message_id}.json"
    doomed_path.write_text("{ not json", encoding="utf-8")
    with pytest.raises(CorruptRecordError):
        CoordinationMessageStore(
            root=store.root, claims_dir=store.claims_dir
        )._messages_for_recipient(CLAUDE_SESSION)

    assert list(store.quarantine_dir.glob("*.corrupt"))
    survivors = CoordinationMessageStore(
        root=store.root, claims_dir=store.claims_dir
    )._messages_for_recipient(CLAUDE_SESSION)
    assert [message.message_id for message, _path in survivors] == [kept.message.message_id]
