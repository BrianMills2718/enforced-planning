#!/usr/bin/env python3
"""Durable cross-client coordination messages and append-only receipts.

Claims remain authoritative for recipient routing and write ownership. Exact
native client identity may authorize message-only send, poll, and
acknowledgement after a write claim ends; it cannot restore write authority.
Recipient routing (resolve_recipient) is claim-backed but not limited to
currently-live claims: a session whose claim ended within the last
DEFAULT_TTL_HOURS is still an addressable recipient (see
_reachable_recipient_claims), because ending a claim reflects that lane's
lifecycle, not proof the process is gone. Caller authorization for send/poll/
acknowledge is unaffected by this and still requires a genuinely live claim or
the native-identity bypass. This module owns only immutable message intent,
runtime/observation/acknowledgement evidence, and derived status. JSON is the
canonical storage format; human-readable projections remain outside this
boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import shlex
import shutil
import sys
import tempfile
import tomllib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, cast

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning import coordination_claims

SCHEMA_VERSION: Literal["1.0"] = "1.0"
INDEX_DIRNAME = "index-v1"
DEFAULT_TTL_SECONDS = 86_400
MAX_NOTE_LENGTH = 2_000
DEFAULT_NOTICE_BODY_LENGTH = 500
DEFAULT_NOTICE_MESSAGE_LIMIT = 20
MessageState = Literal["persisted", "runtime_accepted", "observed", "acknowledged", "expired"]
DeliveryMode = Literal["enforced", "advisory_only", "unavailable"]


class CoordinationMessageError(RuntimeError):
    """Base class for fail-loud mailbox contract and storage errors."""


class UnknownSessionError(CoordinationMessageError):
    """Raised when no live claim or exact native client authorizes a session."""


class AmbiguousRecipientError(CoordinationMessageError):
    """Raised when a claim selector resolves to multiple recipient sessions."""


class IdentityMismatchError(CoordinationMessageError):
    """Raised when caller identity differs from the asserted sender identity."""


class RecordCollisionError(CoordinationMessageError):
    """Raised when an immutable identifier is reused for different content."""


class CorruptRecordError(CoordinationMessageError):
    """Raised after an unreadable or integrity-invalid record is quarantined."""


class MessageNotFoundError(CoordinationMessageError):
    """Raised when a requested canonical message does not exist."""


class WrongRecipientError(CoordinationMessageError):
    """Raised when a session attempts to observe or acknowledge another inbox."""


class StrictContract(BaseModel):
    """Strict immutable base for every public mailbox boundary model."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ExactSessionSelector(StrictContract):
    """Select one recipient by canonical live session identity."""

    kind: Literal["session"] = Field(description="Discriminator for exact-session routing.")
    session_id: str = Field(min_length=1, description="Canonical session ID already present in a live claim.")


class ClaimRecipientSelector(StrictContract):
    """Select one recipient through a live project claim."""

    kind: Literal["claim"] = Field(description="Discriminator for claim-backed routing.")
    project: str = Field(min_length=1, description="Project whose live claim owns the recipient session.")
    scope: str | None = Field(
        default=None,
        description="Optional exact claim scope; omission is valid only when one live session remains.",
    )


RecipientSelector = Annotated[ExactSessionSelector | ClaimRecipientSelector, Field(discriminator="kind")]


class SendMessageRequest(StrictContract):
    """Typed command for persisting one immutable coordination message."""

    caller_session_id: str = Field(min_length=1, description="Session identity supplied by the invoking adapter.")
    sender_session_id: str = Field(min_length=1, description="Sender identity asserted in the durable message.")
    recipient: RecipientSelector = Field(description="Canonical selector resolved at send time.")
    project: str = Field(min_length=1, description="Project context for the requested coordination action.")
    kind: Literal["info", "question", "review_request", "handoff", "coordination_request"] = Field(
        description="Bounded coordination intent, not an authorization to mutate recipient state."
    )
    subject: str = Field(min_length=1, max_length=500, description="Compact human-readable message subject.")
    body: str | None = Field(default=None, min_length=1, description="Inline message content when no content_ref is used.")
    content_ref: str | None = Field(
        default=None,
        min_length=1,
        description="Durable content reference used instead of inline body text.",
    )
    ttl_seconds: int = Field(
        default=DEFAULT_TTL_SECONDS,
        gt=0,
        description="Positive lifetime in seconds; expiry never deletes the audit record.",
    )
    idempotency_key: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description="Caller-owned retry key scoped to sender identity; not persisted verbatim.",
    )
    plan_ref: str | None = Field(default=None, min_length=1, description="Optional governing plan reference.")
    claim_ref: str | None = Field(default=None, min_length=1, description="Optional related claim scope.")
    reply_to_message_id: str | None = Field(
        default=None,
        pattern=r"^msg_[0-9a-f]{32}$",
        description="Optional canonical message ID being answered.",
    )

    @model_validator(mode="after")
    def require_exactly_one_content_source(self) -> SendMessageRequest:
        """Reject missing content and ambiguous dual inline/reference content."""

        if (self.body is None) == (self.content_ref is None):
            raise ValueError("exactly one of body or content_ref is required")
        return self


class PollMessagesRequest(StrictContract):
    """Typed command for reading one canonical session inbox."""

    current_session_id: str = Field(min_length=1, description="Canonical recipient session performing the poll.")
    as_of: AwareDatetime | None = Field(default=None, description="Projection time; current UTC when omitted.")
    project: str | None = Field(default=None, min_length=1, description="Optional exact project filter.")
    include_expired: bool = Field(default=False, description="Whether expired messages remain in the returned view.")
    observe: bool = Field(default=False, description="Whether returned active messages emit observation receipts.")
    delivery_event_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=500,
        description=(
            "Optional adapter-derived identity for one native lifecycle event. "
            "When present, the same message is visible at most once for that event."
        ),
    )


class AcknowledgeMessageRequest(StrictContract):
    """Typed command for appending one recipient acknowledgement."""

    current_session_id: str = Field(min_length=1, description="Canonical recipient session acknowledging the message.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Canonical message being acknowledged.")
    disposition: Literal["accepted", "declined", "deferred", "information_only"] = Field(
        description="Recipient's explicit acknowledgement disposition."
    )
    response_ref: str | None = Field(default=None, min_length=1, description="Optional durable response artifact reference.")
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_NOTE_LENGTH,
        description="Optional bounded recipient note; not an authorization side effect.",
    )


class MessageStatusRequest(StrictContract):
    """Typed command for deriving status from one message and its receipt set."""

    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Canonical message whose status is requested.")
    as_of: AwareDatetime | None = Field(default=None, description="Projection time; current UTC when omitted.")


class CoordinationMessage(StrictContract):
    """Immutable resolved coordination intent persisted by the mailbox."""

    schema_version: Literal["1.0"] = Field(description="Portable message schema version.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="System-assigned globally unique message ID.")
    sender_session_id: str = Field(min_length=1, description="Canonical live sender session at creation time.")
    recipient_selector: RecipientSelector = Field(description="Original routing selector retained for audit.")
    recipient_session_id: str = Field(min_length=1, description="Exact live session resolved at creation time.")
    project: str = Field(min_length=1, description="Project context for this coordination intent.")
    kind: Literal["info", "question", "review_request", "handoff", "coordination_request"] = Field(
        description="Bounded coordination intent."
    )
    subject: str = Field(min_length=1, max_length=500, description="Compact human-readable message subject.")
    body: str | None = Field(default=None, min_length=1, description="Inline content when retained directly.")
    content_ref: str | None = Field(default=None, min_length=1, description="Durable content reference when not inline.")
    created_at: AwareDatetime = Field(description="UTC creation time chosen by the mailbox.")
    expires_at: AwareDatetime = Field(description="UTC time after which the message is inactive but auditable.")
    request_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Canonical semantic-request digest used to detect idempotency collisions.",
    )
    plan_ref: str | None = Field(default=None, min_length=1, description="Optional governing plan reference.")
    claim_ref: str | None = Field(default=None, min_length=1, description="Optional related claim scope.")
    reply_to_message_id: str | None = Field(
        default=None,
        pattern=r"^msg_[0-9a-f]{32}$",
        description="Optional canonical message being answered.",
    )

    @model_validator(mode="after")
    def validate_content_and_time(self) -> CoordinationMessage:
        """Keep persisted content exclusive and expiry strictly after creation."""

        if (self.body is None) == (self.content_ref is None):
            raise ValueError("exactly one of body or content_ref is required")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class MessageReceipt(StrictContract):
    """Immutable evidence of runtime acceptance, observation, or acknowledgement."""

    schema_version: Literal["1.0"] = Field(description="Portable receipt schema version.")
    receipt_id: str = Field(pattern=r"^rcpt_[0-9a-f]{32}$", description="System-assigned deterministic receipt ID.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Message evidenced by this receipt.")
    recipient_session_id: str = Field(min_length=1, description="Canonical recipient session producing the evidence.")
    event: Literal["runtime_accepted", "observed", "acknowledged"] = Field(
        description="Evidence class; no event implies a stronger class by storage alone."
    )
    recorded_at: AwareDatetime = Field(description="UTC time at which the immutable receipt was appended.")
    disposition: Literal["accepted", "declined", "deferred", "information_only"] | None = Field(
        default=None,
        description="Required only for acknowledgement receipts.",
    )
    response_ref: str | None = Field(default=None, min_length=1, description="Optional durable response artifact reference.")
    note: str | None = Field(
        default=None,
        min_length=1,
        max_length=MAX_NOTE_LENGTH,
        description="Optional bounded recipient note.",
    )
    @model_validator(mode="after")
    def validate_acknowledgement_fields(self) -> MessageReceipt:
        """Prevent weaker receipt classes from carrying acknowledgement claims."""

        if self.event == "acknowledged" and self.disposition is None:
            raise ValueError("acknowledged receipts require disposition")
        if self.event != "acknowledged" and any(
            value is not None for value in (self.disposition, self.response_ref, self.note)
        ):
            raise ValueError("only acknowledged receipts may carry disposition, response_ref, or note")
        return self


