"""Typed correction auditing and immutable learning reconciliation.

Semantic classification is supplied by a caller and runs before completion.
The Stop hook consumes only the privacy-reduced :class:`CorrectionAuditReceiptV1`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Reject undeclared fields at every durable boundary."""

    model_config = ConfigDict(extra="forbid")


class TranscriptExchange(StrictModel):
    """One assistant message and the next user-authored message."""

    event_id: str = Field(min_length=1)
    occurred_at: AwareDatetime
    assistant_text: str = Field(min_length=1)
    user_text: str = Field(min_length=1)

    @property
    def event_hash(self) -> str:
        material = (
            f"{self.event_id}\0{self.occurred_at.isoformat()}\0"
            f"{self.assistant_text}\0{self.user_text}"
        )
        return f"corr_{hashlib.sha256(material.encode()).hexdigest()[:32]}"


class CorrectionVerdict(StrictModel):
    """Structured semantic verdict for one exchange."""

    event_id: str = Field(min_length=1)
    classification: Literal["correction", "not_correction", "ambiguous"]
    rationale: str = Field(min_length=1, max_length=240)
    matching_learning_id: str | None = None


class CorrectionClassification(StrictModel):
    """Batch verdict returned by the structured model route."""

    verdicts: list[CorrectionVerdict]

    @model_validator(mode="after")
    def unique_event_ids(self) -> CorrectionClassification:
        ids = [verdict.event_id for verdict in self.verdicts]
        if len(ids) != len(set(ids)):
            raise ValueError("correction verdict event IDs must be unique")
        return self


