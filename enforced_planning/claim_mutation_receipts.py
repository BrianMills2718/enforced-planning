"""Durable, typed evidence for sanctioned claim-registry mutations."""

from __future__ import annotations

import fcntl
import hashlib
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


DEFAULT_EVENTS_PATH = Path.home() / ".claude" / "coordination" / "claim-mutation-events-v1.jsonl"
MutationOperation = Literal["create", "heartbeat", "release", "prune", "session_end", "closeout"]
MutationResult = Literal["applied_projection_current", "applied_projection_stale", "not_applied"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClaimMutationReceiptV1(_StrictModel):
    """One terminal audit record for one sanctioned claim mutation."""

    schema_version: Literal["1.0"] = "1.0"
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    observed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    operation: MutationOperation
    result: MutationResult
    writer_source_path: str
    writer_source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    writer_repo_root: str
    process_id: int = Field(ge=1)
    session_id: str | None
    target_project: str | None
    target_scope: str | None
    target_claim_path: str | None
    registry_digest_before: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    registry_digest_after: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    projection_digest_after: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    projection_current_after: bool | None
    error_code: str | None = None

    @model_validator(mode="after")
    def _require_outcome_details_when_applied(self) -> "ClaimMutationReceiptV1":
        """Applied mutations must retain the complete authority outcome."""

        if self.result == "not_applied":
            return self
        missing = [
            field
            for field, value in (
                ("registry_digest_before", self.registry_digest_before),
                ("registry_digest_after", self.registry_digest_after),
                ("projection_digest_after", self.projection_digest_after),
                ("projection_current_after", self.projection_current_after),
            )
            if value is None
        ]
        if missing:
            raise ValueError(
                "Applied mutation receipts require non-null authority outcome fields: "
                + ", ".join(missing)
            )
        return self


class MutationAuditError(ValueError):
    """A mutation completed, but its durable provenance receipt could not persist."""

    error_code = "mutation_applied_audit_failed"

    def __init__(
        self,
        *,
        operation: MutationOperation,
        target_project: str | None,
        target_scope: str | None,
        registry_digest_after: str | None,
        projection_digest_after: str | None,
        projection_current_after: bool | None,
        cause: OSError,
    ) -> None:
        self.operation = operation
        self.target_project = target_project
        self.target_scope = target_scope
        self.registry_digest_after = registry_digest_after
        self.projection_digest_after = projection_digest_after
        self.projection_current_after = projection_current_after
        self.cause = cause
        super().__init__(
            f"{self.error_code}: operation={operation} target="
            f"{target_project or '<unknown>'}:{target_scope or '<unknown>'} "
            f"registry_digest_after={registry_digest_after or '<none>'} "
            f"projection_digest_after={projection_digest_after or '<none>'} "
            f"projection_current_after={projection_current_after!r}; cause={cause}"
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "error_code": self.error_code,
            "mutation_applied": True,
            "operation": self.operation,
            "target_project": self.target_project,
            "target_scope": self.target_scope,
            "registry_digest_after": self.registry_digest_after,
            "projection_digest_after": self.projection_digest_after,
            "projection_current_after": self.projection_current_after,
            "cause": str(self.cause),
        }


def writer_identity(source_path: Path) -> tuple[str, str, str]:
    """Return the loaded runtime source identity without relying on cwd or repo names."""

    resolved = source_path.resolve()
    source_bytes = resolved.read_bytes()
    return (
        str(resolved),
        hashlib.sha256(source_bytes).hexdigest(),
        str(resolved.parents[1]),
    )


def append_receipt(receipt: ClaimMutationReceiptV1, *, events_path: Path | None = None) -> Path:
    """Append and fsync one receipt while preserving JSONL record boundaries."""

    resolved = (events_path or DEFAULT_EVENTS_PATH).expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = receipt.model_dump_json() + "\n"
    with resolved.open("a", encoding="utf-8") as handle:
        resolved.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return resolved


def load_receipts(*, events_path: Path | None = None) -> list[ClaimMutationReceiptV1]:
    """Load a complete JSONL ledger, rejecting malformed or unknown fields."""

    resolved = (events_path or DEFAULT_EVENTS_PATH).expanduser().resolve()
    if not resolved.exists():
        return []
    receipts: list[ClaimMutationReceiptV1] = []
    for number, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            receipts.append(ClaimMutationReceiptV1.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"Invalid claim mutation receipt at {resolved}:{number}: {exc}") from exc
    return receipts


__all__ = [
    "ClaimMutationReceiptV1",
    "DEFAULT_EVENTS_PATH",
    "MutationAuditError",
    "MutationOperation",
    "MutationResult",
    "append_receipt",
    "load_receipts",
    "writer_identity",
]
