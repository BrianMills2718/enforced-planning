"""Typed pre-write authorization against the canonical coordination claims."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, cast

import yaml  # type: ignore[import-untyped]
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from enforced_planning import coordination_claims
from enforced_planning.worktree_paths import resolve_canonical_repo_root


PreWriteMode = Literal["off", "observe", "enforce"]
PreWriteClient = Literal["codex", "claude-code"]
PreWriteDecisionKind = Literal["allow", "observe_violation", "deny"]

DEFAULT_RECEIPT_PATH = Path.home() / ".claude" / "coordination" / "prewrite-events-v1.jsonl"
DEFAULT_CACHE_DIR = Path.home() / ".claude" / "coordination" / "prewrite-cache-v1"
CACHE_TTL_SECONDS = 2.0


class HookPayloadError(ValueError):
    """Raised when a native hook payload cannot prove its write targets."""


class PreWriteEvaluationError(ValueError):
    """Raised when repository or claim identity cannot be evaluated."""


class StrictContract(BaseModel):
    """Reject unknown fields on durable pre-write contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PreWriteRequestV1(StrictContract):
    """Client-neutral description of one native write attempt."""

    schema_version: Literal["1.0"] = "1.0"
    client: PreWriteClient = Field(description="Native client producing the hook event.")
    hook_event_name: Literal["PreToolUse"] = Field(description="Only the pre-mutation event is valid.")
    tool_name: str = Field(min_length=1, description="Canonical native tool name.")
    session_id: str = Field(min_length=1, description="Canonical client-prefixed session identity.")
    cwd: str = Field(min_length=1, description="Native session working directory.")
    target_paths: tuple[str, ...] = Field(min_length=1, description="Candidate paths before mutation.")


class PreWriteDecisionV1(StrictContract):
    """One attributable authorization decision returned before mutation."""

    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str = Field(pattern=r"^prewrite_[0-9a-f]{32}$")
    decision: PreWriteDecisionKind
    mode: PreWriteMode
    reason_code: str = Field(min_length=1)
    client: PreWriteClient
    session_id: str = Field(min_length=1)
    repo_root: str | None = None
    worktree_path: str | None = None
    branch: str | None = None
    normalized_target_paths: tuple[str, ...] = ()
    claim_project: str | None = None
    claim_scope: str | None = None
    claim_source_file: str | None = None
    details: tuple[str, ...] = ()
    recovery: str | None = None
    elapsed_ms: float = Field(ge=0)
    cache_hit: bool = False


class PreWriteReceiptV1(StrictContract):
    """Append-only local evidence for one pre-write decision."""

    schema_version: Literal["1.0"] = "1.0"
    recorded_at: AwareDatetime
    receipt_id: str
    decision: PreWriteDecisionKind
    mode: PreWriteMode
    reason_code: str
    client: PreWriteClient
    session_id: str
    repo_root: str | None
    worktree_path: str | None
    branch: str | None
    normalized_target_paths: tuple[str, ...]
    claim_project: str | None
    claim_scope: str | None
    claim_source_file: str | None
    details: tuple[str, ...]
    elapsed_ms: float
    cache_hit: bool


class _RepositoryContext(StrictContract):
    worktree_path: str
    repo_root: str
    branch: str
    normalized_target_paths: tuple[str, ...]


_CUSTOM_PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
_CUSTOM_MOVE_PATH = re.compile(r"^\*\*\* Move to: (.+)$")
_UNIFIED_PATCH_PATH = re.compile(r"^(?:---|\+\+\+) (.+)$")


def _nonempty_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HookPayloadError(f"PreToolUse payload requires non-empty {field!r}")
    return value.strip()


def _canonical_session_id(client: PreWriteClient, raw_session_id: str) -> str:
    return raw_session_id if raw_session_id.startswith(f"{client}:") else f"{client}:{raw_session_id}"