class CorrectionAuditReceiptV1(StrictModel):
    """Privacy-reduced output consumed by deterministic lifecycle gates."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["correction_learning_audit"] = "correction_learning_audit"
    agent: Literal["codex", "claude-code", "openclaw"]
    session_id: str = Field(min_length=1)
    analyzed_at: AwareDatetime
    status: Literal[
        "no_corrections",
        "correction_unresolved",
        "correction_resolved",
        "audit_error",
    ]
    correction_event_hashes: list[str] = Field(default_factory=list)
    rationale_hashes: list[str] = Field(default_factory=list)
    learning_ids: list[str] = Field(default_factory=list)
    error_code: str | None = None

    @model_validator(mode="after")
    def coherent_status(self) -> CorrectionAuditReceiptV1:
        correction_count = len(self.correction_event_hashes)
        if len(set(self.correction_event_hashes)) != correction_count:
            raise ValueError("correction event hashes must be unique")
        if len(set(self.learning_ids)) != len(self.learning_ids):
            raise ValueError("learning IDs must be unique")
        if self.status in {"no_corrections", "audit_error"} and (
            correction_count or self.rationale_hashes or self.learning_ids
        ):
            raise ValueError(f"{self.status} cannot carry correction evidence")
        if self.status in {"correction_unresolved", "correction_resolved"} and not correction_count:
            raise ValueError(f"{self.status} requires correction events")
        if correction_count and len(self.rationale_hashes) != correction_count:
            raise ValueError("correction and rationale hash counts must match")
        if self.status == "correction_resolved" and len(self.learning_ids) != correction_count:
            raise ValueError("resolved correction count must equal learning count")
        if self.status == "correction_unresolved" and len(self.learning_ids) >= correction_count:
            raise ValueError("unresolved receipt must retain at least one unmatched correction")
        if self.status == "audit_error" and not self.error_code:
            raise ValueError("audit_error requires error_code")
        if self.status != "audit_error" and self.error_code is not None:
            raise ValueError("only audit_error may carry error_code")
        return self


class LearningCandidate(StrictModel):
    """Same-session immutable learning available for semantic reconciliation."""

    entry_id: str = Field(min_length=1)
    recorded_at: AwareDatetime
    learning: str = Field(min_length=1)


Classifier = Callable[
    [list[TranscriptExchange], list[LearningCandidate]], CorrectionClassification
]


def _message_text(content: object, *, accepted_types: set[str]) -> str | None:
    if isinstance(content, str):
        return content.strip() or None
    if not isinstance(content, list):
        return None
    parts: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") not in accepted_types:
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts) or None


def _transcript_message(payload: dict[str, object], *, agent: str) -> tuple[str, str] | None:
    if agent == "codex":
        item = payload.get("payload")
        if payload.get("type") != "response_item" or not isinstance(item, dict):
            return None
        if item.get("type") != "message" or item.get("role") not in {"user", "assistant"}:
            return None
        role = str(item["role"])
        accepted = {"input_text"} if role == "user" else {"output_text"}
        text = _message_text(item.get("content"), accepted_types=accepted)
    elif agent == "claude-code":
        message = payload.get("message")
        if payload.get("type") not in {"user", "assistant"} or not isinstance(message, dict):
            return None
        if message.get("role") not in {"user", "assistant"}:
            return None
        role = str(message["role"])
        text = _message_text(message.get("content"), accepted_types={"text"})
    else:
        raise ValueError(f"unsupported transcript agent: {agent}")
    return (role, text) if text else None


def extract_transcript_exchanges(path: Path, *, agent: str) -> list[TranscriptExchange]:
    """Extract assistant-to-user exchanges from current native JSONL shapes."""

    exchanges: list[TranscriptExchange] = []
    latest_assistant: str | None = None
    for line_number, raw in enumerate(path.expanduser().read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise TypeError(f"transcript line {line_number} must be an object")
        message = _transcript_message(payload, agent=agent)
        if message is None:
            continue
        role, text = message
        if role == "assistant":
            latest_assistant = text
            continue
        if latest_assistant is None:
            continue
        timestamp = payload.get("timestamp")
        if not isinstance(timestamp, str):
            raise TypeError(f"transcript line {line_number} lacks timestamp")
        occurred_at = datetime.fromisoformat(timestamp)
        event_material = f"{path.name}\0{line_number}\0{timestamp}"
        event_id = hashlib.sha256(event_material.encode()).hexdigest()[:24]
        exchanges.append(
            TranscriptExchange(
                event_id=event_id,
                occurred_at=occurred_at,
                assistant_text=latest_assistant,
                user_text=text,
            )
        )
        latest_assistant = None
    return exchanges


def _source_ref(agent: str, session_id: str) -> str:
    native_id = session_id.split(":", 1)[-1]
    return f"{agent}-thread:{native_id}"


def _eligible_learnings(
    entries_dir: Path,
    *,
    agent: str,
    session_id: str,
) -> list[LearningCandidate]:
    expected_ref = _source_ref(agent, session_id)
    found: list[LearningCandidate] = []
    if not entries_dir.is_dir():
        return found
    for path in entries_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (
                payload.get("schema_version") != "learning/v3"
                or payload.get("source_ref") != expected_ref
            ):
                continue
            entry_id = payload["entry_id"]
            recorded_at = datetime.fromisoformat(payload["recorded_at"])
            learning = payload["learning"]
            if (
                isinstance(entry_id, str)
                and isinstance(learning, str)
                and learning.strip()
                and recorded_at.tzinfo is not None
            ):
                found.append(
                    LearningCandidate(
                        entry_id=entry_id,
                        recorded_at=recorded_at,
                        learning=learning,
                    )
                )
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return sorted(found, key=lambda item: item.recorded_at)


def audit_exchanges(
    *,
    agent: Literal["codex", "claude-code", "openclaw"],
    session_id: str,
    exchanges: list[TranscriptExchange],
    classifier: Classifier,
    learning_entries_dir: Path,
    analyzed_at: datetime | None = None,
) -> CorrectionAuditReceiptV1:
    """Classify exchanges and match each correction to one later learning."""

    now = analyzed_at or datetime.now(UTC)
    try:
        available = _eligible_learnings(
            learning_entries_dir,
            agent=agent,
            session_id=session_id,
        )
        classified = classifier(exchanges, available)
        by_id = {exchange.event_id: exchange for exchange in exchanges}
        verdict_ids = {verdict.event_id for verdict in classified.verdicts}
        if verdict_ids != set(by_id):
            raise ValueError("classifier verdict IDs must exactly match exchange IDs")
    except Exception:  # noqa: BLE001 - model boundary must fail observable and redact details
        return CorrectionAuditReceiptV1(
            agent=agent,
            session_id=session_id,
            analyzed_at=now,
            status="audit_error",
            error_code="classifier_runtime_error",
        )

    corrections = sorted(
        (
            (by_id[verdict.event_id], verdict)
            for verdict in classified.verdicts
            if verdict.classification == "correction"
        ),
        key=lambda item: item[0].occurred_at,
    )
    if not corrections:
        return CorrectionAuditReceiptV1(
            agent=agent,
            session_id=session_id,
            analyzed_at=now,
            status="no_corrections",
        )

    available_by_id = {item.entry_id: item for item in available}
    used: set[str] = set()
    resolved: list[str] = []
    for exchange, verdict in corrections:
        candidate = available_by_id.get(verdict.matching_learning_id or "")
        if (
            candidate is not None
            and candidate.entry_id not in used
            and candidate.recorded_at >= exchange.occurred_at
        ):
            used.add(candidate.entry_id)
            resolved.append(candidate.entry_id)

    correction_hashes = [exchange.event_hash for exchange, _ in corrections]
    rationale_hashes = [
        hashlib.sha256(verdict.rationale.encode()).hexdigest()[:24]
        for _exchange, verdict in corrections
    ]
    return CorrectionAuditReceiptV1(
        agent=agent,
        session_id=session_id,
        analyzed_at=now,
        status=(
            "correction_resolved"
            if len(resolved) == len(corrections)
            else "correction_unresolved"
        ),
        correction_event_hashes=correction_hashes,
        rationale_hashes=rationale_hashes,
        learning_ids=resolved,
    )
