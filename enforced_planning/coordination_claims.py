#!/usr/bin/env python3
"""Cross-brain coordination claims for multi-agent work.

Manages scope claims across agent brains (claude-code, codex, openclaw).
Claims are YAML files in ``~/.claude/coordination/claims/``.

The v2 model preserves backwards-compatible v1 loading while adding the narrow
write-scope metadata needed for real collision avoidance.

Usage:
    check_coordination_claims.py --check [--project PROJECT]
    check_coordination_claims.py --claim --agent AGENT --project PROJECT --scope SCOPE --intent INTENT [--plan PLAN] [--ttl-hours TTL]
    check_coordination_claims.py --release --agent AGENT --project PROJECT --scope SCOPE
    check_coordination_claims.py --list
    check_coordination_claims.py --prune
    check_coordination_claims.py --prune-completed
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import posixpath
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Literal, get_args

import yaml  # type: ignore[import-untyped]
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from enforced_planning import claim_mutation_receipts
from enforced_planning.claim_mutation_receipts import (
    CompletedClaimArchiveError,
    MutationAuditError,
)

_LOADED_WRITER_IDENTITY = claim_mutation_receipts.writer_identity(Path(__file__))

CLAIMS_DIR = Path.home() / ".claude" / "coordination" / "claims"
DEFAULT_TTL_HOURS = 24  # Sprints run 24h; 2h caused false-expiry conflicts mid-sprint
LIVE_STATUSES = {"active", "blocked", "handoff"}
COMPLETED_STATUSES = {"complete", "completed"}
SESSION_ENDED_STATUS = "session_ended"
CLOSEABLE_STATUSES = LIVE_STATUSES | {SESSION_ENDED_STATUS}
CLAIM_TYPES = {"program", "write", "review", "research"}
# `chatgpt` is the ChatGPT/Codex VS Code extension, admitted 2026-09-08. It is a
# real, actively used agent here, not a typo: on the day it was added it owned 10
# live dodaf lanes with trackers and had merged dozens of pull requests that day.
#
# It had been creating claims and session trackers through the Python API for
# some time. That API never validated `agent` -- only the argparse `choices` on
# the CLI did -- so the value flowed straight through. When `start_session`
# started validating the agent (PR #403, closing the hole that produced
# unretireable trackers), that silently blocked this agent from opening any new
# lane. Admitting it here is the correct repair: the validation is right, and the
# list it validated against was simply incomplete. Admitting it also makes those
# existing lanes closeable through ordinary `session-close` for the first time.
#
# It has no `STRICT_NATIVE_SESSION_ENV_KEYS` entry, so
# `validate_native_session_binding` no-ops for it and its `session_id` is a
# caller-supplied label rather than a native runtime marker. That is unchanged
# from how these lanes already worked; giving it a native marker would tighten
# identity further and is a separate improvement, not a prerequisite.
SUPPORTED_AGENTS = ("claude-code", "codex", "openclaw", "chatgpt")
STRICT_LIVE_METADATA_CLAIM_TYPES = {"program", "write", "review", "research"}
CURRENT_CLAIM_SCHEMA_VERSION = 6
BROAD_SCOPE_MODES = {"bootstrap", "bounded"}
BOOTSTRAP_AUTHORITY_DISABLED_SUFFIX = ".bootstrap-no-mutation-authority"
SESSION_TAKEOVER_RESERVATION_FIELD = "session_takeover_reservation"
CLAIM_REGISTRY_LOCK_TIMEOUT_SECONDS = 5.0
CLAIM_REGISTRY_LOCK_POLL_SECONDS = 0.05


class ClaimRegistryLockTimeout(TimeoutError):
    """The single local claim writer stayed busy beyond the bounded wait."""

# Directories whose contents are immutable, uniquely-named artifacts created by
# an atomic exclusive open. Two lanes appending to one of these cannot collide:
# different filenames, no shared file rewritten, and a clean git merge. Treating
# such a directory as an exclusive write surface blocks concurrent recording for
# no safety gain, which is how learnings capture kept dying on a claim conflict.
#
# A path is exempt only when writes to it are append-only ALL the way down. Add
# a prefix here solely when its writer creates new files and never modifies,
# renames, or deletes an existing one.
# Registers whose entries are added as new files and never rewritten in place.
# Two lanes adding different files here cannot clobber each other, so an overlap
# on one of these prefixes is not contention -- which is what the refusal message
# already tells operators ("an append-only store never contends with itself").
# policy/proposals earns its place by its own governing rule, "Preserve proposal
# history unless a proposal is explicitly superseded or retired": supersession is
# rare and deliberate, while the ordinary write is a new dated file. The push-time
# overlapping-write-claim check stays the backstop for the supersession case.
# NOTE: these are consumer-specific paths living in framework code. Making the
# list repository-configurable is the right long-term shape; it is deliberately
# not done here to keep this change to the observed defect.
APPEND_ONLY_WRITE_PREFIXES = (
    "learnings/entries",
    "learnings/invalid_entries",
    "policy/proposals",
)
CREATION_BLOCKING_HEALTH_ISSUES = {
    "missing_project",
    "missing_write_paths",
    "missing_branch",
    "missing_worktree_path",
    "missing_session_id",
    "missing_session_name",
    "missing_plan_ref",
    "missing_work_unit_id",
    "missing_work_graph_path",
    "missing_work_graph_sha256",
    "missing_start_revision",
    "invalid_start_revision",
    "missing_plan_repo_root",
    "invalid_plan_repo_root",
    "missing_plan_revision",
    "invalid_plan_revision",
    "missing_plan_sha256",
    "invalid_plan_sha256",
}
DEFAULT_HEARTBEAT_STALE_MINUTES = 120
DEFAULT_PROGRESS_STALE_MINUTES = 60
ProgressKind = Literal[
    "claim_started",
    "verified_commit",
    "accepted_artifact",
    "new_diagnostic",
    "integration_result",
]
PROGRESS_KINDS = frozenset(get_args(ProgressKind))
PROGRESS_FIELD_NAMES = (
    "progress_at",
    "progress_kind",
    "evidence_ref",
    "next_action",
    "expected_quiet_until",
    "quiet_reason",
)
CLAIM_WRITE_STAGING_MAX_AGE_SECONDS = 300
_LEGACY_CLAIM_TEMP_PATTERN = re.compile(r"^\..+\.ya?ml\.[A-Za-z0-9_-]+\.tmp$")
SESSION_ENV_KEYS = {
    "codex": ("CODEX_THREAD_ID",),
    # CLAUDE_CODE_SESSION_ID is the real per-conversation UUID Claude Code sets
    # in Bash-tool/hook subprocess environments. CLAUDE_SESSION_ID (no
    # "_CODE_") is never actually set by the runtime -- it only exists as a
    # skill-prompt ${...} template substitution -- so every session fell
    # through to CLAUDE_CODE_SSE_PORT, shared by every session the CLI
    # server spawns on one machine. See project-meta policy_friction.md
    # 2026-08-20 (worktree-per-branch / prewrite-claim-gate). This is the
    # canonical source; consumers vendor (copy-paste) this module rather
    # than installing it, so fixing this file does not by itself reach any
    # existing vendored copy -- see project-meta's
    # ACCRETION_DETECTOR_COVERAGE.md for per-repo fix status.
    "claude-code": ("CLAUDE_CODE_SESSION_ID", "CLAUDE_SESSION_ID", "CLAUDE_CODE_SSE_PORT"),
    "openclaw": ("OPENCLAW_SESSION_ID", "OPENCLAW_RUN_ID"),
}
STRICT_NATIVE_SESSION_ENV_KEYS = {
    "codex": "CODEX_THREAD_ID",
    "claude-code": "CLAUDE_CODE_SESSION_ID",
    "openclaw": "OPENCLAW_SESSION_ID",
}
GOAL_AUTHORITY_PATTERN = re.compile(r"^goal:[A-Za-z0-9][A-Za-z0-9._:-]*$")
START_REVISION_PATTERN = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")


class ProgressEventV1(BaseModel):
    """One explicit durable-advancement event for an owning live claim."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = "1.0"
    recorded_at: datetime
    kind: ProgressKind
    evidence_ref: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    expected_quiet_until: datetime | None = None
    quiet_reason: str | None = None

    @field_validator("recorded_at", "expected_quiet_until")
    @classmethod
    def _require_aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("progress timestamps must include a timezone")
        return value.astimezone(timezone.utc) if value is not None else None

    @field_validator("evidence_ref", "next_action", "quiet_reason")
    @classmethod
    def _strip_nonempty_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            raise ValueError("progress text fields must not be blank")
        return stripped

    @model_validator(mode="after")
    def _validate_quiet_interval(self) -> ProgressEventV1:
        quiet_values = (self.expected_quiet_until, self.quiet_reason)
        if any(value is not None for value in quiet_values) and not all(value is not None for value in quiet_values):
            raise ValueError("expected_quiet_until and quiet_reason must be supplied together")
        if self.expected_quiet_until is not None and self.expected_quiet_until <= self.recorded_at:
            raise ValueError("expected_quiet_until must be later than recorded_at")
        return self


@contextmanager
def claim_registry_lock(
    claims_dir: Path | None = None,
    *,
    timeout_seconds: float = CLAIM_REGISTRY_LOCK_TIMEOUT_SECONDS,
) -> Iterator[None]:
    """Serialize mutations, failing with an exact retry condition on contention."""

    if timeout_seconds < 0:
        raise ValueError("claim registry lock timeout_seconds must be non-negative")

    resolved_claims_dir = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    resolved_claims_dir.parent.mkdir(parents=True, exist_ok=True)
    lock_path = resolved_claims_dir.parent / f".{resolved_claims_dir.name}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        lock_path.chmod(0o600)
        deadline = time.monotonic() + timeout_seconds
        while True:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError as exc:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ClaimRegistryLockTimeout(
                        "Claim registry writer is contended at "
                        f"{lock_path}; no claim state changed. Retry after the current "
                        f"writer releases this lock (waited {timeout_seconds:g}s)."
                    ) from exc
                time.sleep(min(CLAIM_REGISTRY_LOCK_POLL_SECONDS, remaining))
        try:
            _prune_abandoned_claim_write_artifacts(resolved_claims_dir)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _claim_write_staging_dir(claims_dir: Path) -> Path:
    """Return same-filesystem staging outside the live claim registry."""

    return claims_dir.parent / f".{claims_dir.name}-write-staging"


def _prune_abandoned_claim_write_artifacts(
    claims_dir: Path,
    *,
    minimum_age_seconds: int = CLAIM_WRITE_STAGING_MAX_AGE_SECONDS,
) -> int:
    """Remove only old atomic-write artifacts from sanctioned claim writers."""

    now = time.time()
    staging_dir = _claim_write_staging_dir(claims_dir)
    candidates = [path for path in claims_dir.glob(".*.tmp") if _LEGACY_CLAIM_TEMP_PATTERN.fullmatch(path.name)]
    if staging_dir.exists():
        candidates.extend(staging_dir.glob("*.tmp"))
    removed = 0
    for candidate in candidates:
        try:
            age = now - candidate.lstat().st_mtime
        except FileNotFoundError:
            continue
        if age < minimum_age_seconds:
            continue
        if not (candidate.is_file() or candidate.is_symlink()):
            continue
        candidate.unlink(missing_ok=True)
        removed += 1
    return removed


def _atomic_write_claim(path: Path, payload: dict[str, Any]) -> None:
    """Replace one claim without exposing a truncated or partially written file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = _claim_write_staging_dir(path.parent)
    staging_dir.mkdir(parents=True, exist_ok=True)
    staging_dir.chmod(0o700)
    _prune_abandoned_claim_write_artifacts(path.parent)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=staging_dir,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            yaml.safe_dump(
                payload,
                handle,
                default_flow_style=False,
                sort_keys=False,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _atomic_restore_file(path: Path, content: bytes | None) -> None:
    """Restore exact prior bytes, or exact prior absence, after a failed transition."""

    if content is None:
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".rollback.tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def _replace_claim_and_refresh_projection_fail_atomic(
    *,
    claim_path: Path,
    payload: dict[str, Any],
    claims_dir: Path,
) -> tuple[str, str]:
    """Replace claim plus projection or restore both exact preflight states."""

    from enforced_planning.prewrite_claim_fast import projection_path_for

    projection_path = projection_path_for(claims_dir)
    prior_claim = claim_path.read_bytes() if claim_path.exists() else None
    prior_projection = projection_path.read_bytes() if projection_path.exists() else None
    try:
        _atomic_write_claim(claim_path, payload)
        return refresh_prewrite_authority_projection(claims_dir)
    except Exception:
        _atomic_restore_file(claim_path, prior_claim)
        _atomic_restore_file(projection_path, prior_projection)
        raise


def replace_claim_payloads_and_refresh_projection_fail_atomic(
    *,
    replacements: dict[Path, dict[str, Any]],
    claims_dir: Path,
) -> tuple[str, str]:
    """Replace a bounded claim set or restore every claim and the projection.

    The caller must hold ``claim_registry_lock``.  This is the multi-claim
    counterpart of the single-claim lifecycle primitive above; it exists for
    root-plus-descendant transitions and never selects the affected claims.
    """

    if not replacements:
        raise ValueError("claim replacement transaction requires at least one claim")
    resolved_claims_dir = claims_dir.expanduser().resolve()
    resolved_replacements = {
        path.expanduser().resolve(): payload for path, payload in replacements.items()
    }
    if any(path.parent != resolved_claims_dir for path in resolved_replacements):
        raise ValueError("claim replacement transaction cannot cross registries")

    from enforced_planning.prewrite_claim_fast import projection_path_for

    projection_path = projection_path_for(resolved_claims_dir)
    prior_claims = {
        path: path.read_bytes() if path.exists() else None for path in resolved_replacements
    }
    prior_projection = projection_path.read_bytes() if projection_path.exists() else None
    try:
        for path in sorted(resolved_replacements):
            _atomic_write_claim(path, resolved_replacements[path])
        return refresh_prewrite_authority_projection(resolved_claims_dir)
    except Exception:
        for path, content in prior_claims.items():
            _atomic_restore_file(path, content)
        _atomic_restore_file(projection_path, prior_projection)
        raise


def refresh_prewrite_authority_projection(
    claims_dir: Path | None = None,
) -> tuple[str, str]:
    """Regenerate the replaceable pre-write projection from canonical YAML."""

    from enforced_planning.prewrite_claim_fast import projection_path_for
    from enforced_planning.prewrite_claim_projection import write_projection

    resolved = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    projection = write_projection(claims_dir=resolved)
    return str(projection_path_for(resolved)), projection.registry_digest


def _registry_digest(claims_dir: Path) -> str:
    """Return the canonical digest used to bind derived projection state."""

    from enforced_planning.prewrite_claim_fast import registry_digest

    return registry_digest(claims_dir.expanduser().resolve())


def _registry_snapshot(claims_dir: Path) -> dict[str, bytes]:
    """Read every YAML authority record once, keyed by the digest's own key."""

    return {path.name: path.read_bytes() for path in sorted(claims_dir.expanduser().resolve().glob("*.yaml"))}


def _registry_digest_from_snapshot(snapshot: dict[str, bytes]) -> str:
    """Reproduce ``prewrite_claim_fast.registry_digest`` from an in-memory snapshot.

    Byte-for-byte equivalent to the on-disk computation: the same name/content
    fields, the same NUL separators, and the same ordering. ``registry_digest``
    sorts ``Path`` objects that all share one parent, which orders them by file
    name exactly as sorting the names does.
    """

    digest = hashlib.sha256()
    for name in sorted(snapshot):
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(snapshot[name])
        digest.update(b"\0")
    return digest.hexdigest()


class PruneRegistryDivergenceError(RuntimeError):
    """The registry moved underneath an in-progress prune, after a mutation applied.

    Unlike ``CompletedClaimArchiveError`` this is not a pre-mutation refusal:
    reaching it means claim files were already unlinked and receipts already
    recorded. It exists so a drain that loses agreement with its own authority
    stops immediately and visibly instead of writing further receipts whose
    digests no longer describe the registry.
    """


def record_claim_mutation(
    *,
    operation: "claim_mutation_receipts.MutationOperation",
    claims_dir: Path,
    registry_digest_before: str | None,
    target_project: str | None,
    target_scope: str | None,
    target_claim_path: Path | None,
    session_id: str | None,
    projection_digest_after: str | None,
    archive_transaction_id: str | None = None,
    known_registry_digest_after: str | None = None,
    known_projection_current_after: bool | None = None,
) -> "claim_mutation_receipts.ClaimMutationReceiptV1":
    """Persist one terminal receipt after a sanctioned YAML/projection mutation.

    The YAML registry remains authoritative. This append-only ledger records
    which loaded runtime performed the mutation and whether the projection it
    produced still matches that authority.
    """

    resolved_claims_dir = claims_dir.expanduser().resolve()
    known_values = (known_registry_digest_after, known_projection_current_after)
    if any(value is not None for value in known_values) and not all(value is not None for value in known_values):
        raise ValueError(
            "known registry digest and projection-current state must be supplied together"
        )
    if known_registry_digest_after is None:
        from enforced_planning.prewrite_claim_projection import projection_is_current

        registry_digest_after = _registry_digest(resolved_claims_dir)
        projection_current_after = projection_is_current(claims_dir=resolved_claims_dir)
    else:
        registry_digest_after = known_registry_digest_after
        projection_current_after = bool(known_projection_current_after)
    result: claim_mutation_receipts.MutationResult = (
        "applied_projection_current" if projection_current_after else "applied_projection_stale"
    )
    # Capture provenance when this module is loaded. Session closeout may
    # intentionally remove the worktree containing this source file before the
    # final receipt is emitted, but the loaded runtime remains the writer.
    writer_source_path, writer_source_sha256, writer_repo_root = _LOADED_WRITER_IDENTITY
    receipt = claim_mutation_receipts.ClaimMutationReceiptV1(
        operation=operation,
        result=result,
        writer_source_path=writer_source_path,
        writer_source_sha256=writer_source_sha256,
        writer_repo_root=writer_repo_root,
        process_id=os.getpid(),
        session_id=session_id,
        target_project=target_project,
        target_scope=target_scope,
        target_claim_path=str(target_claim_path) if target_claim_path else None,
        registry_digest_before=registry_digest_before,
        registry_digest_after=registry_digest_after,
        projection_digest_after=projection_digest_after,
        projection_current_after=projection_current_after,
        archive_transaction_id=archive_transaction_id,
        error_code=None,
    )
    try:
        claim_mutation_receipts.append_receipt(receipt)
    except OSError as exc:
        raise claim_mutation_receipts.MutationAuditError(
            operation=operation,
            target_project=target_project,
            target_scope=target_scope,
            registry_digest_after=registry_digest_after,
            projection_digest_after=projection_digest_after,
            projection_current_after=projection_current_after,
            cause=exc,
        ) from exc
    return receipt


def active_session_takeover_reservation(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Return one validated active custody-takeover reservation from raw claim state."""

    raw = payload.get(SESSION_TAKEOVER_RESERVATION_FIELD)
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise TypeError("claim has malformed session takeover reservation state")
    required_text = (
        "record_type",
        "predecessor_session_id",
        "successor_session_id",
        "worktree_path",
        "claim_epoch_sha256",
        "reserved_at",
    )
    if any(not isinstance(raw.get(field), str) or not raw[field] for field in required_text):
        raise ValueError("claim has incomplete session takeover reservation identity")
    if raw["record_type"] != "claim_session_takeover_reservation":
        raise ValueError("claim has an unsupported session takeover reservation record type")
    if re.fullmatch(r"[0-9a-f]{64}", raw["claim_epoch_sha256"]) is None:
        raise ValueError("claim takeover reservation has an invalid predecessor claim epoch")
    if not isinstance(raw.get("pid"), int) or raw["pid"] <= 1:
        raise ValueError("claim takeover reservation has an invalid predecessor PID")
    if not isinstance(raw.get("process_start_ticks"), int) or raw["process_start_ticks"] < 1:
        raise ValueError("claim takeover reservation has invalid process start ticks")
    return dict(raw)


def reject_mutation_during_session_takeover(
    payload: dict[str, Any],
    *,
    operation: str,
) -> None:
    """Fence predecessor claim mutations while an exact custody takeover is active."""

    reservation = active_session_takeover_reservation(payload)
    if reservation is None:
        return
    raise ValueError(
        f"Cannot {operation} claim while custody takeover is reserved for successor "
        f"{reservation['successor_session_id']!r} at predecessor claim epoch "
        f"{reservation['claim_epoch_sha256']}"
    )


def reserve_session_takeover(
    *,
    claim_file: Path,
    agent: str,
    project: str,
    scope: str,
    predecessor_session_id: str,
    successor_session_id: str,
    worktree_path: str,
    predecessor_pid: int,
    predecessor_process_start_ticks: int,
    reserved_at: str,
    pre_reservation_claim_bytes: bytes,
    claims_dir: Path | None = None,
) -> tuple[ClaimRecord, dict[str, Any], bytes, dict[str, Any]]:
    """Durably reserve one exact predecessor claim epoch before process fencing."""

    resolved_claims_dir = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    resolved_claim_file = claim_file.expanduser().resolve()
    expected_worktree = str(Path(worktree_path).expanduser().resolve())
    with claim_registry_lock(resolved_claims_dir):
        claim_bytes = resolved_claim_file.read_bytes()
        if claim_bytes != pre_reservation_claim_bytes:
            raise ValueError("claim changed before exact custody takeover reservation")
        payload = yaml.safe_load(claim_bytes)
        if not isinstance(payload, dict):
            raise TypeError("session takeover claim must be a YAML mapping")
        claim = normalize_claim(payload, source_file=str(resolved_claim_file))
        if claim is None or claim.status not in CLOSEABLE_STATUSES:
            raise ValueError("session takeover requires one closeable predecessor claim")
        if (
            claim.agent != agent
            or project not in claim.projects
            or claim.scope != scope
            or claim.session_id != predecessor_session_id
        ):
            raise ValueError("session takeover claim identity changed before reservation")
        if claim.worktree_path and str(Path(claim.worktree_path).expanduser().resolve()) != expected_worktree:
            raise ValueError("session takeover worktree changed before reservation")

        requested = {
            "record_type": "claim_session_takeover_reservation",
            "predecessor_session_id": predecessor_session_id,
            "successor_session_id": successor_session_id,
            "worktree_path": expected_worktree,
            "pid": predecessor_pid,
            "process_start_ticks": predecessor_process_start_ticks,
        }
        existing = active_session_takeover_reservation(payload)
        if existing is not None:
            if any(existing.get(field) != value for field, value in requested.items()):
                raise ValueError("claim is reserved for a different exact custody takeover")
            return claim, payload, claim_bytes, existing

        reservation = {
            **requested,
            "claim_epoch_sha256": hashlib.sha256(claim_bytes).hexdigest(),
            "reserved_at": reserved_at,
        }
        registry_digest_before = _registry_digest(resolved_claims_dir)
        payload[SESSION_TAKEOVER_RESERVATION_FIELD] = reservation
        _atomic_write_claim(resolved_claim_file, payload)
        reserved_claim_bytes = resolved_claim_file.read_bytes()
        _projection_path, projection_digest_after = refresh_prewrite_authority_projection(
            resolved_claims_dir
        )
        record_claim_mutation(
            operation="session_upsert",
            claims_dir=resolved_claims_dir,
            registry_digest_before=registry_digest_before,
            target_project=claim.primary_project(),
            target_scope=claim.scope,
            target_claim_path=resolved_claim_file,
            session_id=predecessor_session_id,
            projection_digest_after=projection_digest_after,
        )
        return claim, payload, reserved_claim_bytes, reservation


def abort_unfenced_session_takeover_reservation(
    *,
    claim_file: Path,
    agent: str,
    project: str,
    scope: str,
    successor_session_id: str,
    worktree_path: str,
    claims_dir: Path | None = None,
) -> dict[str, Any]:
    """Cancel one successor-owned reservation before fencing ever began.

    A reservation with a transfer journal has crossed the process-fence boundary
    and must be replayed, never discarded.  This narrow escape only restores a
    retryable session-ended lane when validation failed *before* that boundary.
    """

    resolved_claims_dir = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    resolved_claim_file = claim_file.expanduser().resolve()
    expected_worktree = str(Path(worktree_path).expanduser().resolve())
    with claim_registry_lock(resolved_claims_dir):
        raw_bytes = resolved_claim_file.read_bytes()
        payload = yaml.safe_load(raw_bytes)
        if not isinstance(payload, dict):
            raise TypeError("session takeover claim must be a YAML mapping")
        claim = normalize_claim(payload, source_file=str(resolved_claim_file))
        if claim is None or claim.status != SESSION_ENDED_STATUS:
            raise ValueError("unfenced takeover abort requires one exact session_ended claim")
        if (
            claim.agent != agent
            or project not in claim.projects
            or claim.scope != scope
            or (claim.worktree_path and str(Path(claim.worktree_path).expanduser().resolve()) != expected_worktree)
        ):
            raise ValueError("unfenced takeover abort claim identity changed")
        reservation = active_session_takeover_reservation(payload)
        if reservation is None:
            raise ValueError("claim has no active takeover reservation to abort")
        if reservation["successor_session_id"] != successor_session_id:
            raise ValueError("only the reserved successor session may abort this takeover")
        if reservation.get("transfer_journal") is not None:
            raise ValueError("journalized takeover reservation must be replayed, not aborted")
        registry_digest_before = _registry_digest(resolved_claims_dir)
        aborted = dict(reservation)
        payload.pop(SESSION_TAKEOVER_RESERVATION_FIELD)
        payload["last_unfenced_takeover_abort"] = {
            "record_type": "claim_session_takeover_abort",
            "reservation": aborted,
            "aborted_at": datetime.now(timezone.utc).isoformat(),
            "aborted_by_session_id": successor_session_id,
        }
        _atomic_write_claim(resolved_claim_file, payload)
        _projection_path, projection_digest_after = refresh_prewrite_authority_projection(resolved_claims_dir)
        record_claim_mutation(
            operation="session_upsert",
            claims_dir=resolved_claims_dir,
            registry_digest_before=registry_digest_before,
            target_project=claim.primary_project(),
            target_scope=claim.scope,
            target_claim_path=resolved_claim_file,
            session_id=claim.session_id,
            projection_digest_after=projection_digest_after,
        )
    return {"aborted_reservation": aborted, "claim_path": str(resolved_claim_file)}


def record_claim_narrow_mutation(
    *,
    claims_dir: Path,
    registry_digest_before: str,
    target_project: str,
    target_scope: str,
    target_claim_path: Path,
    session_id: str,
    projection_digest_after: str,
) -> "claim_mutation_receipts.NarrowClaimMutationReceiptV1":
    """Persist one narrow receipt without extending the shared v1 operation enum."""

    resolved_claims_dir = claims_dir.expanduser().resolve()
    from enforced_planning.prewrite_claim_projection import projection_is_current

    registry_digest_after = _registry_digest(resolved_claims_dir)
    projection_current_after = projection_is_current(claims_dir=resolved_claims_dir)
    writer_source_path, writer_source_sha256, writer_repo_root = _LOADED_WRITER_IDENTITY
    receipt = claim_mutation_receipts.NarrowClaimMutationReceiptV1(
        result=(
            "applied_projection_current"
            if projection_current_after
            else "applied_projection_stale"
        ),
        writer_source_path=writer_source_path,
        writer_source_sha256=writer_source_sha256,
        writer_repo_root=writer_repo_root,
        process_id=os.getpid(),
        session_id=session_id,
        target_project=target_project,
        target_scope=target_scope,
        target_claim_path=str(target_claim_path),
        registry_digest_before=registry_digest_before,
        registry_digest_after=registry_digest_after,
        projection_digest_after=projection_digest_after,
        projection_current_after=projection_current_after,
    )
    try:
        claim_mutation_receipts.append_narrow_receipt(receipt)
    except OSError as exc:
        raise claim_mutation_receipts.MutationAuditError(
            operation="narrow",
            target_project=target_project,
            target_scope=target_scope,
            registry_digest_after=registry_digest_after,
            projection_digest_after=projection_digest_after,
            projection_current_after=projection_current_after,
            cause=exc,
        ) from exc
    return receipt


@dataclass(frozen=True)
class PlanAuthorityBinding:
    """Resolved navigation-independent target and numbered-plan identities."""

    target_root: Path
    target_revision: str
    plan_root: Path
    plan_revision: str
    plan_repository_id: str
    external: bool


# --- Company Planning method-conformance receipt binding (Plan #48 WU-CP-MCR-002) ---
# Bind plan-backed claims to an exact Company Planning method-conformance receipt.
#
# Company Planning owns method profiles, compilation, validation, and the adoption
# decision (``PlanningMethodConformanceReceiptV1``, written only by its adoption
# gate). Enforced Planning owns claim admission. This module consumes the receipt
# without re-deciding method policy: it re-resolves the receipt bytes and the plan
# bytes at the exact plan-authority revision, and refuses a missing receipt, a
# digest mismatch, a non-passing receipt, a receipt for another plan, or a plan
# revision newer than its receipt.
#
# Requirement is per repository, declared structurally in ``meta-process.yaml``::
#
#     meta_process:
#       plans:
#         method_conformance:
#           mode: required   # or: off (default)
#
# With ``mode: off`` a claim may still cite a receipt, and the citation is
# verified the same way; it can never be cited by an explicitly unplanned claim.
# Consumer contract: company-planning
# ``plugins/company-planning/contracts/method-conformance/README.md``.

RECEIPT_SCHEMA_VERSION = "planning-method-conformance-receipt.v1"
RECEIPT_RECORD_TYPE = "planning_method_conformance_receipt"
METHOD_FRONT_MATTER_KEY = "method_conformance_receipt"
_RECEIPT_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MethodConformanceRefusal(ValueError):
    """A claim-admission refusal with one stable reason code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"method conformance refused ({code}): {message}")
        self.code = code