def _patch_paths(command: str) -> tuple[str, ...]:
    paths: list[str] = []
    for line in command.splitlines():
        match = _CUSTOM_PATCH_PATH.match(line) or _CUSTOM_MOVE_PATH.match(line)
        if match:
            paths.append(match.group(1).strip())
            continue
        unified = _UNIFIED_PATCH_PATH.match(line)
        if unified:
            candidate = unified.group(1).strip().split("\t", 1)[0]
            if candidate == "/dev/null":
                continue
            if candidate.startswith(("a/", "b/")):
                candidate = candidate[2:]
            paths.append(candidate)
    return tuple(dict.fromkeys(path for path in paths if path))


def adapt_hook_payload(payload: dict[str, Any], *, client: PreWriteClient) -> PreWriteRequestV1:
    """Normalize one supported native pre-tool payload without retaining content."""

    if not isinstance(payload, dict):
        raise HookPayloadError("PreToolUse payload must be a JSON object")
    event_name = _nonempty_string(payload, "hook_event_name")
    if event_name != "PreToolUse":
        raise HookPayloadError(f"Unsupported hook event: {event_name!r}")
    tool_name = _nonempty_string(payload, "tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise HookPayloadError("PreToolUse payload requires object field 'tool_input'")

    if client == "codex":
        if tool_name != "apply_patch":
            raise HookPayloadError(f"Unsupported Codex pre-write tool: {tool_name!r}")
        command = tool_input.get("command")
        if not isinstance(command, str) or not command:
            raise HookPayloadError("Codex apply_patch requires string tool_input.command")
        target_paths = _patch_paths(command)
        if not target_paths:
            raise HookPayloadError("Codex apply_patch payload contains no provable target paths")
    else:
        if tool_name not in {"Edit", "Write"}:
            raise HookPayloadError(f"Unsupported Claude pre-write tool: {tool_name!r}")
        file_path = tool_input.get("file_path")
        if not isinstance(file_path, str) or not file_path.strip():
            raise HookPayloadError(f"Claude {tool_name} requires string tool_input.file_path")
        target_paths = (file_path.strip(),)

    return PreWriteRequestV1(
        client=client,
        hook_event_name="PreToolUse",
        tool_name=tool_name,
        session_id=_canonical_session_id(client, _nonempty_string(payload, "session_id")),
        cwd=_nonempty_string(payload, "cwd"),
        target_paths=target_paths,
    )


def load_prewrite_mode(repo_root: Path) -> PreWriteMode:
    """Read the explicit portable mode; absence is safely disabled."""

    config_path = repo_root / "meta-process.yaml"
    if not config_path.is_file():
        return "off"
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if payload is None:
        return "off"
    if not isinstance(payload, dict):
        raise PreWriteEvaluationError(f"{config_path} must contain a YAML mapping")
    claims = payload.get("claims", {})
    if claims is None:
        return "off"
    if not isinstance(claims, dict):
        raise PreWriteEvaluationError("meta-process.yaml claims must be a mapping")
    mode = claims.get("prewrite_mode", "off")
    if mode not in {"off", "observe", "enforce"}:
        raise PreWriteEvaluationError(
            "claims.prewrite_mode must be one of: off, observe, enforce"
        )
    return cast(PreWriteMode, mode)


def _git(path: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(path), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown Git error"
        raise PreWriteEvaluationError(f"git {' '.join(args)} failed: {detail}")
    return completed.stdout.strip()


def _repository_context(request: PreWriteRequestV1) -> _RepositoryContext:
    cwd = Path(request.cwd).expanduser().resolve()
    worktree = Path(_git(cwd, "rev-parse", "--show-toplevel")).resolve()
    canonical = resolve_canonical_repo_root(worktree)
    branch = _git(worktree, "branch", "--show-current")
    if not branch:
        raise PreWriteEvaluationError("Pre-write enforcement requires a named Git branch")

    normalized: list[str] = []
    for raw_path in request.target_paths:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = worktree / candidate
        resolved = candidate.resolve(strict=False)
        try:
            relative = resolved.relative_to(worktree)
        except ValueError as exc:
            raise PreWriteEvaluationError(
                f"target path escapes active worktree: {raw_path}"
            ) from exc
        value = relative.as_posix()
        if value in {"", "."}:
            raise PreWriteEvaluationError("target path must identify a file below the worktree root")
        normalized.append(value)
    return _RepositoryContext(
        worktree_path=str(worktree),
        repo_root=str(canonical),
        branch=branch,
        normalized_target_paths=tuple(dict.fromkeys(normalized)),
    )


def _registry_digest(claims_dir: Path) -> str:
    digest = hashlib.sha256()
    if not claims_dir.exists():
        return digest.hexdigest()
    for path in sorted(claims_dir.glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _cache_key(
    request: PreWriteRequestV1,
    context: _RepositoryContext,
    *,
    mode: PreWriteMode,
    registry_digest: str,
) -> str:
    payload = {
        "client": request.client,
        "session_id": request.session_id,
        "repo_root": context.repo_root,
        "worktree_path": context.worktree_path,
        "branch": context.branch,
        "target_paths": context.normalized_target_paths,
        "mode": mode,
        "registry_digest": registry_digest,
    }
    rendered = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def _read_cached_allow(cache_path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(payload, dict) or payload.get("expires_at", 0) < time.time():
        return None
    return payload


def _write_cached_allow(cache_path: Path, decision: PreWriteDecisionV1) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    payload = {
        "expires_at": time.time() + CACHE_TTL_SECONDS,
        "claim_project": decision.claim_project,
        "claim_scope": decision.claim_scope,
        "claim_source_file": decision.claim_source_file,
    }
    descriptor = os.open(cache_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True)
        handle.write("\n")


def _path_is_claimed(target: str, claimed_path: str) -> bool:
    normalized = claimed_path.strip().replace("\\", "/").strip("/")
    if normalized in {"", "."}:
        return True
    return target == normalized or target.startswith(f"{normalized}/")


def _make_decision(
    *,
    started: float,
    request: PreWriteRequestV1,
    mode: PreWriteMode,
    decision: PreWriteDecisionKind,
    reason_code: str,
    context: _RepositoryContext | None,
    claim: coordination_claims.ClaimRecord | None = None,
    details: tuple[str, ...] = (),
    recovery: str | None = None,
    cache_hit: bool = False,
) -> PreWriteDecisionV1:
    return PreWriteDecisionV1(
        receipt_id=f"prewrite_{uuid.uuid4().hex}",
        decision=decision,
        mode=mode,
        reason_code=reason_code,
        client=request.client,
        session_id=request.session_id,
        repo_root=context.repo_root if context else None,
        worktree_path=context.worktree_path if context else None,
        branch=context.branch if context else None,
        normalized_target_paths=context.normalized_target_paths if context else (),
        claim_project=claim.primary_project() if claim else None,
        claim_scope=claim.scope if claim else None,
        claim_source_file=claim.source_file if claim else None,
        details=details,
        recovery=recovery,
        elapsed_ms=(time.perf_counter() - started) * 1000,
        cache_hit=cache_hit,
    )


def _record_receipt(path: Path, decision: PreWriteDecisionV1) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    receipt = PreWriteReceiptV1(
        recorded_at=datetime.now(timezone.utc),
        **decision.model_dump(exclude={"recovery"}),
    )
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.write(receipt.model_dump_json() + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def evaluate_prewrite(
    request: PreWriteRequestV1,
    *,
    mode: PreWriteMode,
    claims_dir: Path = coordination_claims.CLAIMS_DIR,
    receipt_path: Path = DEFAULT_RECEIPT_PATH,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> PreWriteDecisionV1:
    """Evaluate and durably record one pre-write authorization decision."""

    started = time.perf_counter()
    context: _RepositoryContext | None = None
    try:
        context = _repository_context(request)
    except PreWriteEvaluationError as exc:
        raw_decision: PreWriteDecisionKind = "observe_violation" if mode == "observe" else "deny"
        if mode == "off":
            raw_decision = "allow"
        result = _make_decision(
            started=started,
            request=request,
            mode=mode,
            decision=raw_decision,
            reason_code="repository_identity_unavailable",
            context=None,
            details=(str(exc),),
            recovery="Run the write from a named branch in a governed Git worktree.",
        )
        _record_receipt(receipt_path, result)
        return result

    if mode == "off":
        result = _make_decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow",
            reason_code="mode_off",
            context=context,
        )
        _record_receipt(receipt_path, result)
        return result

    claims_dir = claims_dir.expanduser().resolve()
    registry_digest = _registry_digest(claims_dir)
    cache_path = cache_dir.expanduser().resolve() / f"{_cache_key(request, context, mode=mode, registry_digest=registry_digest)}.json"
    cached = _read_cached_allow(cache_path)
    if cached is not None:
        result = _make_decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow",
            reason_code="exact_live_claim",
            context=context,
            cache_hit=True,
        ).model_copy(
            update={
                "claim_project": cached.get("claim_project"),
                "claim_scope": cached.get("claim_scope"),
                "claim_source_file": cached.get("claim_source_file"),
            }
        )
        _record_receipt(receipt_path, result)
        return result

    claims = coordination_claims.check_claims(claims_dir=claims_dir)
    candidates = [
        claim
        for claim in claims
        if claim.agent == request.client
        and claim.session_id == request.session_id
        and claim.worktree_path is not None
        and Path(claim.worktree_path).expanduser().resolve() == Path(context.worktree_path)
        and claim.repo_root is not None
        and Path(claim.repo_root).expanduser().resolve() == Path(context.repo_root)
        and claim.branch == context.branch
    ]
    claim: coordination_claims.ClaimRecord | None = None
    reason_code = "exact_live_claim"
    details: tuple[str, ...] = ()
    recovery: str | None = None
    authorized = False

    if not candidates:
        reason_code = "no_exact_claim"
        recovery = "Create or resume an exact claimed worktree lane for this session before editing."
    elif len(candidates) > 1:
        reason_code = "ambiguous_exact_claim"
        details = tuple(sorted(f"{item.primary_project()}:{item.scope}" for item in candidates))
        recovery = "Close or reconcile duplicate live claims before editing."
    else:
        claim = candidates[0]
        health_issues = tuple(
            dict.fromkeys(
                coordination_claims.coordination_health_issues(claim, active_claims=claims)
                + coordination_claims.claim_liveness_issues(claim)
                + [item["code"] for item in coordination_claims.claim_enforcement_issues(claim)]
            )
        )
        if coordination_claims.claim_runtime_status(claim, active_claims=claims) != "healthy" or health_issues:
            reason_code = "claim_not_healthy"
            details = health_issues
            recovery = "Repair or resume the claim through the sanctioned session workflow."
        else:
            outside = tuple(
                target
                for target in context.normalized_target_paths
                if not any(_path_is_claimed(target, claimed) for claimed in claim.write_paths)
            )
            if outside:
                reason_code = "path_outside_claim"
                details = outside
                recovery = "Use a separately claimed lane or update the declared write scope before editing."
            else:
                authorized = True

    if authorized:
        result = _make_decision(
            started=started,
            request=request,
            mode=mode,
            decision="allow",
            reason_code=reason_code,
            context=context,
            claim=claim,
        )
        _write_cached_allow(cache_path, result)
    else:
        result = _make_decision(
            started=started,
            request=request,
            mode=mode,
            decision="observe_violation" if mode == "observe" else "deny",
            reason_code=reason_code,
            context=context,
            claim=claim,
            details=details,
            recovery=recovery,
        )
    _record_receipt(receipt_path, result)
    return result


__all__ = [
    "DEFAULT_CACHE_DIR",
    "DEFAULT_RECEIPT_PATH",
    "HookPayloadError",
    "PreWriteDecisionV1",
    "PreWriteEvaluationError",
    "PreWriteMode",
    "PreWriteReceiptV1",
    "PreWriteRequestV1",
    "adapt_hook_payload",
    "evaluate_prewrite",
    "load_prewrite_mode",
]