class StoredMessageRecord(StrictContract):
    """Integrity envelope for one canonical message file."""

    record_type: Literal["coordination_message"] = Field(description="Discriminator for message storage records.")
    payload: CoordinationMessage = Field(description="Strict canonical message payload.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of canonical payload JSON.")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredMessageRecord:
        """Reject storage bytes whose payload no longer matches its digest."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("message payload_sha256 mismatch")
        return self


class StoredReceiptRecord(StrictContract):
    """Integrity envelope for one canonical receipt file."""

    record_type: Literal["message_receipt"] = Field(description="Discriminator for receipt storage records.")
    payload: MessageReceipt = Field(description="Strict canonical receipt payload.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of canonical payload JSON.")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredReceiptRecord:
        """Reject storage bytes whose payload no longer matches its digest."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("receipt payload_sha256 mismatch")
        return self


class DeliveryEventRecord(StrictContract):
    """Immutable duplicate-suppression marker for one displayed lifecycle event."""

    schema_version: Literal["1.0"] = Field(description="Portable delivery-marker schema version.")
    delivery_id: str = Field(pattern=r"^delivery_[0-9a-f]{32}$", description="Deterministic marker identity.")
    delivery_event_id: str = Field(min_length=1, description="Adapter-derived native lifecycle-event identity.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Message displayed for this event.")
    recipient_session_id: str = Field(
        min_length=1,
        description="Exact session shown the message or sender-facing acknowledgement notification.",
    )
    recorded_at: AwareDatetime = Field(description="UTC marker publication time.")