class MethodConformanceBindingV1(BaseModel):
    """The exact receipt identity a plan-backed claim retains."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0.0"] = "1.0.0"
    mode: Literal["required", "off"]
    plan_path: str
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    plan_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    receipt_path: str
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    receipt_id: str
    route: str
    profile_revision: str
    checklist_definition_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _method_git_show(root: Path, revision: str, path: str) -> bytes | None:
    completed = subprocess.run(
        ["git", "--no-replace-objects", "-C", str(root), "show", f"{revision}:{path}"],
        capture_output=True,
        check=False,
    )
    return completed.stdout if completed.returncode == 0 else None


def _method_repo_relative(path: str, label: str) -> str:
    normalized = PurePosixPath(path.replace("\\", "/"))
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise MethodConformanceRefusal("method_receipt_invalid", f"{label} {path!r} must be repository-relative")
    return normalized.as_posix()


def method_conformance_mode(plan_root: Path, revision: str) -> Literal["required", "off"]:
    """Read the repository's structural requirement at the exact plan revision."""

    content = _method_git_show(plan_root, revision, "meta-process.yaml")
    if content is None:
        return "off"
    payload = yaml.safe_load(content) or {}
    meta = payload.get("meta_process", payload) if isinstance(payload, dict) else {}
    plans = meta.get("plans", {}) if isinstance(meta, dict) else {}
    setting = plans.get("method_conformance") if isinstance(plans, dict) else None
    if setting is None:
        return "off"
    mode = setting.get("mode") if isinstance(setting, dict) else None
    if mode not in ("required", "off"):
        raise MethodConformanceRefusal(
            "invalid_method_conformance_config",
            "meta-process.yaml plans.method_conformance.mode must be 'required' or 'off'",
        )
    return mode


def _method_front_matter(content: str) -> dict[str, Any]:
    if not content.startswith("---\n"):
        return {}
    end = content.find("\n---", 4)
    if end < 0:
        return {}
    loaded = yaml.safe_load(content[4:end])
    return loaded if isinstance(loaded, dict) else {}


def _plan_number_from_path(path: str) -> int | None:
    match = re.fullmatch(r"(\d+)_.*\.md", PurePosixPath(path).name, re.IGNORECASE)
    return int(match.group(1)) if match else None


def resolve_method_conformance_binding(
    *,
    plan_root: Path | str,
    plan_revision: str,
    plan_number: int | None,
    receipt_ref: str | None,
    receipt_sha256: str | None,
) -> MethodConformanceBindingV1 | None:
    """Resolve the exact passing receipt a plan-backed claim names, or refuse.

    Returns ``None`` only when the repository does not require a receipt and the
    claim names none.
    """

    root = Path(plan_root).expanduser().resolve()
    mode = method_conformance_mode(root, plan_revision)
    if receipt_ref is None and receipt_sha256 is None:
        if mode == "required":
            raise MethodConformanceRefusal(
                "missing_method_receipt",
                "this repository requires every plan-backed claim to name its passing Company Planning "
                "method-conformance receipt: pass --method-receipt <path> and --method-receipt-sha256 <digest> "
                "from the plan's adoption decision",
            )
        return None
    if receipt_ref is None or receipt_sha256 is None:
        raise MethodConformanceRefusal(
            "missing_method_receipt", "--method-receipt and --method-receipt-sha256 must be given together"
        )
    if _RECEIPT_SHA256.fullmatch(receipt_sha256) is None:
        raise MethodConformanceRefusal("method_receipt_digest_mismatch", "receipt digest must be 64 lowercase hex")
    receipt_path = _method_repo_relative(receipt_ref, "receipt path")
    receipt_bytes = _method_git_show(root, plan_revision, receipt_path)
    if receipt_bytes is None:
        raise MethodConformanceRefusal(
            "method_receipt_missing", f"receipt {receipt_path} is not committed at plan revision {plan_revision}"
        )
    observed = hashlib.sha256(receipt_bytes).hexdigest()
    if observed != receipt_sha256:
        raise MethodConformanceRefusal(
            "method_receipt_digest_mismatch",
            f"receipt {receipt_path} at {plan_revision} has sha256 {observed}, not the claimed {receipt_sha256}",
        )
    try:
        receipt = json.loads(receipt_bytes)
    except json.JSONDecodeError as exc:
        raise MethodConformanceRefusal("method_receipt_invalid", f"receipt is not JSON: {exc}") from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("schema_version") != RECEIPT_SCHEMA_VERSION
        or receipt.get("record_type") != RECEIPT_RECORD_TYPE
    ):
        raise MethodConformanceRefusal("method_receipt_invalid", "not a PlanningMethodConformanceReceiptV1")
    if receipt.get("result") != "pass":
        raise MethodConformanceRefusal(
            "method_receipt_not_passing",
            f"receipt result is {receipt.get('result')!r}; only a passing receipt admits a plan-backed claim",
        )
    plan = receipt.get("plan") or {}
    plan_path = _method_repo_relative(str(plan.get("plan_ref") or ""), "receipt plan_ref")
    if plan_number is not None and _plan_number_from_path(plan_path) != plan_number:
        raise MethodConformanceRefusal(
            "method_receipt_plan_mismatch", f"receipt is for {plan_path}, not plan #{plan_number}"
        )
    plan_bytes = _method_git_show(root, plan_revision, plan_path)
    if plan_bytes is None:
        raise MethodConformanceRefusal("method_receipt_plan_missing", f"plan {plan_path} is absent at {plan_revision}")
    plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    if plan_sha256 != plan.get("plan_sha256"):
        raise MethodConformanceRefusal(
            "stale_plan_revision",
            f"plan {plan_path} changed after its receipt (now sha256 {plan_sha256}); re-run Company Planning "
            "adoption for this revision before claiming",
        )
    declared = _method_front_matter(plan_bytes.decode("utf-8")).get(METHOD_FRONT_MATTER_KEY)
    if declared != receipt_path:
        raise MethodConformanceRefusal(
            "method_receipt_not_declared_by_plan",
            f"plan front matter declares {METHOD_FRONT_MATTER_KEY}={declared!r}, not {receipt_path!r}",
        )
    checklist = receipt.get("checklist") or {}
    profile = receipt.get("profile") or {}
    return MethodConformanceBindingV1(
        mode=mode,
        plan_path=plan_path,
        plan_sha256=plan_sha256,
        plan_revision=plan_revision,
        receipt_path=receipt_path,
        receipt_sha256=receipt_sha256,
        receipt_id=str(receipt.get("receipt_id")),
        route=str(receipt.get("route")),
        profile_revision=str(profile.get("revision")),
        checklist_definition_sha256=str(checklist.get("definition_sha256")),
    )


@dataclass(frozen=True)
class CanonicalWorkUnitBinding:
    """Exact target-graph and optional external-plan authority custody."""

    work_graph_sha256: str
    approval_revisions: tuple[str, ...]
    start_revision: str
    plan_repo_root: str | None = None
    plan_revision: str | None = None
    plan_sha256: str | None = None
    method_conformance: MethodConformanceBindingV1 | None = None

    def __iter__(self) -> Iterator[object]:
        """Retain the historical three-value unpacking API for local consumers."""

        yield self.work_graph_sha256
        yield self.approval_revisions
        yield self.start_revision


def coerce_canonical_work_unit_binding(
    binding: CanonicalWorkUnitBinding | tuple[str, tuple[str, ...], str],
) -> CanonicalWorkUnitBinding:
    """Adapt legacy test/consumer triples while callers migrate to typed custody."""

    if isinstance(binding, CanonicalWorkUnitBinding):
        return binding
    graph_sha256, approvals, start_revision = binding
    return CanonicalWorkUnitBinding(graph_sha256, approvals, start_revision)


@dataclass(frozen=True)
class ClaimRecord:
    """Normalized coordination claim record used across readable schema versions."""

    agent: str
    claimed_at: str | None
    expires_at: str | None
    projects: list[str]
    scope: str
    intent: str
    claim_type: str
    write_paths: list[str]
    read_paths: list[str]
    worktree_path: str | None
    repo_root: str | None
    branch: str | None
    session_name: str | None
    broader_goal: str | None
    tracker_path: str | None
    session_id: str | None
    heartbeat_at: str | None
    status: str
    updated_at: str | None
    parent_scope: str | None
    notes: str | None
    plan_ref: str | None
    source_file: str | None
    schema_version: int
    start_revision: str | None = None
    plan_repo_root: str | None = None
    plan_revision: str | None = None
    plan_sha256: str | None = None
    work_unit_id: str | None = None
    work_graph_path: str | None = None
    work_graph_sha256: str | None = None
    approval_revisions: tuple[str, ...] = ()
    parallel_root_authorized: bool = False
    progress_at: str | None = None
    progress_kind: str | None = None
    evidence_ref: str | None = None
    next_action: str | None = None
    expected_quiet_until: str | None = None
    quiet_reason: str | None = None
    broad_scope_mode: str | None = None
    broad_scope_reason: str | None = None
    target_worktree_path: str | None = None
    contact_ref: str | None = None
    new_files: tuple[str, ...] = ()
    method_receipt_ref: str | None = None
    method_receipt_sha256: str | None = None

    def primary_project(self) -> str | None:
        """Return the first project for CLI compatibility surfaces."""
        return self.projects[0] if self.projects else None

    def is_live(self) -> bool:
        """Return whether the claim should participate in active coordination."""
        return self.status in LIVE_STATUSES

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON/YAML-safe dictionary for reporting and persistence."""
        data = asdict(self)
        data["project"] = self.primary_project()
        return data


@dataclass(frozen=True)
class ClaimInteraction:
    """Describe how one candidate claim interacts with another active claim."""

    severity: str
    reason: str
    other_agent: str
    other_scope: str
    other_claim_type: str
    projects: list[str]
    overlapping_write_paths: list[str]
    other_source_file: str | None
    other_session_id: str | None = None
    other_session_last_active_at: datetime | None = None
    overlap_relations: tuple[str, ...] = ()
    reservation_kind: str | None = None
    other_broad_scope_mode: str | None = None
    current_diff_disjoint: bool | None = None
    other_contact_ref: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe interaction summary."""
        data = asdict(self)
        if self.other_session_last_active_at is not None:
            data["other_session_last_active_at"] = self.other_session_last_active_at.isoformat()
        return data


@dataclass(frozen=True)
class NarrowClaimResult:
    """Committed result of one owner/session-bound subset-only narrowing."""

    project: str
    scope: str
    session_id: str
    old_write_paths: tuple[str, ...]
    new_write_paths: tuple[str, ...]
    broad_scope_mode: str | None
    projection_path: str
    projection_digest: str
    receipt_id: str

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe narrowing result."""
        return asdict(self)


@dataclass(frozen=True)
class ClaimCheckResult:
    """Structured result for candidate-vs-active-claims evaluation."""

    candidate: ClaimRecord
    interactions: list[ClaimInteraction]

    @property
    def hard_conflicts(self) -> list[ClaimInteraction]:
        """Return hard-conflict interactions only."""
        return [item for item in self.interactions if item.severity == "hard_conflict"]

    def continuation(self) -> dict[str, Any]:
        """Describe safe work that remains outside path-local claim conflicts.

        Claim evaluation can determine whether this candidate is blocked on
        particular write paths. It cannot determine whether the caller's whole
        authorized goal has exhausted its ready queue, so a claim collision is
        never reported as a whole-goal blocker.
        """
        conflicts = self.hard_conflicts
        blocked_paths = sorted(
            {
                overlap.split(" <-> ", 1)[0].removeprefix("yours=")
                for conflict in conflicts
                for overlap in conflict.overlapping_write_paths
            }
        )
        writable_paths = sorted(
            {
                _normalize_repo_path(path)
                for path in self.candidate.write_paths
                if _normalize_repo_path(path) not in blocked_paths
            }
        )
        integration_owners = sorted({(conflict.other_agent, conflict.other_scope) for conflict in conflicts})
        if not conflicts:
            recommended_next_action = "Proceed with the candidate claim."
        elif writable_paths:
            recommended_next_action = (
                "Remove or defer the blocked paths, claim the remaining writable paths, "
                "and continue. Record an authority-reconciliation obligation when the "
                "deferred path indexes or governs the completed artifact."
            )
        else:
            recommended_next_action = (
                "This candidate is path-blocked. Checkpoint any completed work and move "
                "to another authorized ready work unit; report the whole goal blocked only "
                "after its complete ready queue has been evaluated."
            )
        return {
            "state": "integration_wait" if conflicts else "ready",
            "goal_blocked": False,
            "blocked_paths": blocked_paths,
            "writable_paths": writable_paths,
            "integration_owners": [{"agent": agent, "scope": scope} for agent, scope in integration_owners],
            "recommended_next_action": recommended_next_action,
        }

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe check result."""
        return {
            "candidate": self.candidate.to_dict(),
            "interactions": [item.to_dict() for item in self.interactions],
            "has_hard_conflict": bool(self.hard_conflicts),
            "continuation": self.continuation(),
        }


def is_goal_authority_ref(plan_ref: str | None) -> bool:
    """Return whether a ref names one explicit non-plan outcome authority."""

    return isinstance(plan_ref, str) and GOAL_AUTHORITY_PATTERN.fullmatch(plan_ref.strip()) is not None


def requires_work_graph(plan_ref: str | None) -> bool:
    """Return whether write ownership names plan-like authority needing a graph."""

    return (
        isinstance(plan_ref, str)
        and bool(plan_ref.strip())
        and plan_ref.strip() != "UNPLANNED"
        and not is_goal_authority_ref(plan_ref)
    )


def _normalized_repository_id(value: str) -> str:
    """Normalize repository identity spellings used by qualified plan refs."""

    return value.strip().lower().replace("_", "-")


def _qualified_plan_repository(plan_ref: str | None) -> str | None:
    """Return the explicit authority repository from ``repository#number``."""

    if not isinstance(plan_ref, str):
        return None
    match = re.fullmatch(r"\s*([A-Za-z0-9_.-]+)#0*\d+\s*", plan_ref)
    return _normalized_repository_id(match.group(1)) if match else None


def _claim_uses_external_plan_authority(claim: ClaimRecord) -> bool:
    """Return whether a claim's qualified plan belongs to another project."""

    plan_repository = _qualified_plan_repository(claim.plan_ref)
    target_project = claim.primary_project()
    return bool(plan_repository and target_project and plan_repository != _normalized_repository_id(target_project))


def claim_health_issues(claim: ClaimRecord) -> list[str]:
    """Return machine-readable health issues for one normalized claim."""
    issues: list[str] = []
    if not claim.projects:
        issues.append("missing_project")
    if claim.claim_type == "write" and not claim.write_paths:
        issues.append("missing_write_paths")
    if claim.is_live() and claim.claim_type in STRICT_LIVE_METADATA_CLAIM_TYPES:
        if not claim.branch:
            issues.append("missing_branch")
        if not claim.worktree_path:
            issues.append("missing_worktree_path")
        if not claim.session_id:
            issues.append("missing_session_id")
        if not claim.session_name:
            issues.append("missing_session_name")
        if not claim.plan_ref:
            issues.append("missing_plan_ref")
        if claim.plan_ref and claim.session_id:
            if not claim.repo_root:
                issues.append("missing_repo_root")
            if not claim.broader_goal:
                issues.append("missing_broader_goal")
            if not claim.tracker_path:
                # tracker_path being unset here is a legitimate staged
                # reservation, not always a defect -- see "tracker_path's
                # three lifecycle states" in
                # docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md before
                # moving this into CREATION_BLOCKING_HEALTH_ISSUES or having
                # a caller pre-set tracker_path to a path nothing has written
                # yet (crashes start_session()'s resume-reload instead).
                issues.append("missing_tracker_path")
        if claim.schema_version >= 3 and claim.write_paths and requires_work_graph(claim.plan_ref):
            if not claim.work_unit_id:
                issues.append("missing_work_unit_id")
            if not claim.work_graph_path:
                issues.append("missing_work_graph_path")
            if not claim.work_graph_sha256:
                issues.append("missing_work_graph_sha256")
        if claim.schema_version >= 4 and claim.write_paths and requires_work_graph(claim.plan_ref):
            if not claim.start_revision:
                issues.append("missing_start_revision")
            elif START_REVISION_PATTERN.fullmatch(claim.start_revision) is None:
                issues.append("invalid_start_revision")
        if claim.write_paths and _claim_uses_external_plan_authority(claim):
            if not claim.plan_repo_root:
                issues.append("missing_plan_repo_root")
            elif not Path(claim.plan_repo_root).is_absolute():
                issues.append("invalid_plan_repo_root")
            if not claim.plan_revision:
                issues.append("missing_plan_revision")
            elif START_REVISION_PATTERN.fullmatch(claim.plan_revision) is None:
                issues.append("invalid_plan_revision")
            if not claim.plan_sha256:
                issues.append("missing_plan_sha256")
            elif re.fullmatch(r"[0-9a-f]{64}", claim.plan_sha256) is None:
                issues.append("invalid_plan_sha256")
    try:
        broad_issues = _broad_scope_contract_issues(claim)
        issues.extend(issue for issue in broad_issues if issue != "legacy_broad_scope_unclassified")
        if claim.broad_scope_mode == "bootstrap" and not broad_issues:
            issues.append("bootstrap_broad_claim_requires_narrowing")
    except ValueError as exc:
        issues.append(str(exc).split(":", 1)[0])
    return issues


def claim_health_status(claim: ClaimRecord) -> str:
    """Classify one claim as healthy or weak for registry/reporting surfaces."""
    return "weak" if claim_health_issues(claim) else "healthy"


def normalize_plan_identity(plan_ref: str | None) -> str | None:
    """Return one stable numbered-plan identity from descriptive plan text."""

    if not isinstance(plan_ref, str):
        return None
    qualified = re.fullmatch(
        r"\s*([A-Za-z0-9_.-]+)#0*(\d+)\s*",
        plan_ref,
        flags=re.IGNORECASE,
    )
    if qualified:
        project = qualified.group(1).lower().replace("_", "-")
        return f"{project}#{int(qualified.group(2))}"
    match = re.search(r"\bPlan\s*#\s*0*(\d+)\b", plan_ref, flags=re.IGNORECASE)
    if not match:
        return None
    return f"Plan #{int(match.group(1))}"


def _same_claim(left: ClaimRecord, right: ClaimRecord) -> bool:
    """Return whether two records identify the same canonical claim slot."""

    return left.agent == right.agent and left.primary_project() == right.primary_project() and left.scope == right.scope


