"""Portable adapter for canonical, revision-bound plan readiness decisions."""

from __future__ import annotations

import json
import shlex
import subprocess
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    """Canonical decision returned by the ecosystem plan graph."""

    schema_version: Literal["1.0.0"]
    qualified_plan_id: str
    graph_revision: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["ready", "already_active", "blocked", "unknown"]
    blocker_ids: list[str]
    evidence_refs: list[str]
    reason: str
    error_code: ReadinessErrorCode | None


class PlanLaneIdentityV1(StrictContract):
    """Identity of one plan-owned implementation lane at creation time."""

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
    """Result produced before any claim, branch, worktree, or tracker mutation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    allowed: bool
    readiness: PlanReadinessDecisionV1 | None
    lane: PlanLaneIdentityV1 | None
    reason: str


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
    parent_lane_id: str | None = None,
    allow_unplanned: bool = False,
) -> PlanStartGateResultV1:
    """Validate canonical readiness before any lifecycle state is created."""
    if execution_profile == "light" and qualified_plan_id is None and allow_unplanned:
        return PlanStartGateResultV1(
            allowed=True,
            readiness=None,
            lane=None,
            reason="Explicitly unplanned light work does not require plan-graph readiness.",
        )
    if not qualified_plan_id:
        raise ValueError(f"{execution_profile} work requires a qualified plan identity")
    if not query_command or not query_command.strip():
        raise ValueError(
            f"{execution_profile} work requires a configured plan-readiness query command"
        )

    command = [
        *shlex.split(query_command),
        "check-ready",
        qualified_plan_id,
        "--json",
    ]
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
    if readiness.decision != "ready" or completed.returncode != 0:
        raise ValueError(
            f"plan readiness rejected {qualified_plan_id}: "
            f"{readiness.decision} ({readiness.error_code or readiness.reason})"
        )

    lane = PlanLaneIdentityV1(
        schema_version="1.0.0",
        qualified_plan_id=qualified_plan_id,
        lane_id=lane_id,
        parent_lane_id=parent_lane_id,
        repository=repository,
        branch=branch,
        worktree_path=worktree_path,
        claim_identity=claim_identity,
        session_identity=session_identity,
        creation_revision=readiness.graph_revision,
        execution_profile=execution_profile,
    )
    return PlanStartGateResultV1(
        allowed=True,
        readiness=readiness,
        lane=lane,
        reason=readiness.reason,
    )
