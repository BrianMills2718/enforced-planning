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
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import yaml
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
    review_work_graph_sha256: str | None = Field(default=None, pattern=SHA256_PATTERN)
    review_work_unit_id: str | None = None

    @model_validator(mode="after")
    def _validate_review_authority(self) -> IntegrationTargetV1:
        if bool(self.review_work_graph_sha256) != bool(self.review_work_unit_id):
            raise ValueError("review spec work-graph and work-unit authority must be paired")
        return self


class IntegrationClaimBindingV1(_StrictModel):
    agent: Literal["codex", "claude-code", "openclaw"]
    session_id: str = Field(pattern=SESSION_PATTERN)
    scope: str = Field(min_length=1)
    claim_authority_sha256: str = Field(pattern=SHA256_PATTERN)
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
        if (self.valid_until - self.asserted_at).total_seconds() > MAX_ASSERTION_SECONDS:
            raise ValueError(
                f"integration assertion validity exceeds {MAX_ASSERTION_SECONDS} seconds"
            )
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


def _read_review_spec_identity(path: Path) -> tuple[str, str | None, str | None]:
    try:
        resolved = path.expanduser().resolve(strict=True)
        source = resolved.read_bytes()
        payload = json.loads(source)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrationAuthorityError(f"cannot parse trusted review spec: {exc}") from exc
    if not isinstance(payload, dict):
        raise IntegrationAuthorityError("trusted review spec must be a JSON object")
    graph = payload.get("work_graph_sha256")
    unit = payload.get("work_unit_id")
    if graph is not None and (
        not isinstance(graph, str)
        or len(graph) != 64
        or any(character not in "0123456789abcdef" for character in graph)
    ):
        raise IntegrationAuthorityError("trusted review spec work_graph_sha256 is invalid")
    if unit is not None and (not isinstance(unit, str) or not unit.strip()):
        raise IntegrationAuthorityError("trusted review spec work_unit_id is invalid")
    if bool(graph) != bool(unit):
        raise IntegrationAuthorityError(
            "trusted review spec work-graph and work-unit authority must be paired"
        )
    return hashlib.sha256(source).hexdigest(), graph, unit


def review_spec_sha256(path: Path) -> str:
    digest, _graph, _unit = _read_review_spec_identity(path)
    return digest


def _validate_review_spec_identity(target: IntegrationTargetV1, path: Path) -> None:
    digest, graph, unit = _read_review_spec_identity(path)
    if digest != target.review_spec_sha256:
        raise IntegrationAuthorityError("trusted review spec bytes changed")
    if (graph, unit) != (
        target.review_work_graph_sha256,
        target.review_work_unit_id,
    ):
        raise IntegrationAuthorityError("trusted review spec work-unit authority changed")


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


def _claim_authority_sha256(claim: coordination_claims.ClaimRecord) -> str:
    """Hash stable custody fields, excluding expected heartbeat/progress churn."""

    return canonical_sha256(
        {
            "agent": claim.agent,
            "projects": claim.projects,
            "scope": claim.scope,
            "claim_type": claim.claim_type,
            "write_paths": claim.write_paths,
            "worktree_path": claim.worktree_path,
            "repo_root": claim.repo_root,
            "branch": claim.branch,
            "session_id": claim.session_id,
            "parent_scope": claim.parent_scope,
            "plan_ref": claim.plan_ref,
            "start_revision": claim.start_revision,
            "plan_repo_root": claim.plan_repo_root,
            "plan_revision": claim.plan_revision,
            "plan_sha256": claim.plan_sha256,
            "work_unit_id": claim.work_unit_id,
            "work_graph_path": claim.work_graph_path,
            "work_graph_sha256": claim.work_graph_sha256,
            "approval_revisions": claim.approval_revisions,
        }
    )


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise IntegrationAuthorityError(
            f"cannot validate claimed Git identity ({' '.join(args)}): {detail}"
        )
    return result.stdout.strip()