def claim_hierarchy_issues(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> list[str]:
    """Validate one claim against the existing root-program hierarchy.

    A single live session remains valid on its own. Once execution for the same
    project and normalized numbered plan becomes parallel, exactly one
    unparented program claim coordinates every other claim through
    ``parent_scope``.
    """

    if not claim.is_live() or not claim.session_id:
        return []
    project = claim.primary_project()
    plan_identity = normalize_plan_identity(claim.plan_ref)
    if not project or not plan_identity:
        return []

    issues: list[str] = []
    if claim.parent_scope:
        if claim.parent_scope == claim.scope:
            issues.append("self_parent_scope")
        parents = [
            other
            for other in active_claims
            if other.is_live()
            and other.primary_project() == project
            and other.scope == claim.parent_scope
            and not _same_claim(other, claim)
        ]
        if not parents:
            issues.append("missing_parent_claim")
        elif len(parents) > 1:
            issues.append("ambiguous_parent_scope")
        else:
            parent = parents[0]
            if parent.claim_type != "program":
                issues.append("parent_not_program")
            if not parent.session_id or claim_health_issues(parent):
                issues.append("parent_not_healthy")
            if normalize_plan_identity(parent.plan_ref) != plan_identity:
                issues.append("parent_plan_mismatch")

    cohort = [
        other
        for other in active_claims
        if other.is_live()
        and other.session_id
        and other.primary_project() == project
        and normalize_plan_identity(other.plan_ref) == plan_identity
    ]
    if not any(_same_claim(other, claim) for other in cohort):
        cohort.append(claim)
    if len(cohort) < 2:
        return list(dict.fromkeys(issues))

    roots = [other for other in cohort if other.claim_type == "program" and not other.parent_scope]
    if not roots:
        issues.append("missing_program_root")
    elif len(roots) > 1:
        issues.append("multiple_program_roots")
    else:
        root = roots[0]
        if not _same_claim(root, claim):
            if not claim.parent_scope:
                issues.append("missing_parent_scope")
            elif claim.parent_scope != root.scope:
                issues.append("wrong_parent_scope")
    return list(dict.fromkeys(issues))


def coordination_health_issues(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> list[str]:
    """Return local metadata plus cross-claim hierarchy health issues."""

    return list(dict.fromkeys(claim_health_issues(claim) + claim_hierarchy_issues(claim, active_claims=active_claims)))


def validate_claim_hierarchy_for_creation(
    candidate: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> None:
    """Reject a new or refreshed session claim that would be hierarchically invalid."""

    prospective = [claim for claim in active_claims if not _same_claim(claim, candidate)] + [candidate]
    issues = claim_hierarchy_issues(candidate, active_claims=prospective)
    if issues:
        raise ValueError(
            f"Invalid plan claim hierarchy for {candidate.primary_project()}:{candidate.scope}: {', '.join(issues)}"
        )


def session_root_conflicts(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> list[ClaimRecord]:
    """Return other unparented lanes owned by the exact runtime session.

    Claim type classifies the work and its conflict semantics; it does not
    determine whether a lane is a session root. Any live claim without
    ``parent_scope`` is an ownership root for this lifecycle guard.
    """

    if not claim.is_live() or not claim.session_id or claim.parent_scope:
        return []
    return sorted(
        (
            other
            for other in active_claims
            if other.is_live()
            and other.session_id == claim.session_id
            and not other.parent_scope
            and not _same_claim(other, claim)
        ),
        key=lambda item: (item.primary_project() or "", item.scope),
    )


def normalize_parent_scope(parent_scope: str | None, project: str | None) -> str | None:
    """Store a parent scope as the bare scope its parent claim records.

    The root-lane error prints lanes as ``<project>:<scope>`` and tells the
    agent to start a child with ``--parent-scope``; agents then pass that
    printed form. Every parent lookup compares against the bare ``scope``, so a
    prefixed value never matched and the child could never be closed
    (brent-chatgpt, 2026-10-02). Strip the claim's own project prefix.
    """

    if not parent_scope or not project:
        return parent_scope
    prefix = f"{project}:"
    return parent_scope[len(prefix):] if parent_scope.startswith(prefix) else parent_scope


def validate_session_root_for_creation(
    candidate: ClaimRecord,
    *,
    active_claims: list[ClaimRecord],
) -> None:
    """Reject accidental tangent roots while preserving explicit parallelism."""

    conflicts = session_root_conflicts(candidate, active_claims=active_claims)
    if not conflicts or candidate.parallel_root_authorized:
        return
    identities = ", ".join(f"{claim.primary_project()}:{claim.scope}" for claim in conflicts)
    raise ValueError(
        "Runtime session already owns an unresolved root lane: "
        f"{identities}. Start a child with --parent-scope, close/transfer the "
        "existing root, or pass --allow-parallel for intentional parallel roots."
    )


def validate_no_preserved_lane_conflict(
    candidate: ClaimRecord,
    *,
    claims: list[ClaimRecord],
) -> None:
    """Require explicit recovery before replacing preserved ended work."""

    candidate_project = candidate.primary_project()
    candidate_plan = normalize_plan_identity(candidate.plan_ref)
    conflicts: list[ClaimRecord] = []
    for other in claims:
        if other.status != SESSION_ENDED_STATUS or _same_claim(other, candidate):
            continue
        if candidate_project not in other.projects:
            continue
        same_plan = bool(candidate_plan and normalize_plan_identity(other.plan_ref) == candidate_plan)
        write_overlap = bool(_compute_overlapping_write_paths(candidate, other))
        if same_plan or write_overlap:
            conflicts.append(other)
    if not conflicts:
        return
    identities = ", ".join(f"{claim.primary_project()}:{claim.scope}" for claim in conflicts)
    raise ValueError(
        "Preserved session-ended lane(s) still require disposition: "
        f"{identities}. Resume/take over the existing lane or close it through "
        "the sanctioned merge/recovery path before creating a replacement. "
        "If the ended lane's session tracker does not exist (resume and ordinary "
        "reconciliation both refuse it), dispose of it with: session_close.py "
        "--agent <agent> --project <project> --scope <scope> --session-id <your-native-session-id> "
        "--reconcile-session-ended --tracker-absent --claim-sha256 <sha256 of the claim file> "
        "--recovery-archive-dir <absolute empty dir under ~/archive> "
        "--disposition superseded --disposition-reason <why>."
    )


def _heartbeat_stale_after() -> timedelta:
    """Return the configured heartbeat freshness window."""
    raw = os.environ.get("COORDINATION_HEARTBEAT_STALE_MINUTES", "").strip()
    if not raw:
        return timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)
    try:
        minutes = float(raw)
    except ValueError:
        return timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)
    if minutes <= 0:
        return timedelta(minutes=DEFAULT_HEARTBEAT_STALE_MINUTES)
    return timedelta(minutes=minutes)


def _progress_stale_after() -> timedelta:
    """Return the configured durable-progress lease and fail on invalid policy."""

    raw = os.environ.get("COORDINATION_PROGRESS_STALE_MINUTES", "").strip()
    if not raw:
        return timedelta(minutes=DEFAULT_PROGRESS_STALE_MINUTES)
    try:
        minutes = float(raw)
    except ValueError as exc:
        raise ValueError("COORDINATION_PROGRESS_STALE_MINUTES must be a positive number") from exc
    if minutes <= 0:
        raise ValueError("COORDINATION_PROGRESS_STALE_MINUTES must be greater than zero")
    return timedelta(minutes=minutes)


def _run_git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run one git command for lifecycle diagnostics without throwing."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=False,
    )


def _resolve_repo_root_from_worktree_path(worktree_path: str | None) -> Path | None:
    """Resolve the canonical repo root from a claim worktree path when possible."""
    if not worktree_path:
        return None
    expanded = Path(worktree_path).expanduser()
    if expanded.exists():
        result = _run_git(expanded, ["rev-parse", "--show-toplevel"])
        if result.returncode == 0:
            return Path(result.stdout.strip())
    parent = expanded.parent
    if parent.name.endswith("_worktrees"):
        candidate = parent.parent / parent.name.removesuffix("_worktrees")
        if candidate.exists():
            result = _run_git(candidate, ["rev-parse", "--show-toplevel"])
            if result.returncode == 0:
                return Path(result.stdout.strip())
    return None


def _resolve_default_branch(repo_root: Path) -> str | None:
    """Return the canonical default branch name for one repo when resolvable."""
    remote_head = _run_git(repo_root, ["symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD"])
    if remote_head.returncode == 0:
        value = remote_head.stdout.strip()
        if value.startswith("origin/"):
            return value.split("/", 1)[1]
        if value:
            return value
    for candidate in ("main", "master"):
        branch_check = _run_git(repo_root, ["show-ref", "--verify", f"refs/heads/{candidate}"])
        if branch_check.returncode == 0:
            return candidate
    return None


def _default_integration_ref(repo_root: Path, default_branch: str) -> str:
    """Prefer the canonical remote default ref when it exists."""

    remote_ref = f"refs/remotes/origin/{default_branch}"
    remote_check = _run_git(repo_root, ["show-ref", "--verify", remote_ref])
    return remote_ref if remote_check.returncode == 0 else f"refs/heads/{default_branch}"


def resolve_default_integration_revision(repo_root: Path | str) -> str:
    """Resolve one full immutable commit for the canonical integration tip."""

    root = Path(repo_root).expanduser().resolve()
    default_branch = _resolve_default_branch(root)
    if not default_branch:
        raise ValueError("Unable to resolve canonical default branch")
    source_ref = _default_integration_ref(root, default_branch)
    resolved = _run_git(root, ["rev-parse", "--verify", f"{source_ref}^{{commit}}"])
    revision = resolved.stdout.strip()
    if resolved.returncode != 0 or START_REVISION_PATTERN.fullmatch(revision) is None:
        raise ValueError(f"Unable to resolve full canonical integration revision from {source_ref}")
    return revision


def validate_start_revision_targets(
    *,
    repo_root: Path | str,
    start_revision: str,
    branch: str | None,
    worktree_path: str | None,
    require_branch: bool = False,
    require_worktree: bool = False,
) -> None:
    """Require any existing execution identities to retain one start commit."""

    if START_REVISION_PATTERN.fullmatch(start_revision) is None:
        raise ValueError("start_revision must be one full lowercase Git object ID")
    root = Path(repo_root).expanduser().resolve()
    if branch:
        branch_format = _run_git(root, ["check-ref-format", "--branch", branch])
        if branch_format.returncode != 0:
            raise ValueError(f"invalid claimed branch identity {branch!r}")
        branch_ref = f"refs/heads/{branch}"
        branch_check = _run_git(
            root,
            ["rev-parse", "--verify", "--quiet", f"{branch_ref}^{{commit}}"],
        )
        if branch_check.returncode == 0:
            if branch_check.stdout.strip() != start_revision:
                raise ValueError(f"existing branch {branch!r} does not match retained start revision {start_revision}")
        elif branch_check.returncode != 1:
            raise ValueError(f"unable to inspect existing branch {branch!r}: {branch_check.stderr.strip()}")
        elif require_branch:
            raise ValueError(f"required branch {branch!r} does not exist")
    elif require_branch:
        raise ValueError("branch is required for start-revision custody")

    if worktree_path:
        worktree = Path(worktree_path).expanduser()
        if worktree.exists():
            root_common = _run_git(root, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
            worktree_common = _run_git(worktree, ["rev-parse", "--path-format=absolute", "--git-common-dir"])
            worktree_revision = _run_git(worktree, ["rev-parse", "--verify", "HEAD^{commit}"])
            worktree_branch = _run_git(worktree, ["symbolic-ref", "--quiet", "--short", "HEAD"])
            if (
                root_common.returncode != 0
                or worktree_common.returncode != 0
                or Path(root_common.stdout.strip()).resolve() != Path(worktree_common.stdout.strip()).resolve()
            ):
                raise ValueError(f"existing worktree path {worktree} is not attached to the claimed repository")
            if worktree_revision.returncode != 0 or worktree_revision.stdout.strip() != start_revision:
                raise ValueError(
                    f"existing worktree {worktree} does not match retained start revision {start_revision}"
                )
            if branch and (worktree_branch.returncode != 0 or worktree_branch.stdout.strip() != branch):
                raise ValueError(f"existing worktree {worktree} is not attached to claimed branch {branch!r}")
        elif require_worktree:
            raise ValueError(f"required worktree path {worktree} does not exist")
    elif require_worktree:
        raise ValueError("worktree_path is required for start-revision custody")


def _claimed_worktree_has_pending_changes(worktree_path: Path | None) -> bool:
    """Return whether pending tracked or untracked work is positively proven.

    Branch ancestry proves only that committed history has landed.  A live
    worktree can still contain unique staged, modified, or untracked work, so
    that positive evidence preserves the lane.  A failed status probe does not
    prove pending work and therefore preserves the existing fail-closed merged
    enforcement instead of silently authorizing writes.
    """

    if worktree_path is None or not worktree_path.exists():
        return False
    status = _run_git(worktree_path, ["status", "--porcelain", "--untracked-files=normal"])
    return status.returncode == 0 and bool(status.stdout.strip())


def claim_lifecycle_issues(claim: ClaimRecord) -> list[str]:
    """Return mechanically provable stale-lifecycle issues for one live claim."""
    if not claim.is_live():
        return []

    issues: list[str] = []
    repo_root = _resolve_repo_root_from_worktree_path(claim.worktree_path)
    worktree_path = Path(claim.worktree_path).expanduser() if claim.worktree_path else None

    if worktree_path is not None and not worktree_path.exists():
        issues.append("missing_worktree_on_disk")

    if claim.tracker_path:
        tracker_path = Path(claim.tracker_path).expanduser()
        if not tracker_path.exists():
            issues.append("missing_tracker_on_disk")
        elif _tracker_path_yaml_error(claim.tracker_path):
            # Creation now refuses these; this catches claims recorded before
            # that check existed, so an un-closeable lane is visible as an
            # unhealthy claim instead of as a traceback at closeout time.
            issues.append("tracker_path_not_yaml")

    if claim.branch and repo_root is not None:
        branch_ref = f"refs/heads/{claim.branch}"
        branch_check = _run_git(repo_root, ["show-ref", "--verify", branch_ref])
        branch_exists = branch_check.returncode == 0
        if not branch_exists:
            issues.append("missing_branch_ref")
        else:
            default_branch = _resolve_default_branch(repo_root)
            if default_branch and default_branch != claim.branch:
                branch_sha = _run_git(repo_root, ["rev-parse", branch_ref])
                default_ref = _default_integration_ref(repo_root, default_branch)
                default_sha = _run_git(repo_root, ["rev-parse", default_ref])
                if branch_sha.returncode != 0 or default_sha.returncode != 0:
                    return issues
                if claim.start_revision and branch_sha.stdout.strip() == claim.start_revision:
                    return issues
                if branch_sha.stdout.strip() == default_sha.stdout.strip():
                    return issues
                merged_check = _run_git(
                    repo_root,
                    ["merge-base", "--is-ancestor", branch_ref, default_ref],
                )
                if merged_check.returncode == 0 and not _claimed_worktree_has_pending_changes(worktree_path):
                    issues.append("branch_merged_to_default")

    return issues


def _claim_branch_unmerged_progress(claim: ClaimRecord) -> dict[str, Any] | None:
    """Return git evidence that a claim's branch holds real unmerged commits.

    Returns `None` when there is no such evidence: the claim has no
    branch/repo_root, the repo is unreachable, the branch no longer exists,
    the branch is identical to the default branch, or the branch is already
    a merged ancestor of the default branch. Deliberately reuses the same
    git primitives as `claim_lifecycle_issues` (`_resolve_default_branch`,
    `_default_integration_ref`, `_run_git`) rather than a second git-status
    implementation.
    """
    if not claim.branch or not claim.repo_root:
        return None
    repo_root = Path(claim.repo_root).expanduser()
    if not repo_root.is_dir():
        return None
    branch_ref = f"refs/heads/{claim.branch}"
    branch_check = _run_git(repo_root, ["show-ref", "--verify", branch_ref])
    if branch_check.returncode != 0:
        return None
    default_branch = _resolve_default_branch(repo_root)
    if not default_branch or default_branch == claim.branch:
        return None
    default_ref = _default_integration_ref(repo_root, default_branch)
    branch_sha = _run_git(repo_root, ["rev-parse", branch_ref])
    default_sha = _run_git(repo_root, ["rev-parse", default_ref])
    if branch_sha.returncode != 0 or default_sha.returncode != 0:
        return None
    if branch_sha.stdout.strip() == default_sha.stdout.strip():
        return None
    merged_check = _run_git(repo_root, ["merge-base", "--is-ancestor", branch_ref, default_ref])
    if merged_check.returncode == 0:
        return None
    ahead = _run_git(repo_root, ["rev-list", "--count", f"{default_ref}..{branch_ref}"])
    if ahead.returncode != 0:
        return None
    try:
        ahead_count = int(ahead.stdout.strip() or "0")
    except ValueError:
        return None
    if ahead_count <= 0:
        return None
    last_commit = _run_git(repo_root, ["log", "-1", "--format=%cI", branch_ref])
    return {
        "branch": claim.branch,
        "default_branch": default_branch,
        "ahead_of_default": ahead_count,
        "last_commit_at": last_commit.stdout.strip() if last_commit.returncode == 0 else None,
    }


def list_abandoned_claims(
    project: str | None = None,
    *,
    claims_dir: Path | None = None,
    min_ahead: int = 1,
) -> list[tuple[ClaimRecord, dict[str, Any]]]:
    """Surface EXPIRED claims whose branch still holds real unmerged commits.

    `_load_claims` (used by `check_claims`, `--list`, and `--list-stale`)
    intentionally excludes every expired claim before evaluation -- expired
    records stay on disk as read-only audit history until an explicit
    `--prune`/`--prune-stale` removes them. That is correct for
    conflict-checking (an expired claim should never block a new one), but it
    has a real blind spot: a claim that dies mid-task with substantial real,
    never-merged commits behind it becomes permanently invisible to every
    listing the moment it expires -- exactly the kind of abandoned-but-valuable
    work someone should be told about, not silently forgotten (observed
    2026-09-24: a 24-commit NYC-QC-1 QC pipeline branch sat dead for 9 days
    with no PR and no follow-up; see project-meta issue #2155).

    This walks the claims directory without the expiry filter, keeps only
    genuinely expired claims, and checks each one's actual git state so a
    false positive (branch already merged, deleted, or never diverged) is
    never reported. `--prune`/`--prune-stale` should run only after this,
    not before -- they delete the exact claim files this function reads.
    """
    resolved_claims_dir = claims_dir or CLAIMS_DIR
    if not resolved_claims_dir.exists():
        return []
    now = datetime.now(timezone.utc)
    abandoned: list[tuple[ClaimRecord, dict[str, Any]]] = []
    for claim_file in sorted(resolved_claims_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        expires_at = _parse_iso_datetime(data.get("expires_at"))
        if expires_at is None or expires_at >= now:
            continue
        claim = normalize_claim(data, source_file=str(claim_file))
        if claim is None:
            continue
        if project and project not in claim.projects:
            continue
        progress = _claim_branch_unmerged_progress(claim)
        if progress is not None and progress["ahead_of_default"] >= min_ahead:
            abandoned.append((claim, progress))
    return abandoned


def claim_liveness_issues(
    claim: ClaimRecord,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return stale-session issues derived from heartbeat freshness.

    Backward compatibility rule: a live claim with no `heartbeat_at` remains
    readable and does not become stale solely because the heartbeat rollout has
    not touched it yet. It is explicitly uninstrumented rather than healthy.
    """

    if not claim.is_live():
        return []
    if not claim.session_id:
        return []
    if not claim.heartbeat_at:
        return ["missing_session_heartbeat"]
    heartbeat = _parse_iso_datetime(claim.heartbeat_at)
    if heartbeat is None:
        return ["invalid_heartbeat_at"]
    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if reference_now - heartbeat > _heartbeat_stale_after():
        quiet_until = _parse_aware_iso_datetime(claim.expected_quiet_until)
        if (
            quiet_until is not None
            and isinstance(claim.quiet_reason, str)
            and claim.quiet_reason.strip()
            and reference_now < quiet_until
        ):
            return []
        return ["stale_session_heartbeat"]
    return []


def _parse_aware_iso_datetime(value: Any) -> datetime | None:
    """Parse a timezone-aware ISO timestamp without silently assuming UTC."""

    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed.astimezone(timezone.utc)


def build_progress_event(
    *,
    progress_kind: str,
    evidence_ref: str,
    next_action: str,
    expected_quiet_until: str | datetime | None = None,
    quiet_reason: str | None = None,
    progress_at: datetime | None = None,
) -> ProgressEventV1:
    """Validate one server-timestamped progress event before claim mutation."""

    observed_at = progress_at or datetime.now(timezone.utc)
    try:
        return ProgressEventV1(
            recorded_at=observed_at,
            kind=progress_kind,
            evidence_ref=evidence_ref,
            next_action=next_action,
            expected_quiet_until=expected_quiet_until,
            quiet_reason=quiet_reason,
        )
    except ValidationError as exc:
        raise ValueError(f"invalid progress event: {exc}") from exc


def _progress_event_payload(event: ProgressEventV1) -> dict[str, str | None]:
    """Flatten a validated event into the additive claim storage contract."""

    return {
        "progress_at": event.recorded_at.isoformat(),
        "progress_kind": event.kind,
        "evidence_ref": event.evidence_ref,
        "next_action": event.next_action,
        "expected_quiet_until": (
            event.expected_quiet_until.isoformat() if event.expected_quiet_until is not None else None
        ),
        "quiet_reason": event.quiet_reason,
    }


def claim_progress_issues(
    claim: ClaimRecord,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Return instrumentation defects or an expired durable-progress lease."""

    if not claim.is_live():
        return []
    core_values = (
        claim.progress_at,
        claim.progress_kind,
        claim.evidence_ref,
        claim.next_action,
    )
    quiet_values = (claim.expected_quiet_until, claim.quiet_reason)
    if not any(value is not None for value in core_values + quiet_values):
        return []

    issues: list[str] = []
    if not all(isinstance(value, str) and value.strip() for value in core_values):
        issues.append("incomplete_progress_event")

    progress_at = _parse_aware_iso_datetime(claim.progress_at)
    if claim.progress_at is not None and progress_at is None:
        issues.append("invalid_progress_at")
    if claim.progress_kind is not None and claim.progress_kind not in PROGRESS_KINDS:
        issues.append("invalid_progress_kind")

    quiet_until: datetime | None = None
    if any(value is not None for value in quiet_values):
        if not all(isinstance(value, str) and value.strip() for value in quiet_values):
            issues.append("incomplete_quiet_interval")
        else:
            quiet_until = _parse_aware_iso_datetime(claim.expected_quiet_until)
            if quiet_until is None:
                issues.append("invalid_expected_quiet_until")
            elif progress_at is not None and quiet_until <= progress_at:
                issues.append("invalid_quiet_interval")
            expires_at = _parse_aware_iso_datetime(claim.expires_at)
            if expires_at is None:
                issues.append("quiet_interval_requires_valid_claim_expiry")
            elif quiet_until is not None and quiet_until > expires_at:
                issues.append("quiet_interval_exceeds_claim_expiry")

    if issues:
        return list(dict.fromkeys(issues))
    assert progress_at is not None
    reference_now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if progress_at > reference_now:
        return ["future_progress_at"]
    if quiet_until is not None and reference_now < quiet_until:
        return []
    if reference_now >= progress_at + _progress_stale_after():
        return ["stalled_progress_lease"]
    return []


def claim_runtime_status(
    claim: ClaimRecord,
    *,
    active_claims: list[ClaimRecord] | None = None,
    now: datetime | None = None,
) -> str:
    """Classify one live claim across stale/stalled/weak/healthy states."""
    lifecycle_issues = claim_lifecycle_issues(claim)
    if any(issue != "missing_tracker_on_disk" for issue in lifecycle_issues):
        return "stale"
    liveness_issues = claim_liveness_issues(claim, now=now)
    if any(issue != "missing_session_heartbeat" for issue in liveness_issues):
        return "stale"
    progress_issues = claim_progress_issues(claim, now=now)
    issues = (
        coordination_health_issues(claim, active_claims=active_claims)
        if active_claims is not None
        else claim_health_issues(claim)
    )
    invalid_progress = [issue for issue in progress_issues if issue != "stalled_progress_lease"]
    if issues or liveness_issues or invalid_progress:
        return "weak"
    if progress_issues == ["stalled_progress_lease"]:
        return "stalled"
    if lifecycle_issues:
        return "weak"
    return "healthy"


def peer_claims_by_goal(claims: "list[ClaimRecord]") -> "dict[str, list[ClaimRecord]]":
    """Group live claims that declare a byte-identical ``broader_goal``.

    Exact equality only, never similarity. This reports that two sessions
    declared the same string -- identity, not an inference about what either
    means -- so it stays clear of the rule against deciding meaning by
    string-matching prose. A typo therefore shows as two groups rather than
    silently merging unrelated work, which is the safe direction to fail.

    Why this exists: ``parent_scope`` links a session's second lane to its
    first, so it is empty whenever every session holds one lane, which is the
    normal case. Measured 2026-09-08: 11 live claims across 11 distinct
    sessions, ``parent_scope`` populated 0 times, while five separate sessions
    on one project carried an identical ``broader_goal``. That adjacency is
    real, already declared, and was previously discoverable only by colliding
    on a write.
    """
    grouped: dict[str, list[ClaimRecord]] = {}
    for claim in claims:
        goal = (claim.broader_goal or "").strip()
        if not goal:
            continue
        grouped.setdefault(goal, []).append(claim)
    return {goal: members for goal, members in grouped.items() if len(members) > 1}


def render_peer_claim_groups(claims: "list[ClaimRecord]") -> "list[str]":
    """Render the shared-goal groups as display lines, or nothing when none."""
    groups = peer_claims_by_goal(claims)
    if not groups:
        return []
    lines = ["", "Other sessions working the same stated goal:"]
    for goal, members in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0])):
        lines.append(f'  "{goal}"')
        for member in sorted(members, key=lambda c: (c.agent, c.scope)):
            lines.append(f"    [{member.agent}] {member.primary_project()}:{member.scope}")
    return lines


def claim_enforcement_issues(claim: ClaimRecord) -> list[dict[str, str]]:
    """Return blocking operator findings that require an explicit disposition."""

    lifecycle = claim_lifecycle_issues(claim)
    issues: list[dict[str, str]] = []
    if "missing_plan_ref" in claim_health_issues(claim):
        issues.append(
            {
                "code": "live_claim_missing_plan_ref",
                "severity": "high",
                "message": (
                    f"Live claim {claim.primary_project()}:{claim.scope} has no plan_ref. "
                    "Resume or recreate the lane through a sanctioned plan-, goal-, or "
                    "UNPLANNED-bound entrypoint, or close it with an explicit disposition."
                ),
            }
        )
    if "branch_merged_to_default" in lifecycle:
        issues.append(
            {
                "code": "merged_active_claim_requires_disposition",
                "severity": "high",
                "message": (
                    f"Active claim {claim.primary_project()}:{claim.scope} owns branch "
                    f"{claim.branch!r}, which is already integrated into the canonical default branch. "
                    "Run sanctioned session-close or record a supported kept-open disposition."
                ),
            }
        )
    return issues


def validate_claim_for_creation(claim: ClaimRecord) -> None:
    """Reject new claims that omit required ownership metadata for live coordination."""
    issues = [issue for issue in claim_health_issues(claim) if issue in CREATION_BLOCKING_HEALTH_ISSUES]
    if claim.is_live() and issues:
        flag_map = {
            "missing_project": "--project",
            "missing_write_paths": "--write-path",
            "missing_branch": "--branch",
            "missing_worktree_path": "--worktree-path",
            "missing_session_id": "--session-id",
            "missing_session_name": "--session-name",
            "missing_plan_ref": "--plan (or explicit UNPLANNED authority via `--plan UNPLANNED`, as `make maintenance-worktree` passes)",
            "missing_work_unit_id": "--work-unit-id",
            "missing_work_graph_path": "--work-graph",
            "missing_work_graph_sha256": "a validated canonical work-graph binding",
            "missing_start_revision": "a validated full --start-point revision",
            "invalid_start_revision": "a valid full --start-point revision",
            "missing_plan_repo_root": "an explicit --plan-repo-root",
            "invalid_plan_repo_root": "an absolute --plan-repo-root",
            "missing_plan_revision": "an exact --plan-start-point",
            "invalid_plan_revision": "a valid full --plan-start-point revision",
            "missing_plan_sha256": "a validated external plan digest",
            "invalid_plan_sha256": "a valid external plan SHA-256 digest",
        }
        required_flags = [flag_map[item] for item in issues if item in flag_map]
        required_text = ", ".join(required_flags)
        raise ValueError(
            f"Active {claim.claim_type} claims require {required_text}. "
            "Legacy claims remain readable, but new live claims must declare real ownership."
        )
    broad_issues = _broad_scope_contract_issues(claim)
    if claim.is_live() and claim.schema_version >= 6 and broad_issues:
        raise ValueError("; ".join(broad_issues))


def _plan_number(plan_ref: str | None) -> int | None:
    """Extract a numbered-plan identity from canonical claim spellings."""

    if not isinstance(plan_ref, str):
        return None
    match = re.search(r"(?:\bPlan\s*#?|#)\s*0*(\d+)\b", plan_ref, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _resolve_commit(repo_root: Path, start_point: str, *, label: str) -> str:
    """Resolve one commit-ish to a full immutable object ID."""

    resolved = _run_git(repo_root, ["rev-parse", "--verify", f"{start_point}^{{commit}}"])
    revision = resolved.stdout.strip()
    if resolved.returncode != 0 or START_REVISION_PATTERN.fullmatch(revision) is None:
        raise ValueError(f"Unable to resolve one full {label} revision from {start_point!r}")
    return revision


def _numbered_plan_digest(repo_root: Path, revision: str, plan_number: int) -> str:
    """Bind exact plan bytes even when structural integrity enforcement is off."""

    from enforced_planning.plan_validation import (
        _git_object_bytes,
        _numbered_plan_paths_at_revision,
        parse_planning_integrity_config_bytes,
    )

    config_bytes = _git_object_bytes(repo_root, revision, "meta-process.yaml")
    _config, plans_dir, _config_sha256 = parse_planning_integrity_config_bytes(config_bytes)
    matches = _numbered_plan_paths_at_revision(
        repo_root, revision=revision, plans_dir=plans_dir, plan_number=plan_number
    )
    if len(matches) != 1:
        raise ValueError(
            f"External plan authority requires exactly one plan #{plan_number} at {revision}; found {len(matches)}"
        )
    plan_bytes = _git_object_bytes(repo_root, revision, matches[0])
    if plan_bytes is None:
        raise ValueError(f"External plan bytes are unavailable at {revision}:{matches[0]}")
    return hashlib.sha256(plan_bytes).hexdigest()


def resolve_plan_authority_binding(
    *,
    repo_root: str,
    plan_ref: str,
    start_point: str = "HEAD",
    plan_repo_root: str | None = None,
    plan_start_point: str | None = None,
    target_repository_id: str | None = None,
) -> PlanAuthorityBinding:
    """Resolve explicit plan authority separately from exact mutation-target custody."""

    root = Path(repo_root).expanduser().resolve()
    target_revision = _resolve_commit(root, start_point, label="target start")
    plan_number = _plan_number(plan_ref)
    if plan_number is None:
        raise ValueError(f"Unable to resolve numbered plan identity from {plan_ref!r}")
    qualified_match = re.fullmatch(r"([a-zA-Z0-9_.-]+)#0*(\d+)", plan_ref.strip())
    from enforced_planning.plan_validation import detect_repository_id

    resolved_target_repository_id = _normalized_repository_id(target_repository_id or detect_repository_id(root))
    repository_id = (
        _normalized_repository_id(qualified_match.group(1)) if qualified_match else resolved_target_repository_id
    )
    cross_repository = qualified_match is not None and repository_id != resolved_target_repository_id
    if (plan_repo_root is None) != (plan_start_point is None):
        raise ValueError("--plan-repo-root and --plan-start-point must be provided together")
    if cross_repository and (plan_repo_root is None or plan_start_point is None):
        raise ValueError(
            "Cross-repository plan binding requires explicit --plan-repo-root and --plan-start-point; "
            "the plan authority is never guessed from neighboring repositories"
        )
    if plan_repo_root is not None:
        supplied_plan_root = Path(plan_repo_root).expanduser()
        if not supplied_plan_root.is_absolute():
            raise ValueError("--plan-repo-root must be an absolute repository path")
        authority_root = supplied_plan_root.resolve()
        actual_plan_repository_id = _normalized_repository_id(detect_repository_id(authority_root))
        if actual_plan_repository_id != repository_id:
            raise ValueError(
                f"Plan repository {actual_plan_repository_id!r} does not match qualified plan "
                f"repository {repository_id!r}"
            )
        assert plan_start_point is not None
        if START_REVISION_PATTERN.fullmatch(plan_start_point) is None:
            raise ValueError("--plan-start-point must be one full lowercase Git object ID")
        authority_revision = _resolve_commit(authority_root, plan_start_point, label="plan authority")
    else:
        authority_root = root
        authority_revision = target_revision
    if not cross_repository and (authority_root != root or authority_revision != target_revision):
        raise ValueError("Same-repository plan authority must retain the target repository and revision")
    return PlanAuthorityBinding(
        target_root=root,
        target_revision=target_revision,
        plan_root=authority_root,
        plan_revision=authority_revision,
        plan_repository_id=repository_id,
        external=cross_repository,
    )


def resolve_canonical_work_unit_binding(
    *,
    repo_root: str,
    plan_ref: str,
    work_graph_path: str,
    work_unit_id: str,
    start_point: str = "HEAD",
    plan_repo_root: str | None = None,
    plan_start_point: str | None = None,
    target_repository_id: str | None = None,
    method_receipt_ref: str | None = None,
    method_receipt_sha256: str | None = None,
) -> CanonicalWorkUnitBinding:
    """Validate an owning plan graph and its target revision independently.

    When the plan-authority repository requires Company Planning method
    conformance (or the claim cites a receipt), the exact passing receipt is
    re-resolved at the plan-authority revision before the unit is admitted.
    """

    from enforced_planning.plan_validation import validate_plan_integrity_at_revision

    authority = resolve_plan_authority_binding(
        repo_root=repo_root,
        plan_ref=plan_ref,
        start_point=start_point,
        plan_repo_root=plan_repo_root,
        plan_start_point=plan_start_point,
        target_repository_id=target_repository_id,
    )
    root = authority.target_root
    target_revision = authority.target_revision
    authority_root = authority.plan_root
    authority_revision = authority.plan_revision
    repository_id = authority.plan_repository_id
    cross_repository = authority.external
    plan_number = _plan_number(plan_ref)
    assert plan_number is not None
    normalized_path = _normalize_repo_path(work_graph_path)
    if Path(normalized_path).is_absolute() or normalized_path == ".." or normalized_path.startswith("../"):
        raise ValueError("--work-graph must be a repository-relative path")

    integrity = validate_plan_integrity_at_revision(
        repo_root=authority_root,
        repository_id=repository_id,
        plan_number=plan_number,
        start_point=authority_revision,
    )
    if integrity.mode == "enforce" and integrity.disposition == "fail":
        finding_codes = ", ".join(item.code for item in integrity.findings)
        raise ValueError(f"Planning integrity rejected {plan_ref} at {integrity.source_revision}: {finding_codes}")
    source_revision = integrity.source_revision
    if not source_revision or START_REVISION_PATTERN.fullmatch(source_revision) is None:
        raise ValueError("Planning integrity did not resolve one full Git start revision")
    if source_revision != authority_revision:
        raise ValueError("Planning integrity resolved a different revision than the retained plan authority")
    if not Path(normalized_path).name.startswith(f"{plan_number}_"):
        raise ValueError(f"Work graph {normalized_path!r} does not match {plan_ref}; expected a {plan_number}_ prefix")
    graph_root = authority_root if cross_repository else root
    graph_revision = authority_revision if cross_repository else target_revision
    rendered = _run_git(graph_root, ["show", f"{graph_revision}:{normalized_path}"])
    if rendered.returncode != 0:
        raise ValueError(f"Canonical work graph {normalized_path!r} is unavailable at {graph_revision}")
    try:
        payload = json.loads(rendered.stdout)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Canonical work graph {normalized_path!r} is invalid JSON: {exc}") from exc
    units = payload.get("units") if isinstance(payload, dict) else None
    if not isinstance(units, list):
        raise ValueError(f"Canonical work graph {normalized_path!r} requires a units list")
    matches = [unit for unit in units if isinstance(unit, dict) and unit.get("id") == work_unit_id]
    if len(matches) != 1:
        raise ValueError(
            f"Canonical work graph must contain exactly one work unit {work_unit_id!r}; found {len(matches)}"
        )
    unit = matches[0]
    plan_sha256: str | None = None
    if cross_repository:
        plan_sha256 = integrity.plan_sha256 or _numbered_plan_digest(authority_root, authority_revision, plan_number)
        if unit.get("design_revision") != f"sha256:{plan_sha256}":
            raise ValueError(
                f"Work unit {work_unit_id!r} design_revision does not bind external plan digest sha256:{plan_sha256}"
            )
    readiness = unit.get("readiness")
    readiness_status = readiness.get("status") if isinstance(readiness, dict) else None
    unit_status = unit.get("status")
    if unit_status != "ready" or readiness_status != "ready":
        raise ValueError(
            f"Work unit {work_unit_id!r} is not claimable: status={unit_status!r}, readiness={readiness_status!r}"
        )
    control_types = unit.get("control_approval_types", [])
    readiness_types = readiness.get("required_approval_types", []) if isinstance(readiness, dict) else []
    approvals = readiness.get("approvals", []) if isinstance(readiness, dict) else []
    if not isinstance(control_types, list) or not all(isinstance(item, str) for item in control_types):
        raise ValueError(f"Work unit {work_unit_id!r} has invalid control_approval_types")
    if not isinstance(readiness_types, list) or not all(isinstance(item, str) for item in readiness_types):
        raise ValueError(f"Work unit {work_unit_id!r} has invalid required_approval_types")
    if not isinstance(approvals, list):
        raise ValueError(f"Work unit {work_unit_id!r} has invalid readiness approvals")
    required_types = sorted(set(control_types + readiness_types))
    approval_revisions: list[str] = []
    for approval_type in required_types:
        matching = [
            item
            for item in approvals
            if isinstance(item, dict)
            and item.get("approval_type") == approval_type
            and isinstance(item.get("role"), str)
            and item["role"].strip()
            and isinstance(item.get("approver_id"), str)
            and item["approver_id"].strip()
            and isinstance(item.get("approved_revision"), str)
            and item["approved_revision"].strip()
            and isinstance(item.get("approved_at"), str)
            and _parse_iso_datetime(item["approved_at"]) is not None
            and (
                item.get("expires_at") is None
                or (
                    isinstance(item.get("expires_at"), str)
                    and (expires_at := _parse_iso_datetime(item["expires_at"])) is not None
                    and expires_at > datetime.now(timezone.utc)
                )
            )
        ]
        if len(matching) != 1:
            raise ValueError(
                f"Work unit {work_unit_id!r} requires exactly one {approval_type!r} approval; found {len(matching)}"
            )
        approval_revisions.append(f"{approval_type}={matching[0]['approved_revision'].strip()}")
    graph_sha256 = hashlib.sha256(rendered.stdout.encode("utf-8")).hexdigest()
    method_conformance = resolve_method_conformance_binding(
        plan_root=authority_root,
        plan_revision=authority_revision,
        plan_number=plan_number,
        receipt_ref=method_receipt_ref,
        receipt_sha256=method_receipt_sha256,
    )
    return CanonicalWorkUnitBinding(
        work_graph_sha256=graph_sha256,
        approval_revisions=tuple(sorted(approval_revisions)),
        start_revision=target_revision,
        plan_repo_root=str(authority_root) if cross_repository else None,
        plan_revision=authority_revision if cross_repository else None,
        plan_sha256=plan_sha256,
        method_conformance=method_conformance,
    )


#: Claude Code registers each live session here as ``<pid>.json`` carrying the
#: real per-session UUID. Reading it lets any descendant process recover the
#: identity of the session it belongs to.
CLAUDE_SESSION_REGISTRY = Path.home() / ".claude" / "sessions"


def _parent_pid(pid: int) -> int | None:
    """Return a process's parent pid, or None when it cannot be read."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        # comm may contain spaces and parentheses; fields follow the final ")".
        return int(stat.rsplit(") ", 1)[1].split()[1])
    except (IndexError, ValueError):
        return None


def session_id_from_process_tree(registry_dir: Path | None = None) -> str | None:
    """Recover the owning Claude Code session id by walking process ancestry.

    A hook or CLI subprocess is a descendant of the ``claude`` process that owns
    the session, and that process has a registry entry naming its real session
    UUID. Walking to it gives a genuinely per-session identity, which
    CLAUDE_CODE_SSE_PORT does not: that port belongs to the CLI server and every
    session hosted by it derives the same value.
    """

    registry = registry_dir or CLAUDE_SESSION_REGISTRY
    pid: int | None = os.getpid()
    seen: set[int] = set()
    while pid and pid > 1 and pid not in seen:
        seen.add(pid)
        entry = registry / f"{pid}.json"
        if entry.is_file():
            try:
                payload = json.loads(entry.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return None
            session_id = payload.get("sessionId")
            if isinstance(session_id, str) and session_id.strip():
                return session_id.strip()
            return None
        pid = _parent_pid(pid)
    return None


def session_identity_aliases(agent: str, resolved_session_id: str | None) -> tuple[str, ...]:
    """Return every identity this process may legitimately claim ownership under.

    Transitional. Claims filed before per-session resolution carry the shared
    CLAUDE_CODE_SSE_PORT identity, and their owner must still be able to
    heartbeat and release them; otherwise this change would strand live lanes it
    cannot re-file. The legacy alias is as ambiguous as it always was -- two
    sessions on one CLI server share it -- so it is accepted for matching an
    existing claim and never minted for a new one.
    """

    identities: list[str] = []
    if resolved_session_id:
        identities.append(resolved_session_id)
    if agent == "claude-code":
        port = os.environ.get("CLAUDE_CODE_SSE_PORT", "").strip()
        legacy = f"claude-code:sse:{port}" if port else ""
        if legacy and legacy not in identities:
            identities.append(legacy)
    return tuple(identities)


def resolve_session_id(agent: str, explicit_session_id: str | None = None) -> str | None:
    """Return an explicit or environment-derived session identifier.

    The result is scoped to the named agent so one tool runtime does not
    accidentally borrow another tool's ambient session marker.
    """

    if explicit_session_id:
        return explicit_session_id
    for key in SESSION_ENV_KEYS.get(agent, ()):
        raw_value = os.environ.get(key, "").strip()
        if not raw_value:
            continue
        if agent == "claude-code" and key == "CLAUDE_CODE_SSE_PORT":
            # Last resort only. This port belongs to the CLI server, so every
            # session it hosts derives the same value and claim ownership stops
            # being per-session. Prefer the real session id from the registry,
            # which is also the identity Claude Code puts in hook payloads and
            # therefore the one the pre-write gate compares against.
            from_tree = session_id_from_process_tree()
            if from_tree:
                return f"{agent}:{from_tree}"
            return f"claude-code:sse:{raw_value}"
        return f"{agent}:{raw_value}"
    if agent == "claude-code":
        from_tree = session_id_from_process_tree()
        if from_tree:
            return f"{agent}:{from_tree}"
    return None


def validate_native_session_binding(
    agent: str,
    session_id: str | None,
    *,
    require_native_marker: bool = False,
) -> None:
    """Reject an explicit session identity that contradicts the native runtime.

    Explicit identities remain necessary for lifecycle hooks and recovery tools
    whose subprocess environment does not expose a native marker. When a native
    marker *is* present, however, accepting a different value creates an owner
    that no real session can heartbeat, receive mailbox messages for, or close.
    """

    native_key = STRICT_NATIVE_SESSION_ENV_KEYS.get(agent)
    native_value = os.environ.get(native_key, "").strip() if native_key else ""
    native_session_id = f"{agent}:{native_value}" if native_value else None
    if require_native_marker and native_session_id is None:
        expected = native_key or "a supported native session marker"
        raise ValueError(
            f"This mutation requires the current native {agent} runtime via {expected}; "
            "an explicit session ID alone cannot renew another runtime's progress lease."
        )
    if not session_id:
        return
    if native_session_id is None or session_id == native_session_id:
        return
    raise ValueError(
        f"Explicit session ID {session_id!r} does not match the current "
        f"{agent} runtime {native_session_id!r}. Use the native session identity; "
        "do not substitute a lane name. Use sanctioned transfer or takeover for "
        "ownership changes."
    )


def _safe_string_list(value: Any) -> list[str]:
    """Normalize a scalar-or-list YAML value into a clean string list."""
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, list):
        items = [item for item in value if isinstance(item, str)]
    else:
        return []
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        stripped = item.strip()
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        deduped.append(stripped)
    return deduped


def _normalize_repo_path(path: str) -> str:
    """Normalize a repo-relative path for parent/child overlap checks."""
    normalized = posixpath.normpath(path.replace("\\", "/").strip())
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def bootstrap_authority_disabled_worktree_path(target_worktree_path: str) -> str:
    """Return a deterministic non-Git path that older readers cannot authorize."""

    target = Path(target_worktree_path).expanduser()
    if not target.is_absolute():
        raise ValueError("target_worktree_path must be absolute for bootstrap authority")
    return f"{target.resolve(strict=False)}{BOOTSTRAP_AUTHORITY_DISABLED_SUFFIX}"


def classify_broad_write_paths(
    repo_root: str | None,
    write_paths: list[str],
    *,
    verified_new_files: set[str] | None = None,
) -> dict[str, str]:
    """Classify root/top-level directory reservations without guessing.

    Nested paths are narrow for this contract. A missing top-level component is
    ambiguous because filesystem evidence cannot distinguish an intended file
    from a directory reservation. Symlinks must remain within the declared root.
    """

    normalized = list(dict.fromkeys(_normalize_repo_path(path) for path in write_paths))
    verified_files = verified_new_files or set()
    if any(Path(path).is_absolute() or path == ".." or path.startswith("../") for path in normalized):
        raise ValueError("write paths must remain repository-relative and cannot traverse outside repo_root")
    if not repo_root:
        raise ValueError("repo_root is required to classify broad write paths")
    root = Path(repo_root).expanduser()
    if not root.is_absolute():
        raise ValueError("repo_root must be absolute to classify broad write paths")
    resolved_root = root.resolve(strict=False)
    for path in normalized:
        if path == ".":
            continue
        resolved = (resolved_root / path).resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"write path {path!r} escapes repo_root through symlink resolution") from exc
    candidates = [path for path in normalized if path == "." or "/" not in path]
    if not candidates:
        return {}
    broad: dict[str, str] = {}
    for path in candidates:
        if path == ".":
            broad[path] = "repository_root"
            continue
        candidate = resolved_root / path
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"broad path {path!r} escapes repo_root through symlink resolution") from exc
        # A broken symlink is still an existing directory entry. It can be
        # reserved exactly for repair after the resolved target passed the
        # repository-containment check above.
        if not candidate.exists() and path in verified_files:
            continue
        if not candidate.exists() and not candidate.is_symlink():
            raise ValueError(f"broad_scope_ambiguous: top-level path {path!r} does not exist")
        if candidate.is_dir():
            broad[path] = "existing_top_level_directory"
    return broad


def _regular_top_level_files_at_revision(
    repo_root: str | None,
    revision: str | None,
    write_paths: list[str],
) -> set[str]:
    """Return exact top-level regular files recorded by one retained Git tree."""

    if not repo_root or not revision or START_REVISION_PATTERN.fullmatch(revision) is None:
        return set()
    root = Path(repo_root).expanduser()
    if not root.is_absolute():
        return set()
    verified: set[str] = set()
    for path in write_paths:
        normalized = _normalize_repo_path(path)
        if normalized in {"", ".", ".."} or "/" in normalized:
            continue
        result = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-z", revision, "--", normalized],
            capture_output=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.endswith(b"\0"):
            continue
        records = [record for record in result.stdout.split(b"\0") if record]
        if len(records) != 1 or b"\t" not in records[0]:
            continue
        metadata, raw_path = records[0].split(b"\t", 1)
        fields = metadata.split()
        if (
            len(fields) == 3
            and fields[0] in {b"100644", b"100755"}
            and raw_path == normalized.encode()
        ):
            verified.add(normalized)
    return verified


def _broad_scope_contract_issues(claim: ClaimRecord) -> list[str]:
    """Return deterministic schema-v6 broad-scope contract violations."""

    if not _has_write_ownership(claim):
        return []
    mode = claim.broad_scope_mode.strip() if isinstance(claim.broad_scope_mode, str) else None
    reason = claim.broad_scope_reason.strip() if isinstance(claim.broad_scope_reason, str) else None
    issues: list[str] = []
    if claim.schema_version < 6:
        possible_broad = any(
            _normalize_repo_path(path) == "." or "/" not in _normalize_repo_path(path)
            for path in claim.write_paths
        )
        if possible_broad:
            issues.append("legacy_broad_scope_unclassified")
        return issues
    verified_new_files: set[str] = set()
    worktree = Path(claim.target_worktree_path or claim.worktree_path or "")
    canonical_root = Path(claim.repo_root or "")
    staged_worktree = (
        bool(claim.worktree_path)
        and bool(claim.repo_root)
        and bool(claim.branch)
        and Path(claim.worktree_path or "").is_absolute()
        and not Path(claim.worktree_path or "").exists()
        and Path(claim.worktree_path or "").resolve(strict=False)
        == (Path(claim.repo_root or "") / "worktrees" / Path(claim.branch or "")).resolve(strict=False)
    )
    for path in claim.write_paths:
        normalized = _normalize_repo_path(path)
        created = worktree / normalized
        if (
            normalized not in {"", ".", ".."}
            and "/" not in normalized
            and created.is_file()
            and not created.is_symlink()
        ):
            verified_new_files.add(normalized)
    if staged_worktree:
        verified_new_files.update(
            _regular_top_level_files_at_revision(
                claim.repo_root,
                claim.start_revision,
                list(claim.write_paths),
            )
        )
    for path in claim.new_files:
        created = worktree / path
        canonical = canonical_root / path
        if (
            path in claim.write_paths
            and "/" not in path
            and path not in {"", ".", ".."}
            and not canonical.exists()
            and not canonical.is_symlink()
            and created.is_file()
            and not created.is_symlink()
        ):
            verified_new_files.add(path)
        elif (
            staged_worktree
            and path in claim.write_paths
            and "/" not in path
            and path not in {"", ".", ".."}
            and not canonical.exists()
            and not canonical.is_symlink()
        ):
            # A typed maintenance transaction reserves its exact final paths
            # before creating the branch/worktree. Once the worktree exists,
            # the ordinary exact-file checks above take over.
            verified_new_files.add(path)
        elif not canonical.is_file():
            issues.append("invalid_new_file_contract")
    try:
        broad_paths = classify_broad_write_paths(
            claim.repo_root,
            claim.write_paths,
            verified_new_files=verified_new_files,
        )
    except ValueError as exc:
        # A live claim's repo_root/worktree commonly stops existing on disk
        # long before its claim file is cleaned up (see missing_worktree_on_disk
        # in claim_lifecycle_issues). classify_broad_write_paths cannot resolve
        # broad-vs-narrow from filesystem evidence that is no longer there, and
        # every caller of this function -- including read-only --list/--check
        # rendering across the whole registry -- must survive one such claim
        # rather than crash on it.
        issues.append(str(exc).split(":", 1)[0])
        broad_paths = None
    if broad_paths:
        if mode not in BROAD_SCOPE_MODES:
            issues.append("broad_scope_mode_required")
        if not reason:
            issues.append("broad_scope_reason_required")
    elif broad_paths is not None and (mode is not None or reason is not None):
        issues.append("broad scope metadata is forbidden when no broad path remains")
    if mode == "bootstrap":
        if not claim.target_worktree_path:
            issues.append("bootstrap_target_worktree_path_required")
        elif claim.worktree_path != claim.target_worktree_path:
            issues.append("bootstrap_physical_worktree_identity_mismatch")
    elif mode == "bounded" and claim.target_worktree_path not in {None, claim.worktree_path}:
        issues.append("bounded_target_worktree_mismatch")
    return issues


def _projects_overlap(left: ClaimRecord, right: ClaimRecord) -> bool:
    """Return whether two claims touch at least one common project."""
    return bool(set(left.projects) & set(right.projects))


def _paths_overlap(left: str, right: str) -> bool:
    """Return whether two normalized repo-relative paths overlap."""
    left_norm = _normalize_repo_path(left)
    right_norm = _normalize_repo_path(right)
    if left_norm == "." or right_norm == ".":
        return True
    return left_norm == right_norm or left_norm.startswith(f"{right_norm}/") or right_norm.startswith(f"{left_norm}/")


CODEX_SESSION_ROOT = Path("~/.codex/sessions")
CLAUDE_SESSION_ROOT = Path("~/.claude/projects")


def session_transcript_path(
    session_id: str | None,
    *,
    codex_root: Path | None = None,
    claude_root: Path | None = None,
) -> Path | None:
    """Locate the runtime transcript one session is actually writing to.

    A claim's ``heartbeat_at`` only advances when the claim itself is touched,
    so a working session looks idle and an abandoned one looks alive. The
    client's own transcript is written on every model turn, which makes it the
    honest liveness signal.
    """

    if not session_id or ":" not in session_id:
        return None
    agent, _, runtime_id = session_id.partition(":")
    if not runtime_id:
        return None
    if agent == "codex":
        root = (codex_root or CODEX_SESSION_ROOT).expanduser()
        pattern = f"*/*/*/rollout-*-{runtime_id}.jsonl"
    elif agent == "claude-code":
        root = (claude_root or CLAUDE_SESSION_ROOT).expanduser()
        pattern = f"*/{runtime_id}.jsonl"
    else:
        return None
    if not root.is_dir():
        return None
    matches = sorted(root.glob(pattern))
    return matches[-1] if matches else None


def session_last_active_at(
    session_id: str | None,
    *,
    codex_root: Path | None = None,
    claude_root: Path | None = None,
) -> datetime | None:
    """Return when a session's own client last wrote, or None when unknowable.

    None means unknown, never idle. Report it as unknown rather than treating
    absence of a transcript as evidence the session ended.
    """

    path = session_transcript_path(session_id, codex_root=codex_root, claude_root=claude_root)
    if path is None:
        return None
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def describe_session_activity(last_active_at: datetime | None, *, now: datetime | None = None) -> str:
    """Render one claim owner's liveness for an operator reading a conflict.

    Absence of a transcript is reported as unknown. A session that has not
    written for a long time is still only quiet: say so, and never let a
    reader infer permission to take its claim.
    """

    if last_active_at is None:
        return "liveness unknown"
    moment = now or datetime.now(timezone.utc)
    minutes = max(0, int((moment - last_active_at).total_seconds() // 60))
    if minutes < 2:
        return "active seconds ago"
    if minutes < 60:
        return f"last active {minutes} min ago"
    hours = minutes // 60
    return f"last active {hours}h ago — likely ended without releasing"


def _is_append_only_path(path: str) -> bool:
    """Return whether a declared write path lands only in an append-only store.

    True for the store itself and for anything beneath it. False for a parent
    that also covers mutable siblings: claiming ``learnings`` reaches
    ``learnings.md``, which lanes do rewrite, so it stays exclusive.
    """

    normalized = _normalize_repo_path(path)
    return any(normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in APPEND_ONLY_WRITE_PREFIXES)


def _compute_overlapping_write_paths(candidate: ClaimRecord, other: ClaimRecord) -> list[str]:
    """Return normalized write-path overlaps between two claims.

    Append-only stores are excluded: concurrent lanes each create their own
    immutable file there, so a shared declaration is not contention.
    """
    overlaps: list[str] = []
    for left in candidate.write_paths:
        for right in other.write_paths:
            if not _paths_overlap(left, right):
                continue
            if _is_append_only_path(left) and _is_append_only_path(right):
                continue
            overlaps.append(
                f"yours={_normalize_repo_path(left)} <-> theirs={_normalize_repo_path(right)}"
            )
    return sorted(set(overlaps))


def _overlap_relations(candidate: ClaimRecord, other: ClaimRecord) -> tuple[str, ...]:
    """Classify every effective overlap from the candidate's perspective."""

    relations: set[str] = set()
    for left_raw in candidate.write_paths:
        for right_raw in other.write_paths:
            if not _paths_overlap(left_raw, right_raw):
                continue
            if _is_append_only_path(left_raw) and _is_append_only_path(right_raw):
                continue
            left = _normalize_repo_path(left_raw)
            right = _normalize_repo_path(right_raw)
            if left == right:
                relations.add("exact")
            elif left == "." or right.startswith(f"{left}/"):
                relations.add("candidate_parent")
            else:
                relations.add("owner_parent")
    return tuple(sorted(relations))


def _reservation_kind(other: ClaimRecord, relations: tuple[str, ...]) -> str | None:
    """Explain a parent reservation without changing conflict severity."""

    if "owner_parent" not in relations:
        return None
    if other.broad_scope_mode == "bounded":
        return "deliberate_bounded_reservation"
    if other.broad_scope_mode == "bootstrap" or "legacy_broad_scope_unclassified" in _broad_scope_contract_issues(other):
        return "overbroad_reservation"
    return None


def _current_diff_disjoint(candidate: ClaimRecord, other: ClaimRecord) -> bool | None:
    """Return advisory Git status disjointness, or unknown when unreadable."""

    if not other.worktree_path:
        return None
    worktree = Path(other.worktree_path).expanduser()
    result = subprocess.run(
        ["git", "-C", str(worktree), "status", "--porcelain=v1", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    changed: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.rsplit(" -> ", 1)[1]
        changed.append(_normalize_repo_path(path.strip('"')))
    return not any(
        _paths_overlap(changed_path, candidate_path)
        for changed_path in changed
        for candidate_path in candidate.write_paths
    )


def _interaction_explanation(candidate: ClaimRecord, other: ClaimRecord) -> dict[str, Any]:
    """Build shared explanatory fields for one overlap interaction."""

    relations = _overlap_relations(candidate, other)
    return {
        "overlap_relations": relations,
        "reservation_kind": _reservation_kind(other, relations),
        "other_broad_scope_mode": (
            other.broad_scope_mode
            or ("legacy_unclassified" if "legacy_broad_scope_unclassified" in _broad_scope_contract_issues(other) else None)
        ),
        "current_diff_disjoint": _current_diff_disjoint(candidate, other),
    }


def _git_worktree_boundary(claim: ClaimRecord) -> tuple[Path, Path, Path, str] | None:
    """Return verified repository, common-dir, worktree, and target kind.

    A candidate claim is created before its managed worktree exists. That one
    absent target is accepted only at the sanctioned ``repo/worktrees/branch``
    location; the surrounding claim/worktree transaction removes the claim if
    creation fails. Existing targets must be exact Git worktree roots sharing
    the declared repository's common directory.
    """

    if not claim.repo_root or not claim.worktree_path or not claim.branch:
        return None
    repo_root = Path(claim.repo_root).expanduser().resolve()
    worktree_path = Path(claim.worktree_path).expanduser().resolve()
    if not repo_root.is_dir():
        return None

    def git_path(root: Path, field: str) -> Path | None:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute", field],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return Path(result.stdout.strip()).expanduser().resolve()

    canonical_top = git_path(repo_root, "--show-toplevel")
    common_dir = git_path(repo_root, "--git-common-dir")
    if canonical_top != repo_root or common_dir is None:
        return None
    if worktree_path == repo_root:
        return repo_root, common_dir, worktree_path, "canonical"
    if worktree_path.exists():
        worktree_top = git_path(worktree_path, "--show-toplevel")
        worktree_common = git_path(worktree_path, "--git-common-dir")
        if worktree_top != worktree_path or worktree_common != common_dir:
            return None
        return repo_root, common_dir, worktree_path, "linked"

    planned_target = (repo_root / "worktrees" / claim.branch).resolve()
    if worktree_path == planned_target:
        return repo_root, common_dir, worktree_path, "planned_linked"
    return None


def _has_isolated_worktree_boundary(candidate: ClaimRecord, other: ClaimRecord) -> bool:
    """Return whether Git isolates the two overlapping mutation surfaces."""

    candidate_boundary = _git_worktree_boundary(candidate)
    other_boundary = _git_worktree_boundary(other)
    if candidate_boundary is None or other_boundary is None:
        return False
    candidate_root, candidate_common, candidate_worktree, candidate_kind = candidate_boundary
    other_root, other_common, other_worktree, other_kind = other_boundary
    return (
        candidate_kind != "canonical"
        and other_kind != "canonical"
        and candidate_root == other_root
        and candidate_common == other_common
        and candidate_worktree != other_worktree
        and candidate.branch != other.branch
    )


def _has_write_ownership(claim: ClaimRecord) -> bool:
    """Return whether a claim owns its declared write paths.

    Sanctioned worktree lanes use ``program`` claims as their root while still
    carrying exact write paths. Those paths are ownership, just as they are for
    a narrow ``write`` claim.
    """

    return claim.claim_type in {"program", "write"} and bool(claim.write_paths)


def _parse_iso_datetime(value: Any) -> datetime | None:
    """Parse an ISO timestamp from claim data if present."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _progress_text_with_presence(
    data: dict[str, Any],
    key: str,
    *,
    null_is_invalid: bool = True,
) -> str | None:
    """Preserve invalid explicit progress keys instead of erasing them as legacy absence."""

    if key not in data:
        return None
    value = data.get(key)
    if value is None and not null_is_invalid:
        return None
    return value if isinstance(value, str) else ""


def normalize_claim(data: dict[str, Any], *, source_file: str | None = None) -> ClaimRecord | None:
    """Normalize a raw YAML claim into the v2 in-memory representation."""
    agent = data.get("agent")
    scope = data.get("scope")
    intent = data.get("intent")
    if not all(isinstance(value, str) and value.strip() for value in (agent, scope, intent)):
        return None
    assert isinstance(agent, str)
    assert isinstance(scope, str)
    assert isinstance(intent, str)
    agent_text = agent.strip()
    scope_text = scope.strip()
    intent_text = intent.strip()

    projects = _safe_string_list(data.get("projects"))
    legacy_project = data.get("project")
    if isinstance(legacy_project, str) and legacy_project.strip() and legacy_project.strip() not in projects:
        projects.insert(0, legacy_project.strip())

    write_paths = [_normalize_repo_path(path) for path in _safe_string_list(data.get("write_paths"))]
    read_paths = [_normalize_repo_path(path) for path in _safe_string_list(data.get("read_paths"))]
    raw_claim_type = data.get("claim_type")
    claim_type = raw_claim_type if isinstance(raw_claim_type, str) and raw_claim_type in CLAIM_TYPES else None
    if claim_type is None:
        claim_type = "write" if write_paths else "program"

    raw_status = data.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status.strip() else "active"
    raw_schema_version = data.get("schema_version")
    if isinstance(raw_schema_version, int) and raw_schema_version in {1, 2, 3, 4, 5, 6}:
        schema_version = raw_schema_version
    elif any(key in data for key in ("broad_scope_mode", "broad_scope_reason", "target_worktree_path")):
        schema_version = 6
    elif any(key in data for key in ("plan_repo_root", "plan_revision", "plan_sha256")):
        schema_version = 5
    elif "start_revision" in data:
        schema_version = 4
    elif any(
        key in data
        for key in (
            "work_unit_id",
            "work_graph_path",
            "work_graph_sha256",
            "approval_revisions",
        )
    ):
        schema_version = 3
    elif any(
        key in data
        for key in (
            "claim_type",
            "projects",
            "write_paths",
            "read_paths",
            "worktree_path",
            "repo_root",
            "branch",
            "session_name",
            "broader_goal",
            "tracker_path",
            "session_id",
            "heartbeat_at",
            "status",
            "updated_at",
            "parent_scope",
            "notes",
            "parallel_root_authorized",
        )
    ):
        schema_version = 2
    else:
        schema_version = 1

    target_worktree_path = (
        data.get("target_worktree_path")
        if isinstance(data.get("target_worktree_path"), str)
        else None
    )
    worktree_path = data.get("worktree_path") if isinstance(data.get("worktree_path"), str) else None
    if (
        schema_version >= 6
        and data.get("broad_scope_mode") == "bootstrap"
        and target_worktree_path is not None
        and worktree_path
        in {
            target_worktree_path,
            bootstrap_authority_disabled_worktree_path(target_worktree_path),
        }
    ):
        # Bootstrap disables write authority in the derived projection, not by
        # corrupting the canonical lane's physical identity. Normalize legacy
        # sentinel claims to their immutable physical worktree on read.
        worktree_path = target_worktree_path

    return ClaimRecord(
        agent=agent_text,
        claimed_at=data.get("claimed_at") if isinstance(data.get("claimed_at"), str) else None,
        expires_at=data.get("expires_at") if isinstance(data.get("expires_at"), str) else None,
        projects=projects,
        scope=scope_text,
        intent=intent_text,
        claim_type=claim_type,
        write_paths=write_paths,
        read_paths=read_paths,
        worktree_path=worktree_path,
        repo_root=data.get("repo_root") if isinstance(data.get("repo_root"), str) else None,
        branch=data.get("branch") if isinstance(data.get("branch"), str) else None,
        session_name=data.get("session_name") if isinstance(data.get("session_name"), str) else None,
        broader_goal=data.get("broader_goal") if isinstance(data.get("broader_goal"), str) else None,
        tracker_path=data.get("tracker_path") if isinstance(data.get("tracker_path"), str) else None,
        session_id=data.get("session_id") if isinstance(data.get("session_id"), str) else None,
        heartbeat_at=data.get("heartbeat_at") if isinstance(data.get("heartbeat_at"), str) else None,
        status=status,
        updated_at=data.get("updated_at") if isinstance(data.get("updated_at"), str) else None,
        parent_scope=normalize_parent_scope(
            data.get("parent_scope") if isinstance(data.get("parent_scope"), str) else None,
            projects[0] if projects else None,
        ),
        notes=data.get("notes") if isinstance(data.get("notes"), str) else None,
        plan_ref=data.get("plan_ref") if isinstance(data.get("plan_ref"), str) else None,
        source_file=source_file,
        schema_version=schema_version,
        start_revision=(
            data.get("start_revision")
            if isinstance(data.get("start_revision"), str)
            else ("" if "start_revision" in data else None)
        ),
        plan_repo_root=(data.get("plan_repo_root") if isinstance(data.get("plan_repo_root"), str) else None),
        plan_revision=data.get("plan_revision") if isinstance(data.get("plan_revision"), str) else None,
        plan_sha256=data.get("plan_sha256") if isinstance(data.get("plan_sha256"), str) else None,
        work_unit_id=data.get("work_unit_id") if isinstance(data.get("work_unit_id"), str) else None,
        work_graph_path=(data.get("work_graph_path") if isinstance(data.get("work_graph_path"), str) else None),
        work_graph_sha256=(data.get("work_graph_sha256") if isinstance(data.get("work_graph_sha256"), str) else None),
        approval_revisions=tuple(_safe_string_list(data.get("approval_revisions"))),
        parallel_root_authorized=data.get("parallel_root_authorized") is True,
        progress_at=_progress_text_with_presence(data, "progress_at"),
        progress_kind=_progress_text_with_presence(data, "progress_kind"),
        evidence_ref=_progress_text_with_presence(data, "evidence_ref"),
        next_action=_progress_text_with_presence(data, "next_action"),
        expected_quiet_until=_progress_text_with_presence(
            data,
            "expected_quiet_until",
            null_is_invalid=False,
        ),
        quiet_reason=_progress_text_with_presence(
            data,
            "quiet_reason",
            null_is_invalid=False,
        ),
        broad_scope_mode=(
            data.get("broad_scope_mode")
            if isinstance(data.get("broad_scope_mode"), str)
            else None
        ),
        broad_scope_reason=(
            data.get("broad_scope_reason")
            if isinstance(data.get("broad_scope_reason"), str)
            else None
        ),
        target_worktree_path=target_worktree_path,
        contact_ref=data.get("contact_ref") if isinstance(data.get("contact_ref"), str) else None,
        new_files=tuple(_safe_string_list(data.get("new_files"))),
        method_receipt_ref=(
            data.get("method_receipt_ref") if isinstance(data.get("method_receipt_ref"), str) else None
        ),
        method_receipt_sha256=(
            data.get("method_receipt_sha256") if isinstance(data.get("method_receipt_sha256"), str) else None
        ),
    )


#: Paths already warned about in this process, so a hot read path (claim
#: checks run on nearly every tool call, ecosystem-wide) doesn't spam stderr
#: once per call for the same corrupt file. A fresh process (new session, new
#: hook invocation) warns again, which is exactly the point: the corruption is
#: still there until someone fixes or removes the file.
_WARNED_MALFORMED_CLAIM_FILES: set[str] = set()


def _load_claims(claims_dir: Path | None = None) -> list[ClaimRecord]:
    """Load live claim files from the configured or explicitly supplied registry.

    A claim file that fails to parse as YAML is skipped, not fatal to the rest
    of the registry -- one bad file must never take down every session's view
    of every other live claim (the same posture #513 established for
    filesystem-evidence errors in `_broad_scope_contract_issues`). But a silent
    `except: continue` here previously made a corrupt claim invisible with no
    trace at all: it vanished from every listing and conflict check with
    nothing printed anywhere, which is worse than a loud failure -- nobody
    investigating "why doesn't my claim show up" or "why did two sessions
    write overlapping paths" had any signal that a file existed and had been
    dropped. Observed twice: an unquoted colon inside a multi-line
    `broader_goal` scalar in a hand-written (non-CLI) claim file broke this
    exact path, once 2026-08-21 and again 2026-09-14 for the identical reason.
    Warn to stderr, attributed to the exact file and parse error, the first
    time this process encounters it.
    """
    resolved_claims_dir = claims_dir or CLAIMS_DIR
    if not resolved_claims_dir.exists():
        return []
    claims: list[ClaimRecord] = []
    now = datetime.now(timezone.utc)
    for claim_file in resolved_claims_dir.glob("*.yaml"):
        try:
            data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except Exception as exc:
            claim_path_str = str(claim_file)
            if claim_path_str not in _WARNED_MALFORMED_CLAIM_FILES:
                _WARNED_MALFORMED_CLAIM_FILES.add(claim_path_str)
                print(
                    f"WARNING: coordination claim file {claim_file} is not valid "
                    f"YAML and is being skipped ({exc}). This claim is invisible "
                    "to every listing/conflict check until it is fixed or "
                    "removed; see `malformed_claim_files()` / "
                    "`--list --json`'s malformed_claim_files field.",
                    file=sys.stderr,
                )
            continue
        if not isinstance(data, dict):
            continue
        expires_at = _parse_iso_datetime(data.get("expires_at"))
        if expires_at is not None and expires_at < now:
            # Loading and listing are read-only. Expired source records remain
            # auditable until the explicit --prune lifecycle action removes
            # them.
            continue
        claim = normalize_claim(data, source_file=str(claim_file))
        if claim is not None:
            claims.append(claim)
    return claims


def unregistered_claim_files() -> list[str]:
    """Return claim-dir files that coordination tooling cannot parse as claims.

    Every file in the claims directory is a claim by convention. Free-form
    `.md`/`.txt` claims (observed from Codex sessions, 2026-07-06) are invisible
    to listing/conflict/registry tooling; surfacing them loudly is the fix for
    that silent blind spot.
    """
    if not CLAIMS_DIR.exists():
        return []
    return sorted(
        str(path) for path in CLAIMS_DIR.iterdir() if path.is_file() and path.suffix.lower() not in {".yaml", ".yml"}
    )


def malformed_claim_files(claims_dir: Path | None = None) -> list[dict[str, str]]:
    """Return `.yaml` claim-dir files that exist but fail to parse as YAML.

    Companion to `unregistered_claim_files()` for the other way a claim can be
    invisible to every listing/conflict check: right extension, broken content.
    `_load_claims()` already warns to stderr the first time a process hits one
    of these; this gives `--list`/`--check` (both text and `--json`) an
    explicit, queryable, per-invocation view instead of relying on a reader
    having seen that one-time stderr line.
    """
    resolved_claims_dir = claims_dir or CLAIMS_DIR
    if not resolved_claims_dir.exists():
        return []
    malformed: list[dict[str, str]] = []
    for claim_file in sorted(resolved_claims_dir.glob("*.yaml")):
        try:
            data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except Exception as exc:
            malformed.append({"path": str(claim_file), "error": str(exc)})
            continue
        if not isinstance(data, dict):
            malformed.append(
                {
                    "path": str(claim_file),
                    "error": f"parses as YAML but is not a mapping (got {type(data).__name__})",
                }
            )
    return malformed


def _claim_filename(agent: str, project: str, scope: str) -> str:
    """Generate a deterministic filename for a claim."""

    def safe(value: str) -> str:
        return value.replace("/", "_").replace(" ", "_").strip("_")

    return f"{safe(agent)}_{safe(project)}_{safe(scope)}.yaml"


def check_claims(project: str | None = None, *, claims_dir: Path | None = None) -> list[ClaimRecord]:
    """Check active claims, optionally selecting a registry and project."""
    claims = [claim for claim in _load_claims(claims_dir) if claim.is_live()]
    if project:
        claims = [claim for claim in claims if project in claim.projects]
    return claims


def list_claims(
    project: str | None = None,
    *,
    claims_dir: Path | None = None,
    include_inactive: bool = False,
) -> list[ClaimRecord]:
    """List claims with an explicit option to retain non-live audit records."""

    claims = _load_claims(claims_dir)
    if not include_inactive:
        claims = [claim for claim in claims if claim.is_live()]
    if project:
        claims = [claim for claim in claims if project in claim.projects]
    return claims


def evaluate_claim(candidate: ClaimRecord, *, active_claims: list[ClaimRecord] | None = None) -> ClaimCheckResult:
    """Classify candidate claim interactions against active live claims."""
    claims = active_claims if active_claims is not None else check_claims()
    interactions: list[ClaimInteraction] = []
    for other in claims:
        if other is candidate:
            continue
        if other.agent == candidate.agent and candidate.session_id and other.session_id == candidate.session_id:
            continue
        if not _projects_overlap(candidate, other):
            continue

        overlapping_write_paths = _compute_overlapping_write_paths(candidate, other)
        if _has_write_ownership(candidate) and _has_write_ownership(other) and overlapping_write_paths:
            # Worktrees isolate filesystem writes, not ownership or duplicated
            # effort. Preserve the isolated recovery exception only after the
            # incumbent claim is no longer healthy; an active healthy owner
            # retains exclusive authority over its declared paths.
            other_runtime_status = claim_runtime_status(other, active_claims=claims)
            isolated_worktrees = (
                _has_isolated_worktree_boundary(candidate, other)
                and other_runtime_status != "healthy"
            )
            interactions.append(
                ClaimInteraction(
                    severity="advisory_overlap" if isolated_worktrees else "hard_conflict",
                    reason=(
                        "isolated_worktree_overlap"
                        if isolated_worktrees
                        else "write ownership overlaps across active claims"
                    ),
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                    other_session_id=other.session_id,
                    other_session_last_active_at=session_last_active_at(other.session_id),
                    other_contact_ref=other.contact_ref,
                    **_interaction_explanation(candidate, other),
                )
            )
            continue

        if overlapping_write_paths and (
            (candidate.claim_type == "review" and _has_write_ownership(other))
            or (other.claim_type == "review" and _has_write_ownership(candidate))
        ):
            interactions.append(
                ClaimInteraction(
                    severity="soft_overlap",
                    reason="review claim overlaps an active write claim",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                    other_session_id=other.session_id,
                    other_session_last_active_at=session_last_active_at(other.session_id),
                    other_contact_ref=other.contact_ref,
                    **_interaction_explanation(candidate, other),
                )
            )
            continue

        if candidate.scope == other.scope:
            interactions.append(
                ClaimInteraction(
                    severity="informational",
                    reason="same project/scope is already claimed, but no write-path conflict was detected",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                    other_session_id=other.session_id,
                    other_session_last_active_at=session_last_active_at(other.session_id),
                    other_contact_ref=other.contact_ref,
                    **(_interaction_explanation(candidate, other) if overlapping_write_paths else {}),
                )
            )
            continue

        if overlapping_write_paths:
            interactions.append(
                ClaimInteraction(
                    severity="informational",
                    reason="write-path overlap exists but the claim types do not require blocking",
                    other_agent=other.agent,
                    other_scope=other.scope,
                    other_claim_type=other.claim_type,
                    projects=sorted(set(candidate.projects) & set(other.projects)),
                    overlapping_write_paths=overlapping_write_paths,
                    other_source_file=other.source_file,
                    other_session_id=other.session_id,
                    other_session_last_active_at=session_last_active_at(other.session_id),
                    other_contact_ref=other.contact_ref,
                    **_interaction_explanation(candidate, other),
                )
            )
            continue

        interactions.append(
            ClaimInteraction(
                severity="informational",
                reason="same project has another active claim with no overlapping write paths",
                other_agent=other.agent,
                other_scope=other.scope,
                other_claim_type=other.claim_type,
                projects=sorted(set(candidate.projects) & set(other.projects)),
                overlapping_write_paths=[],
                other_source_file=other.source_file,
                other_session_id=other.session_id,
                other_session_last_active_at=session_last_active_at(other.session_id),
                other_contact_ref=other.contact_ref,
            )
        )
    return ClaimCheckResult(candidate=candidate, interactions=interactions)


def build_candidate_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    intent: str,
    plan_ref: str | None = None,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    worktree_path: str | None = None,
    repo_root: str | None = None,
    branch: str | None = None,
    session_name: str | None = None,
    broader_goal: str | None = None,
    tracker_path: str | None = None,
    session_id: str | None = None,
    heartbeat_at: str | None = None,
    status: str = "active",
    parent_scope: str | None = None,
    notes: str | None = None,
    claimed_at: str | None = None,
    expires_at: str | None = None,
    updated_at: str | None = None,
    start_revision: str | None = None,
    plan_repo_root: str | None = None,
    plan_revision: str | None = None,
    plan_sha256: str | None = None,
    work_unit_id: str | None = None,
    work_graph_path: str | None = None,
    work_graph_sha256: str | None = None,
    approval_revisions: tuple[str, ...] = (),
    parallel_root_authorized: bool = False,
    progress_at: str | None = None,
    progress_kind: str | None = None,
    evidence_ref: str | None = None,
    next_action: str | None = None,
    expected_quiet_until: str | None = None,
    quiet_reason: str | None = None,
    broad_scope_mode: str | None = None,
    broad_scope_reason: str | None = None,
    target_worktree_path: str | None = None,
    contact_ref: str | None = None,
    new_files: list[str] | tuple[str, ...] | None = None,
    schema_version: int | None = None,
    method_receipt_ref: str | None = None,
    method_receipt_sha256: str | None = None,
) -> ClaimRecord:
    """Build a normalized candidate claim from CLI or test inputs."""
    normalized_write_paths = [_normalize_repo_path(path) for path in (write_paths or [])]
    normalized_read_paths = [_normalize_repo_path(path) for path in (read_paths or [])]
    resolved_session_id = resolve_session_id(agent, session_id)
    resolved_claim_type = claim_type or ("write" if normalized_write_paths else "program")
    if resolved_claim_type not in CLAIM_TYPES:
        raise ValueError(f"Unsupported claim type: {resolved_claim_type}")
    if resolved_claim_type == "write" and not normalized_write_paths:
        raise ValueError("Write claims require at least one --write-path.")
    normalized_mode = broad_scope_mode.strip() if isinstance(broad_scope_mode, str) else None
    normalized_reason = broad_scope_reason.strip() if isinstance(broad_scope_reason, str) else None
    effective_target_worktree = target_worktree_path
    effective_worktree = worktree_path
    if normalized_mode == "bootstrap":
        effective_target_worktree = target_worktree_path or worktree_path
        effective_worktree = effective_target_worktree
    return ClaimRecord(
        agent=agent,
        claimed_at=claimed_at,
        expires_at=expires_at,
        projects=[project],
        scope=scope,
        intent=intent,
        claim_type=resolved_claim_type,
        write_paths=normalized_write_paths,
        read_paths=normalized_read_paths,
        worktree_path=effective_worktree,
        repo_root=repo_root,
        branch=branch,
        session_name=session_name,
        broader_goal=broader_goal,
        tracker_path=tracker_path,
        session_id=resolved_session_id,
        heartbeat_at=heartbeat_at,
        status=status,
        updated_at=updated_at,
        parent_scope=normalize_parent_scope(parent_scope, project),
        notes=notes,
        plan_ref=plan_ref,
        source_file=None,
        schema_version=(
            schema_version
            if schema_version is not None
            else (
                6
                if any((broad_scope_mode, broad_scope_reason, target_worktree_path))
                else (
                    5
                    if any((plan_repo_root, plan_revision, plan_sha256))
                    else (4 if start_revision is not None else 3)
                )
            )
        ),
        start_revision=start_revision,
        plan_repo_root=plan_repo_root,
        plan_revision=plan_revision,
        plan_sha256=plan_sha256,
        work_unit_id=work_unit_id,
        work_graph_path=work_graph_path,
        work_graph_sha256=work_graph_sha256,
        approval_revisions=approval_revisions,
        parallel_root_authorized=parallel_root_authorized,
        progress_at=progress_at,
        progress_kind=progress_kind,
        evidence_ref=evidence_ref,
        next_action=next_action,
        expected_quiet_until=expected_quiet_until,
        quiet_reason=quiet_reason,
        broad_scope_mode=normalized_mode,
        broad_scope_reason=normalized_reason,
        target_worktree_path=effective_target_worktree,
        contact_ref=contact_ref,
        new_files=tuple(_normalize_repo_path(path) for path in (new_files or ())),
        method_receipt_ref=method_receipt_ref,
        method_receipt_sha256=method_receipt_sha256,
    )


def _refresh_exact_owner_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str | None,
    intent: str,
    plan_ref: str | None,
    claim_type: str | None,
    write_paths: list[str] | None,
    read_paths: list[str] | None,
    worktree_path: str | None,
    repo_root: str | None,
    branch: str | None,
    session_name: str | None,
    broader_goal: str | None,
    status: str,
    parent_scope: str | None,
    notes: str | None,
    allow_parallel: bool,
    broad_scope_mode: str | None,
    broad_scope_reason: str | None,
    target_worktree_path: str | None,
    ttl_hours: float,
) -> tuple[bool, str] | None:
    """Expand an exact-owner live claim without reconstructing retained custody."""

    claim_path = CLAIMS_DIR / _claim_filename(agent, project, scope)
    if not claim_path.is_file():
        return None
    with claim_registry_lock(CLAIMS_DIR):
        raw = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        existing = normalize_claim(raw, source_file=str(claim_path)) if isinstance(raw, dict) else None
        if existing is None or not existing.is_live():
            return None
        resolved_session_id = resolve_session_id(agent, session_id)
        if not resolved_session_id or existing.session_id != resolved_session_id:
            return None
        if existing.status != status:
            raise ValueError("exact-owner claim refresh cannot change lifecycle status")
        requested_identity = {
            "intent": intent,
            "plan_ref": plan_ref,
            "claim_type": claim_type,
            "worktree_path": worktree_path,
            "repo_root": repo_root,
            "branch": branch,
            "session_name": session_name,
            "broader_goal": broader_goal,
            "parent_scope": parent_scope,
            "broad_scope_mode": broad_scope_mode,
            "broad_scope_reason": broad_scope_reason,
            "target_worktree_path": target_worktree_path,
        }
        for field, requested in requested_identity.items():
            if requested is not None and requested != getattr(existing, field):
                raise ValueError(f"exact-owner claim refresh cannot change retained {field}")
        if allow_parallel and not existing.parallel_root_authorized:
            raise ValueError("exact-owner claim refresh cannot add parallel-root authority")

        payload = dict(raw)
        if write_paths:
            payload["write_paths"] = [_normalize_repo_path(path) for path in write_paths]
        if read_paths:
            payload["read_paths"] = [_normalize_repo_path(path) for path in read_paths]
        if notes is not None:
            payload["notes"] = notes
        now = datetime.now(timezone.utc)
        payload["expires_at"] = (now + timedelta(hours=ttl_hours)).isoformat()
        payload["updated_at"] = now.isoformat()
        candidate = normalize_claim(payload, source_file=str(claim_path))
        if candidate is None:
            raise ValueError("exact-owner claim refresh produced an invalid claim")
        validate_claim_for_creation(candidate)
        active_claims = check_claims(project)
        check_result = evaluate_claim(candidate, active_claims=active_claims)
        if check_result.hard_conflicts:
            formatted = "; ".join(
                f"{item.other_agent} ({item.other_scope}: {', '.join(item.overlapping_write_paths)})"
                for item in check_result.hard_conflicts
            )
            return False, f"CONFLICT: active write claim overlap in '{project}' — {formatted}. Check which side is YOURS before attributing cause: the path prefixed 'yours=' is the one this lane declared, not the other agent's. Narrowing your own write path is often the fix, and an append-only store never contends with itself."
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        _projection_path, projection_digest_after = _replace_claim_and_refresh_projection_fail_atomic(
            claim_path=claim_path,
            payload=payload,
            claims_dir=CLAIMS_DIR,
        )
        record_claim_mutation(
            operation="create",
            claims_dir=CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=claim_path,
            session_id=resolved_session_id,
            projection_digest_after=projection_digest_after,
        )
    return True, f"Refreshed exact-owner claim: {agent} → {project}:{scope}"


def _tracker_path_yaml_error(tracker_path: str | None) -> str | None:
    """Why this tracker path cannot serve as a session tracker, or None.

    A tracker is read and rewritten as a YAML mapping by every lane closeout.
    Nothing used to check that at claim time, so a Markdown path -- a plan
    document or a register front door, both natural-looking things to name --
    was accepted, and the lane then died at CLOSEOUT on a bare
    ``yaml.scanner.ScannerError`` after its work was already merged. The lane
    could not be closed at all, and the failure surfaced only as a parser
    traceback pointing at a line of English prose.

    A missing file is NOT an error here: a claim may legitimately name a
    tracker that a later step will write. Only a file that exists and cannot
    be a tracker is refused.
    """

    if not tracker_path:
        return None
    path = Path(tracker_path).expanduser()
    if not path.exists() or not path.is_file():
        return None
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    except yaml.YAMLError as exc:
        first = str(exc).strip().splitlines()[0] if str(exc).strip() else "parse error"
        return (
            f"tracker_path {tracker_path!r} exists but is not parseable as YAML "
            f"({first}). Every lane closeout reads and rewrites its tracker as a "
            f"YAML mapping, so this claim could be created and then never closed."
        )
    # Deliberately NOT rejecting a file that parses as YAML but is not a
    # mapping. A scalar placeholder is common in fixtures and in trackers a
    # later step overwrites, and refusing it here breaks claim creation for
    # cases that were never the problem. The defect this check exists to stop
    # -- a Markdown document as a tracker path -- fails to PARSE, so the
    # narrower rule still catches it. `read_session_tracker` reports a
    # non-mapping clearly if one ever reaches a closeout.
    return None


def _reject_unreadable_tracker_path(tracker_path: str | None) -> None:
    """Fail at claim time rather than stranding a lane at closeout."""

    problem = _tracker_path_yaml_error(tracker_path)
    if problem:
        raise ValueError(problem)


def create_claim(
    agent: str,
    project: str,
    scope: str,
    intent: str,
    plan_ref: str | None = None,
    ttl_hours: float = DEFAULT_TTL_HOURS,
    claim_type: str | None = None,
    write_paths: list[str] | None = None,
    read_paths: list[str] | None = None,
    worktree_path: str | None = None,
    repo_root: str | None = None,
    branch: str | None = None,
    session_name: str | None = None,
    broader_goal: str | None = None,
    tracker_path: str | None = None,
    session_id: str | None = None,
    status: str = "active",
    parent_scope: str | None = None,
    notes: str | None = None,
    work_graph_path: str | None = None,
    work_unit_id: str | None = None,
    start_point: str = "HEAD",
    plan_repo_root: str | None = None,
    plan_start_point: str | None = None,
    resume_requested: bool = False,
    require_new: bool = False,
    allow_parallel: bool = False,
    require_native_session_binding: bool = False,
    require_native_session_marker: bool = False,
    broad_scope_mode: str | None = None,
    broad_scope_reason: str | None = None,
    target_worktree_path: str | None = None,
    contact_ref: str | None = None,
    new_files: list[str] | None = None,
    verified_goal_default_revision: str | None = None,
    verified_maintenance_default_revision: str | None = None,
    method_receipt_ref: str | None = None,
    method_receipt_sha256: str | None = None,
) -> tuple[bool, str]:
    """Create a new claim after checking for hard conflicts.

    A plan-backed write claim re-resolves its Company Planning
    method-conformance receipt (``method_receipt_ref`` plus
    ``method_receipt_sha256``) when the plan repository requires one or the
    claim cites one. An unplanned claim can never cite plan conformance.
    """
    method_receipt_cited = method_receipt_ref is not None or method_receipt_sha256 is not None
    if method_receipt_cited and not (write_paths and requires_work_graph(plan_ref)):
        raise MethodConformanceRefusal(
            "method_receipt_on_unplanned_claim",
            "only a plan-backed write claim bound to a work unit can cite a method-conformance receipt; "
            "explicitly unplanned work keeps its separate admission rule and cannot imply plan conformance",
        )
    if verified_goal_default_revision is not None and not is_goal_authority_ref(plan_ref):
        raise ValueError("verified goal default revision is valid only for goal-bound ownership")
    if verified_maintenance_default_revision is not None and is_goal_authority_ref(plan_ref):
        raise ValueError("verified maintenance default revision is valid only for unplanned maintenance")
    now = datetime.now(timezone.utc)
    initial_progress = build_progress_event(
        progress_kind="claim_started",
        evidence_ref=plan_ref or scope,
        next_action=intent,
        progress_at=now,
    )
    if require_native_session_binding:
        validate_native_session_binding(
            agent,
            session_id,
            require_native_marker=require_native_session_marker,
        )
    if not require_new:
        refreshed = _refresh_exact_owner_claim(
            agent=agent,
            project=project,
            scope=scope,
            session_id=session_id,
            intent=intent,
            plan_ref=plan_ref,
            claim_type=claim_type,
            write_paths=write_paths,
            read_paths=read_paths,
            worktree_path=worktree_path,
            repo_root=repo_root,
            branch=branch,
            session_name=session_name,
            broader_goal=broader_goal,
            status=status,
            parent_scope=parent_scope,
            notes=notes,
            allow_parallel=allow_parallel,
            broad_scope_mode=broad_scope_mode,
            broad_scope_reason=broad_scope_reason,
            target_worktree_path=target_worktree_path,
            ttl_hours=ttl_hours,
        )
        if refreshed is not None:
            return refreshed
    resolved_claim_type = claim_type or ("write" if write_paths else "program")
    work_graph_sha256: str | None = None
    approval_revisions: tuple[str, ...] = ()
    start_revision: str | None = None
    retained_plan_repo_root: str | None = None
    plan_revision: str | None = None
    plan_sha256: str | None = None
    if write_paths and requires_work_graph(plan_ref):
        if not repo_root:
            raise ValueError("Plan-bound write ownership requires --repo-root for canonical work-unit validation")
        if not work_graph_path or not work_unit_id:
            raise ValueError("Plan-bound write ownership requires --work-graph and --work-unit-id")
        binding = coerce_canonical_work_unit_binding(
            resolve_canonical_work_unit_binding(
                repo_root=repo_root,
                plan_ref=plan_ref,
                work_graph_path=work_graph_path,
                work_unit_id=work_unit_id,
                start_point=start_point,
                plan_repo_root=plan_repo_root,
                plan_start_point=plan_start_point,
                target_repository_id=project,
                method_receipt_ref=method_receipt_ref,
                method_receipt_sha256=method_receipt_sha256,
            )
        )
        work_graph_sha256 = binding.work_graph_sha256
        approval_revisions = binding.approval_revisions
        start_revision = binding.start_revision
        method_binding = binding.method_conformance
        if method_binding is not None:
            method_receipt_ref = method_binding.receipt_path
            method_receipt_sha256 = method_binding.receipt_sha256
        retained_plan_repo_root = binding.plan_repo_root
        plan_revision = binding.plan_revision
        plan_sha256 = binding.plan_sha256
        if retained_plan_repo_root is not None:
            plan_default_revision = resolve_default_integration_revision(retained_plan_repo_root)
            if plan_revision != plan_default_revision:
                raise ValueError(
                    f"new cross-repository claim plan revision {plan_revision} is not the canonical "
                    f"plan-authority default-integration tip {plan_default_revision}; "
                    "retain the existing lane or refresh the target work graph against current authority"
                )
        default_revision = resolve_default_integration_revision(repo_root)
        if start_revision != default_revision:
            raise ValueError(
                f"new plan-bound claim start revision {start_revision} is not canonical "
                f"default-integration tip {default_revision}; --resume is not recovery evidence. "
                "Resume an existing retained lane through session-resume instead."
            )
        validate_start_revision_targets(
            repo_root=repo_root,
            start_revision=start_revision,
            branch=branch,
            worktree_path=worktree_path,
            require_branch=tracker_path is not None,
            require_worktree=tracker_path is not None,
        )
    elif write_paths and is_goal_authority_ref(plan_ref):
        if not repo_root:
            raise ValueError("Goal-bound write ownership requires --repo-root for revision custody")
        root = Path(repo_root).expanduser().resolve()
        start_revision = _resolve_commit(root, start_point, label="goal worktree start")
        default_revision = (
            verified_goal_default_revision
            if verified_goal_default_revision is not None
            else resolve_default_integration_revision(root)
        )
        if verified_goal_default_revision is not None and not (tracker_path and branch and worktree_path):
            raise ValueError(
                "verified goal default revision requires one exact tracker, branch, and worktree transaction"
            )
        if START_REVISION_PATTERN.fullmatch(default_revision) is None:
            raise ValueError("verified goal default revision must be one full lowercase Git object ID")
        if start_revision != default_revision:
            raise ValueError(
                f"new goal-bound claim start revision {start_revision} is not canonical "
                f"default-integration tip {default_revision}"
            )
        validate_start_revision_targets(
            repo_root=root,
            start_revision=start_revision,
            branch=branch,
            worktree_path=worktree_path,
            require_branch=tracker_path is not None,
            require_worktree=tracker_path is not None,
        )
    elif write_paths and verified_maintenance_default_revision is not None:
        if not (require_native_session_binding and tracker_path and branch and worktree_path and repo_root):
            raise ValueError(
                "verified maintenance default revision requires one native-bound tracker, branch, and worktree transaction"
            )
        if START_REVISION_PATTERN.fullmatch(verified_maintenance_default_revision) is None:
            raise ValueError("verified maintenance default revision must be one full lowercase Git object ID")
        root = Path(repo_root).expanduser().resolve()
        resolved_start = _resolve_commit(root, start_point, label="maintenance worktree start")
        if resolved_start != verified_maintenance_default_revision:
            raise ValueError("maintenance worktree start does not match its freshly verified default revision")
        start_revision = resolved_start
    _reject_unreadable_tracker_path(tracker_path)
    candidate = build_candidate_claim(
        agent=agent,
        project=project,
        scope=scope,
        intent=intent,
        plan_ref=plan_ref,
        claim_type=resolved_claim_type,
        write_paths=write_paths,
        read_paths=read_paths,
        worktree_path=worktree_path,
        repo_root=repo_root,
        branch=branch,
        session_name=session_name,
        broader_goal=broader_goal,
        tracker_path=tracker_path,
        session_id=session_id,
        heartbeat_at=now.isoformat(),
        status=status,
        parent_scope=parent_scope,
        notes=notes,
        work_unit_id=work_unit_id,
        work_graph_path=_normalize_repo_path(work_graph_path) if work_graph_path else None,
        work_graph_sha256=work_graph_sha256,
        approval_revisions=approval_revisions,
        parallel_root_authorized=allow_parallel,
        claimed_at=now.isoformat(),
        expires_at=(now + timedelta(hours=ttl_hours)).isoformat(),
        updated_at=now.isoformat(),
        start_revision=start_revision,
        plan_repo_root=retained_plan_repo_root,
        plan_revision=plan_revision,
        plan_sha256=plan_sha256,
        broad_scope_mode=broad_scope_mode,
        broad_scope_reason=broad_scope_reason,
        target_worktree_path=target_worktree_path,
        contact_ref=contact_ref,
        new_files=new_files,
        schema_version=6,
        method_receipt_ref=method_receipt_ref,
        method_receipt_sha256=method_receipt_sha256,
        **_progress_event_payload(initial_progress),
    )
    validate_claim_for_creation(candidate)

    with claim_registry_lock():
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        claim_path = CLAIMS_DIR / _claim_filename(agent, project, scope)
        if claim_path.exists():
            if require_new:
                raise ValueError(
                    f"Claim slot {project}:{scope} already exists; new-lane creation will not overwrite it"
                )
            raw_existing = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
            existing = (
                normalize_claim(raw_existing, source_file=str(claim_path)) if isinstance(raw_existing, dict) else None
            )
            if existing and existing.status == SESSION_ENDED_STATUS:
                raise ValueError(
                    "Existing claim is session_ended; use session-resume/takeover "
                    "or sanctioned closeout instead of overwriting it."
                )
            if (
                existing
                and existing.is_live()
                and (not candidate.session_id or existing.session_id != candidate.session_id)
            ):
                owner = existing.session_id or "<missing-session-id>"
                raise ValueError(
                    f"Existing live claim slot {project}:{scope} is owned by runtime session {owner}; "
                    "use sanctioned handoff/session-end plus session-resume, or close the lane, "
                    "instead of overwriting it."
                )
        active_claims = check_claims(project)
        validate_no_preserved_lane_conflict(
            candidate,
            claims=list_claims(include_inactive=True),
        )
        validate_claim_hierarchy_for_creation(candidate, active_claims=active_claims)
        validate_session_root_for_creation(candidate, active_claims=check_claims())
        check_result = evaluate_claim(candidate, active_claims=active_claims)
        if check_result.hard_conflicts:
            formatted = "; ".join(
                f"{item.other_agent} ({item.other_scope}: {', '.join(item.overlapping_write_paths)}"
                f"; owner {describe_session_activity(item.other_session_last_active_at)}"
                f"{f'; contact {item.other_contact_ref}' if item.other_contact_ref else ''})"
                for item in check_result.hard_conflicts
            )
            return False, (
                f"CONFLICT: active write claim overlap in '{project}' — {formatted}. "
                f"Check which side is YOURS before attributing cause: the path "
                f"prefixed 'yours=' is the one this lane declared, not the other "
                f"agent's. Narrowing your own write path is often the fix, and an "
                f"append-only store never contends with itself. "
                "This is a path-local integration wait, not a whole-goal blocker: "
                "continue claim-compatible work or record the required reconciliation "
                "obligation before deferring the overlapping authority surface."
            )

        if start_revision is not None:
            staged_verified_maintenance = verified_maintenance_default_revision is not None
            validate_start_revision_targets(
                repo_root=repo_root or "",
                start_revision=start_revision,
                branch=branch,
                worktree_path=worktree_path,
                require_branch=tracker_path is not None and not staged_verified_maintenance,
                require_worktree=tracker_path is not None and not staged_verified_maintenance,
            )

        CLAIMS_DIR.mkdir(parents=True, exist_ok=True)
        claim_payload = candidate.to_dict()
        claim_payload.pop("source_file", None)
        claim_payload.pop("project", None)
        for key in ("method_receipt_ref", "method_receipt_sha256"):
            if claim_payload.get(key) is None:
                claim_payload.pop(key, None)
        if candidate.start_revision is None:
            claim_payload.pop("start_revision", None)
        _atomic_write_claim(claim_path, claim_payload)
        _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
        record_claim_mutation(
            operation="create",
            claims_dir=CLAIMS_DIR,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=claim_path,
            session_id=candidate.session_id,
            projection_digest_after=projection_digest_after,
        )
    return True, (f"Claimed: {agent} → {project}:{scope} [{candidate.claim_type}] (expires in {ttl_hours}h)")


def _replacement_is_within_existing_authority(replacement: str, existing: str) -> bool:
    """Return whether one normalized replacement is equal to/below an old path."""

    new = _normalize_repo_path(replacement)
    old = _normalize_repo_path(existing)
    return old == "." or new == old or new.startswith(f"{old}/")


def _validate_bootstrap_target_identity(claim: ClaimRecord) -> None:
    """Require the separated bootstrap target to be the claimed Git branch/repository."""

    if not claim.target_worktree_path or not claim.repo_root or not claim.branch:
        raise ValueError("bootstrap narrowing requires target_worktree_path, repo_root, and branch")
    target = Path(claim.target_worktree_path).expanduser().resolve()
    repository = Path(claim.repo_root).expanduser().resolve()
    target_identity = _run_git(target, ["rev-parse", "--show-toplevel", "--git-common-dir", "--abbrev-ref", "HEAD"])
    repository_identity = _run_git(repository, ["rev-parse", "--git-common-dir"])
    lines = target_identity.stdout.splitlines() if target_identity.returncode == 0 else []
    if len(lines) != 3 or repository_identity.returncode != 0:
        raise ValueError("bootstrap target worktree Git identity is unavailable")
    actual_root = Path(lines[0]).expanduser().resolve()
    target_common = Path(lines[1])
    if not target_common.is_absolute():
        target_common = target / target_common
    repository_common = Path(repository_identity.stdout.strip())
    if not repository_common.is_absolute():
        repository_common = repository / repository_common
    if (
        actual_root != target
        or target_common.resolve() != repository_common.resolve()
        or lines[2] != claim.branch
    ):
        raise ValueError("bootstrap target worktree does not match claimed repository and branch")


def narrow_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str | None,
    write_paths: list[str],
    claims_dir: Path | None = None,
    require_native_session_binding: bool = False,
    known_new_files: list[str] | None = None,
    start_revision: str | None = None,
) -> NarrowClaimResult:
    """Commit one owner-only strict subset claim/projection transition."""

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError("narrowing requires an exact session_id")
    if require_native_session_binding:
        validate_native_session_binding(agent, resolved_session_id, require_native_marker=True)
    replacements = list(dict.fromkeys(_normalize_repo_path(path) for path in write_paths))
    if not replacements:
        raise ValueError("narrowing requires at least one replacement write path")
    if any(Path(path).is_absolute() or path == ".." or path.startswith("../") for path in replacements):
        raise ValueError("replacement write paths must remain repository-relative")

    resolved_claims = (claims_dir or CLAIMS_DIR).expanduser().resolve()
    claim_path = resolved_claims / _claim_filename(agent, project, scope)
    with claim_registry_lock(resolved_claims):
        if not claim_path.is_file():
            raise ValueError(f"live claim {project}:{scope} does not exist")
        raw = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        claim = normalize_claim(raw, source_file=str(claim_path)) if isinstance(raw, dict) else None
        if claim is None or not claim.is_live():
            raise ValueError(f"claim {project}:{scope} is not one valid live claim")
        if claim.agent != agent or claim.primary_project() != project:
            raise ValueError(f"claim {project}:{scope} belongs to another owner")
        if claim.session_id != resolved_session_id:
            raise ValueError(
                f"claim {project}:{scope} belongs to session {claim.session_id or '<missing>'}, "
                f"not {resolved_session_id}"
            )
        old_paths = list(dict.fromkeys(_normalize_repo_path(path) for path in claim.write_paths))
        if set(replacements) == set(old_paths):
            raise ValueError("narrowing requires at least one strict reduction")
        outside = [
            path
            for path in replacements
            if not any(_replacement_is_within_existing_authority(path, old) for old in old_paths)
        ]
        if outside:
            raise ValueError(
                "replacement path outside existing authority: " + ", ".join(outside)
            )

        verified_new_files: set[str] = set()
        for path in list(dict.fromkeys(_normalize_repo_path(item) for item in (known_new_files or []))):
            if path not in replacements or "/" in path or path in {"", ".", ".."}:
                raise ValueError("known new files must be top-level replacement write paths")
            canonical = Path(claim.repo_root or "") / path
            worktree = Path(claim.target_worktree_path or claim.worktree_path or "")
            created = worktree / path
            if canonical.exists() or canonical.is_symlink():
                raise ValueError(f"known new file already exists in canonical repository: {path}")
            if not created.is_file() or created.is_symlink() or created.stat().st_size != 0:
                raise ValueError(f"known new file is not an exact empty regular worktree file: {path}")
            verified_new_files.add(path)

        remaining_broad = classify_broad_write_paths(
            claim.repo_root,
            replacements,
            verified_new_files=verified_new_files,
        )
        if remaining_broad and claim.broad_scope_mode not in BROAD_SCOPE_MODES:
            raise ValueError(
                "a legacy/untyped broad claim may narrow only to non-broad exact paths"
            )
        payload = dict(raw)
        payload["schema_version"] = 6
        payload["write_paths"] = replacements
        if start_revision is not None:
            if START_REVISION_PATTERN.fullmatch(start_revision) is None:
                raise ValueError("narrowed claim start_revision must be one full commit SHA")
            payload["start_revision"] = start_revision
        if verified_new_files:
            payload["new_files"] = sorted(verified_new_files)
        else:
            payload.pop("new_files", None)
        if remaining_broad:
            payload["broad_scope_mode"] = claim.broad_scope_mode
            payload["broad_scope_reason"] = claim.broad_scope_reason
        else:
            payload.pop("broad_scope_mode", None)
            payload.pop("broad_scope_reason", None)
            if claim.broad_scope_mode == "bootstrap":
                _validate_bootstrap_target_identity(claim)
                payload["worktree_path"] = claim.target_worktree_path
            payload.pop("target_worktree_path", None)

        candidate = normalize_claim(payload, source_file=str(claim_path))
        if candidate is None:
            raise ValueError("narrowed claim payload could not be normalized")
        validate_claim_for_creation(candidate)
        active_claims = check_claims(project, claims_dir=resolved_claims)
        conflict_result = evaluate_claim(candidate, active_claims=active_claims)
        if conflict_result.hard_conflicts:
            formatted = "; ".join(
                f"{item.other_agent}:{item.other_scope}" for item in conflict_result.hard_conflicts
            )
            raise ValueError(f"narrowed authority still conflicts with {formatted}")

        registry_digest_before = _registry_digest(resolved_claims)
        projection_path, projection_digest = _replace_claim_and_refresh_projection_fail_atomic(
            claim_path=claim_path,
            payload=payload,
            claims_dir=resolved_claims,
        )
        receipt = record_claim_narrow_mutation(
            claims_dir=resolved_claims,
            registry_digest_before=registry_digest_before,
            target_project=project,
            target_scope=scope,
            target_claim_path=claim_path,
            session_id=resolved_session_id,
            projection_digest_after=projection_digest,
        )
        return NarrowClaimResult(
            project=project,
            scope=scope,
            session_id=resolved_session_id,
            old_write_paths=tuple(old_paths),
            new_write_paths=tuple(replacements),
            broad_scope_mode=payload.get("broad_scope_mode"),
            projection_path=projection_path,
            projection_digest=projection_digest,
            receipt_id=receipt.event_id,
        )


def hydrate_missing_session_ids(
    *,
    agent: str,
    project: str,
    session_id: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
) -> tuple[int, list[str], str]:
    """Fill in missing session IDs for matching live claims.

    This is an explicit remediation tool for older live claims that were created
    before automatic session capture was wired into the v2 claim surface.
    """

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )

    updated_scopes: list[str] = []
    now = datetime.now(timezone.utc).isoformat()
    with claim_registry_lock(CLAIMS_DIR):
        if not CLAIMS_DIR.exists():
            return 0, [], resolved_session_id
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if claim.agent != agent:
                continue
            if project not in claim.projects:
                continue
            if scope and claim.scope != scope:
                continue
            if branch and claim.branch != branch:
                continue
            if claim.session_id:
                continue
            data["session_id"] = resolved_session_id
            data["heartbeat_at"] = now
            data["updated_at"] = now
            _atomic_write_claim(claim_file, data)
            updated_scopes.append(claim.scope)
        if updated_scopes:
            refresh_prewrite_authority_projection(CLAIMS_DIR)
    return len(updated_scopes), sorted(updated_scopes), resolved_session_id


def _extended_lease_expiry(
    current_expires_at: Any,
    renewed_at: str,
    ttl_hours: float,
) -> str:
    """Return the later of a claim's current lease and one renewed at ``renewed_at``."""

    renewed = datetime.fromisoformat(renewed_at) + timedelta(hours=ttl_hours)
    if isinstance(current_expires_at, str) and current_expires_at:
        try:
            existing = datetime.fromisoformat(current_expires_at)
        except ValueError:
            return renewed.isoformat()
        if existing.tzinfo is None:
            existing = existing.replace(tzinfo=timezone.utc)
        if existing > renewed:
            return current_expires_at
    return renewed.isoformat()


def heartbeat_claims(
    *,
    agent: str,
    project: str,
    session_id: str | None = None,
    scope: str | None = None,
    branch: str | None = None,
    claims_dir: Path | None = None,
    require_exact_session: bool = False,
    ttl_hours: float = DEFAULT_TTL_HOURS,
) -> tuple[int, list[str], str, str]:
    """Refresh heartbeat metadata and the lease for live claims owned by one session."""

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )

    resolved_claims_dir = claims_dir or CLAIMS_DIR
    heartbeat_at = datetime.now(timezone.utc).isoformat()
    updated_claims: list[tuple[Path, ClaimRecord]] = []
    # Lifecycle hooks run concurrently across sessions. Keep the canonical
    # heartbeat write and its derived projection refresh in the same registry
    # critical section as every other live-claim mutation.
    with claim_registry_lock(resolved_claims_dir):
        registry_digest_before = _registry_digest(resolved_claims_dir)
        if not resolved_claims_dir.exists():
            return 0, [], resolved_session_id, heartbeat_at
        for claim_file in resolved_claims_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if claim.agent != agent:
                continue
            if project not in claim.projects:
                continue
            if scope and claim.scope != scope:
                continue
            if branch and claim.branch != branch:
                continue
            owned = session_identity_aliases(agent, resolved_session_id)
            if require_exact_session and claim.session_id not in owned:
                continue
            if not require_exact_session and claim.session_id and claim.session_id not in owned:
                continue
            reject_mutation_during_session_takeover(data, operation="heartbeat")
            data["session_id"] = resolved_session_id
            data["heartbeat_at"] = heartbeat_at
            data["updated_at"] = heartbeat_at
            # An ordinary heartbeat refreshes the lease as well as liveness.
            # A deliberately bounded broad claim is the exception: its expiry
            # is an ownership ceiling, so background activity must not silently
            # turn that fixed window into a rolling reservation.
            # Until 2026-09-08 this wrote only the heartbeat, so a session that
            # kept heartbeating past its 24-hour TTL expired anyway. That is
            # worse than a stale timestamp: load_claims() above drops an expired
            # record *before* normalize_claim(), so the lane stops existing for
            # every registry consumer -- the push gate reports
            # missing_branch_claim, "no claim is attached to this branch", about
            # a file on disk that says status: active with the caller's own
            # session_id (lrn-20260908T170436862573Z-d2c739d527).
            #
            # Renewal cannot keep a dead lane alive, because abandonment is
            # detected by heartbeat_at ageing rather than by the TTL lapsing: a
            # session that stops heartbeating stops renewing, and
            # stale_session_heartbeat still classifies it for --prune-stale.
            #
            # Renewal only ever extends. A claim may deliberately carry an
            # expiry beyond the default TTL, and a liveness signal must never be
            # what shortens it: clamping every heartbeat to now + TTL would pull
            # a long-lived lease back to a day. The existing invariant test that
            # lists expires_at as heartbeat-preserved is what caught that.
            if claim.broad_scope_mode != "bounded":
                data["expires_at"] = _extended_lease_expiry(
                    data.get("expires_at"), heartbeat_at, ttl_hours
                )
            _atomic_write_claim(claim_file, data)
            updated_claims.append((claim_file, claim))
        if updated_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(resolved_claims_dir)
            for claim_file, claim in updated_claims:
                record_claim_mutation(
                    operation="heartbeat",
                    claims_dir=resolved_claims_dir,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=resolved_session_id,
                    projection_digest_after=projection_digest_after,
                )
    updated_scopes = [claim.scope for _path, claim in updated_claims]
    return len(updated_scopes), sorted(updated_scopes), resolved_session_id, heartbeat_at


def record_progress_claims(
    *,
    agent: str,
    project: str,
    scope: str,
    progress_kind: str,
    evidence_ref: str,
    next_action: str,
    session_id: str | None = None,
    expected_quiet_until: str | datetime | None = None,
    quiet_reason: str | None = None,
    claims_dir: Path | None = None,
    require_native_session_binding: bool = False,
    now: datetime | None = None,
) -> tuple[ClaimRecord, ProgressEventV1]:
    """Record durable advancement on exactly one live claim owned by this session."""

    if not scope.strip():
        raise ValueError("Progress recording requires one exact non-empty scope")
    if require_native_session_binding:
        validate_native_session_binding(
            agent,
            session_id,
            require_native_marker=True,
        )
    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )
    event = build_progress_event(
        progress_kind=progress_kind,
        evidence_ref=evidence_ref,
        next_action=next_action,
        expected_quiet_until=expected_quiet_until,
        quiet_reason=quiet_reason,
        progress_at=now,
    )
    resolved_claims_dir = (claims_dir or CLAIMS_DIR).expanduser().resolve()

    with claim_registry_lock(resolved_claims_dir):
        registry_digest_before = _registry_digest(resolved_claims_dir)
        matches: list[tuple[Path, dict[str, Any], ClaimRecord]] = []
        if resolved_claims_dir.exists():
            for claim_file in sorted(resolved_claims_dir.glob("*.yaml")):
                try:
                    data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
                except Exception:
                    continue
                if not isinstance(data, dict):
                    continue
                claim = normalize_claim(data, source_file=str(claim_file))
                if claim is None or not claim.is_live():
                    continue
                if claim.agent != agent or project not in claim.projects or claim.scope != scope:
                    continue
                if claim.session_id != resolved_session_id:
                    continue
                matches.append((claim_file, data, claim))

        if not matches:
            raise ValueError(
                "Progress matched no exact live owning claim for "
                f"agent={agent}, project={project}, scope={scope}, session_id={resolved_session_id}."
            )
        if len(matches) != 1:
            raise ValueError(
                "Progress matched multiple live claims; repair duplicate claim identity before recording advancement."
            )

        claim_file, data, claim = matches[0]
        reject_mutation_during_session_takeover(data, operation="record progress on")
        previous_progress_at = _parse_aware_iso_datetime(claim.progress_at)
        if previous_progress_at is not None and event.recorded_at <= previous_progress_at:
            raise ValueError("Progress event timestamp must advance beyond the claim's current progress_at")
        expires_at = _parse_aware_iso_datetime(claim.expires_at)
        if expires_at is not None and event.recorded_at > expires_at:
            raise ValueError("Cannot record progress after the claim expiry")
        if event.expected_quiet_until is not None and expires_at is None:
            raise ValueError("A quiet interval requires a valid timezone-aware claim expiry")
        if (
            expires_at is not None
            and event.expected_quiet_until is not None
            and event.expected_quiet_until > expires_at
        ):
            raise ValueError("expected_quiet_until cannot exceed the current claim expiry")

        data.update(_progress_event_payload(event))
        data["updated_at"] = event.recorded_at.isoformat()
        _atomic_write_claim(claim_file, data)
        _projection_path, projection_digest_after = refresh_prewrite_authority_projection(resolved_claims_dir)
        record_claim_mutation(
            # `session_upsert` is the backward-compatible typed ledger class for
            # additive claim/session state. Adding a new closed Literal would
            # make older installed readers reject the shared v1 event stream.
            operation="session_upsert",
            claims_dir=resolved_claims_dir,
            registry_digest_before=registry_digest_before,
            target_project=claim.primary_project(),
            target_scope=claim.scope,
            target_claim_path=claim_file,
            session_id=resolved_session_id,
            projection_digest_after=projection_digest_after,
        )

    updated = normalize_claim(data, source_file=str(claim_file))
    if updated is None:
        raise RuntimeError("Progress mutation produced an invalid claim")
    return updated, event


def end_session_claims(
    *,
    agent: str,
    session_id: str | None = None,
    reason: str = "session ended",
    claims_dir: Path | None = None,
) -> tuple[int, list[str], str, str]:
    """Retire exact-session live ownership without deleting recovery state."""

    resolved_session_id = resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise ValueError(
            "Unable to resolve a session ID. Pass --session-id explicitly or run from a supported tool runtime."
        )
    resolved_claims_dir = claims_dir or CLAIMS_DIR
    ended_at = datetime.now(timezone.utc).isoformat()
    ended_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(resolved_claims_dir):
        registry_digest_before = _registry_digest(resolved_claims_dir)
        if not resolved_claims_dir.exists():
            return 0, [], resolved_session_id, ended_at
        for claim_file in resolved_claims_dir.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError):
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if (
                claim is None
                or not claim.is_live()
                or claim.agent != agent
                or claim.session_id not in session_identity_aliases(agent, resolved_session_id)
            ):
                continue
            data["previous_status"] = claim.status
            data["status"] = SESSION_ENDED_STATUS
            data["session_end_reason"] = reason.strip() or "session ended"
            data["session_ended_at"] = ended_at
            data["updated_at"] = ended_at
            _atomic_write_claim(claim_file, data)
            ended_claims.append((claim_file, claim))
        if ended_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(resolved_claims_dir)
            for claim_file, claim in ended_claims:
                record_claim_mutation(
                    operation="session_end",
                    claims_dir=resolved_claims_dir,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=resolved_session_id,
                    projection_digest_after=projection_digest_after,
                )
    ended_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in ended_claims]
    return len(ended_labels), sorted(ended_labels), resolved_session_id, ended_at


