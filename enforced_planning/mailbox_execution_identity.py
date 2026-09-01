"""Durable primary-execution binding for mailbox lifecycle callbacks.

One native session can produce callbacks from more than one execution run.  A
session ID therefore identifies the inbox, while the hook run ID identifies
which execution may expose or enforce that inbox.  Advisory callbacks never
claim an unbound inbox.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

DEFAULT_BINDING_ROOT = Path("~/.claude/coordination/mailbox-primary-executions-v1")
BindingRole = Literal["primary", "secondary", "unbound"]


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PrimaryExecutionBindingV1(StrictContract):
    """Content-free durable binding between one inbox session and one run."""

    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["mailbox_primary_execution_binding"] = (
        "mailbox_primary_execution_binding"
    )
    session_id_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: Literal["active", "awaiting_primary_run"] = "active"
    primary_run_id_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    generation: int = Field(ge=1)
    bound_at: AwareDatetime
    binding_event: Literal["SessionStart", "UserPromptSubmit", "PreToolUse", "Stop"]

    @model_validator(mode="after")
    def require_status_identity_consistency(self) -> PrimaryExecutionBindingV1:
        if (self.status == "active") != (self.primary_run_id_sha256 is not None):
            raise ValueError("active binding status requires exactly one primary run identity")
        return self


class PrimaryExecutionDecisionV1(StrictContract):
    """Classification consumed by a lifecycle hook before mailbox access."""

    schema_version: Literal["1.0"] = "1.0"
    role: BindingRole
    reason: Literal[
        "authoritative_event_bound",
        "authoritative_event_rotated",
        "session_start_awaiting_primary_run",
        "awaiting_primary_run",
        "matches_primary_binding",
        "different_execution_run",
        "advisory_event_cannot_bind",
        "legacy_missing_run_identity",
    ]
    generation: int | None = Field(default=None, ge=1)
    binding_path: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(UTC)


class PrimaryExecutionBindingStore:
    """Serialize exact-session run binding without storing raw identities."""

    def __init__(self, root: Path = DEFAULT_BINDING_ROOT) -> None:
        self.root = root.expanduser().resolve()

    def _record_path(self, session_id: str) -> Path:
        return self.root / f"{_digest(session_id)[:40]}.json"

    def _lock_path(self, session_id: str) -> Path:
        return self.root / f".{_digest(session_id)[:40]}.lock"

    @staticmethod
    def _read(path: Path) -> PrimaryExecutionBindingV1 | None:
        if not path.exists():
            return None
        return PrimaryExecutionBindingV1.model_validate_json(path.read_text(encoding="utf-8"))

    @staticmethod
    def _write(path: Path, binding: PrimaryExecutionBindingV1) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_raw = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True
        )
        temporary = Path(temporary_raw)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(binding.model_dump_json())
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def classify(
        self,
        *,
        session_id: str,
        run_id: str | None,
        event_name: str,
        now: datetime | None = None,
    ) -> PrimaryExecutionDecisionV1:
        """Bind at an authoritative boundary or classify against that binding.

        SessionStart opens a new root execution epoch. UserPromptSubmit binds
        only an unbound or newly opened epoch; a different-run prompt cannot
        steal an active binding. PreToolUse and Stop may bootstrap an older
        already-running session that predates this store. PostToolUse is
        advisory and can never win an unbound inbox.
        """

        path = self._record_path(session_id)
        normalized_run = run_id.strip() if isinstance(run_id, str) else ""
        if not normalized_run and event_name != "SessionStart":
            return PrimaryExecutionDecisionV1(
                # Older hook clients do not supply a run identity. Preserve
                # their behavior without persisting a session-ID fallback as
                # if it were exact run evidence.
                role="primary",
                reason="legacy_missing_run_identity",
                binding_path=str(path),
            )
        run_digest = _digest(normalized_run) if normalized_run else None
        session_digest = _digest(session_id)
        authoritative = event_name in {"SessionStart", "UserPromptSubmit"}
        compatibility_bootstrap = event_name in {"PreToolUse", "Stop"}
        self.root.mkdir(parents=True, exist_ok=True)
        lock_path = self._lock_path(session_id)
        descriptor = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            current = self._read(path)
            if current is not None and current.session_id_sha256 != session_digest:
                raise ValueError("primary execution binding session digest mismatch")
            if event_name == "SessionStart" and run_digest is None:
                if current is not None and current.status == "awaiting_primary_run":
                    return PrimaryExecutionDecisionV1(
                        role="unbound",
                        reason="session_start_awaiting_primary_run",
                        generation=current.generation,
                        binding_path=str(path),
                    )
                generation = 1 if current is None else current.generation + 1
                self._write(
                    path,
                    PrimaryExecutionBindingV1(
                        session_id_sha256=session_digest,
                        status="awaiting_primary_run",
                        primary_run_id_sha256=None,
                        generation=generation,
                        bound_at=now or _utc_now(),
                        binding_event="SessionStart",
                    ),
                )
                return PrimaryExecutionDecisionV1(
                    role="unbound",
                    reason="session_start_awaiting_primary_run",
                    generation=generation,
                    binding_path=str(path),
                )
            if current is not None and current.status == "awaiting_primary_run":
                if event_name not in {"SessionStart", "UserPromptSubmit"}:
                    return PrimaryExecutionDecisionV1(
                        role="unbound",
                        reason="awaiting_primary_run",
                        generation=current.generation,
                        binding_path=str(path),
                    )
                binding = PrimaryExecutionBindingV1(
                    session_id_sha256=session_digest,
                    status="active",
                    primary_run_id_sha256=run_digest,
                    generation=current.generation,
                    bound_at=now or _utc_now(),
                    binding_event=event_name,
                )
                self._write(path, binding)
                return PrimaryExecutionDecisionV1(
                    role="primary",
                    reason="authoritative_event_bound",
                    generation=current.generation,
                    binding_path=str(path),
                )
            if current is not None and current.primary_run_id_sha256 == run_digest:
                return PrimaryExecutionDecisionV1(
                    role="primary",
                    reason="matches_primary_binding",
                    generation=current.generation,
                    binding_path=str(path),
                )
            if current is None and not (authoritative or compatibility_bootstrap):
                return PrimaryExecutionDecisionV1(
                    role="unbound",
                    reason="advisory_event_cannot_bind",
                    binding_path=str(path),
                )
            if current is not None and event_name != "SessionStart":
                return PrimaryExecutionDecisionV1(
                    role="secondary",
                    reason="different_execution_run",
                    generation=current.generation,
                    binding_path=str(path),
                )
            generation = 1 if current is None else current.generation + 1
            binding = PrimaryExecutionBindingV1(
                session_id_sha256=session_digest,
                status="active",
                primary_run_id_sha256=run_digest,
                generation=generation,
                bound_at=now or _utc_now(),
                binding_event=event_name,
            )
            self._write(path, binding)
            return PrimaryExecutionDecisionV1(
                role="primary",
                reason=(
                    "authoritative_event_bound"
                    if current is None
                    else "authoritative_event_rotated"
                ),
                generation=generation,
                binding_path=str(path),
            )
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def hook_run_id(payload: dict[str, object]) -> str | None:
    """Return the native execution-run identity without session fallback."""

    for field in ("hook_run_id", "hookRunId"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


__all__ = [
    "DEFAULT_BINDING_ROOT",
    "PrimaryExecutionBindingStore",
    "PrimaryExecutionBindingV1",
    "PrimaryExecutionDecisionV1",
    "hook_run_id",
]
