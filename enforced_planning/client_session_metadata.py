"""Read-only client display metadata and truthful mailbox response projections."""

from __future__ import annotations

import json
import shlex
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from enforced_planning import coordination_claims, coordination_messages

DEFAULT_CODEX_SESSION_INDEX = Path.home() / ".codex" / "session_index.jsonl"
DEFAULT_CLAUDE_SESSION_REGISTRY = Path.home() / ".claude" / "sessions"


class StrictProjection(BaseModel):
    """Strict immutable base for local operator projections."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ClientSessionDisplayV1(StrictProjection):
    """Mutable client display metadata kept separate from routing identity."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    session_id: str = Field(min_length=1)
    client: Literal["codex", "claude-code", "openclaw", "unknown"]
    state: Literal["resolved", "not_found", "source_unavailable", "not_supported"]
    display_name: str | None = None
    source: str | None = None
    client_updated_at: str | None = None
    warnings: tuple[str, ...] = ()


class CoordinationResponseReadoutV1(StrictProjection):
    """Legacy joined operator view retained for strict consumer compatibility."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    message_id: str
    recipient_session_id: str
    client_display: ClientSessionDisplayV1
    internal_session_names: tuple[str, ...]
    active_claim_scopes: tuple[str, ...]
    retained_claim_scopes: tuple[str, ...]
    message_state: coordination_messages.MessageState
    response_state: Literal[
        "persisted_not_displayed",
        "runtime_accepted_not_displayed",
        "displayed_awaiting_acknowledgement",
        "recipient_acknowledged",
        "expired_unresolved",
    ]
    acknowledgement_disposition: str | None = None
    acknowledgement_note: str | None = None
    response_ref: str | None = None
    manual_resume_command: str | None = None
    completion_claim: Literal["not_evaluated"] = "not_evaluated"


class CoordinationResponseReadoutV2(CoordinationResponseReadoutV1):
    """Versioned operator view with explicit host delivery capability."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    operator_host_delivery_capability: coordination_messages.HostDeliveryCapabilityV1


ResponseState = Literal[
    "persisted_not_displayed",
    "runtime_accepted_not_displayed",
    "displayed_awaiting_acknowledgement",
    "recipient_acknowledged",
    "expired_unresolved",
]


def _portable_path(path: Path) -> str:
    """Render a home-relative path without persisting a personal home prefix."""

    resolved = path.expanduser()
    try:
        return f"~/{resolved.relative_to(Path.home()).as_posix()}"
    except ValueError:
        return str(resolved)


def _client_name(session_id: str) -> Literal["codex", "claude-code", "openclaw", "unknown"]:
    """Classify one canonical session ID without inventing client metadata."""

    prefix = session_id.partition(":")[0]
    if prefix in {"codex", "claude-code", "openclaw"}:
        return prefix  # type: ignore[return-value]
    return "unknown"


def _resolve_claude_code_display(
    session_id: str,
    *,
    claude_session_registry: Path,
) -> ClientSessionDisplayV1:
    """Resolve one Claude Code session's addressable peer name from its registry.

    Claude Code writes one JSON record per live session under
    ``~/.claude/sessions/<pid>.json``. Its ``name`` is the identity peers use to
    address it with the native ``SendMessage`` tool, so resolving it here is what
    turns a claim's canonical ``session_id`` into something a live agent can
    actually talk to. Routing identity is unchanged; this is display metadata.
    """

    raw_session_id = session_id.removeprefix("claude-code:")
    source = _portable_path(claude_session_registry)
    registry = claude_session_registry.expanduser()
    if not registry.is_dir():
        return ClientSessionDisplayV1(
            session_id=session_id,
            client="claude-code",
            state="source_unavailable",
            source=source,
        )

    warnings: list[str] = []
    matched: ClientSessionDisplayV1 | None = None
    for record_path in sorted(registry.glob("*.json")):
        try:
            record = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            warnings.append(f"unreadable_record:{record_path.name}")
            continue
        if not isinstance(record, dict) or record.get("sessionId") != raw_session_id:
            continue
        name = record.get("name")
        if not isinstance(name, str) or not name.strip():
            warnings.append(f"matching_record_missing_name:{record_path.name}")
            continue
        if matched is not None:
            warnings.append(f"duplicate_matching_record:{record_path.name}")
            continue
        updated_at = record.get("updatedAt")
        client_updated_at: str | None = None
        if isinstance(updated_at, (int, float)) and not isinstance(updated_at, bool):
            client_updated_at = datetime.fromtimestamp(
                updated_at / 1000, tz=UTC
            ).isoformat()
        elif updated_at is not None:
            warnings.append(f"matching_record_invalid_updated_at:{record_path.name}")
        matched = ClientSessionDisplayV1(
            session_id=session_id,
            client="claude-code",
            state="resolved",
            display_name=name.strip(),
            source=source,
            client_updated_at=client_updated_at,
        )

    # Scan every record before returning: a warning about an unreadable peer
    # record must not depend on whether the match happened to sort first.
    if matched is not None:
        return matched.model_copy(update={"warnings": tuple(warnings)})

    return ClientSessionDisplayV1(
        session_id=session_id,
        client="claude-code",
        state="not_found",
        source=source,
        warnings=tuple(warnings),
    )