def release_claim(
    agent: str,
    project: str,
    scope: str,
    *,
    expected_session_id: str | None = None,
    expected_start_revision: str | None = None,
    allow_managed_lane_rollback: bool = False,
) -> tuple[bool, str]:
    """Release an existing claim, optionally guarded by exact custody.

    ``allow_managed_lane_rollback`` is reserved for the claim bootstrap's
    compensating transaction after it has proved that no worktree survived.
    Ordinary callers must close managed lanes through ``session-close``.
    """
    filename = _claim_filename(agent, project, scope)
    path = CLAIMS_DIR / filename
    with claim_registry_lock(CLAIMS_DIR):
        if path.exists():
            registry_digest_before = _registry_digest(CLAIMS_DIR)
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            claim = normalize_claim(raw, source_file=str(path)) if isinstance(raw, dict) else None
            if expected_session_id is not None and (claim is None or claim.session_id != expected_session_id):
                raise ValueError(f"Refusing to release {project}:{scope}: session custody changed")
            if expected_start_revision is not None and (
                claim is None or claim.start_revision != expected_start_revision
            ):
                raise ValueError(f"Refusing to release {project}:{scope}: start-revision custody changed")
            if claim is not None and claim.worktree_path:
                worktree_exists = Path(claim.worktree_path).expanduser().exists()
                branch_exists = False
                if claim.repo_root and claim.branch:
                    repo_root = Path(claim.repo_root).expanduser()
                    if repo_root.exists():
                        branch_exists = (
                            _run_git(
                                repo_root,
                                ["show-ref", "--verify", f"refs/heads/{claim.branch}"],
                            ).returncode
                            == 0
                        )
                rollback_is_safe = (
                    allow_managed_lane_rollback
                    and expected_session_id is not None
                    and not worktree_exists
                )
                if (worktree_exists or branch_exists) and not rollback_is_safe:
                    raise ValueError(
                        "Refusing to release a managed worktree claim independently of its lane. "
                        "Use session-close so disposition, worktree removal, branch deletion, "
                        "claim archival, and projection refresh remain one sanctioned operation."
                    )
            path.unlink()
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            record_claim_mutation(
                operation="release",
                claims_dir=CLAIMS_DIR,
                registry_digest_before=registry_digest_before,
                target_project=project,
                target_scope=scope,
                target_claim_path=path,
                session_id=claim.session_id if claim else None,
                projection_digest_after=projection_digest_after,
            )
            return True, f"Released: {agent} → {project}:{scope}"
    return False, f"No claim found for {agent} → {project}:{scope}"


