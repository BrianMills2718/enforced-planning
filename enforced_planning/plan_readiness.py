"""Portable, revision-bound plan start and explicit-resume decisions."""

from __future__ import annotations

import json
import re
import shlex
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from enforced_planning import coordination_claims
from enforced_planning.plan_validation import PlanIntegrityResultV1, validate_plan_integrity_at_revision

ExecutionProfile = Literal["light", "coordinated", "release"]
ReadinessErrorCode = Literal[
    "invalid_qualified_plan_id",
    "missing_plan",
    "ambiguous_plan_identity",
    "dependency_cycle",
    "stale_graph_revision",
    "non_actionable_status",
]


class StrictContract(BaseModel):
    """Base class for internal enforcement contracts."""

    model_config = ConfigDict(extra="forbid")


class PlanReadinessDecisionV1(StrictContract):
    """Canonical static decision returned by the ecosystem plan graph."""

    schema_version: Literal["1.0.0"]
    qualified_plan_id: str
    graph_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["ready", "already_active", "blocked", "unknown"]
    blocker_ids: list[str]
    evidence_refs: list[str]
    reason: str
    error_code: ReadinessErrorCode | None


class PlanLaneIdentityV1(StrictContract):
    """Backward-compatible Plan 74 lane identity payload."""

    schema_version: Literal["1.0.0"]
    qualified_plan_id: str
    lane_id: str
    parent_lane_id: str | None
    repository: str
    branch: str
    worktree_path: str
    claim_identity: str
    session_identity: str
    creation_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_profile: ExecutionProfile