class StoredDeliveryEventRecord(StrictContract):
    """Integrity envelope for one lifecycle duplicate-suppression marker."""

    record_type: Literal["mailbox_delivery_event"] = Field(description="Discriminator for delivery-marker storage.")
    payload: DeliveryEventRecord = Field(description="Strict immutable delivery-marker payload.")
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$", description="Digest of canonical marker payload JSON.")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredDeliveryEventRecord:
        """Reject marker bytes whose payload no longer matches its digest."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("delivery marker payload_sha256 mismatch")
        return self


class BoundaryBlockRecord(StrictContract):
    """Immutable evidence that active mailbox debt denied one lifecycle boundary."""

    schema_version: Literal["1.0"] = Field(description="Portable boundary-record schema version.")
    boundary_id: str = Field(pattern=r"^boundary_[0-9a-f]{32}$", description="Deterministic record identity.")
    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$", description="Active message causing the denial.")
    recipient_session_id: str = Field(min_length=1, description="Exact session whose boundary was denied.")
    hook_event_name: Literal["PreToolUse", "Stop"] = Field(description="Denied native lifecycle boundary.")
    delivery_event_id: str = Field(min_length=1, max_length=500, description="Native callback identity.")
    tool_name: str | None = Field(default=None, min_length=1, max_length=500)
    recorded_at: AwareDatetime = Field(description="UTC time at which denial evidence was appended.")

    @model_validator(mode="after")
    def validate_tool_boundary(self) -> BoundaryBlockRecord:
        """Only a tool boundary may retain a tool name."""

        if self.hook_event_name == "Stop" and self.tool_name is not None:
            raise ValueError("Stop boundary records cannot carry tool_name")
        return self


class StoredBoundaryBlockRecord(StrictContract):
    """Integrity envelope for one immutable mailbox boundary denial."""

    record_type: Literal["mailbox_boundary_block"] = Field(description="Boundary-record discriminator.")
    payload: BoundaryBlockRecord
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_digest(self) -> StoredBoundaryBlockRecord:
        """Reject boundary bytes whose payload no longer matches its digest."""

        if self.payload_sha256 != _model_digest(self.payload):
            raise ValueError("boundary block payload_sha256 mismatch")
        return self


class MessageStatusView(StrictContract):
    """Derived lifecycle view computed from immutable message and receipts."""

    message: CoordinationMessage = Field(description="Canonical immutable message being projected.")
    state: MessageState = Field(
        description="Strongest active lifecycle state at the requested projection time."
    )
    runtime_accepted: bool = Field(description="Whether runtime acceptance evidence exists.")
    observed: bool = Field(description="Whether observation or acknowledgement evidence exists.")
    acknowledged: bool = Field(description="Whether explicit acknowledgement evidence exists.")
    expired: bool = Field(description="Whether the message is inactive at the projection time.")
    receipts: tuple[MessageReceipt, ...] = Field(description="Exact ordered receipt set used for this projection.")
    receipt_paths: tuple[str, ...] = Field(
        description="Evidence paths aligned one-to-one with the ordered receipt set."
    )
    receipt_set_sha256: str = Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Digest watermark of ordered canonical receipt payloads.",
    )
    message_path: str = Field(min_length=1, description="Evidence path to the canonical stored message.")


class HostDeliveryCapabilityV1(StrictContract):
    """Sender-visible local host capability for the recipient's client type.

    This is deliberately scoped to the sender's current host configuration. It
    does not claim that a remote recipient process loaded those bytes.
    """

    schema_version: Literal["mailbox_host_delivery_capability.v1"] = (
        "mailbox_host_delivery_capability.v1"
    )
    client: Literal["codex", "claude-code", "unknown"]
    config_path: str = Field(min_length=1)
    scope: Literal[
        "sender_host_recipient_client_config",
        "operator_host_recipient_client_config",
    ] = "sender_host_recipient_client_config"
    configured_events: tuple[str, ...]
    delivery_mode: DeliveryMode
    mutation_enforcement_available: bool
    stop_enforcement_available: bool
    issues: tuple[str, ...]
    operator_message: str = Field(min_length=1)
    observed_proves_exposure_only: Literal[True] = True
    observed_proves_stopped: Literal[False] = False
    observed_proves_acknowledged: Literal[False] = False


_CLIENT_HOOK_REQUIREMENTS: dict[str, tuple[tuple[str, str], ...]] = {
    "codex": (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|apply_patch"),
        ("Stop", ""),
    ),
    "claude-code": (
        ("SessionStart", "startup|resume|clear|compact"),
        ("UserPromptSubmit", ""),
        ("PostToolUse", "*"),
        ("PreToolUse", "Bash|Edit|Write"),
        ("Stop", ""),
    ),
}


def _event_state_name(event: str) -> str:
    """Render native CamelCase hook names as Codex state-table identifiers."""

    return "".join(f"_{char.lower()}" if char.isupper() else char for char in event).lstrip("_")


def _configured_coordination_hook_command(
    config: dict[str, Any], event: str, matcher: str, *, config_path: Path
) -> str | None:
    """Return the enabled coordination adapter command for one exact hook surface."""

    hooks = config.get("hooks")
    blocks = hooks.get(event) if isinstance(hooks, dict) else None
    state = hooks.get("state") if isinstance(hooks, dict) else None
    if not isinstance(blocks, list):
        return None
    resolved_config_path = config_path.expanduser().resolve()
    for block_index, block in enumerate(blocks):
        if not isinstance(block, dict) or block.get("matcher", "") != matcher:
            continue
        entries = block.get("hooks")
        if not isinstance(entries, list):
            continue
        for hook_index, entry in enumerate(entries):
            command = entry.get("command") if isinstance(entry, dict) else None
            if isinstance(command, str) and (
                "coordination_hook.py" in command or "notify-coordination-messages.sh" in command
            ):
                state_key = (
                    f"{resolved_config_path}:{_event_state_name(event)}:{block_index}:{hook_index}"
                )
                state_record = state.get(state_key) if isinstance(state, dict) else None
                if isinstance(state_record, dict) and state_record.get("enabled") is False:
                    continue
                return command
    return None


def _configured_adapter_issue(client: str, commands: tuple[str, ...]) -> str | None:
    """Fail closed unless configured commands match the canonical adapter bytes."""

    canonical_root = Path(__file__).resolve().parents[1]
    expected_by_name = {
        "coordination_hook.py": canonical_root / "scripts" / "coordination_hook.py",
        "notify-coordination-messages.sh": (
            canonical_root / "hooks" / ("codex" if client == "codex" else "claude")
            / "notify-coordination-messages.sh"
        ),
    }
    for command in commands:
        try:
            tokens = shlex.split(command)
        except ValueError:
            return "adapter_command_invalid"
        adapter_token: str | None = None
        interpreter = Path(tokens[0]).expanduser() if tokens else None
        if interpreter is not None and not interpreter.is_absolute():
            resolved_interpreter = shutil.which(tokens[0])
            interpreter = Path(resolved_interpreter) if resolved_interpreter else None
        try:
            trusted_interpreter = Path(sys.executable).resolve(strict=True)
            trusted_bash = Path("/bin/bash").resolve(strict=True)
            interpreter_is_trusted = bool(
                interpreter is not None
                and interpreter.is_file()
                and os.access(interpreter, os.X_OK)
                and interpreter.resolve(strict=True) == trusted_interpreter
            )
        except OSError:
            interpreter_is_trusted = False
            trusted_bash = None
        direct_python_adapter = (
            len(tokens) == 4
            and interpreter_is_trusted
            and Path(tokens[1]).name == "coordination_hook.py"
            and tokens[2:] == ["--agent", client]
        )
        direct_shell_adapter = (
            len(tokens) == 2
            and interpreter is not None
            and interpreter.is_file()
            and os.access(interpreter, os.X_OK)
            and trusted_bash is not None
            and interpreter.resolve() == trusted_bash
            and Path(tokens[1]).name == "notify-coordination-messages.sh"
        )
        if direct_python_adapter or direct_shell_adapter:
            adapter_token = tokens[1]
        elif len(tokens) == 1 and Path(tokens[0]).name == "notify-coordination-messages.sh":
            adapter_token = tokens[0]
        if adapter_token is None:
            return "adapter_command_invalid"
        adapter_path = Path(adapter_token).expanduser()
        expected_path = expected_by_name[adapter_path.name]
        if not adapter_path.is_absolute() or not adapter_path.is_file():
            return "adapter_missing"
        if len(tokens) == 1 and not os.access(adapter_path, os.X_OK):
            return "adapter_command_invalid"
        if not expected_path.is_file():
            return "canonical_adapter_missing"
        if hashlib.sha256(adapter_path.read_bytes()).digest() != hashlib.sha256(
            expected_path.read_bytes()
        ).digest():
            return "adapter_digest_mismatch"
    return None


def inspect_host_delivery_capability(
    session_id: str,
    *,
    codex_config_path: Path | None = None,
    claude_config_path: Path | None = None,
    scope: Literal[
        "sender_host_recipient_client_config",
        "operator_host_recipient_client_config",
    ] = "sender_host_recipient_client_config",
) -> HostDeliveryCapabilityV1:
    """Inspect local configured hook state without promoting it to runtime proof."""

    if session_id.startswith("codex:"):
        client = "codex"
        path = codex_config_path or Path.home() / ".codex" / "config.toml"
        parser = "toml"
    elif session_id.startswith("claude-code:"):
        client = "claude-code"
        path = claude_config_path or Path.home() / ".claude" / "settings.json"
        parser = "json"
    else:
        return HostDeliveryCapabilityV1(
            client="unknown",
            config_path="unknown",
            scope=scope,
            configured_events=(),
            delivery_mode="unavailable",
            mutation_enforcement_available=False,
            stop_enforcement_available=False,
            issues=("unsupported_recipient_client",),
            operator_message=(
                "Mailbox delivery enforcement is unavailable for this recipient client. "
                "Persistence is not delivery, and an observed receipt proves exposure only, "
                "not that the recipient stopped or acknowledged."
            ),
        )

    issues: list[str] = []
    try:
        if parser == "toml":
            with path.open("rb") as handle:
                raw = tomllib.load(handle)
        else:
            raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise TypeError("host hook config must be an object")
    except (OSError, tomllib.TOMLDecodeError, json.JSONDecodeError, TypeError) as exc:
        issues.append(f"config_unavailable:{type(exc).__name__}")
        raw = {}

    configured_commands = {
        event: command
        for event, matcher in _CLIENT_HOOK_REQUIREMENTS[client]
        if (
            command := _configured_coordination_hook_command(
                raw, event, matcher, config_path=path
            )
        )
        is not None
    }
    configured_events = tuple(configured_commands)
    missing_required = len(configured_events) != len(_CLIENT_HOOK_REQUIREMENTS[client])
    if missing_required:
        issues.append("missing_required_hook")
    adapter_issue = _configured_adapter_issue(
        client, tuple(dict.fromkeys(configured_commands.values()))
    )
    if adapter_issue is not None:
        issues.append(adapter_issue)
    adapter_ready = adapter_issue is None
    surface_ready = adapter_ready and not missing_required
    mutation_available = "PreToolUse" in configured_events and surface_ready
    stop_available = "Stop" in configured_events and adapter_ready
    advisory_events = {"SessionStart", "UserPromptSubmit", "PostToolUse"}
    has_advisory_delivery = bool(advisory_events.intersection(configured_events)) and adapter_ready
    if mutation_available:
        delivery_mode: DeliveryMode = "enforced"
        operator_message = (
            "Mailbox mutation enforcement is configured on this host. An observed receipt "
            "proves exposure only, not that the recipient stopped or acknowledged."
        )
    elif has_advisory_delivery:
        delivery_mode = "advisory_only"
        issues.append("pretooluse_coordination_hook_missing")
        operator_message = (
            "Mailbox delivery is advisory-only on this host: the coordination surface is incomplete "
            "or its PreToolUse hook is disabled, so mutation enforcement is unavailable. An observed receipt "
            "proves exposure only, not that the recipient stopped or acknowledged."
        )
    else:
        delivery_mode = "unavailable"
        issues.append("coordination_delivery_hooks_missing")
        operator_message = (
            "Mailbox delivery enforcement is unavailable on this host for this recipient client. "
            "Persistence is not delivery, and an observed receipt proves exposure only, not that "
            "the recipient stopped or acknowledged."
        )
    return HostDeliveryCapabilityV1(
        client=client,
        config_path=str(path),
        scope=scope,
        configured_events=configured_events,
        delivery_mode=delivery_mode,
        mutation_enforcement_available=mutation_available,
        stop_enforcement_available=stop_available,
        issues=tuple(issues),
        operator_message=operator_message,
    )


UNREACHABLE_BACKLOG_SECONDS = 300.0
"""How stale an unobserved message must be before it implies a deaf recipient."""


def _looks_unreachable(backlog: int, oldest_age_seconds: float | None) -> bool:
    """Treat an aged, never-observed backlog as evidence the recipient cannot read."""

    if backlog <= 0 or oldest_age_seconds is None:
        return False
    return oldest_age_seconds >= UNREACHABLE_BACKLOG_SECONDS


class PersistedMessageResult(StrictContract):
    """Legacy V1 send result retained for strict consumer compatibility."""

    message: CoordinationMessage = Field(description="Canonical persisted message.")
    message_path: str = Field(min_length=1, description="Evidence path to the canonical message record.")
    idempotent_replay: bool = Field(description="Whether an identical existing message satisfied this request.")
    recipient_unobserved_backlog: int = Field(
        default=0,
        ge=0,
        description="Earlier active messages the recipient has never observed.",
    )
    recipient_oldest_unobserved_seconds: float | None = Field(
        default=None,
        ge=0,
        description="Age of the recipient's oldest never-observed active message at send time.",
    )
    recipient_may_be_unreachable: bool = Field(
        default=False,
        description=(
            "Whether the recipient looks unable to receive: it has an earlier active message "
            "it never observed. Storing a message is persistence, never delivery."
        ),
    )


class PersistedMessageResultV2(PersistedMessageResult):
    """Versioned send result that adds truthful sender-host delivery capability."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    local_host_delivery_capability: HostDeliveryCapabilityV1 = Field(
        description=(
            "Sender-host configured capability for the recipient client type; this is not proof "
            "that a remote recipient process loaded the configuration."
        )
    )