def _validate_claimed_git_identity(
    claim: coordination_claims.ClaimRecord,
    *,
    target: IntegrationTargetV1,
    repo_root: Path,
) -> None:
    if not claim.worktree_path:
        raise IntegrationAuthorityError("integration claim has no worktree path")
    worktree = Path(claim.worktree_path).expanduser().resolve()
    if not worktree.is_dir():
        raise IntegrationAuthorityError("integration claim worktree is unavailable")
    observed_root = Path(_git_output(worktree, "rev-parse", "--show-toplevel")).resolve()
    if observed_root != worktree:
        raise IntegrationAuthorityError("claim worktree path is not the exact Git root")
    common = Path(_git_output(worktree, "rev-parse", "--git-common-dir"))
    if not common.is_absolute():
        common = (worktree / common).resolve()
    canonical_common = Path(_git_output(repo_root, "rev-parse", "--git-common-dir"))
    if not canonical_common.is_absolute():
        canonical_common = (repo_root / canonical_common).resolve()
    if common.resolve() != canonical_common.resolve():
        raise IntegrationAuthorityError("claim worktree belongs to a different Git repository")
    if _git_output(worktree, "symbolic-ref", "--short", "HEAD") != target.branch:
        raise IntegrationAuthorityError("claim worktree is checked out on a different branch")
    if _git_output(worktree, "rev-parse", "HEAD") != target.head_sha:
        raise IntegrationAuthorityError("claim worktree HEAD differs from reviewed PR head")
    if _git_output(worktree, "status", "--porcelain=v1", "--untracked-files=all"):
        raise IntegrationAuthorityError("claim worktree is dirty at integration authority gate")


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
    active_claims = _strict_active_claims(
        project=target.project, claims_dir=claims_dir, now=now
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
    if (claim.work_graph_sha256, claim.work_unit_id) != (
        target.review_work_graph_sha256,
        target.review_work_unit_id,
    ):
        raise IntegrationAuthorityError(
            "trusted review spec work-unit authority differs from canonical claim"
        )
    _validate_claimed_git_identity(claim, target=target, repo_root=repo_root)
    return claim


def _strict_active_claims(
    *, project: str, claims_dir: Path | None, now: datetime
) -> list[coordination_claims.ClaimRecord]:
    """Load one complete locked registry view or fail on any malformed record."""

    root = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    if not root.exists():
        return []
    claims: list[coordination_claims.ClaimRecord] = []
    for claim_file in sorted(root.glob("*.yaml")):
        try:
            payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise IntegrationAuthorityError(
                f"canonical claim registry contains malformed YAML: {claim_file.name}"
            ) from exc
        if not isinstance(payload, dict):
            raise IntegrationAuthorityError(
                f"canonical claim registry contains a non-mapping record: {claim_file.name}"
            )
        try:
            claim = coordination_claims.normalize_claim(
                payload, source_file=str(claim_file)
            )
        except (TypeError, ValueError) as exc:
            raise IntegrationAuthorityError(
                f"canonical claim registry contains an invalid record: {claim_file.name}"
            ) from exc
        if claim is None:
            raise IntegrationAuthorityError(
                f"canonical claim registry contains an invalid record: {claim_file.name}"
            )
        expires_at = _parse_time(claim.expires_at)
        if expires_at is not None and expires_at < now:
            continue
        if claim.is_live() and project in claim.projects:
            claims.append(claim)
    return claims


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
        claim_authority_sha256=_claim_authority_sha256(claim),
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
    review_spec_path: Path,
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
    session_id = resolve_native_session(agent)
    resolved_root = repo_root.expanduser().resolve()

    def build(observed: datetime) -> IntegrationAuthorityAssertionV1:
        _validate_review_spec_identity(target, review_spec_path)
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
        observed = (now or datetime.now(UTC)).astimezone(UTC)
        return build(observed)
    with coordination_claims.claim_registry_lock(claims_dir):
        observed = (now or datetime.now(UTC)).astimezone(UTC)
        return build(observed)


def validate_integration_authority(
    assertion: IntegrationAuthorityAssertionV1,
    *,
    expected_target: IntegrationTargetV1,
    agent: str,
    repo_root: Path,
    review_spec_path: Path,
    claims_dir: Path | None = None,
    now: datetime | None = None,
    lock_registry: bool = True,
) -> None:
    """Reject a stale assertion or any change to target, owner, or claim bytes."""

    session_id = resolve_native_session(agent)
    if assertion.claim.session_id != session_id or assertion.claim.agent != agent:
        raise IntegrationAuthorityError(
            "integration authority assertion belongs to another native session"
        )

    def validate(observed: datetime) -> None:
        if assertion.target != expected_target:
            raise IntegrationAuthorityError(
                "integration target or trusted review spec changed after authority was asserted"
            )
        if assertion.valid_until <= observed:
            raise IntegrationAuthorityError("integration authority assertion is stale")
        _validate_review_spec_identity(assertion.target, review_spec_path)
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
        observed = (now or datetime.now(UTC)).astimezone(UTC)
        validate(observed)
        return
    with coordination_claims.claim_registry_lock(claims_dir):
        observed = (now or datetime.now(UTC)).astimezone(UTC)
        validate(observed)


@contextmanager
def integration_authority_guard(
    assertion: IntegrationAuthorityAssertionV1,
    *,
    expected_target: IntegrationTargetV1,
    agent: str,
    repo_root: Path,
    review_spec_path: Path,
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
            review_spec_path=review_spec_path,
            claims_dir=claims_dir,
            now=now,
            lock_registry=False,
        )
        yield