def release_claims_for_branch(branch: str) -> tuple[int, list[str]]:
    """Release every live canonical claim attached to one branch.

    Backs the legacy ``worktree-coordination/check_claims.py --release --id
    BRANCH`` facade (called by ``merge_pr.py`` after a merge). A managed lane
    whose worktree or branch still exists is refused by :func:`release_claim`
    with a ``ValueError`` naming ``session-close``; that error propagates so the
    caller can exit non-zero with the message instead of silently succeeding.
    """

    normalized = branch.strip()
    if not normalized:
        raise ValueError("branch must be non-empty")
    released: list[str] = []
    for claim in check_claims():
        if claim.branch != normalized:
            continue
        project = claim.primary_project()
        if not project:
            continue
        ok, message = release_claim(claim.agent, project, claim.scope)
        if ok:
            released.append(message)
    return len(released), released


def _archive_completed_claim_locked(
    claim_file: Path,
    *,
    claims_dir: Path,
) -> tuple[ClaimRecord, claim_mutation_receipts.CompletedClaimArchiveReceiptV1]:
    """Archive and remove one exact completed claim while the registry lock is held."""

    source_bytes = claim_file.read_bytes()
    try:
        data = yaml.safe_load(source_bytes.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise CompletedClaimArchiveError(
            error_code="invalid_completed_claim_source",
            source_path=str(claim_file),
            cause=exc,
        ) from exc
    claim = normalize_claim(data, source_file=str(claim_file)) if isinstance(data, dict) else None
    if claim is None or claim.status.strip().lower() not in COMPLETED_STATUSES:
        cause = ValueError("claim must be a valid completed record before archival")
        raise CompletedClaimArchiveError(
            error_code="invalid_completed_claim_source",
            source_path=str(claim_file),
            cause=cause,
        ) from cause
    archive_receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="live_prune",
        source_path=claim_file,
        source_bytes=source_bytes,
        writer=_LOADED_WRITER_IDENTITY,
    )
    try:
        claim_mutation_receipts.append_completed_claim_archive_receipt(archive_receipt)
    except (OSError, ValueError) as exc:
        raise CompletedClaimArchiveError(
            error_code="completed_claim_archive_write_failed",
            source_path=str(claim_file),
            cause=exc,
        ) from exc
    if claim_file.read_bytes() != source_bytes:
        cause = ValueError("claim source bytes changed after archive persistence")
        raise CompletedClaimArchiveError(
            error_code="completed_claim_source_changed_before_prune",
            source_path=str(claim_file),
            cause=cause,
        ) from cause

    registry_digest_before = _registry_digest(claims_dir)
    claim_file.unlink()
    _projection_path, projection_digest_after = refresh_prewrite_authority_projection(claims_dir)
    record_claim_mutation(
        operation="prune",
        claims_dir=claims_dir,
        registry_digest_before=registry_digest_before,
        target_project=claim.primary_project(),
        target_scope=claim.scope,
        target_claim_path=claim_file,
        session_id=claim.session_id,
        projection_digest_after=projection_digest_after,
        archive_transaction_id=archive_receipt.prune_binding.transaction_id,
        known_registry_digest_after=projection_digest_after,
        known_projection_current_after=True,
    )
    return claim, archive_receipt


