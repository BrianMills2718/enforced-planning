"""Narrow self-service claim mutations for a natively identified agent session.

This module is intentionally not a general lifecycle command proxy.  It accepts
only typed claim-registry operations, derives the caller's session identity from
the native runtime, and never creates branches, worktrees, commits, or project
files.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_validator

from enforced_planning import coordination_claims, session_contracts, session_lifecycle

AgentName = Literal["codex", "claude-code", "openclaw"]
ClaimType = Literal["program", "write", "review", "research"]
ProgressKind = Literal[
    "claim_started",
    "verified_commit",
    "accepted_artifact",
    "new_diagnostic",
    "integration_result",
]


class ClaimBootstrapError(ValueError):
    """A bootstrap request was malformed or exceeded self-service authority."""


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal["1.0"] = "1.0"
    operation: str
    agent: AgentName | None = None
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)

    @field_validator("project", "scope")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must contain non-whitespace text")
        return stripped


class SessionStartOrUpdateRequest(_StrictRequest):
    operation: Literal["session_start_or_update"]
    intent: str = Field(min_length=1)
    claim_type: ClaimType
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    session_name: str = Field(min_length=1)
    broader_goal: str = Field(min_length=1)
    plan_ref: str = Field(min_length=1)
    write_paths: list[str] = Field(default_factory=list)
    read_paths: list[str] = Field(default_factory=list)
    current_phase: str = Field(min_length=1)
    next_action: str | None = None
    parent_scope: str | None = None
    work_graph_path: str | None = None
    work_unit_id: str | None = None
    start_revision: str | None = None

    @field_validator(
        "intent",
        "branch",
        "session_name",
        "broader_goal",
        "plan_ref",
        "current_phase",
    )
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must contain non-whitespace text")
        return stripped

    @field_validator("repo_root", "worktree_path")
    @classmethod
    def _require_absolute_path(cls, value: str) -> str:
        path = Path(value).expanduser()
        if not path.is_absolute():
            raise ValueError("must be an absolute path")
        return str(path.resolve())

    @field_validator("write_paths", "read_paths")
    @classmethod
    def _validate_repo_paths(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            path = value.strip()
            if not path or Path(path).is_absolute() or ".." in Path(path).parts:
                raise ValueError("claim paths must be non-empty repo-relative paths without '..'")
            if path not in cleaned:
                cleaned.append(path)
        return cleaned

    @model_validator(mode="after")
    def _validate_claim_shape(self) -> SessionStartOrUpdateRequest:
        if self.claim_type == "write" and not self.write_paths:
            raise ValueError("write claims require at least one write_paths entry")
        if self.plan_ref == "UNPLANNED" and (self.work_graph_path or self.work_unit_id or self.start_revision):
            raise ValueError("UNPLANNED bootstrap cannot carry plan work-unit or start-revision fields")
        return self


class HeartbeatRequest(_StrictRequest):
    operation: Literal["heartbeat"]
    branch: str | None = None
    current_phase: str | None = None


class ProgressRequest(_StrictRequest):
    operation: Literal["progress"]
    progress_kind: ProgressKind
    evidence_ref: str = Field(min_length=1)
    next_action: str = Field(min_length=1)
    expected_quiet_until: str | None = None
    quiet_reason: str | None = None


class ReleaseSelfRequest(_StrictRequest):
    operation: Literal["release_self"]


ClaimBootstrapRequest = Annotated[
    SessionStartOrUpdateRequest | HeartbeatRequest | ProgressRequest | ReleaseSelfRequest,
    Field(discriminator="operation"),
]
_REQUEST_ADAPTER = TypeAdapter(ClaimBootstrapRequest)
SESSION_TRACKERS_DIR = session_contracts.DEFAULT_SESSION_TRACKERS_DIR


def parse_request_json(raw_json: str) -> ClaimBootstrapRequest:
    """Parse one strict v1 request; unknown fields, including session_id, fail."""

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        raise ClaimBootstrapError(f"request-json is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ClaimBootstrapError("request-json must be one JSON object")
    try:
        return _REQUEST_ADAPTER.validate_python(payload)
    except ValueError as exc:
        raise ClaimBootstrapError(str(exc)) from exc


def canonical_script_path(repo_root: Path | None = None) -> Path:
    """Return the one canonical script path accepted by the raw Bash grammar."""

    root = repo_root or Path(__file__).resolve().parents[1]
    return (root / "scripts" / "claim_bootstrap.py").resolve()


def parse_raw_bash_command(
    raw_command: str,
    *,
    script_path: Path | None = None,
) -> ClaimBootstrapRequest:
    """Accept only one uncomposed absolute Python bootstrap command.

    The JSON is enclosed by one shell single-quoted token.  A JSON string that
    needs an apostrophe must encode it as ``\\u0027``; a literal apostrophe
    cannot occur in the accepted raw command.
    """

    if "\n" in raw_command or "\r" in raw_command:
        raise ClaimBootstrapError("claim bootstrap command must be exactly one line")
    canonical = str((script_path or canonical_script_path()).resolve())
    prefix = f"/usr/bin/python3 {canonical} --request-json '"
    if not raw_command.startswith(prefix) or not raw_command.endswith("'"):
        raise ClaimBootstrapError(
            "command must be exactly /usr/bin/python3 <canonical>/scripts/claim_bootstrap.py --request-json '<JSON>'"
        )
    raw_json = raw_command[len(prefix) : -1]
    if "'" in raw_json:
        raise ClaimBootstrapError("JSON apostrophes must be encoded as \\u0027")
    return parse_request_json(raw_json)


def _native_agent(requested: AgentName | None) -> tuple[AgentName, str]:
    """Resolve one current native runtime and reject borrowed agent identity."""

    strong_markers: dict[AgentName, str] = {
        "codex": os.environ.get("CODEX_THREAD_ID", "").strip(),
        "claude-code": os.environ.get("CLAUDE_CODE_SESSION_ID", "").strip(),
        "openclaw": os.environ.get("OPENCLAW_SESSION_ID", "").strip(),
    }
    detected = [agent for agent, marker in strong_markers.items() if marker]
    if requested is None:
        if len(detected) != 1:
            raise ClaimBootstrapError("agent is required unless exactly one native runtime marker is present")
        agent = detected[0]
    else:
        agent = requested
    session_id = coordination_claims.resolve_session_id(agent)
    if not session_id:
        raise ClaimBootstrapError(f"unable to derive native session identity for {agent}")
    try:
        coordination_claims.validate_native_session_binding(
            agent,
            session_id,
            require_native_marker=True,
        )
    except ValueError as exc:
        raise ClaimBootstrapError(str(exc)) from exc
    return agent, session_id


def _require_self_owned_slot(
    *,
    agent: AgentName,
    session_id: str,
    project: str,
    scope: str,
    allow_absent: bool,
) -> None:
    """Refuse ambiguous, ownerless, or foreign claim-slot mutation."""

    matches = [
        claim for claim in coordination_claims.check_claims(project) if claim.agent == agent and claim.scope == scope
    ]
    if not matches:
        if allow_absent:
            return
        raise ClaimBootstrapError(f"no exact live self-owned claim for {agent} -> {project}:{scope}")
    if len(matches) != 1:
        raise ClaimBootstrapError(f"multiple live claims occupy {project}:{scope}; repair registry identity first")
    owner = matches[0].session_id
    if owner != session_id:
        raise ClaimBootstrapError(
            f"claim slot {project}:{scope} belongs to session {owner or '<missing>'}, "
            f"not current session {session_id}; bootstrap cannot take over another slot"
        )


def execute_request(request: ClaimBootstrapRequest) -> dict[str, Any]:
    """Execute one self-owned claim mutation and return a JSON-safe receipt."""

    agent, session_id = _native_agent(request.agent)

    if isinstance(request, SessionStartOrUpdateRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=True,
        )
        payload = session_lifecycle.start_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            intent=request.intent,
            repo_root=request.repo_root,
            worktree_path=request.worktree_path,
            branch=request.branch,
            broader_goal=request.broader_goal,
            current_phase=request.current_phase,
            plan_ref=None if request.plan_ref == "UNPLANNED" else request.plan_ref,
            session_id=session_id,
            session_name=request.session_name,
            intended_next_phases=[request.next_action] if request.next_action else None,
            claim_type=request.claim_type,
            write_paths=list(request.write_paths),
            read_paths=list(request.read_paths),
            parent_scope=request.parent_scope,
            work_graph_path=request.work_graph_path,
            work_unit_id=request.work_unit_id,
            start_revision=request.start_revision,
            tracker_dir=SESSION_TRACKERS_DIR,
            allow_unplanned=request.plan_ref == "UNPLANNED",
        )
    elif isinstance(request, HeartbeatRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=False,
        )
        payload = session_lifecycle.heartbeat_session(
            agent=agent,
            project=request.project,
            scope=request.scope,
            branch=request.branch,
            session_id=session_id,
            current_phase=request.current_phase,
            tracker_dir=SESSION_TRACKERS_DIR,
        )
    elif isinstance(request, ProgressRequest):
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=False,
        )
        claim, event = coordination_claims.record_progress_claims(
            agent=agent,
            project=request.project,
            scope=request.scope,
            progress_kind=request.progress_kind,
            evidence_ref=request.evidence_ref,
            next_action=request.next_action,
            session_id=session_id,
            expected_quiet_until=request.expected_quiet_until,
            quiet_reason=request.quiet_reason,
            require_native_session_binding=True,
        )
        payload = {
            "action": "progress_recorded",
            "project": claim.primary_project(),
            "scope": claim.scope,
            "progress_event": event.model_dump(mode="json"),
        }
    else:
        _require_self_owned_slot(
            agent=agent,
            session_id=session_id,
            project=request.project,
            scope=request.scope,
            allow_absent=False,
        )
        released, message = coordination_claims.release_claim(
            agent,
            request.project,
            request.scope,
            expected_session_id=session_id,
        )
        if not released:
            raise ClaimBootstrapError(message)
        payload = {"action": "claim_released", "message": message}

    return {
        "ok": True,
        "schema_version": "1.0",
        "operation": request.operation,
        "agent": agent,
        "session_id": session_id,
        "project": request.project,
        "scope": request.scope,
        "result": payload,
    }


__all__ = [
    "ClaimBootstrapError",
    "ClaimBootstrapRequest",
    "HeartbeatRequest",
    "ProgressRequest",
    "ReleaseSelfRequest",
    "SessionStartOrUpdateRequest",
    "canonical_script_path",
    "execute_request",
    "parse_raw_bash_command",
    "parse_request_json",
]
