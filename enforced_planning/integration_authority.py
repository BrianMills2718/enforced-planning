"""Canonical-claim authority for the hook-governed pull-request finish path.

The existing exact-session branch claim is the integration lease. This module
does not mint another owner token: it binds a short-lived assertion to the raw
canonical claim bytes, native session, PR revision, and trusted review spec.
Callers revalidate under ``claim_registry_lock`` immediately around GitHub's
exact-head compare-and-swap merge.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from enforced_planning import coordination_claims

FULL_SHA_PATTERN = r"^[0-9a-f]{40}$"
SHA256_PATTERN = r"^[0-9a-f]{64}$"
SESSION_PATTERN = r"^(?:codex|claude-code|openclaw):[^\s]+$"
DEFAULT_ASSERTION_SECONDS = 300
MAX_ASSERTION_SECONDS = 600


class IntegrationAuthorityError(RuntimeError):
    """Raised when an exact native branch owner cannot integrate one PR head."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IntegrationTargetV1(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    project: str = Field(min_length=1)
    pr_number: int = Field(gt=0)
    branch: str = Field(min_length=1)
    base_sha: str = Field(pattern=FULL_SHA_PATTERN)
    head_sha: str = Field(pattern=FULL_SHA_PATTERN)
    review_spec_sha256: str = Field(pattern=SHA256_PATTERN)


class IntegrationClaimBindingV1(_StrictModel):
    agent: Literal["codex", "claude-code", "openclaw"]
    session_id: str = Field(pattern=SESSION_PATTERN)
    scope: str = Field(min_length=1)
    claim_snapshot_sha256: str = Field(pattern=SHA256_PATTERN)
    plan_ref: str = Field(min_length=1)
    work_graph_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    work_unit_id: str | None = None
    approval_revisions: tuple[str, ...] = ()


class IntegrationAuthorityAssertionV1(_StrictModel):
    schema_version: Literal["1.0"] = "1.0"
    record_type: Literal["integration_authority_assertion"] = (
        "integration_authority_assertion"
    )
    target: IntegrationTargetV1
    claim: IntegrationClaimBindingV1
    asserted_at: AwareDatetime
    valid_until: AwareDatetime
    assertion_sha256: str = Field(pattern=SHA256_PATTERN)

    @model_validator(mode="after")
    def _validate_assertion(self) -> IntegrationAuthorityAssertionV1:
        if self.valid_until <= self.asserted_at:
            raise ValueError("integration assertion validity interval is empty")
        expected = canonical_sha256(
            self.model_dump(mode="json", exclude={"assertion_sha256"})
        )
        if self.assertion_sha256 != expected:
            raise ValueError("integration assertion digest is invalid")
        return self


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def review_spec_sha256(path: Path) -> str:
    try:
        resolved = path.expanduser().resolve(strict=True)
        return hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        raise IntegrationAuthorityError(f"cannot read trusted review spec: {exc}") from exc


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(UTC)


def _claim_snapshot_sha256(claim: coordination_claims.ClaimRecord) -> str:
    if not claim.source_file:
        raise IntegrationAuthorityError("canonical claim has no source file")
    try:
        return hashlib.sha256(Path(claim.source_file).read_bytes()).hexdigest()
    except OSError as exc:
        raise IntegrationAuthorityError(f"cannot read canonical claim bytes: {exc}") from exc


def resolve_native_session(agent: str) -> str:
    session_id = coordination_claims.resolve_session_id(agent)
    if session_id is None:
        raise IntegrationAuthorityError(
            f"integration requires the native {agent} session marker"
        )
    try:
        coordination_claims.validate_native_session_binding(
            agent, session_id, require_native_marker=True
        )
    except ValueError as exc:
        raise IntegrationAuthorityError(str(exc)) from exc
    return session_id


def _exact_active_claim(
    *,
    target: IntegrationTargetV1,
    agent: str,
    session_id: str,
    repo_root: Path,
    claims_dir: Path | None,
    now: datetime,
) -> coordination_claims.ClaimRecord:
    active_claims = coordination_claims.list_claims(
        target.project, claims_dir=claims_dir, include_inactive=False
    )
    matches = [
        claim
        for claim in active_claims
        if claim.agent == agent
        and claim.session_id == session_id
        and claim.status == "active"
        and claim.branch == target.branch
        and claim.repo_root is not None
        and Path(claim.repo_root).expanduser().resolve() == repo_root
    ]
    if len(matches) != 1:
        raise IntegrationAuthorityError(
            "integration requires exactly one active canonical branch claim "
            "owned by the native session"
        )
    claim = matches[0]
    runtime_status = coordination_claims.claim_runtime_status(
        claim, active_claims=active_claims, now=now
    )
    if runtime_status != "healthy":
        raise IntegrationAuthorityError(
            f"integration claim runtime status is {runtime_status}, not healthy"
        )
    expires_at = _parse_time(claim.expires_at)
    if expires_at is None or expires_at <= now:
        raise IntegrationAuthorityError("integration claim is expired")
    return claim