class PlanStartGateResultV1(StrictContract):
    """Backward-compatible Plan 74 start-gate payload."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    allowed: bool
    readiness: PlanReadinessDecisionV1 | None
    lane: PlanLaneIdentityV1 | None
    reason: str


class PlanLaneIdentityV2(StrictContract):
    """Identity and distinct source/graph revisions for one planned lane."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    qualified_plan_id: str
    lane_id: str
    parent_lane_id: str | None
    repository: str
    branch: str
    worktree_path: str
    claim_identity: str
    session_identity: str
    start_revision: str = Field(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
    graph_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_profile: ExecutionProfile


class PlanStartGateResultV2(StrictContract):
    """Result produced before mutation, including visible integrity evidence."""

    schema_version: Literal["2.0.0"] = "2.0.0"
    allowed: bool
    planning_integrity: PlanIntegrityResultV1 | None
    readiness: PlanReadinessDecisionV1 | None
    lane: PlanLaneIdentityV2 | None
    reason: str


def _plan_number(value: str | None) -> int | None:
    """Extract the numbered-plan identity from canonical and legacy spellings."""
    if not isinstance(value, str):
        return None
    match = re.search(r"(?:\bPlan\s*#?|#)\s*0*(\d+)\b", value, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _live_matching_claim_scopes(*, repository: str, qualified_plan_id: str) -> list[str]:
    """Return live or preserved canonical claim scopes for one numbered plan."""
    plan_number = _plan_number(qualified_plan_id)
    if plan_number is None:
        raise ValueError(f"invalid qualified plan identity for resume: {qualified_plan_id}")
    scopes = []
    for claim in coordination_claims.list_claims(
        repository,
        include_inactive=True,
    ):
        if claim.status not in coordination_claims.CLOSEABLE_STATUSES or claim.primary_project() != repository:
            continue
        if _plan_number(claim.plan_ref) == plan_number:
            scopes.append(claim.scope)
    return sorted(set(scopes))


def check_plan_start_readiness(
    *,
    qualified_plan_id: str | None,
    execution_profile: ExecutionProfile,
    query_command: str | None,
    repository: str,
    lane_id: str,
    branch: str,
    worktree_path: str,
    claim_identity: str,
    session_identity: str,
    repo_root: Path | str | None = None,
    start_point: str = "HEAD",
    plan_repo_root: Path | str | None = None,
    plan_start_point: str | None = None,
    parent_lane_id: str | None = None,
    allow_unplanned: bool = False,
    resume_requested: bool = False,
) -> PlanStartGateResultV2:
    """Validate static readiness and the non-owning precondition for a resume.

    A successful resume remains provisional: the canonical claim registry's
    lock and hierarchy checks are the final ownership guard before a worktree
    can be created.
    """
    if execution_profile == "light" and qualified_plan_id is None and allow_unplanned:
        return PlanStartGateResultV2(
            allowed=True,
            planning_integrity=None,
            readiness=None,
            lane=None,
            reason="Explicitly unplanned light work does not require plan-graph readiness.",
        )
    if not qualified_plan_id:
        raise ValueError(f"{execution_profile} work requires a qualified plan identity")
    plan_number = _plan_number(qualified_plan_id)
    if plan_number is None:
        raise ValueError(f"invalid qualified plan identity: {qualified_plan_id}")
    if repo_root is None:
        raise ValueError(f"{execution_profile} work requires --repo-root for exact plan integrity")
    if not query_command or not query_command.strip():
        raise ValueError(f"{execution_profile} work requires a configured plan-readiness query command")
    authority = coordination_claims.resolve_plan_authority_binding(
        repo_root=str(repo_root),
        plan_ref=qualified_plan_id,
        start_point=start_point,
        plan_repo_root=str(plan_repo_root) if plan_repo_root is not None else None,
        plan_start_point=plan_start_point,
        target_repository_id=repository,
    )
    integrity = validate_plan_integrity_at_revision(
        repo_root=authority.plan_root,
        repository_id=authority.plan_repository_id,
        plan_number=plan_number,
        start_point=authority.plan_revision,
    )
    if integrity.mode == "enforce" and integrity.disposition == "fail":
        codes = ", ".join(item.code for item in integrity.findings)
        raise ValueError(f"planning integrity rejected {qualified_plan_id} at {integrity.source_revision}: {codes}")
    if not integrity.source_revision:
        raise ValueError("planning integrity did not resolve one full Git start revision")
    if integrity.source_revision != authority.plan_revision:
        raise ValueError("planning integrity resolved a different revision than the retained plan authority")
    if not resume_requested:
        default_revision = coordination_claims.resolve_default_integration_revision(Path(repo_root))
        if authority.target_revision != default_revision:
            raise ValueError(
                f"new lane start revision {authority.target_revision} is not the canonical "
                f"default-integration tip {default_revision}; use explicit resume/recovery custody "
                "for a retained non-tip lane"
            )
        if authority.external:
            plan_default_revision = coordination_claims.resolve_default_integration_revision(authority.plan_root)
            if authority.plan_revision != plan_default_revision:
                raise ValueError(
                    f"new lane plan revision {authority.plan_revision} is not the canonical "
                    f"plan-authority default-integration tip {plan_default_revision}"
                )
    command = [*shlex.split(query_command), "check-ready", qualified_plan_id, "--json"]
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    try:
        readiness = PlanReadinessDecisionV1.model_validate_json(completed.stdout)
    except ValidationError as exc:
        raise ValueError(f"invalid readiness payload: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid readiness payload: {exc}") from exc

    if readiness.qualified_plan_id != qualified_plan_id:
        raise ValueError(
            "readiness payload identity mismatch: "
            f"requested {qualified_plan_id}, received {readiness.qualified_plan_id}"
        )
    # ``check-ready`` deliberately uses a nonzero exit for every decision that
    # does not open a *new* lane.  An explicit resume is the one controlled
    # exception: a structurally valid ``already_active`` decision is evidence
    # to inspect claim ownership, not a transport or producer failure.
    resumable_already_active = readiness.decision == "already_active" and resume_requested
    if completed.returncode != 0 and not resumable_already_active:
        raise ValueError(
            f"plan readiness rejected {qualified_plan_id}: "
            f"{readiness.decision} ({readiness.error_code or readiness.reason})"
        )

    if readiness.decision == "already_active":
        if not resume_requested:
            raise ValueError(
                f"plan readiness rejected {qualified_plan_id}: already_active requires an explicit resume request"
            )
        live_scopes = _live_matching_claim_scopes(
            repository=repository,
            qualified_plan_id=qualified_plan_id,
        )
        if live_scopes:
            raise ValueError(
                f"plan resume rejected {qualified_plan_id}: live claim(s) already own it: " + ", ".join(live_scopes)
            )
    elif readiness.decision != "ready":
        raise ValueError(
            f"plan readiness rejected {qualified_plan_id}: "
            f"{readiness.decision} ({readiness.error_code or readiness.reason})"
        )

    lane = PlanLaneIdentityV2(
        qualified_plan_id=qualified_plan_id,
        lane_id=lane_id,
        parent_lane_id=parent_lane_id,
        repository=repository,
        branch=branch,
        worktree_path=worktree_path,
        claim_identity=claim_identity,
        session_identity=session_identity,
        start_revision=authority.target_revision,
        graph_revision=readiness.graph_revision,
        execution_profile=execution_profile,
    )
    reason = readiness.reason
    if readiness.decision == "already_active":
        reason = f"{reason} Explicit resume is provisionally allowed; claim acquisition remains atomic."
    return PlanStartGateResultV2(
        allowed=True,
        planning_integrity=integrity,
        readiness=readiness,
        lane=lane,
        reason=reason,
    )