def complete_claims_for_plan(
    *,
    project: str,
    plan_ref: str,
    note: str | None = None,
) -> tuple[int, list[str]]:
    """Mark matching live claims completed and return the affected scopes.

    This is retained for non-worktree coordination records. Managed worktree
    lanes close through ``session-close``. Every completed YAML record is moved
    immediately into the exact-byte archive so terminal history cannot grow the
    synchronous live registry.
    """

    now = datetime.now(timezone.utc).isoformat()
    completed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if project not in claim.projects:
                continue
            if claim.plan_ref != plan_ref:
                continue
            data["status"] = "completed"
            data["updated_at"] = now
            if note:
                existing_notes = data.get("notes")
                if isinstance(existing_notes, str) and existing_notes.strip():
                    if note not in existing_notes:
                        data["notes"] = f"{existing_notes.rstrip()} | {note}"
                else:
                    data["notes"] = note
            _atomic_write_claim(claim_file, data)
            completed_claims.append((claim_file, claim))
        if completed_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            for claim_file, claim in completed_claims:
                record_claim_mutation(
                    operation="closeout",
                    claims_dir=CLAIMS_DIR,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=claim.session_id,
                    projection_digest_after=projection_digest_after,
                )
            for claim_file, _claim in completed_claims:
                _archive_completed_claim_locked(
                    claim_file,
                    claims_dir=CLAIMS_DIR,
                )
    completed_scopes = [claim.scope for _path, claim in completed_claims]
    return len(completed_scopes), sorted(completed_scopes)