class MessagePollResult(StrictContract):
    """Ordered inbox views and any observation receipts appended by polling."""

    current_session_id: str = Field(min_length=1, description="Canonical session whose inbox was polled.")
    messages: tuple[MessageStatusView, ...] = Field(description="Creation-ordered message views for the recipient.")
    observation_receipts: tuple[MessageReceipt, ...] = Field(
        description="Observation receipts created or idempotently reused by this poll."
    )
    observation_receipt_paths: tuple[str, ...] = Field(
        description="Evidence paths aligned one-to-one with observation_receipts."
    )
    delivery_event_id: str | None = Field(
        default=None,
        description="Lifecycle event identity used for duplicate suppression, when supplied by an adapter.",
    )
    suppressed_message_ids: tuple[str, ...] = Field(
        default=(),
        description="Messages withheld because another adapter already displayed them for this exact lifecycle event.",
    )


class AcknowledgementResult(StrictContract):
    """Acknowledgement receipt plus the resulting derived message status."""

    receipt: MessageReceipt = Field(description="Canonical acknowledgement receipt.")
    receipt_path: str = Field(min_length=1, description="Evidence path to the canonical acknowledgement receipt.")
    status: MessageStatusView = Field(description="Status projected after appending the receipt.")
    idempotent_replay: bool = Field(description="Whether an identical receipt already existed.")
    acknowledgement_latency_seconds: float = Field(
        ge=0,
        description="Elapsed time from message creation to the durable acknowledgement receipt.",
    )


class SessionInboxNotice(StrictContract):
    """Compact agent-facing projection of one lifecycle mailbox poll."""

    session_id: str = Field(min_length=1, description="Canonical session identity whose inbox was polled.")
    project: str | None = Field(default=None, min_length=1, description="Optional exact project filter applied to the poll.")
    active_count: int = Field(ge=0, description="Number of non-expired messages visible to the session.")
    message_ids: tuple[str, ...] = Field(description="Canonical active message IDs in creation order.")
    acknowledgement_count: int = Field(
        default=0,
        ge=0,
        description="Number of newly surfaced acknowledgements for messages sent by this session.",
    )
    acknowledgement_message_ids: tuple[str, ...] = Field(
        default=(),
        description="Sent message IDs whose acknowledgements were newly surfaced.",
    )
    summary: str = Field(description="Bounded text suitable for injection into an agent lifecycle response.")


def _canonical_json(value: Any) -> bytes:
    """Serialize one JSON-compatible value deterministically for identity and storage."""

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _model_digest(model: BaseModel) -> str:
    """Hash one strict model in JSON mode using canonical ordering."""

    return hashlib.sha256(_canonical_json(model.model_dump(mode="json"))).hexdigest()


def _receipt_set_digest(receipts: list[MessageReceipt]) -> str:
    """Hash the exact ordered receipt payload set used by a status projection."""

    payloads = [receipt.model_dump(mode="json") for receipt in receipts]
    return hashlib.sha256(_canonical_json(payloads)).hexdigest()


def _utc_now() -> datetime:
    """Return an aware UTC timestamp for default runtime operations."""

    return datetime.now(UTC)


def _fsync_directory(path: Path) -> None:
    """Durably commit a directory-entry change before reporting success."""

    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stable_id(prefix: str, *parts: str) -> str:
    """Build a collision-resistant deterministic ID from a namespaced tuple."""

    digest = hashlib.sha256("\0".join((prefix, *parts)).encode("utf-8")).hexdigest()[:32]
    return f"{prefix}_{digest}"


