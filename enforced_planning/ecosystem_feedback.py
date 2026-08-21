"""Portable append-only transport for actionable ecosystem feedback.

The transport deliberately records only concrete friction or evidence-backed
recommendations.  Evidence references remain inert strings: this module never
opens, fetches, or otherwise dereferences them, and recording feedback never
changes policy or any other governed artifact.
"""

from __future__ import annotations

import fcntl
import json
import os
import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

FeedbackType = Literal["friction", "recommendation"]
FeedbackScopeKind = Literal[
    "policy",
    "skill",
    "instruction",
    "tool",
    "project",
    "general",
]
FeedbackDispositionKind = Literal[
    "resolved",
    "accepted",
    "accepted_risk",
    "duplicate",
    "superseded",
    "misrouted",
]
FeedbackStatus = Literal[
    "open",
    "resolved",
    "accepted",
    "accepted_risk",
    "duplicate",
    "superseded",
    "misrouted",
]
FeedbackId = Annotated[str, Field(pattern=r"^ecosystem_feedback_[0-9a-f]{32}$")]
FeedbackDispositionId = Annotated[
    str,
    Field(pattern=r"^ecosystem_feedback_disposition_[0-9a-f]{32}$"),
]

FEEDBACK_TYPES: tuple[FeedbackType, ...] = ("friction", "recommendation")
FEEDBACK_SCOPE_KINDS: tuple[FeedbackScopeKind, ...] = (
    "policy",
    "skill",
    "instruction",
    "tool",
    "project",
    "general",
)
FEEDBACK_DISPOSITIONS: tuple[FeedbackDispositionKind, ...] = (
    "resolved",
    "accepted",
    "accepted_risk",
    "duplicate",
    "superseded",
    "misrouted",
)
FEEDBACK_STATUSES: tuple[FeedbackStatus, ...] = ("open", *FEEDBACK_DISPOSITIONS)

DEFAULT_FEEDBACK_PATH = Path.home() / ".claude" / "coordination" / "ecosystem-feedback-v1.jsonl"


class EcosystemFeedbackError(ValueError):
    """Raised when feedback cannot be validated or appended safely."""