def _matches_prune_selectors(
    claim: ClaimRecord,
    *,
    agent: str | None,
    project: str | None,
    scope: str | None,
) -> bool:
    """Return whether one normalized claim matches every supplied selector."""

    return not (
        (agent is not None and claim.agent != agent)
        or (project is not None and project not in claim.projects)
        or (scope is not None and claim.scope != scope)
    )


def prune_expired(
    *,
    agent: str | None = None,
    project: str | None = None,
    scope: str | None = None,
) -> tuple[int, list[str]]:
    """Remove selected expired claims and return count plus exact scope labels."""
    now = datetime.now(timezone.utc)
    removed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not _matches_prune_selectors(
                claim,
                agent=agent,
                project=project,
                scope=scope,
            ):
                continue
            expires_at = _parse_iso_datetime(data.get("expires_at"))
            if expires_at is None or expires_at >= now:
                continue
            claim_file.unlink()
            removed_claims.append((claim_file, claim))
        if removed_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            for claim_file, claim in removed_claims:
                record_claim_mutation(
                    operation="prune",
                    claims_dir=CLAIMS_DIR,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=claim.session_id,
                    projection_digest_after=projection_digest_after,
                )
    removed_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in removed_claims]
    return len(removed_labels), sorted(removed_labels)


def prune_stale(
    *,
    agent: str | None = None,
    project: str | None = None,
    scope: str | None = None,
) -> tuple[int, list[str]]:
    """Remove selected stale live claims and return count plus scope labels."""
    removed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        registry_digest_before = _registry_digest(CLAIMS_DIR)
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in CLAIMS_DIR.glob("*.yaml"):
            try:
                data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None or not claim.is_live():
                continue
            if not _matches_prune_selectors(
                claim,
                agent=agent,
                project=project,
                scope=scope,
            ):
                continue
            liveness_issues = claim_liveness_issues(claim)
            proven_stale_liveness = [issue for issue in liveness_issues if issue != "missing_session_heartbeat"]
            if not (claim_lifecycle_issues(claim) or proven_stale_liveness):
                continue
            claim_file.unlink()
            removed_claims.append((claim_file, claim))
        if removed_claims:
            _projection_path, projection_digest_after = refresh_prewrite_authority_projection(CLAIMS_DIR)
            for claim_file, claim in removed_claims:
                record_claim_mutation(
                    operation="prune",
                    claims_dir=CLAIMS_DIR,
                    registry_digest_before=registry_digest_before,
                    target_project=claim.primary_project(),
                    target_scope=claim.scope,
                    target_claim_path=claim_file,
                    session_id=claim.session_id,
                    projection_digest_after=projection_digest_after,
                )
    removed_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in removed_claims]
    return len(removed_labels), sorted(removed_labels)


def prune_completed(
    *,
    agent: str | None = None,
    project: str | None = None,
    scope: str | None = None,
) -> tuple[int, list[str]]:
    """Remove claims already marked complete/completed.

    This is intentionally narrower than ``prune_expired``: it never removes a
    live active/blocked/handoff claim solely because its TTL elapsed. Use it for
    housekeeping completed claim history after the claim's audit value has been
    captured elsewhere.
    """

    archive_candidates: list[
        tuple[
            Path,
            bytes,
            ClaimRecord,
            claim_mutation_receipts.CompletedClaimArchiveReceiptV1,
        ]
    ] = []
    removed_claims: list[tuple[Path, ClaimRecord]] = []
    with claim_registry_lock(CLAIMS_DIR):
        if not CLAIMS_DIR.exists():
            return 0, []
        for claim_file in sorted(CLAIMS_DIR.glob("*.yaml")):
            try:
                source_bytes = claim_file.read_bytes()
                data = yaml.safe_load(source_bytes.decode("utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            if not isinstance(data, dict):
                invalid_mapping = ValueError("claim YAML must decode to a mapping")
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=invalid_mapping,
                ) from invalid_mapping
            claim = normalize_claim(data, source_file=str(claim_file))
            if claim is None:
                invalid_claim = ValueError("claim YAML does not satisfy the claim identity contract")
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=invalid_claim,
                ) from invalid_claim
            if claim.status.strip().lower() not in COMPLETED_STATUSES:
                continue
            if not _matches_prune_selectors(
                claim,
                agent=agent,
                project=project,
                scope=scope,
            ):
                continue
            try:
                archive_receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
                    source_kind="live_prune",
                    source_path=claim_file,
                    source_bytes=source_bytes,
                    writer=_LOADED_WRITER_IDENTITY,
                )
            except ValueError as exc:
                raise CompletedClaimArchiveError(
                    error_code="invalid_completed_claim_source",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            archive_candidates.append((claim_file, source_bytes, claim, archive_receipt))

        for claim_file, _source_bytes, _claim, archive_receipt in archive_candidates:
            try:
                claim_mutation_receipts.append_completed_claim_archive_receipt(archive_receipt)
            except (OSError, ValueError) as exc:
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_archive_write_failed",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc

        for claim_file, source_bytes, _claim, _archive_receipt in archive_candidates:
            try:
                current_bytes = claim_file.read_bytes()
            except OSError as exc:
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_source_changed_before_prune",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            if current_bytes != source_bytes:
                changed_source = ValueError("claim source bytes changed after archive persistence and before prune")
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_source_changed_before_prune",
                    source_path=str(claim_file),
                    cause=changed_source,
                ) from changed_source

        if not archive_candidates:
            return 0, []

        from enforced_planning.prewrite_claim_fast import projection_path_for
        from enforced_planning.prewrite_claim_projection import (
            build_projection,
            rebind_projection_digest,
            write_projection_document,
        )

        # The prune loop used to rebuild the projection from disk after every
        # unlink, which re-read and re-parsed the whole registry once per claim
        # and made a drain quadratic: a 542-claim drain held the global registry
        # lock for 887.9s. Two facts make that unnecessary. The projection only
        # carries live claims, and COMPLETED_STATUSES is disjoint from
        # LIVE_STATUSES, so removing a completed claim cannot change which
        # claims the projection carries or their static issues. And the registry
        # digest is a pure function of the YAML bytes, which are already read
        # here under the lock. So the claim set is built once and the digest is
        # advanced in memory, while each receipt still observes a projection
        # that is genuinely current on disk at the moment it is written.
        resolved_claims_dir = CLAIMS_DIR.expanduser().resolve()
        registry_snapshot = _registry_snapshot(resolved_claims_dir)
        running_digest = _registry_digest_from_snapshot(registry_snapshot)
        observed_digest = _registry_digest(CLAIMS_DIR)
        if running_digest != observed_digest:
            snapshot_mismatch = ValueError(
                "in-memory registry snapshot does not reproduce the on-disk registry digest: "
                f"snapshot={running_digest} disk={observed_digest}"
            )
            raise CompletedClaimArchiveError(
                error_code="registry_snapshot_digest_mismatch",
                source_path=str(resolved_claims_dir),
                cause=snapshot_mismatch,
            ) from snapshot_mismatch
        projection_path = projection_path_for(resolved_claims_dir)
        live_projection = build_projection(claims_dir=resolved_claims_dir)

        for claim_file, source_bytes, claim, archive_receipt in archive_candidates:
            try:
                if claim_file.read_bytes() != source_bytes:
                    raise ValueError("claim source bytes changed immediately before prune")
            except (OSError, ValueError) as exc:
                raise CompletedClaimArchiveError(
                    error_code="completed_claim_source_changed_before_prune",
                    source_path=str(claim_file),
                    cause=exc,
                ) from exc
            if registry_snapshot.pop(claim_file.name, None) != source_bytes:
                untracked = ValueError("claim is absent from the registry snapshot taken for this prune")
                raise PruneRegistryDivergenceError(f"{claim_file}: {untracked}") from untracked
            registry_digest_before = running_digest
            claim_file.unlink()
            running_digest = _registry_digest_from_snapshot(registry_snapshot)
            projection_digest_after = running_digest
            write_projection_document(
                claims_dir=resolved_claims_dir,
                projection=rebind_projection_digest(
                    live_projection,
                    registry_digest_value=projection_digest_after,
                ),
                projection_path=projection_path,
            )
            receipt = record_claim_mutation(
                operation="prune",
                claims_dir=CLAIMS_DIR,
                registry_digest_before=registry_digest_before,
                target_project=claim.primary_project(),
                target_scope=claim.scope,
                target_claim_path=claim_file,
                session_id=claim.session_id,
                projection_digest_after=projection_digest_after,
                archive_transaction_id=archive_receipt.prune_binding.transaction_id,
                known_registry_digest_after=projection_digest_after,
                known_projection_current_after=True,
            )
            # The lock-owned snapshot and just-written projection define the
            # per-step receipt. A single full rebuild below cross-checks the
            # batch against real authority without rescanning N files N times.
            if receipt.registry_digest_after != projection_digest_after:
                raise PruneRegistryDivergenceError(
                    f"{claim_file}: registry digest diverged from the in-memory prune snapshot: "
                    f"snapshot={projection_digest_after} disk={receipt.registry_digest_after}"
                )
            removed_claims.append((claim_file, claim))

        # Terminal equivalence check: rebuild from disk exactly as the
        # per-unlink path used to, and require that the incrementally
        # maintained state is what a full rebuild produces.
        rebuilt = build_projection(claims_dir=resolved_claims_dir)
        if rebuilt.registry_digest != running_digest:
            raise PruneRegistryDivergenceError(
                "rebuilt projection digest does not match the pruned registry snapshot: "
                f"snapshot={running_digest} rebuilt={rebuilt.registry_digest}"
            )
        if rebuilt.claims != live_projection.claims:
            raise PruneRegistryDivergenceError(
                "pruning completed claims changed the projected live claim set, "
                "which the incremental prune projection assumes cannot happen"
            )
        # Leave the on-disk projection written by the canonical refresh path,
        # still inside this critical section.
        refresh_prewrite_authority_projection(CLAIMS_DIR)
    removed_labels = [f"{claim.primary_project()}:{claim.scope}" for _path, claim in removed_claims]
    return len(removed_labels), sorted(removed_labels)