class CoordinationMessageStore:
    """Filesystem authority for immutable messages, receipts, and derived views."""

    def __init__(self, *, root: Path, claims_dir: Path) -> None:
        self.root = root.expanduser().resolve()
        self.claims_dir = claims_dir.expanduser().resolve()
        self.messages_dir = self.root / "messages"
        self.receipts_dir = self.root / "receipts"
        self.deliveries_dir = self.root / "deliveries"
        self.boundary_blocks_dir = self.root / "boundary-blocks"
        self.quarantine_dir = self.root / "quarantine"
        # Derived, rebuildable lookup index over the immutable canonical
        # records.  Lifecycle hooks run on every mutation-shaped tool call, so
        # they must never pay a cost proportional to every message and receipt
        # the store has ever held.  Nothing here is authoritative: every marker
        # is an empty file whose name is derived from a canonical record, and
        # deleting the whole directory only costs one rebuild.
        self.index_dir = self.root / INDEX_DIRNAME
        self.index_messages_by_recipient_dir = self.index_dir / "messages-by-recipient"
        self.index_messages_by_sender_dir = self.index_dir / "messages-by-sender"
        self.index_receipts_by_message_dir = self.index_dir / "receipts-by-message"
        self.index_indexed_messages_dir = self.index_dir / "indexed-messages"
        self.index_indexed_receipts_dir = self.index_dir / "indexed-receipts"
        # One backfill scan per store instance.  Records this instance writes
        # are indexed inline at write time, so the scan only has to pick up
        # records published by other processes, and a status projection is
        # already a point-in-time view bounded by ``as_of``.
        self._messages_backfilled = False
        self._receipts_backfilled = False

    @staticmethod
    def _index_key(session_id: str) -> str:
        """Derive one path-safe directory name for an arbitrary session identity."""

        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:40]

    @staticmethod
    def _record_ids(directory: Path, *, suffix: str = "") -> set[str]:
        """List record identifiers in one directory without reading any record."""

        if not directory.exists():
            return set()
        names: set[str] = set()
        with os.scandir(directory) as entries:
            for entry in entries:
                name = entry.name
                if suffix:
                    if not name.endswith(suffix):
                        continue
                    name = name[: -len(suffix)]
                names.add(name)
        return names

    @staticmethod
    def _write_marker(path: Path) -> None:
        """Create one empty derived-index marker, tolerating a concurrent writer.

        ``FileExistsError`` is the success case for a second writer publishing
        the identical derived fact; every other error is raised so an unusable
        index fails loudly instead of degrading into a silent full scan.
        """

        try:
            os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
        except FileExistsError:
            return
        except FileNotFoundError:
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644))
            except FileExistsError:
                return

    def _index_message(self, message: CoordinationMessage) -> None:
        """Publish the derived lookup markers for one canonical message."""

        self._write_marker(
            self.index_messages_by_recipient_dir
            / self._index_key(message.recipient_session_id)
            / message.message_id
        )
        self._write_marker(
            self.index_messages_by_sender_dir
            / self._index_key(message.sender_session_id)
            / message.message_id
        )
        # Written last: a crash between the lookup markers and this one only
        # costs an idempotent re-index on the next backfill.
        self._write_marker(self.index_indexed_messages_dir / message.message_id)

    def _index_receipt(self, receipt: MessageReceipt) -> None:
        """Publish the derived lookup marker for one canonical receipt."""

        self._write_marker(
            self.index_receipts_by_message_dir / receipt.message_id / receipt.receipt_id
        )
        self._write_marker(self.index_indexed_receipts_dir / receipt.receipt_id)

    def _refresh_message_index(self) -> None:
        """Backfill messages published without a derived index, once per instance."""

        if self._messages_backfilled:
            return
        pending = self._record_ids(self.messages_dir, suffix=".json") - self._record_ids(
            self.index_indexed_messages_dir
        )
        for message_id in sorted(pending):
            self._index_message(self._read_message_path(self.messages_dir / f"{message_id}.json"))
        self._messages_backfilled = True

    def _refresh_receipt_index(self) -> None:
        """Backfill receipts published without a derived index, once per instance."""

        if self._receipts_backfilled:
            return
        pending = self._record_ids(self.receipts_dir, suffix=".json") - self._record_ids(
            self.index_indexed_receipts_dir
        )
        for receipt_id in sorted(pending):
            self._index_receipt(self._read_receipt_path(self.receipts_dir / f"{receipt_id}.json"))
        self._receipts_backfilled = True

    def _indexed_messages(self, index_root: Path, session_id: str) -> list[tuple[CoordinationMessage, Path]]:
        """Load only the messages one session owns, in deterministic creation order."""

        self._refresh_message_index()
        selected: list[tuple[CoordinationMessage, Path]] = []
        for message_id in sorted(self._record_ids(index_root / self._index_key(session_id))):
            path = self.messages_dir / f"{message_id}.json"
            if not path.is_file():
                # The canonical record set is authoritative and the index is
                # derived: a quarantined record leaves an orphan marker, and
                # dropping that empty marker discards no content.
                self._drop_orphan_marker(index_root / self._index_key(session_id) / message_id)
                continue
            selected.append((self._read_message_path(path), path))
        return sorted(selected, key=lambda item: (item[0].created_at, item[0].message_id))

    def _drop_orphan_marker(self, path: Path) -> None:
        """Remove one derived marker whose canonical record no longer exists."""

        try:
            path.unlink()
        except FileNotFoundError:
            return

    def _messages_for_recipient(self, session_id: str) -> list[tuple[CoordinationMessage, Path]]:
        """Return every message addressed to one exact recipient session."""

        return self._indexed_messages(self.index_messages_by_recipient_dir, session_id)

    def _messages_for_sender(self, session_id: str) -> list[tuple[CoordinationMessage, Path]]:
        """Return every message sent by one exact session."""

        return self._indexed_messages(self.index_messages_by_sender_dir, session_id)

    def _live_claims(self, project: str | None = None) -> list[coordination_claims.ClaimRecord]:
        """Read canonical live identity records without introducing another registry."""
        check_claims = cast(
            "Callable[..., list[coordination_claims.ClaimRecord]]",
            coordination_claims.check_claims,
        )
        parameters = inspect.signature(check_claims).parameters
        if "claims_dir" in parameters:
            return check_claims(project, claims_dir=self.claims_dir)
        canonical_claims_dir = Path(coordination_claims.CLAIMS_DIR).expanduser().resolve()
        if self.claims_dir != canonical_claims_dir:
            raise CoordinationMessageError(
                "Installed claim registry cannot read a custom claims directory; "
                "upgrade enforced_planning.coordination_claims before overriding claims_dir"
            )
        return check_claims(project)

    def _require_live_session(self, session_id: str) -> None:
        """Fail when a caller or exact recipient is absent from live claims."""

        if not any(claim.session_id == session_id for claim in self._live_claims()):
            raise UnknownSessionError(f"No live claim owns session {session_id!r}")

    def _reachable_recipient_claims(
        self, project: str | None = None, *, now: datetime | None = None
    ) -> list[coordination_claims.ClaimRecord]:
        """Live claims plus recently-ended ones, for RECIPIENT resolution only.

        A claim's ``session_ended`` status means the runtime session stopped
        heartbeating that specific lane -- not that the process is gone. The
        friction this closes (2026-07-16, cluster coordination-mailbox-session-
        resolution): "the mailbox rejected a message to the registry's active
        Plan 136 session... the active owner cannot be notified through the
        prescribed channel" -- a sender could not reach a recipient whose claim
        had just ended, exactly when a handoff notice was most needed.

        Deliberately narrower than a general relaxation: caller authorization
        (``_require_live_session``, used by send/poll/acknowledge) is untouched
        and still requires a genuinely live claim or the existing native-identity
        bypass. This module's own docstring states claims "cannot restore write
        authority" for a session past its claim -- recipient reachability for a
        message is a different, lower-stakes question than write authority, and
        this method is invoked only from resolve_recipient, never from a write
        or caller-identity path.

        Bounded by DEFAULT_TTL_HOURS (24h, the same claim-lifetime constant used
        throughout coordination_claims.py) measured from the claim's own
        ``updated_at`` -- a session_ended claim from weeks ago almost certainly
        has no live process behind it anymore.
        """
        list_claims = cast(
            "Callable[..., list[coordination_claims.ClaimRecord]]",
            coordination_claims.list_claims,
        )
        parameters = inspect.signature(list_claims).parameters
        kwargs: dict[str, Any] = {"include_inactive": True}
        if "claims_dir" in parameters:
            kwargs["claims_dir"] = self.claims_dir
        else:
            canonical_claims_dir = Path(coordination_claims.CLAIMS_DIR).expanduser().resolve()
            if self.claims_dir != canonical_claims_dir:
                raise CoordinationMessageError(
                    "Installed claim registry cannot read a custom claims directory; "
                    "upgrade enforced_planning.coordination_claims before overriding claims_dir"
                )
        all_claims = list_claims(project, **kwargs)
        now = now or _utc_now()
        cutoff = timedelta(hours=coordination_claims.DEFAULT_TTL_HOURS)
        reachable = []
        for claim in all_claims:
            if claim.is_live():
                reachable.append(claim)
                continue
            if claim.status != "session_ended" or not claim.updated_at:
                continue
            try:
                updated = datetime.fromisoformat(claim.updated_at.replace("Z", "+00:00"))
            except ValueError:
                continue
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=UTC)
            if now - updated <= cutoff:
                reachable.append(claim)
        return reachable

    def resolve_recipient(self, selector: RecipientSelector, *, now: datetime | None = None) -> str:
        """Resolve an exact or claim-backed selector to one canonical session.

        Reachability (not write authority) also admits a claim that ended
        within the last DEFAULT_TTL_HOURS -- see _reachable_recipient_claims.
        """

        if isinstance(selector, ExactSessionSelector):
            if not any(
                claim.session_id == selector.session_id
                for claim in self._reachable_recipient_claims(now=now)
            ):
                raise UnknownSessionError(f"No live claim owns session {selector.session_id!r}")
            return selector.session_id
        claims = self._reachable_recipient_claims(selector.project, now=now)
        if selector.scope is not None:
            claims = [claim for claim in claims if claim.scope == selector.scope]
        sessions = sorted({claim.session_id for claim in claims if claim.session_id})
        if not sessions:
            raise UnknownSessionError(
                f"No live recipient session matches project={selector.project!r}, scope={selector.scope!r}"
            )
        if len(sessions) > 1:
            raise AmbiguousRecipientError(
                f"Recipient selector matched {len(sessions)} sessions: {', '.join(sessions)}"
            )
        return sessions[0]

    def _quarantine(self, path: Path, reason: str) -> NoReturn:
        """Move one corrupt record out of the canonical scan path and retain its evidence."""

        self.quarantine_dir.mkdir(parents=True, exist_ok=True)
        suffix = f".{_utc_now().strftime('%Y%m%dT%H%M%S%fZ')}.{uuid.uuid4().hex[:8]}.corrupt"
        destination = self.quarantine_dir / f"{path.name}{suffix}"
        try:
            os.replace(path, destination)
            _fsync_directory(self.quarantine_dir)
            if path.parent != self.quarantine_dir:
                _fsync_directory(path.parent)
        except OSError as exc:
            raise CorruptRecordError(f"Corrupt record {path} could not be quarantined: {reason}; {exc}") from exc
        raise CorruptRecordError(f"Quarantined corrupt record {path} at {destination}: {reason}")

    def _read_message_path(self, path: Path) -> CoordinationMessage:
        """Validate one message record, quarantining malformed or digest-invalid content."""

        try:
            record = StoredMessageRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            return self._quarantine(path, str(exc))
        return record.payload

    def _read_receipt_path(self, path: Path) -> MessageReceipt:
        """Validate one receipt record, quarantining malformed or digest-invalid content."""

        try:
            record = StoredReceiptRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            return self._quarantine(path, str(exc))
        return record.payload

    def _read_delivery_path(self, path: Path) -> DeliveryEventRecord:
        """Validate one marker before treating an event as already delivered."""

        try:
            record = StoredDeliveryEventRecord.model_validate_json(path.read_bytes())
        except (OSError, ValidationError, ValueError) as exc:
            return self._quarantine(path, str(exc))
        return record.payload

    def _write_immutable(self, path: Path, payload: bytes) -> bool:
        """Atomically publish immutable bytes without overwriting an existing identifier."""

        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile("wb", dir=path.parent, delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.link(temp_path, path)
            except FileExistsError:
                return False
            _fsync_directory(path.parent)
            return True
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def _store_message(self, message: CoordinationMessage) -> tuple[Path, bool]:
        """Persist one integrity-wrapped message or verify an idempotent replay."""

        path = self.messages_dir / f"{message.message_id}.json"
        record = StoredMessageRecord(
            record_type="coordination_message",
            payload=message,
            payload_sha256=_model_digest(message),
        )
        encoded = _canonical_json(record.model_dump(mode="json")) + b"\n"
        if self._write_immutable(path, encoded):
            self._index_message(message)
            return path, False
        existing = self._read_message_path(path)
        if existing.request_sha256 != message.request_sha256:
            raise RecordCollisionError(f"Message ID {message.message_id} already contains different content")
        self._index_message(existing)
        return path, True

    def _store_receipt(self, receipt: MessageReceipt) -> tuple[Path, bool]:
        """Append one integrity-wrapped receipt or verify an idempotent replay."""

        path = self.receipts_dir / f"{receipt.receipt_id}.json"
        record = StoredReceiptRecord(
            record_type="message_receipt",
            payload=receipt,
            payload_sha256=_model_digest(receipt),
        )
        encoded = _canonical_json(record.model_dump(mode="json")) + b"\n"
        if self._write_immutable(path, encoded):
            self._index_receipt(receipt)
            return path, False
        existing = self._read_receipt_path(path)
        comparable_existing = existing.model_copy(update={"recorded_at": receipt.recorded_at})
        if comparable_existing != receipt:
            raise RecordCollisionError(f"Receipt ID {receipt.receipt_id} already contains different content")
        self._index_receipt(existing)
        return path, True

    def _claim_event_delivery(
        self,
        message: CoordinationMessage,
        *,
        display_session_id: str | None = None,
        delivery_event_id: str,
        now: datetime,
    ) -> bool:
        """Atomically reserve one agent-visible delivery for a native event.

        This marker is intentionally weaker than an observation receipt: it
        proves only that one adapter won the right to render the message for
        this exact event. It never acknowledges work and a different event ID
        may display the still-unacknowledged message again.
        """

        display_session = display_session_id or message.recipient_session_id
        delivery_id = _stable_id("delivery", message.message_id, display_session, delivery_event_id)
        marker = DeliveryEventRecord(
            schema_version=SCHEMA_VERSION,
            delivery_id=delivery_id,
            delivery_event_id=delivery_event_id,
            message_id=message.message_id,
            recipient_session_id=display_session,
            recorded_at=now,
        )
        path = self.deliveries_dir / f"{delivery_id}.json"
        record = StoredDeliveryEventRecord(
            record_type="mailbox_delivery_event",
            payload=marker,
            payload_sha256=_model_digest(marker),
        )
        encoded = _canonical_json(record.model_dump(mode="json")) + b"\n"
        if self._write_immutable(path, encoded):
            return True
        existing = self._read_delivery_path(path)
        comparable_existing = existing.model_copy(update={"recorded_at": marker.recorded_at})
        if comparable_existing != marker:
            raise RecordCollisionError(f"Delivery marker {delivery_id} already contains different content")
        return False

    def poll_sender_acknowledgements(
        self,
        *,
        current_session_id: str,
        project: str | None = None,
        consume: bool = True,
        limit: int = DEFAULT_NOTICE_MESSAGE_LIMIT,
        now: datetime | None = None,
    ) -> tuple[MessageStatusView, ...]:
        """Return acknowledgements not yet surfaced to the exact sender session.

        A sender notification is a derived view over the canonical acknowledgement
        receipt.  Consuming it writes only an immutable delivery marker, so it
        cannot create a reply message or an acknowledgement loop.
        """

        if limit < 1:
            raise ValueError("limit must be positive")
        recorded_at = now or _utc_now()
        pending: list[MessageStatusView] = []
        for message, _path in self._messages_for_sender(current_session_id):
            if project is not None and message.project != project:
                continue
            status = self.status(MessageStatusRequest(message_id=message.message_id, as_of=recorded_at))
            acknowledgements = [receipt for receipt in status.receipts if receipt.event == "acknowledged"]
            if not acknowledgements:
                continue
            acknowledgement = acknowledgements[-1]
            delivery_event_id = f"acknowledgement:{acknowledgement.receipt_id}"
            if consume:
                claimed = self._claim_event_delivery(
                    message,
                    display_session_id=current_session_id,
                    delivery_event_id=delivery_event_id,
                    now=recorded_at,
                )
                if not claimed:
                    continue
            else:
                delivery_id = _stable_id("delivery", message.message_id, current_session_id, delivery_event_id)
                marker_path = self.deliveries_dir / f"{delivery_id}.json"
                if marker_path.is_file():
                    self._read_delivery_path(marker_path)
                    continue
            pending.append(status)
            if len(pending) >= limit:
                break
        return tuple(pending)

    def _message(self, message_id: str) -> tuple[CoordinationMessage, Path]:
        """Load one canonical message or fail when it is absent."""

        path = self.messages_dir / f"{message_id}.json"
        if not path.is_file():
            raise MessageNotFoundError(f"Message {message_id} does not exist")
        return self._read_message_path(path), path

    def _all_messages(self) -> list[tuple[CoordinationMessage, Path]]:
        """Load every canonical message in deterministic creation order."""

        if not self.messages_dir.exists():
            return []
        messages = [(self._read_message_path(path), path) for path in sorted(self.messages_dir.glob("*.json"))]
        return sorted(messages, key=lambda item: (item[0].created_at, item[0].message_id))

    def _receipts_for(self, message_id: str) -> list[MessageReceipt]:
        """Load and order only the receipts recorded against one message.

        ``status`` is called once per polled message, so reading and validating
        every receipt in the store here made one inbox poll cost
        ``messages x receipts``.  The derived index keeps the cost proportional
        to the receipts of the requested message.
        """

        if not self.receipts_dir.exists():
            return []
        self._refresh_receipt_index()
        message_index = self.index_receipts_by_message_dir / message_id
        matching: list[MessageReceipt] = []
        for receipt_id in sorted(self._record_ids(message_index)):
            path = self.receipts_dir / f"{receipt_id}.json"
            if not path.is_file():
                self._drop_orphan_marker(message_index / receipt_id)
                continue
            matching.append(self._read_receipt_path(path))
        return sorted(matching, key=lambda receipt: (receipt.recorded_at, receipt.receipt_id))

    def assess_recipient_reachability(
        self,
        recipient_session_id: str,
        *,
        now: datetime,
        before: datetime | None = None,
    ) -> tuple[int, float | None]:
        """Count active messages the recipient has never once observed.

        A message is stored durably whether or not its recipient can read it.
        A session running without the mailbox hook accumulates never-observed
        messages while every send reports success, so an existing backlog is
        the cheapest evidence that the next send will not be read either.
        """

        cutoff = before or now
        backlog = 0
        oldest: datetime | None = None
        for message, _path in self._messages_for_recipient(recipient_session_id):
            if message.created_at >= cutoff or message.expires_at <= now:
                continue
            if any(
                receipt.event in {"observed", "acknowledged"}
                for receipt in self._receipts_for(message.message_id)
            ):
                continue
            backlog += 1
            if oldest is None or message.created_at < oldest:
                oldest = message.created_at
        age = (now - oldest).total_seconds() if oldest is not None else None
        return backlog, age

    def send(
        self,
        request: SendMessageRequest,
        *,
        now: datetime | None = None,
        require_live_claim: bool = True,
    ) -> PersistedMessageResultV2:
        """Resolve identities and persist one immutable coordination message.

        Native client adapters may set ``require_live_claim=False`` only after
        verifying that their current client session exactly matches the caller
        and sender IDs. Recipient routing remains claim-backed.
        """

        if request.caller_session_id != request.sender_session_id:
            raise IdentityMismatchError(
                f"Caller {request.caller_session_id!r} cannot assert sender {request.sender_session_id!r}"
            )
        if require_live_claim:
            self._require_live_session(request.caller_session_id)
        semantic_request = request.model_dump(mode="json", exclude={"idempotency_key"})
        request_sha256 = hashlib.sha256(_canonical_json(semantic_request)).hexdigest()
        if request.idempotency_key is None:
            message_id = f"msg_{uuid.uuid4().hex}"
        else:
            message_id = _stable_id("msg", request.sender_session_id, request.idempotency_key)
            existing_path = self.messages_dir / f"{message_id}.json"
            if existing_path.is_file():
                existing = self._read_message_path(existing_path)
                if existing.request_sha256 != request_sha256:
                    raise RecordCollisionError(f"Message ID {message_id} already contains different content")
                backlog, age = self.assess_recipient_reachability(
                    existing.recipient_session_id,
                    now=now or _utc_now(),
                    before=existing.created_at,
                )
                return PersistedMessageResultV2(
                    message=existing,
                    message_path=str(existing_path),
                    idempotent_replay=True,
                    recipient_unobserved_backlog=backlog,
                    recipient_oldest_unobserved_seconds=age,
                    recipient_may_be_unreachable=_looks_unreachable(backlog, age),
                    local_host_delivery_capability=inspect_host_delivery_capability(
                        existing.recipient_session_id
                    ),
                )
        created_at = now or _utc_now()
        if created_at.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        recipient_session_id = self.resolve_recipient(request.recipient, now=created_at)
        message = CoordinationMessage(
            schema_version=SCHEMA_VERSION,
            message_id=message_id,
            sender_session_id=request.sender_session_id,
            recipient_selector=request.recipient,
            recipient_session_id=recipient_session_id,
            project=request.project,
            kind=request.kind,
            subject=request.subject,
            body=request.body,
            content_ref=request.content_ref,
            created_at=created_at,
            expires_at=created_at + timedelta(seconds=request.ttl_seconds),
            request_sha256=request_sha256,
            plan_ref=request.plan_ref,
            claim_ref=request.claim_ref,
            reply_to_message_id=request.reply_to_message_id,
        )
        backlog, age = self.assess_recipient_reachability(
            recipient_session_id, now=created_at, before=created_at
        )
        path, idempotent = self._store_message(message)
        if idempotent:
            message = self._read_message_path(path)
        return PersistedMessageResultV2(
            message=message,
            message_path=str(path),
            idempotent_replay=idempotent,
            recipient_unobserved_backlog=backlog,
            recipient_oldest_unobserved_seconds=age,
            recipient_may_be_unreachable=_looks_unreachable(backlog, age),
            local_host_delivery_capability=inspect_host_delivery_capability(recipient_session_id),
        )

    def _append_observation(self, message: CoordinationMessage, *, now: datetime) -> tuple[MessageReceipt, Path]:
        """Append or reuse one observation receipt for the exact recipient."""

        receipt = MessageReceipt(
            schema_version=SCHEMA_VERSION,
            receipt_id=_stable_id("rcpt", message.message_id, message.recipient_session_id, "observed"),
            message_id=message.message_id,
            recipient_session_id=message.recipient_session_id,
            event="observed",
            recorded_at=now,
        )
        path, idempotent = self._store_receipt(receipt)
        return (self._read_receipt_path(path) if idempotent else receipt), path

    def record_boundary_block(
        self,
        *,
        current_session_id: str,
        message_ids: tuple[str, ...],
        hook_event_name: Literal["PreToolUse", "Stop"],
        delivery_event_id: str,
        tool_name: str | None = None,
        now: datetime | None = None,
    ) -> tuple[BoundaryBlockRecord, ...]:
        """Append idempotent evidence that active mailbox debt denied a boundary."""

        recorded_at = now or _utc_now()
        records: list[BoundaryBlockRecord] = []
        for message_id in message_ids:
            message, _path = self._message(message_id)
            if message.recipient_session_id != current_session_id:
                raise WrongRecipientError(
                    f"Session {current_session_id!r} cannot record a boundary for {message.recipient_session_id!r}"
                )
            status = self.status(MessageStatusRequest(message_id=message_id, as_of=recorded_at))
            if status.expired or status.acknowledged:
                continue
            boundary = BoundaryBlockRecord(
                schema_version=SCHEMA_VERSION,
                boundary_id=_stable_id(
                    "boundary",
                    message_id,
                    current_session_id,
                    hook_event_name,
                    delivery_event_id,
                ),
                message_id=message_id,
                recipient_session_id=current_session_id,
                hook_event_name=hook_event_name,
                delivery_event_id=delivery_event_id,
                tool_name=tool_name,
                recorded_at=recorded_at,
            )
            path = self.boundary_blocks_dir / f"{boundary.boundary_id}.json"
            stored = StoredBoundaryBlockRecord(
                record_type="mailbox_boundary_block",
                payload=boundary,
                payload_sha256=_model_digest(boundary),
            )
            encoded = _canonical_json(stored.model_dump(mode="json")) + b"\n"
            if not self._write_immutable(path, encoded):
                existing = StoredBoundaryBlockRecord.model_validate_json(path.read_bytes()).payload
                comparable_existing = existing.model_copy(update={"recorded_at": recorded_at})
                if comparable_existing != boundary:
                    raise RecordCollisionError(
                        f"Boundary record {boundary.boundary_id} already contains different content"
                    )
                boundary = existing
            records.append(boundary)
        return tuple(records)

    def boundary_blocks(self, message_id: str) -> tuple[BoundaryBlockRecord, ...]:
        """Return validated boundary-denial evidence for one message in time order."""

        if not self.boundary_blocks_dir.exists():
            return ()
        records: list[BoundaryBlockRecord] = []
        for path in sorted(self.boundary_blocks_dir.glob("*.json")):
            try:
                record = StoredBoundaryBlockRecord.model_validate_json(path.read_bytes()).payload
            except (OSError, ValidationError, ValueError) as exc:
                self._quarantine(path, str(exc))
            if record.message_id == message_id:
                records.append(record)
        return tuple(sorted(records, key=lambda item: (item.recorded_at, item.boundary_id)))

    def status(self, request: MessageStatusRequest) -> MessageStatusView:
        """Derive lifecycle state from one immutable message and exact receipt set."""

        message, path = self._message(request.message_id)
        receipts = self._receipts_for(message.message_id)
        as_of = request.as_of or _utc_now()
        relevant = [receipt for receipt in receipts if receipt.recorded_at <= as_of]
        runtime_accepted = any(receipt.event == "runtime_accepted" for receipt in relevant)
        acknowledgements = [receipt for receipt in relevant if receipt.event == "acknowledged"]
        observed = bool(acknowledgements) or any(receipt.event == "observed" for receipt in relevant)
        acknowledged = bool(acknowledgements)
        expired = as_of >= message.expires_at and not any(
            receipt.recorded_at <= message.expires_at for receipt in acknowledgements
        )
        state: MessageState
        if expired:
            state = "expired"
        elif acknowledged:
            state = "acknowledged"
        elif observed:
            state = "observed"
        elif runtime_accepted:
            state = "runtime_accepted"
        else:
            state = "persisted"
        return MessageStatusView(
            message=message,
            state=state,
            runtime_accepted=runtime_accepted,
            observed=observed,
            acknowledged=acknowledged,
            expired=expired,
            receipts=tuple(relevant),
            receipt_paths=tuple(str(self.receipts_dir / f"{receipt.receipt_id}.json") for receipt in relevant),
            receipt_set_sha256=_receipt_set_digest(relevant),
            message_path=str(path),
        )

    def poll(
        self,
        request: PollMessagesRequest,
        *,
        now: datetime | None = None,
        require_live_claim: bool = True,
        max_messages: int | None = None,
        active_only: bool = False,
    ) -> MessagePollResult:
        """Read one session inbox and optionally append observation receipts.

        ``require_live_claim=False`` is reserved for a native client lifecycle
        adapter that receives the current session ID from the client itself.
        Write claims remain mandatory for message routing and sender identity;
        completing a write claim must not make the still-running client's
        read-only inbox unavailable.
        """

        if require_live_claim:
            self._require_live_session(request.current_session_id)
        as_of = request.as_of or now or _utc_now()
        if as_of.tzinfo is None:
            raise ValueError("as_of must be timezone-aware")
        if max_messages is not None and max_messages < 1:
            raise ValueError("max_messages must be positive")
        selected = [
            message
            for message, _path in self._messages_for_recipient(request.current_session_id)
            if request.project is None or message.project == request.project
        ]
        eligible: list[CoordinationMessage] = []
        for message in selected:
            before = self.status(MessageStatusRequest(message_id=message.message_id, as_of=as_of))
            if before.expired and not request.include_expired:
                continue
            if active_only and before.acknowledged:
                continue
            eligible.append(message)
        if max_messages is not None:
            eligible = eligible[:max_messages]

        observations: list[MessageReceipt] = []
        observation_paths: list[str] = []
        views: list[MessageStatusView] = []
        suppressed_message_ids: list[str] = []
        for message in eligible:
            before = self.status(MessageStatusRequest(message_id=message.message_id, as_of=as_of))
            if (
                request.delivery_event_id is not None
                and not before.acknowledged
                and not self._claim_event_delivery(
                    message,
                    delivery_event_id=request.delivery_event_id,
                    now=as_of,
                )
            ):
                suppressed_message_ids.append(message.message_id)
                continue
            if request.observe and not before.expired and not before.observed:
                observation, observation_path = self._append_observation(message, now=as_of)
                observations.append(observation)
                observation_paths.append(str(observation_path))
            views.append(self.status(MessageStatusRequest(message_id=message.message_id, as_of=as_of)))
        return MessagePollResult(
            current_session_id=request.current_session_id,
            messages=tuple(views),
            observation_receipts=tuple(observations),
            observation_receipt_paths=tuple(observation_paths),
            delivery_event_id=request.delivery_event_id,
            suppressed_message_ids=tuple(suppressed_message_ids),
        )

    def acknowledge(
        self,
        request: AcknowledgeMessageRequest,
        *,
        now: datetime | None = None,
        require_live_claim: bool = True,
    ) -> AcknowledgementResult:
        """Append one recipient acknowledgement without mutating message state.

        A native client adapter may bypass claim liveness after proving the
        current client session exactly matches ``current_session_id``.
        """

        if require_live_claim:
            self._require_live_session(request.current_session_id)
        message, _path = self._message(request.message_id)
        if message.recipient_session_id != request.current_session_id:
            raise WrongRecipientError(
                f"Session {request.current_session_id!r} is not recipient {message.recipient_session_id!r}"
            )
        recorded_at = now or _utc_now()
        receipt = MessageReceipt(
            schema_version=SCHEMA_VERSION,
            receipt_id=_stable_id("rcpt", message.message_id, request.current_session_id, "acknowledged"),
            message_id=message.message_id,
            recipient_session_id=request.current_session_id,
            event="acknowledged",
            recorded_at=recorded_at,
            disposition=request.disposition,
            response_ref=request.response_ref,
            note=request.note,
        )
        path, idempotent = self._store_receipt(receipt)
        if idempotent:
            receipt = self._read_receipt_path(path)
        status = self.status(MessageStatusRequest(message_id=message.message_id, as_of=recorded_at))
        return AcknowledgementResult(
            receipt=receipt,
            receipt_path=str(path),
            status=status,
            idempotent_replay=idempotent,
            acknowledgement_latency_seconds=max(
                0.0,
                (receipt.recorded_at - message.created_at).total_seconds(),
            ),
        )


def default_message_root(claims_dir: Path | None = None) -> Path:
    """Derive the mailbox authority beside the configured canonical claims directory."""

    return (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve().parent / "messages-v1"


def poll_session_inbox(
    *,
    agent: str,
    project: str | None,
    session_id: str | None = None,
    observe: bool = True,
    claims_dir: Path | None = None,
    root: Path | None = None,
    max_body_chars: int = DEFAULT_NOTICE_BODY_LENGTH,
    max_messages: int = DEFAULT_NOTICE_MESSAGE_LIMIT,
    delivery_event_id: str | None = None,
    require_live_claim: bool = True,
) -> SessionInboxNotice:
    """Resolve one native session and return an agent-visible mailbox notice.

    Native lifecycle adapters may set ``require_live_claim=False`` because the
    client event supplies the exact current session identity. They may also omit
    ``project`` when a workspace-level current directory has no repository
    context; the exact native session identity still confines the poll to that
    session's inbox, including messages retained after a claim closes.
    Observation evidence still means the notice reached an agent-facing command
    result, not merely that a background process scanned storage.
    """

    if max_body_chars < 1 or max_messages < 1:
        raise ValueError("max_body_chars and max_messages must be positive")
    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise UnknownSessionError(
            f"Unable to resolve a canonical session ID for agent {agent!r}; "
            "pass session_id or run from a supported client runtime"
        )
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    store = CoordinationMessageStore(
        root=root or default_message_root(resolved_claims_dir),
        claims_dir=resolved_claims_dir,
    )
    result = store.poll(
        PollMessagesRequest(
            current_session_id=resolved_session_id,
            project=project,
            observe=observe,
            delivery_event_id=delivery_event_id,
        ),
        require_live_claim=require_live_claim,
        max_messages=max_messages,
        active_only=True,
    )
    active = tuple(
        view for view in result.messages if not view.expired and not view.acknowledged
    )
    all_visible = store.poll(
        PollMessagesRequest(
            current_session_id=resolved_session_id,
            project=project,
            observe=False,
        ),
        require_live_claim=require_live_claim,
    )
    all_active = tuple(
        view for view in all_visible.messages if not view.expired and not view.acknowledged
    )
    acknowledgements = store.poll_sender_acknowledgements(
        current_session_id=resolved_session_id,
        project=project,
        consume=observe,
        limit=max_messages,
    )
    summary_parts: list[str] = []
    acknowledgement_script = Path(__file__).resolve().parents[1] / "scripts" / "coordination_messages.py"
    if active:
        displayed = active
        rendered_messages: list[str] = []
        acknowledgement_commands: list[str] = []
        for view in displayed:
            content = view.message.body or f"content_ref={view.message.content_ref}"
            compact_content = " ".join(content.split())
            if len(compact_content) > max_body_chars:
                compact_content = compact_content[: max_body_chars - 1] + "…"
            rendered_messages.append(
                f"{view.message.message_id} [{view.message.kind}] "
                f"{view.message.subject}: {compact_content}"
            )
            acknowledgement_request = json.dumps(
                {
                    "current_session_id": resolved_session_id,
                    "message_id": view.message.message_id,
                    "disposition": "<accepted|declined|deferred|information_only>",
                    "note": "<what you did, why you deferred, or why no action is needed>",
                },
                separators=(",", ":"),
            )
            acknowledgement_commands.append(
                f"/usr/bin/python3 {acknowledgement_script} acknowledge "
                f"--request-json {shlex.quote(acknowledgement_request)}"
            )
        details = "; ".join(rendered_messages)
        remainder = max(0, len(all_active) - len(displayed))
        suffix = f"; {remainder} more not shown" if remainder else ""
        summary_parts.extend(
            (
                (
                    "ACKNOWLEDGEMENT REQUIRED. DO NOT pass the next natural work "
                    "boundary until every displayed message has a truthful durable "
                    "disposition"
                ),
                f"{len(all_active)} active message(s): {details}{suffix}",
                "Acknowledge each displayed message by replacing the disposition "
                "and note placeholders in its command: "
                + " ; ".join(acknowledgement_commands),
                "This notice will repeat until acknowledgement is recorded.",
            )
        )
    else:
        summary_parts.append("no active messages")
    if acknowledgements:
        rendered_acknowledgements: list[str] = []
        for view in acknowledgements:
            acknowledgement = next(
                receipt for receipt in reversed(view.receipts) if receipt.event == "acknowledged"
            )
            detail = acknowledgement.note or acknowledgement.response_ref or "no note"
            compact_detail = " ".join(detail.split())
            if len(compact_detail) > max_body_chars:
                compact_detail = compact_detail[: max_body_chars - 1] + "…"
            rendered_acknowledgements.append(
                f"{view.message.message_id} [{acknowledgement.disposition}]: {compact_detail}"
            )
        summary_parts.append(
            f"{len(acknowledgements)} new acknowledgement(s): "
            + "; ".join(rendered_acknowledgements)
        )
    summary = "coordination mailbox: " + "; ".join(summary_parts)
    return SessionInboxNotice(
        session_id=resolved_session_id,
        project=project,
        active_count=len(all_active) if active else 0,
        message_ids=tuple(view.message.message_id for view in active),
        acknowledgement_count=len(acknowledgements),
        acknowledgement_message_ids=tuple(view.message.message_id for view in acknowledgements),
        summary=summary,
    )


def _request_json(raw: str) -> str:
    """Read a request from an inline JSON string or stdin marker."""

    return sys.stdin.read() if raw == "-" else raw


def _is_current_native_session(session_id: str) -> bool:
    """Return whether ambient client identity exactly matches one canonical ID."""

    return any(
        coordination_claims.resolve_session_id(agent) == session_id
        for agent in coordination_claims.SESSION_ENV_KEYS
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the agent-drivable JSON request CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="Override canonical mailbox root.")
    parser.add_argument("--claims-dir", type=Path, help="Override canonical claims registry.")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for operation in ("send", "poll", "status", "acknowledge"):
        command = subparsers.add_parser(operation)
        command.add_argument(
            "--request-json",
            default="-",
            help="Strict request JSON, or '-' to read one object from stdin.",
        )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Execute one typed mailbox operation and print a strict JSON result."""

    args = build_parser().parse_args(argv)
    claims_dir = (args.claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    store = CoordinationMessageStore(root=args.root or default_message_root(claims_dir), claims_dir=claims_dir)
    raw = _request_json(args.request_json)
    try:
        if args.operation == "send":
            send_request = SendMessageRequest.model_validate_json(raw)
            result: BaseModel = store.send(
                send_request,
                require_live_claim=not _is_current_native_session(send_request.caller_session_id),
            )
        elif args.operation == "poll":
            poll_request = PollMessagesRequest.model_validate_json(raw)
            result = store.poll(
                poll_request,
                require_live_claim=not _is_current_native_session(poll_request.current_session_id),
            )
        elif args.operation == "status":
            result = store.status(MessageStatusRequest.model_validate_json(raw))
        else:
            acknowledge_request = AcknowledgeMessageRequest.model_validate_json(raw)
            result = store.acknowledge(
                acknowledge_request,
                require_live_claim=not _is_current_native_session(
                    acknowledge_request.current_session_id
                ),
            )
    except (ValidationError, CoordinationMessageError, ValueError) as exc:
        print(json.dumps({"ok": False, "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True))
        return 2
    if isinstance(result, PersistedMessageResultV2) and result.recipient_may_be_unreachable:
        age_minutes = int((result.recipient_oldest_unobserved_seconds or 0) // 60)
        print(
            "WARNING: this message is stored but probably will not be read. "
            f"{result.message.recipient_session_id} has {result.recipient_unobserved_backlog} earlier "
            f"message(s) it has never once observed, the oldest sent {age_minutes} minute(s) ago. "
            "A session running without the mailbox hook loaded accumulates exactly this backlog while "
            "every send still reports success. Check "
            "scripts/verify_mailbox_hook_activation.py before waiting on a reply.",
            file=sys.stderr,
        )
    if (
        isinstance(result, PersistedMessageResultV2)
        and result.local_host_delivery_capability.delivery_mode != "enforced"
    ):
        print(
            f"WARNING: {result.local_host_delivery_capability.operator_message}",
            file=sys.stderr,
        )
    print(result.model_dump_json(indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