class StrictContract(BaseModel):
    """Reject unknown fields and freeze all public feedback contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, validate_default=True)


def _strip_required(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise ValueError("value must contain non-whitespace text")
    return stripped


def _strip_optional(value: str | None) -> str | None:
    if value is None:
        return None
    return _strip_required(value)


def _require_utc(value: datetime) -> datetime:
    if value.utcoffset() != UTC.utcoffset(value):
        raise ValueError("timestamp must use UTC")
    return value


class EcosystemFeedbackSourceV1(StrictContract):
    """Privacy-reduced identity for the client that observed feedback."""

    client: str = Field(min_length=1)
    project: str | None = Field(default=None, min_length=1)
    task_id: str | None = Field(default=None, min_length=1)
    session_id: str | None = Field(default=None, min_length=1)
    working_directory: str | None = Field(default=None, min_length=1)

    @field_validator("client")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("project", "task_id", "session_id", "working_directory")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class EcosystemFeedbackCreateV1(StrictContract):
    """Validated input for one actionable ecosystem feedback record."""

    feedback_type: FeedbackType
    scope_kind: FeedbackScopeKind
    scope_id: str | None = Field(default=None, min_length=1)
    observation: str = Field(min_length=1)
    expected_behavior: str | None = Field(default=None, min_length=1)
    recommendation: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    source: EcosystemFeedbackSourceV1

    @field_validator("scope_id", "expected_behavior")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("observation", "recommendation")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_strip_required(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("evidence_refs must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _validate_semantics(self) -> EcosystemFeedbackCreateV1:
        if self.scope_kind == "general" and self.scope_id is not None:
            raise ValueError("general feedback must not fabricate a scope_id")
        if self.scope_kind != "general" and self.scope_id is None:
            raise ValueError(f"{self.scope_kind} feedback requires scope_id")
        if self.feedback_type == "friction" and self.expected_behavior is None:
            raise ValueError("friction feedback requires expected_behavior")
        return self


class EcosystemFeedbackV1(StrictContract):
    """One immutable open feedback record in the durable JSONL stream."""

    schema_version: Literal["1.0"]
    record_type: Literal["feedback"]
    feedback_id: FeedbackId
    recorded_at: AwareDatetime
    feedback_type: FeedbackType
    scope_kind: FeedbackScopeKind
    scope_id: str | None = Field(default=None, min_length=1)
    observation: str = Field(min_length=1)
    expected_behavior: str | None = Field(default=None, min_length=1)
    recommendation: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    source: EcosystemFeedbackSourceV1
    status: Literal["open"]

    @field_validator("recorded_at")
    @classmethod
    def _validate_recorded_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("scope_id", "expected_behavior")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("observation", "recommendation")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_strip_required(value) for value in values)
        if len(set(normalized)) != len(normalized):
            raise ValueError("evidence_refs must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _validate_semantics(self) -> EcosystemFeedbackV1:
        if self.scope_kind == "general" and self.scope_id is not None:
            raise ValueError("general feedback must not fabricate a scope_id")
        if self.scope_kind != "general" and self.scope_id is None:
            raise ValueError(f"{self.scope_kind} feedback requires scope_id")
        if self.feedback_type == "friction" and self.expected_behavior is None:
            raise ValueError("friction feedback requires expected_behavior")
        return self


class EcosystemFeedbackDispositionCreateV1(StrictContract):
    """Validated input for one terminal feedback disposition."""

    feedback_id: FeedbackId
    disposition: FeedbackDispositionKind
    rationale: str = Field(min_length=1)
    successor_ref: str | None = Field(default=None, min_length=1)

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("successor_ref")
    @classmethod
    def _validate_successor_ref(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class EcosystemFeedbackDispositionV1(StrictContract):
    """One immutable terminal decision for a prior feedback record."""

    schema_version: Literal["1.0"]
    record_type: Literal["feedback_disposition"]
    disposition_id: FeedbackDispositionId
    recorded_at: AwareDatetime
    feedback_id: FeedbackId
    disposition: FeedbackDispositionKind
    rationale: str = Field(min_length=1)
    successor_ref: str | None = Field(default=None, min_length=1)

    @field_validator("recorded_at")
    @classmethod
    def _validate_recorded_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("rationale")
    @classmethod
    def _validate_rationale(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("successor_ref")
    @classmethod
    def _validate_successor_ref(cls, value: str | None) -> str | None:
        return _strip_optional(value)


class EcosystemFeedbackViewV1(StrictContract):
    """Original feedback fields plus their effective append-only lifecycle."""

    schema_version: Literal["1.0"]
    record_type: Literal["feedback"]
    feedback_id: FeedbackId
    recorded_at: AwareDatetime
    feedback_type: FeedbackType
    scope_kind: FeedbackScopeKind
    scope_id: str | None
    observation: str
    expected_behavior: str | None
    recommendation: str
    evidence_refs: tuple[str, ...]
    source: EcosystemFeedbackSourceV1
    status: FeedbackStatus
    disposition: EcosystemFeedbackDispositionV1 | None = None

    @field_validator("recorded_at")
    @classmethod
    def _validate_recorded_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @field_validator("scope_id", "expected_behavior")
    @classmethod
    def _validate_optional_text(cls, value: str | None) -> str | None:
        return _strip_optional(value)

    @field_validator("observation", "recommendation")
    @classmethod
    def _validate_required_text(cls, value: str) -> str:
        return _strip_required(value)

    @field_validator("evidence_refs")
    @classmethod
    def _validate_evidence_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(_strip_required(value) for value in values)
        if not normalized:
            raise ValueError("evidence_refs must contain at least one reference")
        if len(set(normalized)) != len(normalized):
            raise ValueError("evidence_refs must not contain duplicates")
        return normalized

    @model_validator(mode="after")
    def _validate_lifecycle(self) -> EcosystemFeedbackViewV1:
        if self.scope_kind == "general" and self.scope_id is not None:
            raise ValueError("general feedback must not fabricate a scope_id")
        if self.scope_kind != "general" and self.scope_id is None:
            raise ValueError(f"{self.scope_kind} feedback requires scope_id")
        if self.feedback_type == "friction" and self.expected_behavior is None:
            raise ValueError("friction feedback requires expected_behavior")
        if self.disposition is None and self.status != "open":
            raise ValueError("terminal view status requires a disposition")
        if self.disposition is not None:
            if self.disposition.feedback_id != self.feedback_id:
                raise ValueError("view disposition references a different feedback_id")
            if self.status != self.disposition.disposition:
                raise ValueError("view status must match its disposition")
        return self


class EcosystemFeedbackReportV1(StrictContract):
    """Aggregate feedback counts with stable-ID step-down evidence."""

    schema_version: Literal["1.0"]
    generated_at: AwareDatetime
    feedback_count: int = Field(ge=0)
    open_count: int = Field(ge=0)
    dispositioned_count: int = Field(ge=0)
    feedback_type_counts: dict[FeedbackType, int]
    scope_kind_counts: dict[FeedbackScopeKind, int]
    status_counts: dict[FeedbackStatus, int]
    feedback_ids: tuple[FeedbackId, ...]
    open_feedback_ids: tuple[FeedbackId, ...]
    dispositioned_feedback_ids: tuple[FeedbackId, ...]

    @field_validator("generated_at")
    @classmethod
    def _validate_generated_at(cls, value: datetime) -> datetime:
        return _require_utc(value)

    @model_validator(mode="after")
    def _validate_counts(self) -> EcosystemFeedbackReportV1:
        if set(self.feedback_type_counts) != set(FEEDBACK_TYPES):
            raise ValueError("feedback_type_counts must contain every feedback type")
        if set(self.scope_kind_counts) != set(FEEDBACK_SCOPE_KINDS):
            raise ValueError("scope_kind_counts must contain every scope kind")
        if set(self.status_counts) != set(FEEDBACK_STATUSES):
            raise ValueError("status_counts must contain every feedback status")
        if self.open_count + self.dispositioned_count != self.feedback_count:
            raise ValueError("open and dispositioned counts must equal feedback_count")
        if len(self.feedback_ids) != self.feedback_count:
            raise ValueError("feedback_ids must step down every counted record")
        if len(self.open_feedback_ids) != self.open_count:
            raise ValueError("open_feedback_ids must step down every open record")
        if len(self.dispositioned_feedback_ids) != self.dispositioned_count:
            raise ValueError("dispositioned_feedback_ids must step down every dispositioned record")
        if len(set(self.feedback_ids)) != len(self.feedback_ids):
            raise ValueError("feedback_ids must be unique")
        if set(self.open_feedback_ids) & set(self.dispositioned_feedback_ids):
            raise ValueError("open and dispositioned feedback IDs must be disjoint")
        if set(self.open_feedback_ids) | set(self.dispositioned_feedback_ids) != set(self.feedback_ids):
            raise ValueError("open and dispositioned feedback IDs must partition feedback_ids")
        if sum(self.feedback_type_counts.values()) != self.feedback_count:
            raise ValueError("feedback_type_counts must equal feedback_count")
        if sum(self.scope_kind_counts.values()) != self.feedback_count:
            raise ValueError("scope_kind_counts must equal feedback_count")
        if sum(self.status_counts.values()) != self.feedback_count:
            raise ValueError("status_counts must equal feedback_count")
        if self.status_counts["open"] != self.open_count:
            raise ValueError("open status count must equal open_count")
        if sum(count for status, count in self.status_counts.items() if status != "open") != self.dispositioned_count:
            raise ValueError("terminal status counts must equal dispositioned_count")
        if any(
            count < 0
            for counts in (
                self.feedback_type_counts,
                self.scope_kind_counts,
                self.status_counts,
            )
            for count in counts.values()
        ):
            raise ValueError("report counts must be non-negative")
        open_id_set = set(self.open_feedback_ids)
        if (
            tuple(feedback_id for feedback_id in self.feedback_ids if feedback_id in open_id_set)
            != self.open_feedback_ids
        ):
            raise ValueError("open_feedback_ids must preserve feedback_ids order")
        dispositioned_id_set = set(self.dispositioned_feedback_ids)
        if (
            tuple(feedback_id for feedback_id in self.feedback_ids if feedback_id in dispositioned_id_set)
            != self.dispositioned_feedback_ids
        ):
            raise ValueError("dispositioned_feedback_ids must preserve feedback_ids order")
        return self


@contextmanager
def _locked_stream(path: Path, *, exclusive: bool) -> Iterator[IO[str]]:
    """Open and lock an existing stream, or create one for an append."""

    resolved = path.expanduser().resolve()
    if exclusive:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        mode = "a+"
    else:
        mode = "r"
    try:
        with resolved.open(mode, encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            try:
                yield handle
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise EcosystemFeedbackError(f"cannot access feedback stream {resolved}: {exc}") from exc


def _decode_record(
    payload: dict[str, Any],
    *,
    resolved: Path,
    line_number: int,
) -> EcosystemFeedbackV1 | EcosystemFeedbackDispositionV1:
    record_type = payload.get("record_type")
    model: type[EcosystemFeedbackV1 | EcosystemFeedbackDispositionV1]
    if record_type == "feedback":
        model = EcosystemFeedbackV1
    elif record_type == "feedback_disposition":
        model = EcosystemFeedbackDispositionV1
    else:
        raise EcosystemFeedbackError(f"unknown record_type at {resolved}:{line_number}: {record_type!r}")
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise EcosystemFeedbackError(f"schema-invalid feedback row at {resolved}:{line_number}: {exc}") from exc


def _read_locked_stream(
    handle: IO[str],
    *,
    path: Path,
) -> tuple[
    tuple[EcosystemFeedbackV1, ...],
    dict[str, EcosystemFeedbackDispositionV1],
]:
    """Validate the full stream and return its one-terminal-decision state."""

    resolved = path.expanduser().resolve()
    handle.seek(0)
    feedback: list[EcosystemFeedbackV1] = []
    feedback_by_id: dict[str, EcosystemFeedbackV1] = {}
    dispositions_by_feedback_id: dict[str, EcosystemFeedbackDispositionV1] = {}
    disposition_ids: set[str] = set()

    for line_number, line in enumerate(handle, start=1):
        if not line.strip():
            raise EcosystemFeedbackError(f"blank feedback row at {resolved}:{line_number}")
        if not line.endswith("\n"):
            raise EcosystemFeedbackError(f"unterminated feedback row at {resolved}:{line_number}")
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EcosystemFeedbackError(f"malformed JSONL at {resolved}:{line_number}: {exc}") from exc
        if not isinstance(payload, dict):
            raise EcosystemFeedbackError(f"feedback row at {resolved}:{line_number} is not an object")
        record = _decode_record(payload, resolved=resolved, line_number=line_number)
        if isinstance(record, EcosystemFeedbackV1):
            if record.feedback_id in feedback_by_id:
                raise EcosystemFeedbackError(f"duplicate feedback_id at {resolved}:{line_number}: {record.feedback_id}")
            feedback.append(record)
            feedback_by_id[record.feedback_id] = record
            continue

        if record.disposition_id in disposition_ids:
            raise EcosystemFeedbackError(
                f"duplicate disposition_id at {resolved}:{line_number}: {record.disposition_id}"
            )
        disposition_ids.add(record.disposition_id)
        original = feedback_by_id.get(record.feedback_id)
        if original is None:
            raise EcosystemFeedbackError(
                f"disposition at {resolved}:{line_number} references unknown prior feedback_id {record.feedback_id}"
            )
        if record.feedback_id in dispositions_by_feedback_id:
            raise EcosystemFeedbackError(f"feedback_id {record.feedback_id} has multiple terminal dispositions")
        if record.recorded_at < original.recorded_at:
            raise EcosystemFeedbackError(f"disposition for {record.feedback_id} predates its feedback record")
        dispositions_by_feedback_id[record.feedback_id] = record

    return tuple(feedback), dispositions_by_feedback_id


def _load_stream(
    path: Path,
) -> tuple[
    tuple[EcosystemFeedbackV1, ...],
    dict[str, EcosystemFeedbackDispositionV1],
]:
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        return (), {}
    with _locked_stream(resolved, exclusive=False) as handle:
        return _read_locked_stream(handle, path=resolved)


def _append_locked(handle: IO[str], record: StrictContract) -> None:
    payload = json.dumps(record.model_dump(mode="json"), sort_keys=True)
    handle.seek(0, os.SEEK_END)
    handle.write(payload + "\n")
    handle.flush()
    os.fsync(handle.fileno())


def _view(
    feedback: EcosystemFeedbackV1,
    disposition: EcosystemFeedbackDispositionV1 | None,
) -> EcosystemFeedbackViewV1:
    payload = feedback.model_dump()
    payload["status"] = disposition.disposition if disposition is not None else "open"
    payload["disposition"] = disposition
    return EcosystemFeedbackViewV1.model_validate(payload)


def record_ecosystem_feedback(
    request: EcosystemFeedbackCreateV1,
    *,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
) -> EcosystemFeedbackV1:
    """Validate and durably append one open feedback record."""

    if not isinstance(request, EcosystemFeedbackCreateV1):
        raise TypeError("request must be EcosystemFeedbackCreateV1")
    record = EcosystemFeedbackV1(
        schema_version="1.0",
        record_type="feedback",
        feedback_id=f"ecosystem_feedback_{uuid.uuid4().hex}",
        recorded_at=datetime.now(UTC),
        status="open",
        **request.model_dump(),
    )
    with _locked_stream(feedback_path, exclusive=True) as handle:
        existing, _ = _read_locked_stream(handle, path=feedback_path)
        if any(item.feedback_id == record.feedback_id for item in existing):
            raise EcosystemFeedbackError(f"generated duplicate feedback_id {record.feedback_id}")
        _append_locked(handle, record)
    return record


def disposition_ecosystem_feedback(
    request: EcosystemFeedbackDispositionCreateV1,
    *,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
) -> EcosystemFeedbackDispositionV1:
    """Append the exactly-one terminal decision for an existing feedback ID."""

    if not isinstance(request, EcosystemFeedbackDispositionCreateV1):
        raise TypeError("request must be EcosystemFeedbackDispositionCreateV1")
    disposition = EcosystemFeedbackDispositionV1(
        schema_version="1.0",
        record_type="feedback_disposition",
        disposition_id=f"ecosystem_feedback_disposition_{uuid.uuid4().hex}",
        recorded_at=datetime.now(UTC),
        **request.model_dump(),
    )
    with _locked_stream(feedback_path, exclusive=True) as handle:
        feedback, existing_dispositions = _read_locked_stream(
            handle,
            path=feedback_path,
        )
        feedback_by_id = {item.feedback_id: item for item in feedback}
        original = feedback_by_id.get(disposition.feedback_id)
        if original is None:
            raise EcosystemFeedbackError(f"cannot disposition unknown feedback_id {disposition.feedback_id}")
        if disposition.feedback_id in existing_dispositions:
            raise EcosystemFeedbackError(f"feedback_id {disposition.feedback_id} already has a terminal disposition")
        if any(existing.disposition_id == disposition.disposition_id for existing in existing_dispositions.values()):
            raise EcosystemFeedbackError(f"generated duplicate disposition_id {disposition.disposition_id}")
        if disposition.recorded_at < original.recorded_at:
            raise EcosystemFeedbackError(f"disposition for {disposition.feedback_id} predates its feedback record")
        _append_locked(handle, disposition)
    return disposition


def _validate_filter(value: str | None, allowed: tuple[str, ...], name: str) -> None:
    if value is not None and value not in allowed:
        raise EcosystemFeedbackError(f"unsupported {name} filter {value!r}")


def list_ecosystem_feedback(
    *,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
    feedback_type: FeedbackType | None = None,
    scope_kind: FeedbackScopeKind | None = None,
    scope_id: str | None = None,
    status: FeedbackStatus | None = None,
) -> tuple[EcosystemFeedbackViewV1, ...]:
    """Return ordered, fully validated feedback views matching the filters."""

    _validate_filter(feedback_type, FEEDBACK_TYPES, "feedback_type")
    _validate_filter(scope_kind, FEEDBACK_SCOPE_KINDS, "scope_kind")
    _validate_filter(status, FEEDBACK_STATUSES, "status")
    normalized_scope_id = _strip_optional(scope_id)
    feedback, dispositions = _load_stream(feedback_path)
    views = tuple(_view(item, dispositions.get(item.feedback_id)) for item in feedback)
    return tuple(
        view
        for view in views
        if (feedback_type is None or view.feedback_type == feedback_type)
        and (scope_kind is None or view.scope_kind == scope_kind)
        and (normalized_scope_id is None or view.scope_id == normalized_scope_id)
        and (status is None or view.status == status)
    )


def report_ecosystem_feedback(
    *,
    feedback_path: Path = DEFAULT_FEEDBACK_PATH,
    feedback_type: FeedbackType | None = None,
    scope_kind: FeedbackScopeKind | None = None,
    scope_id: str | None = None,
    status: FeedbackStatus | None = None,
) -> EcosystemFeedbackReportV1:
    """Build counts and stable-ID step-downs from the validated stream."""

    views = list_ecosystem_feedback(
        feedback_path=feedback_path,
        feedback_type=feedback_type,
        scope_kind=scope_kind,
        scope_id=scope_id,
        status=status,
    )
    feedback_type_counter = Counter(view.feedback_type for view in views)
    scope_kind_counter = Counter(view.scope_kind for view in views)
    status_counter = Counter(view.status for view in views)
    open_ids = tuple(view.feedback_id for view in views if view.status == "open")
    dispositioned_ids = tuple(view.feedback_id for view in views if view.status != "open")
    return EcosystemFeedbackReportV1(
        schema_version="1.0",
        generated_at=datetime.now(UTC),
        feedback_count=len(views),
        open_count=len(open_ids),
        dispositioned_count=len(dispositioned_ids),
        feedback_type_counts={kind: feedback_type_counter.get(kind, 0) for kind in FEEDBACK_TYPES},
        scope_kind_counts={kind: scope_kind_counter.get(kind, 0) for kind in FEEDBACK_SCOPE_KINDS},
        status_counts={kind: status_counter.get(kind, 0) for kind in FEEDBACK_STATUSES},
        feedback_ids=tuple(view.feedback_id for view in views),
        open_feedback_ids=open_ids,
        dispositioned_feedback_ids=dispositioned_ids,
    )


__all__ = [
    "DEFAULT_FEEDBACK_PATH",
    "EcosystemFeedbackCreateV1",
    "EcosystemFeedbackDispositionCreateV1",
    "EcosystemFeedbackDispositionV1",
    "EcosystemFeedbackError",
    "EcosystemFeedbackReportV1",
    "EcosystemFeedbackSourceV1",
    "EcosystemFeedbackV1",
    "EcosystemFeedbackViewV1",
    "FeedbackDispositionKind",
    "FeedbackScopeKind",
    "FeedbackStatus",
    "FeedbackType",
    "disposition_ecosystem_feedback",
    "list_ecosystem_feedback",
    "record_ecosystem_feedback",
    "report_ecosystem_feedback",
]