def resolve_client_session_display(
    session_id: str,
    *,
    codex_session_index: Path = DEFAULT_CODEX_SESSION_INDEX,
    claude_session_registry: Path = DEFAULT_CLAUDE_SESSION_REGISTRY,
) -> ClientSessionDisplayV1:
    """Resolve optional human-facing metadata without changing canonical identity."""

    client = _client_name(session_id)
    if client == "claude-code":
        return _resolve_claude_code_display(
            session_id,
            claude_session_registry=claude_session_registry,
        )
    if client != "codex":
        return ClientSessionDisplayV1(
            session_id=session_id,
            client=client,
            state="not_supported",
        )
    raw_session_id = session_id.removeprefix("codex:")
    source = _portable_path(codex_session_index)
    if not codex_session_index.expanduser().is_file():
        return ClientSessionDisplayV1(
            session_id=session_id,
            client="codex",
            state="source_unavailable",
            source=source,
        )

    matches: list[tuple[datetime, str, str]] = []
    warnings: list[str] = []
    for line_number, line in enumerate(
        codex_session_index.expanduser().read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            warnings.append(f"invalid_json_line:{line_number}")
            continue
        if not isinstance(record, dict) or record.get("id") != raw_session_id:
            continue
        thread_name = record.get("thread_name")
        updated_at = record.get("updated_at")
        if not isinstance(thread_name, str) or not thread_name.strip():
            warnings.append(f"matching_row_missing_thread_name:{line_number}")
            continue
        if not isinstance(updated_at, str):
            warnings.append(f"matching_row_missing_updated_at:{line_number}")
            continue
        try:
            parsed_updated_at = datetime.fromisoformat(updated_at)
        except ValueError:
            warnings.append(f"matching_row_invalid_updated_at:{line_number}")
            continue
        if parsed_updated_at.tzinfo is None:
            warnings.append(f"matching_row_naive_updated_at:{line_number}")
            continue
        matches.append((parsed_updated_at, thread_name.strip(), updated_at))

    if not matches:
        return ClientSessionDisplayV1(
            session_id=session_id,
            client="codex",
            state="not_found",
            source=source,
            warnings=tuple(warnings),
        )
    _timestamp, thread_name, updated_at = max(matches, key=lambda item: item[0])
    return ClientSessionDisplayV1(
        session_id=session_id,
        client="codex",
        state="resolved",
        display_name=thread_name,
        source=source,
        client_updated_at=updated_at,
        warnings=tuple(warnings),
    )


def build_coordination_response_readout(
    status: coordination_messages.MessageStatusView,
    *,
    claims: list[coordination_claims.ClaimRecord],
    codex_session_index: Path = DEFAULT_CODEX_SESSION_INDEX,
    codex_config_path: Path | None = None,
    claude_config_path: Path | None = None,
) -> CoordinationResponseReadoutV2:
    """Join message lifecycle and display metadata without inferring completion."""

    recipient_session_id = status.message.recipient_session_id
    recipient_claims = [
        claim for claim in claims if claim.session_id == recipient_session_id
    ]
    acknowledgements = [
        receipt for receipt in status.receipts if receipt.event == "acknowledged"
    ]
    acknowledgement = max(acknowledgements, key=lambda item: item.recorded_at) if acknowledgements else None

    response_state: ResponseState
    if status.expired:
        response_state = "expired_unresolved"
    elif status.acknowledged:
        response_state = "recipient_acknowledged"
    elif status.observed:
        response_state = "displayed_awaiting_acknowledgement"
    elif status.runtime_accepted:
        response_state = "runtime_accepted_not_displayed"
    else:
        response_state = "persisted_not_displayed"

    manual_resume_command: str | None = None
    if not status.expired and not status.acknowledged and recipient_session_id.startswith("codex:"):
        raw_session_id = recipient_session_id.removeprefix("codex:")
        prompt = (
            f"Review coordination message {status.message.message_id}, record a truthful "
            "acknowledgement, and continue only within its existing authority and claims."
        )
        manual_resume_command = shlex.join(("codex", "exec", "resume", raw_session_id, prompt))

    return CoordinationResponseReadoutV2(
        message_id=status.message.message_id,
        recipient_session_id=recipient_session_id,
        client_display=resolve_client_session_display(
            recipient_session_id,
            codex_session_index=codex_session_index,
        ),
        internal_session_names=tuple(
            sorted(
                {
                    claim.session_name
                    for claim in recipient_claims
                    if isinstance(claim.session_name, str) and claim.session_name
                }
            )
        ),
        active_claim_scopes=tuple(
            sorted({claim.scope for claim in recipient_claims if claim.is_live()})
        ),
        retained_claim_scopes=tuple(
            sorted({claim.scope for claim in recipient_claims if not claim.is_live()})
        ),
        message_state=status.state,
        operator_host_delivery_capability=coordination_messages.inspect_host_delivery_capability(
            recipient_session_id,
            codex_config_path=codex_config_path,
            claude_config_path=claude_config_path,
            scope="operator_host_recipient_client_config",
        ),
        response_state=response_state,
        acknowledgement_disposition=acknowledgement.disposition if acknowledgement else None,
        acknowledgement_note=acknowledgement.note if acknowledgement else None,
        response_ref=acknowledgement.response_ref if acknowledgement else None,
        manual_resume_command=manual_resume_command,
    )