def backfill_completed_claim_archive(
    *,
    source_claim_snapshot: Path,
    expected_source_sha256: str,
    prune_event_id: str,
) -> tuple[claim_mutation_receipts.CompletedClaimArchiveReceiptV1, bool]:
    """Archive one legacy completed claim using exact bytes and prune provenance."""

    resolved_snapshot = source_claim_snapshot.expanduser().resolve()
    source_bytes = resolved_snapshot.read_bytes()
    observed_source_sha256 = hashlib.sha256(source_bytes).hexdigest()
    if observed_source_sha256 != expected_source_sha256:
        raise ValueError(
            f"source SHA-256 mismatch: expected={expected_source_sha256} observed={observed_source_sha256}"
        )

    mutation_receipts = claim_mutation_receipts.load_receipts()
    matching_events = [event for event in mutation_receipts if event.event_id == prune_event_id]
    if len(matching_events) != 1:
        raise ValueError(
            "legacy completed-claim backfill requires exactly one historical prune "
            f"event for event_id={prune_event_id!r}"
        )
    prune_event = matching_events[0]
    if not prune_event.target_claim_path:
        raise ValueError("historical prune event is missing its target claim path")
    historical_claim_path = Path(prune_event.target_claim_path).expanduser().resolve()
    receipt = claim_mutation_receipts.build_completed_claim_archive_receipt(
        source_kind="legacy_reconciliation",
        source_path=historical_claim_path,
        source_bytes=source_bytes,
        prune_event_id=prune_event.event_id,
        writer=_LOADED_WRITER_IDENTITY,
    )
    expected_filename = _claim_filename(
        receipt.agent,
        receipt.project,
        receipt.scope,
    )
    if historical_claim_path.name != expected_filename:
        raise ValueError(
            "historical prune event path does not match the completed claim identity: "
            f"expected filename={expected_filename!r} "
            f"observed={historical_claim_path.name!r}"
        )
    claim_mutation_receipts.validate_completed_claim_archive_prune_binding(
        receipt,
        mutation_receipts=mutation_receipts,
    )
    _archive_path, appended = claim_mutation_receipts.append_completed_claim_archive_receipt(receipt)
    persisted = [
        candidate
        for candidate in claim_mutation_receipts.load_completed_claim_archive_receipts()
        if candidate.archive_id == receipt.archive_id
    ]
    if len(persisted) != 1:
        raise ValueError(
            f"completed-claim archive did not retain exactly one validated receipt for archive_id={receipt.archive_id}"
        )
    return persisted[0], appended


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for coordination-claim management."""
    parser = argparse.ArgumentParser(description="Cross-brain coordination claims")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="Check for active claims")
    group.add_argument("--claim", action="store_true", help="Create a new claim")
    group.add_argument("--release", action="store_true", help="Release an existing claim")
    group.add_argument("--list", action="store_true", help="List all active claims")
    group.add_argument(
        "--list-stale",
        action="store_true",
        help=(
            "Report live claims with a liveness or lifecycle issue (e.g. stale "
            "heartbeat, missing worktree/branch, already merged to default), "
            "read-only. The same checks --prune-stale acts on, without deleting "
            "anything -- use this to answer 'what work is another agent still "
            "covering' before assuming a claim is abandoned."
        ),
    )
    group.add_argument(
        "--list-abandoned",
        action="store_true",
        help=(
            "Report EXPIRED claims whose branch still holds real unmerged "
            "commits (ahead of default, not already merged), read-only. "
            "--list-stale never sees these: expired claims are excluded from "
            "every other listing before evaluation. Use this to find "
            "substantive work that died mid-task with nobody following up, "
            "before --prune/--prune-stale deletes the claim record."
        ),
    )
    group.add_argument("--prune", action="store_true", help="Remove expired claims")
    group.add_argument(
        "--prune-stale",
        action="store_true",
        help="Remove mechanically stale live claims whose lifecycle state is no longer truthful.",
    )
    group.add_argument(
        "--prune-completed",
        action="store_true",
        help="Remove valid YAML claims already marked complete/completed; never prunes live claims.",
    )
    group.add_argument(
        "--backfill-completed-claim-archive",
        action="store_true",
        help="Archive one legacy completed claim from exact snapshot bytes and an applied prune event.",
    )
    group.add_argument(
        "--hydrate-session-ids",
        action="store_true",
        help="Fill in missing session_id metadata for matching live claims.",
    )
    group.add_argument(
        "--heartbeat",
        action="store_true",
        help="Refresh heartbeat metadata for matching live claims owned by the current session.",
    )
    group.add_argument(
        "--progress",
        action="store_true",
        help="Record one durable progress event on an exact live claim owned by the current session.",
    )

    parser.add_argument(
        "--agent",
        choices=SUPPORTED_AGENTS,
        help="Agent brain name (claude-code, codex, openclaw)",
    )
    parser.add_argument("--project", help="Project name")
    parser.add_argument("--scope", help="Scope path or identifier")
    parser.add_argument("--intent", help="What the agent intends to do")
    parser.add_argument("--plan", help="Plan reference (e.g., Plan #28)")
    parser.add_argument("--ttl-hours", type=float, default=DEFAULT_TTL_HOURS, help="Claim TTL in hours")
    parser.add_argument("--claim-type", choices=sorted(CLAIM_TYPES), help="Claim category")
    parser.add_argument("--write-path", action="append", default=[], help="Repo-relative write path")
    parser.add_argument("--read-path", action="append", default=[], help="Repo-relative read path")
    parser.add_argument("--worktree-path", help="Worktree path for this claim")
    parser.add_argument("--broad-scope-mode", choices=sorted(BROAD_SCOPE_MODES))
    parser.add_argument("--broad-scope-reason")
    parser.add_argument("--target-worktree-path")
    parser.add_argument(
        "--contact-ref",
        help=(
            "Optional peer-messaging identity for this claim (e.g. a ListAgents name/ref), "
            "so another session hitting overlapping_write_claim against it can message the "
            "owner directly instead of only seeing agent/project/scope."
        ),
    )
    parser.add_argument("--repo-root", help="Canonical repository root for readiness validation")
    parser.add_argument("--branch", help="Branch for this claim")
    parser.add_argument(
        "--start-point",
        default="HEAD",
        help="Exact Git start point whose committed plan/config bytes must pass admission.",
    )
    parser.add_argument(
        "--plan-repo-root",
        help="Absolute canonical repository root for a qualified external plan authority.",
    )
    parser.add_argument(
        "--plan-start-point",
        help="Full immutable plan-authority revision for a qualified external plan.",
    )
    parser.add_argument(
        "--method-receipt",
        help=(
            "Repository-relative path of the plan's passing Company Planning method-conformance receipt "
            "(required for plan-backed claims when meta-process.yaml sets plans.method_conformance.mode: required)."
        ),
    )
    parser.add_argument(
        "--method-receipt-sha256",
        help="SHA-256 of the receipt file bytes, from the plan's adoption decision.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "Mark a plan-state resume attempt; this does not authorize a new non-tip claim. "
            "Use session-resume for an existing retained lane."
        ),
    )
    parser.add_argument(
        "--require-new",
        action="store_true",
        help="Reject an occupied claim slot instead of refreshing it.",
    )
    parser.add_argument(
        "--expected-start-revision",
        help="Guard release on the exact retained Git start revision.",
    )
    parser.add_argument(
        "--require-current-session",
        action="store_true",
        help="Guard release on the native session identity of the current agent runtime.",
    )
    parser.add_argument(
        "--rollback-managed-lane",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument("--session-id", help="Session identifier")
    parser.add_argument("--progress-kind", choices=sorted(PROGRESS_KINDS), help="Durable progress kind")
    parser.add_argument("--evidence-ref", help="Non-empty durable evidence reference")
    parser.add_argument("--next-action", help="Concrete next action after this progress event")
    parser.add_argument("--expected-quiet-until", help="Bounded timezone-aware quiet deadline")
    parser.add_argument("--quiet-reason", help="Reason for a paired quiet deadline")
    parser.add_argument(
        "--session-name",
        help="Human-readable broader-goal session name; required for live program/write/research claims",
    )
    parser.add_argument(
        "--broader-goal",
        help="Human-readable outcome that the claimed session advances.",
    )
    parser.add_argument(
        "--tracker-path",
        help=(
            "Path to a durable session tracker for this claim; required for a "
            "live program/write/research claim to pass push-check. "
            "`make maintenance-worktree` / `start_session` generate one "
            "automatically -- only pass this directly when creating a claim "
            "through the bare --claim CLI."
        ),
    )
    parser.add_argument("--status", default="active", help="Claim status (default: active)")
    parser.add_argument("--parent-scope", help="Parent/broad-scope identifier")
    parser.add_argument(
        "--allow-parallel",
        action="store_true",
        help="Explicitly authorize an additional root for this runtime session.",
    )
    parser.add_argument("--notes", help="Freeform notes")
    parser.add_argument(
        "--work-graph",
        help="Repository-relative canonical work graph required for plan-bound write ownership.",
    )
    parser.add_argument(
        "--work-unit-id",
        help="Exact ready work-unit ID required for plan-bound write ownership.",
    )
    parser.add_argument(
        "--source-claim-snapshot",
        type=Path,
        help="Exact completed-claim YAML snapshot used for legacy archive reconciliation.",
    )
    parser.add_argument(
        "--expected-source-sha256",
        help="Operator-reviewed SHA-256 of --source-claim-snapshot.",
    )
    parser.add_argument(
        "--prune-event-id",
        help="Existing applied claim-mutation event ID for the legacy prune.",
    )
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    return parser.parse_args(argv)


def _validate_explicit_prune_selectors(args: argparse.Namespace) -> None:
    """Reject empty prune selectors before the registry lock can be acquired."""

    if not (args.prune or args.prune_stale or args.prune_completed):
        return
    for name in ("project", "scope"):
        value = getattr(args, name)
        if value is not None and not value.strip():
            raise SystemExit(f"--{name} must contain non-whitespace text when supplied")


def _render_check_output(
    *,
    claims: list[ClaimRecord],
    project: str | None,
    candidate: ClaimRecord | None,
) -> dict[str, Any]:
    """Build a structured report for list/check operations."""
    observed_at = datetime.now(timezone.utc)
    enforcement_issues = [issue for claim in claims for issue in claim_enforcement_issues(claim)]
    payload: dict[str, Any] = {
        "project": project,
        "has_high_severity_issues": bool(enforcement_issues),
        "enforcement_issues": enforcement_issues,
        "claims": [
            {
                **claim.to_dict(),
                "health_status": claim_runtime_status(
                    claim,
                    active_claims=claims,
                    now=observed_at,
                ),
                "health_issues": coordination_health_issues(
                    claim,
                    active_claims=claims,
                ),
                "lifecycle_issues": claim_lifecycle_issues(claim),
                "liveness_issues": claim_liveness_issues(claim, now=observed_at),
                "progress_issues": claim_progress_issues(claim, now=observed_at),
                "enforcement_issues": claim_enforcement_issues(claim),
                "broad_scope_diagnostic": (
                    "legacy_unclassified"
                    if "legacy_broad_scope_unclassified" in _broad_scope_contract_issues(claim)
                    else None
                ),
            }
            for claim in claims
        ],
        "unregistered_claim_files": unregistered_claim_files(),
        "malformed_claim_files": malformed_claim_files(),
    }
    if candidate is not None:
        prospective_claims = [claim for claim in claims if not _same_claim(claim, candidate)] + [candidate]
        payload["check"] = {
            **evaluate_claim(candidate, active_claims=claims).to_dict(),
            "candidate_health_status": claim_runtime_status(
                candidate,
                active_claims=prospective_claims,
                now=observed_at,
            ),
            "candidate_health_issues": coordination_health_issues(
                candidate,
                active_claims=prospective_claims,
            ),
            "candidate_lifecycle_issues": claim_lifecycle_issues(candidate),
            "candidate_liveness_issues": claim_liveness_issues(candidate, now=observed_at),
            "candidate_progress_issues": claim_progress_issues(candidate, now=observed_at),
        }
    return payload


def _render_mutation_audit_failure(exc: MutationAuditError, *, as_json: bool) -> int:
    """Report an already-applied mutation whose receipt could not be persisted."""

    if as_json:
        print(json.dumps(exc.to_dict(), indent=2, sort_keys=True))
    else:
        print(str(exc), file=sys.stderr)
    return 1


def _render_completed_claim_archive_failure(
    exc: CompletedClaimArchiveError,
    *,
    as_json: bool,
) -> int:
    """Report an archive-before-prune failure that left claim YAML unchanged."""

    if as_json:
        print(json.dumps({"ok": False, **exc.to_dict()}, indent=2, sort_keys=True))
    else:
        print(str(exc), file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    """Run the CLI for cross-brain coordination claim management."""
    args = parse_args(argv)
    _validate_explicit_prune_selectors(args)

    if args.check:
        claims = check_claims(args.project)
        candidate = None
        if args.project and (args.claim_type or args.write_path or args.scope or args.agent):
            candidate = build_candidate_claim(
                agent=args.agent or "candidate",
                project=args.project,
                scope=args.scope or "preview",
                intent=args.intent or "preview active coordination interactions",
                plan_ref=args.plan,
                claim_type=args.claim_type,
                write_paths=args.write_path,
                read_paths=args.read_path,
                broad_scope_mode=args.broad_scope_mode,
                broad_scope_reason=args.broad_scope_reason,
                target_worktree_path=args.target_worktree_path,
                contact_ref=args.contact_ref,
                worktree_path=args.worktree_path,
                repo_root=args.repo_root,
                branch=args.branch,
                session_name=args.session_name,
                broader_goal=args.broader_goal,
                session_id=args.session_id,
                status=args.status,
                parent_scope=args.parent_scope,
                notes=args.notes,
                parallel_root_authorized=args.allow_parallel,
            )
        if args.json:
            print(json.dumps(_render_check_output(claims=claims, project=args.project, candidate=candidate), indent=2))
            return 1 if any(claim_enforcement_issues(claim) for claim in claims) else 0
        if not claims:
            print("No active claims.")
            return 0
        for claim in claims:
            print(f"  [{claim.agent}] {claim.primary_project()}:{claim.scope} [{claim.claim_type}] — {claim.intent}")
            print(f"    expires: {claim.expires_at}")
            if claim.write_paths:
                print(f"    write_paths: {', '.join(claim.write_paths)}")
            if "legacy_broad_scope_unclassified" in _broad_scope_contract_issues(claim):
                print("    broad_scope: legacy_unclassified (narrow or explicitly classify on material upsert)")
            for issue in claim_enforcement_issues(claim):
                print(
                    f"HIGH: {issue['code']}: {issue['message']}",
                    file=sys.stderr,
                )
        if candidate is not None:
            result = evaluate_claim(candidate, active_claims=claims)
            if not result.interactions:
                print("No interactions for candidate claim.")
            else:
                print("Candidate interactions:")
                for item in result.interactions:
                    overlaps = ", ".join(item.overlapping_write_paths) or "none"
                    print(
                        f"  - {item.severity}: {item.other_agent} {item.other_scope} "
                        f"({item.reason}; overlap={overlaps}; "
                        f"relations={','.join(item.overlap_relations) or 'none'}; "
                        f"reservation={item.reservation_kind or 'none'}; "
                        f"current_diff_disjoint={item.current_diff_disjoint!r})"
                    )
        return 1 if any(claim_enforcement_issues(claim) for claim in claims) else 0

    if args.list:
        claims = check_claims(args.project)
        if args.json:
            print(json.dumps(_render_check_output(claims=claims, project=args.project, candidate=None), indent=2))
            return 0
        unregistered = unregistered_claim_files()
        if unregistered:
            print(
                f"⚠ {len(unregistered)} claim file(s) in unregistered format — invisible to "
                "coordination tooling; refile via `make claim` / --claim:",
                file=sys.stderr,
            )
            for path in unregistered:
                print(f"    {path}", file=sys.stderr)
        malformed = malformed_claim_files()
        if malformed:
            print(
                f"⚠ {len(malformed)} claim file(s) have invalid YAML — invisible to "
                "coordination tooling until fixed or removed:",
                file=sys.stderr,
            )
            for entry in malformed:
                print(f"    {entry['path']}: {entry['error']}", file=sys.stderr)
        if not claims:
            print("No active claims.")
            return 0
        for claim in claims:
            print(f"  [{claim.agent}] {claim.primary_project()}:{claim.scope} [{claim.claim_type}] — {claim.intent}")
            if "legacy_broad_scope_unclassified" in _broad_scope_contract_issues(claim):
                print("    broad_scope: legacy_unclassified")
        for line in render_peer_claim_groups(claims):
            print(line)
        return 0

    if args.list_stale:
        claims = check_claims(args.project)
        stale = []
        for claim in claims:
            liveness_issues = claim_liveness_issues(claim)
            proven_stale_liveness = [
                issue for issue in liveness_issues if issue != "missing_session_heartbeat"
            ]
            lifecycle_issues = claim_lifecycle_issues(claim)
            issues = lifecycle_issues + proven_stale_liveness
            if issues:
                stale.append((claim, issues))
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "agent": claim.agent,
                            "project": claim.primary_project(),
                            "scope": claim.scope,
                            "session_id": claim.session_id,
                            "heartbeat_at": claim.heartbeat_at,
                            "issues": issues,
                        }
                        for claim, issues in stale
                    ],
                    indent=2,
                )
            )
            return 0
        if not stale:
            print("No live claims with a liveness or lifecycle issue.")
            return 0
        for claim, issues in stale:
            print(f"  [{claim.agent}] {claim.primary_project()}:{claim.scope} — {', '.join(issues)}")
            print(f"    heartbeat_at: {claim.heartbeat_at}")
        return 0

    if args.list_abandoned:
        abandoned = list_abandoned_claims(args.project)
        if args.json:
            print(
                json.dumps(
                    [
                        {
                            "agent": claim.agent,
                            "project": claim.primary_project(),
                            "scope": claim.scope,
                            "intent": claim.intent,
                            "repo_root": claim.repo_root,
                            "expires_at": claim.expires_at,
                            "next_action": claim.next_action,
                            **progress,
                        }
                        for claim, progress in abandoned
                    ],
                    indent=2,
                )
            )
            return 0
        if not abandoned:
            print("No expired claims with real unmerged branch progress.")
            return 0
        for claim, progress in abandoned:
            print(f"  [{claim.agent}] {claim.primary_project()}:{claim.scope} — {claim.intent}")
            print(
                f"    branch: {progress['branch']} ({progress['ahead_of_default']} ahead of "
                f"{progress['default_branch']}, last commit {progress['last_commit_at']})"
            )
            print(f"    expired: {claim.expires_at}")
            if claim.next_action:
                print(f"    next_action: {claim.next_action}")
        return 0

    if args.progress:
        if not all(
            [
                args.agent,
                args.project,
                args.scope,
                args.progress_kind,
                args.evidence_ref,
                args.next_action,
            ]
        ):
            raise SystemExit(
                "--progress requires --agent, --project, --scope, --progress-kind, --evidence-ref, and --next-action"
            )
        try:
            claim, event = record_progress_claims(
                agent=args.agent,
                project=args.project,
                scope=args.scope,
                progress_kind=args.progress_kind,
                evidence_ref=args.evidence_ref,
                next_action=args.next_action,
                session_id=args.session_id,
                expected_quiet_until=args.expected_quiet_until,
                quiet_reason=args.quiet_reason,
                require_native_session_binding=True,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
            else:
                print(str(exc), file=sys.stderr)
            return 1
        payload = {
            "ok": True,
            "project": claim.primary_project(),
            "scope": claim.scope,
            "session_id": claim.session_id,
            "progress_event": event.model_dump(mode="json"),
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(
                f"Progress recorded: {claim.primary_project()}:{claim.scope} "
                f"[{event.kind}] at {event.recorded_at.isoformat()}"
            )
        return 0

    if args.claim:
        if not all([args.agent, args.project, args.scope, args.intent]):
            raise SystemExit("--claim requires --agent, --project, --scope, --intent")
        if args.worktree_path and not Path(args.worktree_path).expanduser().is_absolute():
            # Claim consumers check this path from their own working directory, so a relative
            # path silently reads as "missing worktree" and blocks every later push of the lane.
            base = Path(args.repo_root).expanduser() if args.repo_root else Path.cwd()
            args.worktree_path = str((base / args.worktree_path).resolve())
        try:
            ok, msg = create_claim(
                args.agent,
                args.project,
                args.scope,
                args.intent,
                args.plan,
                args.ttl_hours,
                claim_type=args.claim_type,
                write_paths=args.write_path,
                read_paths=args.read_path,
                worktree_path=args.worktree_path,
                repo_root=args.repo_root,
                branch=args.branch,
                session_name=args.session_name,
                broader_goal=args.broader_goal,
                tracker_path=args.tracker_path,
                session_id=args.session_id,
                status=args.status,
                parent_scope=args.parent_scope,
                notes=args.notes,
                work_graph_path=args.work_graph,
                work_unit_id=args.work_unit_id,
                start_point=args.start_point,
                plan_repo_root=args.plan_repo_root,
                plan_start_point=args.plan_start_point,
                resume_requested=args.resume,
                require_new=args.require_new,
                allow_parallel=args.allow_parallel,
                broad_scope_mode=args.broad_scope_mode,
                broad_scope_reason=args.broad_scope_reason,
                target_worktree_path=args.target_worktree_path,
                contact_ref=args.contact_ref,
                require_native_session_binding=True,
                require_native_session_marker=True,
                method_receipt_ref=args.method_receipt,
                method_receipt_sha256=args.method_receipt_sha256,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        if args.json:
            print(json.dumps({"ok": ok, "message": msg}, indent=2))
        else:
            print(msg)
        return 0 if ok else 1

    if args.release:
        if not all([args.agent, args.project, args.scope]):
            raise SystemExit("--release requires --agent, --project, --scope")
        try:
            expected_session_id = args.session_id
            if args.require_current_session:
                expected_session_id = resolve_session_id(args.agent, args.session_id)
                if not expected_session_id:
                    raise ValueError("Unable to resolve current native session identity for guarded release")
                validate_native_session_binding(
                    args.agent,
                    expected_session_id,
                    require_native_marker=True,
                )
            ok, msg = release_claim(
                args.agent,
                args.project,
                args.scope,
                expected_session_id=expected_session_id,
                expected_start_revision=args.expected_start_revision,
                allow_managed_lane_rollback=args.rollback_managed_lane,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        if args.json:
            print(json.dumps({"ok": ok, "message": msg}, indent=2))
        else:
            print(msg)
        return 0 if ok else 1

    if args.prune:
        try:
            removed, removed_scopes = prune_expired(
                agent=args.agent,
                project=args.project,
                scope=args.scope,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        payload = {"pruned": removed, "removed_scopes": removed_scopes}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Expired claims pruned: {removed}")
            if removed_scopes:
                print("Removed scopes: " + ", ".join(removed_scopes))
        return 0

    if args.prune_stale:
        try:
            removed, removed_scopes = prune_stale(
                agent=args.agent,
                project=args.project,
                scope=args.scope,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        payload = {"pruned": removed, "removed_scopes": removed_scopes}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Stale claims pruned: {removed}")
            if removed_scopes:
                print("Removed scopes: " + ", ".join(removed_scopes))
        return 0

    if args.prune_completed:
        try:
            removed, removed_scopes = prune_completed(
                agent=args.agent,
                project=args.project,
                scope=args.scope,
            )
        except CompletedClaimArchiveError as exc:
            return _render_completed_claim_archive_failure(
                exc,
                as_json=args.json,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        payload = {"pruned": removed, "removed_scopes": removed_scopes}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Completed claims pruned: {removed}")
            if removed_scopes:
                print("Removed scopes: " + ", ".join(removed_scopes))
        return 0

    if args.backfill_completed_claim_archive:
        if not all(
            [
                args.source_claim_snapshot,
                args.expected_source_sha256,
                args.prune_event_id,
            ]
        ):
            raise SystemExit(
                "--backfill-completed-claim-archive requires "
                "--source-claim-snapshot, --expected-source-sha256, and "
                "--prune-event-id"
            )
        try:
            receipt, appended = backfill_completed_claim_archive(
                source_claim_snapshot=args.source_claim_snapshot,
                expected_source_sha256=args.expected_source_sha256,
                prune_event_id=args.prune_event_id,
            )
        except (OSError, ValueError) as exc:
            payload = {
                "ok": False,
                "error_code": "completed_claim_archive_backfill_failed",
                "error": str(exc),
            }
            if args.json:
                print(json.dumps(payload, indent=2, sort_keys=True))
            else:
                print(str(exc), file=sys.stderr)
            return 1
        payload = {
            "ok": True,
            "archive_id": receipt.archive_id,
            "receipt_sha256": receipt.receipt_sha256,
            "archive_path": str(claim_mutation_receipts.DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH.expanduser().resolve()),
            "appended": appended,
            "source_kind": receipt.source_kind,
            "prune_event_id": receipt.prune_binding.mutation_event_id,
        }
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            action = "appended" if appended else "already present"
            print(f"Completed-claim archive receipt {receipt.archive_id} {action} at {payload['archive_path']}")
        return 0

    if args.hydrate_session_ids:
        if not all([args.agent, args.project]):
            raise SystemExit("--hydrate-session-ids requires --agent and --project")
        try:
            updated_count, updated_scopes, resolved_session_id = hydrate_missing_session_ids(
                agent=args.agent,
                project=args.project,
                session_id=args.session_id,
                scope=args.scope,
                branch=args.branch,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        payload = {
            "ok": True,
            "updated_count": updated_count,
            "updated_scopes": updated_scopes,
            "session_id": resolved_session_id,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Hydrated {updated_count} claim(s) for {args.agent}:{args.project} "
                f"with session_id={resolved_session_id}"
            )
        return 0

    if args.heartbeat:
        if not all([args.agent, args.project]):
            raise SystemExit("--heartbeat requires --agent and --project")
        try:
            updated_count, updated_scopes, resolved_session_id, heartbeat_at = heartbeat_claims(
                agent=args.agent,
                project=args.project,
                session_id=args.session_id,
                scope=args.scope,
                branch=args.branch,
            )
        except MutationAuditError as exc:
            return _render_mutation_audit_failure(exc, as_json=args.json)
        except ValueError as exc:
            if args.json:
                print(json.dumps({"ok": False, "message": str(exc)}, indent=2))
            else:
                print(str(exc))
            return 1
        payload = {
            "ok": True,
            "updated_count": updated_count,
            "updated_scopes": updated_scopes,
            "session_id": resolved_session_id,
            "heartbeat_at": heartbeat_at,
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(
                f"Heartbeated {updated_count} claim(s) for {args.agent}:{args.project} "
                f"with session_id={resolved_session_id} at {heartbeat_at}"
            )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