def _claim_binding(
    claim: coordination_claims.ClaimRecord,
) -> IntegrationClaimBindingV1:
    if not claim.session_id or not claim.plan_ref:
        raise IntegrationAuthorityError("integration claim lacks session or plan authority")
    if bool(claim.work_graph_sha256) != bool(claim.work_unit_id):
        raise IntegrationAuthorityError(
            "integration claim has an incomplete work-unit authority binding"
        )
    return IntegrationClaimBindingV1(
        agent=claim.agent,
        session_id=claim.session_id,
        scope=claim.scope,
        claim_snapshot_sha256=_claim_snapshot_sha256(claim),
        plan_ref=claim.plan_ref,
        work_graph_sha256=claim.work_graph_sha256,
        work_unit_id=claim.work_unit_id,
        approval_revisions=claim.approval_revisions,
    )


def assert_integration_authority(
    *,
    target: IntegrationTargetV1,
    agent: str,
    repo_root: Path,
    claims_dir: Path | None = None,
    now: datetime | None = None,
    validity: timedelta = timedelta(seconds=DEFAULT_ASSERTION_SECONDS),
    lock_registry: bool = True,
) -> IntegrationAuthorityAssertionV1:
    """Build a digest-bound assertion from the current canonical branch claim."""

    seconds = validity.total_seconds()
    if seconds <= 0 or seconds > MAX_ASSERTION_SECONDS:
        raise IntegrationAuthorityError(
            f"assertion validity must be 1..{MAX_ASSERTION_SECONDS} seconds"
        )
    observed = (now or datetime.now(UTC)).astimezone(UTC)
    session_id = resolve_native_session(agent)
    resolved_root = repo_root.expanduser().resolve()

    def build() -> IntegrationAuthorityAssertionV1:
        claim = _exact_active_claim(
            target=target,
            agent=agent,
            session_id=session_id,
            repo_root=resolved_root,
            claims_dir=claims_dir,
            now=observed,
        )
        payload = {
            "schema_version": "1.0",
            "record_type": "integration_authority_assertion",
            "target": target,
            "claim": _claim_binding(claim),
            "asserted_at": observed,
            "valid_until": observed + validity,
        }
        provisional = IntegrationAuthorityAssertionV1.model_construct(
            **payload, assertion_sha256="0" * 64
        )
        digest_payload = provisional.model_dump(
            mode="json", exclude={"assertion_sha256"}
        )
        return IntegrationAuthorityAssertionV1.model_validate(
            {
                **provisional.model_dump(mode="json"),
                "assertion_sha256": canonical_sha256(digest_payload),
            }
        )

    if not lock_registry:
        return build()
    with coordination_claims.claim_registry_lock(claims_dir):
        return build()


def validate_integration_authority(
    assertion: IntegrationAuthorityAssertionV1,
    *,
    expected_target: IntegrationTargetV1,
    agent: str,
    repo_root: Path,
    claims_dir: Path | None = None,
    now: datetime | None = None,
    lock_registry: bool = True,
) -> None:
    """Reject a stale assertion or any change to target, owner, or claim bytes."""

    observed = (now or datetime.now(UTC)).astimezone(UTC)
    if assertion.target != expected_target:
        raise IntegrationAuthorityError(
            "integration target or trusted review spec changed after authority was asserted"
        )
    if assertion.valid_until <= observed:
        raise IntegrationAuthorityError("integration authority assertion is stale")
    session_id = resolve_native_session(agent)
    if assertion.claim.session_id != session_id or assertion.claim.agent != agent:
        raise IntegrationAuthorityError(
            "integration authority assertion belongs to another native session"
        )

    def validate() -> None:
        claim = _exact_active_claim(
            target=assertion.target,
            agent=agent,
            session_id=session_id,
            repo_root=repo_root.expanduser().resolve(),
            claims_dir=claims_dir,
            now=observed,
        )
        if _claim_binding(claim) != assertion.claim:
            raise IntegrationAuthorityError(
                "canonical claim changed after integration authority was asserted"
            )

    if not lock_registry:
        validate()
        return
    with coordination_claims.claim_registry_lock(claims_dir):
        validate()


@contextmanager
def integration_authority_guard(
    assertion: IntegrationAuthorityAssertionV1,
    *,
    expected_target: IntegrationTargetV1,
    agent: str,
    repo_root: Path,
    claims_dir: Path | None = None,
    now: datetime | None = None,
) -> Iterator[None]:
    """Hold claim custody stable across the final remote head CAS operation."""

    with coordination_claims.claim_registry_lock(claims_dir):
        validate_integration_authority(
            assertion,
            expected_target=expected_target,
            agent=agent,
            repo_root=repo_root,
            claims_dir=claims_dir,
            now=now,
            lock_registry=False,
        )
        yield
