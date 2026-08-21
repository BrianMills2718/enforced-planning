"""Provider-free ready-queue evaluation and blocker disposition policy.

This module is deliberately read-only.  It turns a revision-bound work graph,
claim snapshot, blocker request, and optional mailbox evidence into strict
contracts.  It never mutates claims, trackers, branches, or worktrees.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Annotated, Any, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

HEX_SHA256 = r"^[0-9a-f]{64}$"
LIVE_CLAIM_STATUSES = frozenset({"active", "blocked", "handoff"})
WORK_UNIT_STATUSES = frozenset(
    {
        "draft",
        "decomposed",
        "readiness_review",
        "ready",
        "claimed",
        "in_progress",
        "blocked",
        "released",
        "completion_review",
        "changes_requested",
        "accepted",
        "deployed",
        "operationally_observed",
        "deployment_failed",
        "rolled_back",
        "superseded",
        "cancelled",
    }
)
TERMINAL_UNIT_STATUSES = frozenset(
    {"accepted", "deployed", "operationally_observed", "rolled_back", "superseded", "cancelled"}
)
AVAILABLE_CLAIMABILITY = frozenset({"available", "ready_for_execution"})
NONEXECUTABLE_CLASSES = frozenset({"decision", "coupled", "deferred"})
WRITE_HOLDING_STATUSES = frozenset({"claimed", "in_progress", "completion_review", "changes_requested"})
SUPPORTED_WHOLE_GOAL_BLOCKERS = frozenset(
    {
        "hard_dependency",
        "external_authority",
        "external_system",
        "required_data",
        "irreversible_shared_action",
    }
)

QueueCoverage = Literal["complete", "partial", "unavailable"]
BlockerClass = Literal[
    "hard_dependency",
    "human_decision",
    "external_authority",
    "external_system",
    "required_data",
    "irreversible_shared_action",
    "path_conflict",
    "unknown",
]
MailboxState = Literal["persisted", "runtime_accepted", "observed", "acknowledged", "expired"]
RequiredMailboxState = Literal["runtime_accepted", "observed", "acknowledged"]
RequestedClaimAction = Literal["retain_narrow", "handoff", "session_end"]
DispositionDecision = Literal[
    "continue_ready_work",
    "integration_wait",
    "goal_blocked_verified",
    "blocker_unverified_return_control",
    "human_decision_required",
]
DispositionClaimAction = Literal["retain_narrow", "handoff_scope", "retire_goal_scope", "none"]
NonEmptyString = Annotated[str, Field(min_length=1)]


def _require_aware_datetime_string(value: str, *, field_name: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 date-time") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must carry a timezone")
    return value


def _reject_explicit_nulls(value: Any, *, field_names: frozenset[str], contract_name: str) -> Any:
    if isinstance(value, dict):
        explicit_nulls = sorted(field for field in field_names if field in value and value[field] is None)
        if explicit_nulls:
            raise ValueError(f"{contract_name} fields may be omitted but not null: {', '.join(explicit_nulls)}")
    return value


class StrictContract(BaseModel):
    """Strict immutable base for Plan 110 public contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class VersionedReferenceV1(StrictContract):
    kind: str = Field(min_length=1)
    id: str = Field(min_length=1)
    revision: str = Field(min_length=1)


class WorkUnitScopeV1(StrictContract):
    included: list[NonEmptyString] = Field(min_length=1)
    excluded: list[NonEmptyString]


class ConflictSurfaceV1(StrictContract):
    kind: Literal[
        "repository_path",
        "contract",
        "database",
        "migration",
        "deployment_target",
        "route",
        "data",
        "external_system",
    ]
    target: str = Field(min_length=1)
    repository: str | None = Field(default=None, min_length=1)
    access: Literal["read", "write", "exclusive"]
    coordination_key: str | None = None

    @model_validator(mode="before")
    @classmethod
    def omitted_optional_fields_are_not_nullable(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            field_names=frozenset({"repository", "coordination_key"}),
            contract_name="ConflictSurfaceV1",
        )

    @model_validator(mode="after")
    def repository_paths_name_repository(self) -> ConflictSurfaceV1:
        if self.kind == "repository_path" and self.repository is None:
            raise ValueError("repository_path conflict surfaces require repository")
        return self


class AcceptanceCriterionV1(StrictContract):
    id: str = Field(min_length=1)
    criterion: str = Field(min_length=1)
    evidence_required: list[NonEmptyString] = Field(min_length=1)
    negative_control: str | None = None

    @model_validator(mode="before")
    @classmethod
    def omitted_optional_fields_are_not_nullable(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            field_names=frozenset({"negative_control"}),
            contract_name="AcceptanceCriterionV1",
        )


class ApprovalV1(StrictContract):
    approval_type: Literal[
        "initiative",
        "design",
        "security_compliance",
        "readiness",
        "completion",
        "deployment",
    ]
    role: str = Field(min_length=1)
    approver_id: str = Field(min_length=1)
    approved_revision: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    expires_at: str | None = None

    @field_validator("approved_at", "expires_at")
    @classmethod
    def timestamps_are_aware(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_aware_datetime_string(value, field_name=info.field_name)


class WorkUnitReadinessV1(StrictContract):
    status: Literal["not_reviewed", "blocked", "ready"]
    required_approval_types: list[Literal["design", "security_compliance", "readiness", "deployment"]]
    approvals: list[ApprovalV1]
    failed_guards: list[NonEmptyString]


class ClaimPolicyV1(StrictContract):
    eligibility_rule: str = Field(min_length=1)
    lease_policy: Literal["none", "renewable", "fixed", "manual_only"]
    lease_duration_minutes: int | None = Field(default=None, ge=1)
    max_active_per_claimant: int = Field(ge=1)
    named_owner_id: str | None = Field(default=None, min_length=1)


class UnitStatusGateV1(StrictContract):
    type: Literal["unit_status"]
    required_status: Literal["accepted", "deployed", "operationally_observed"]


class ApprovalCurrentGateV1(StrictContract):
    type: Literal["approval_current"]
    approval_type: Literal["design", "security_compliance", "readiness", "deployment"]
    approved_revision: str = Field(min_length=1)
    satisfied: bool
    evidence_ref: str = Field(min_length=1)


class ArtifactExistsGateV1(StrictContract):
    type: Literal["artifact_exists"]
    artifact_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    satisfied: bool
    evidence_ref: str = Field(min_length=1)


class ContractStatusGateV1(StrictContract):
    type: Literal["contract_status"]
    contract_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    required_status: Literal["reviewed", "ready_for_release", "accepted"]
    satisfied: bool
    evidence_ref: str = Field(min_length=1)


class ExternalEventGateV1(StrictContract):
    type: Literal["external_event"]
    event_id: str = Field(min_length=1)
    required_state: str = Field(min_length=1)
    satisfied: bool
    evidence_ref: str = Field(min_length=1)


DependencyGateV1 = Annotated[
    UnitStatusGateV1 | ApprovalCurrentGateV1 | ArtifactExistsGateV1 | ContractStatusGateV1 | ExternalEventGateV1,
    Field(discriminator="type"),
]


class WorkDependencyV1(StrictContract):
    unit_id: str = Field(min_length=1)
    type: Literal["hard", "evidence", "operational", "sequencing", "optional"]
    gate: DependencyGateV1
    rationale: str = Field(min_length=1)


class QueueWorkUnitV1(StrictContract):
    """Strict runtime projection of canonical WorkUnitV1.

    Queue coverage is never called complete for a partial convenience fixture.
    This projection deliberately owns every canonical field even though the
    evaluator consumes only identity, status, readiness, and dependencies.
    """

    schema_version: Literal["1.0"]
    record_type: Literal["work_unit"]
    id: str = Field(min_length=1)
    initiative_id: str = Field(min_length=1)
    goal_id: str = Field(min_length=1)
    design_revision: str = Field(min_length=1)
    spec_revision: str = Field(min_length=1)
    title: str = Field(min_length=1)
    unit_class: Literal[
        "implementation",
        "integration",
        "infrastructure",
        "migration",
        "research",
        "documentation",
        "verification",
        "deployment",
        "decision",
    ] = Field(alias="class")
    objective: str = Field(min_length=1)
    profile: Literal["small", "standard", "controlled"]
    control_approval_types: (
        Annotated[
            list[Literal["security_compliance", "readiness", "deployment"]],
            Field(min_length=1),
        ]
        | None
    ) = None
    execution_class: Literal["independently_executable", "named_owner", "decision", "coupled", "deferred"]
    claimability: Literal[
        "ready_for_execution",
        "available",
        "unavailable_active_claim",
        "blocked_dependencies",
        "pending_approval",
        "restricted",
        "not_applicable",
    ]
    scope: WorkUnitScopeV1
    inputs: list[VersionedReferenceV1]
    outputs: list[NonEmptyString] = Field(min_length=1)
    dependencies: list[WorkDependencyV1]
    conflict_surfaces: list[ConflictSurfaceV1]
    acceptance: list[AcceptanceCriterionV1] = Field(min_length=1)
    readiness: WorkUnitReadinessV1
    claim_policy: ClaimPolicyV1 | None = None
    authorization_mode: Literal["host_workspace", "registry_claim", "manual_authorization"] | None = None
    integration_owner_id: str | None = Field(default=None, min_length=1)
    deployment_contract: VersionedReferenceV1 | None = None
    deployment_environment: str | None = Field(default=None, min_length=1)
    status: Literal[
        "draft",
        "decomposed",
        "readiness_review",
        "ready",
        "claimed",
        "in_progress",
        "blocked",
        "released",
        "completion_review",
        "changes_requested",
        "accepted",
        "deployed",
        "operationally_observed",
        "deployment_failed",
        "rolled_back",
        "superseded",
        "cancelled",
    ]
    record_version: int = Field(ge=1)
    created_at: str | None = Field(default=None, min_length=1)
    updated_at: str | None = Field(default=None, min_length=1)

    @model_validator(mode="before")
    @classmethod
    def omitted_optional_fields_are_not_nullable(cls, value: Any) -> Any:
        return _reject_explicit_nulls(
            value,
            field_names=frozenset(
                {
                    "control_approval_types",
                    "claim_policy",
                    "authorization_mode",
                    "integration_owner_id",
                    "deployment_contract",
                    "deployment_environment",
                    "created_at",
                    "updated_at",
                }
            ),
            contract_name="QueueWorkUnitV1",
        )

    @field_validator("created_at", "updated_at")
    @classmethod
    def timestamps_are_aware(cls, value: str | None, info: Any) -> str | None:
        if value is None:
            return None
        return _require_aware_datetime_string(value, field_name=info.field_name)

    @model_validator(mode="after")
    def conditional_contract_fields_are_present(self) -> QueueWorkUnitV1:
        if self.execution_class == "named_owner" and (
            self.claim_policy is None or not self.claim_policy.named_owner_id
        ):
            raise ValueError("named_owner work requires claim_policy.named_owner_id")
        if self.unit_class == "deployment":
            if self.deployment_contract is None or self.deployment_environment is None:
                raise ValueError("deployment work requires deployment contract and environment")
            if self.deployment_contract.kind != "DeploymentContractV1":
                raise ValueError("deployment contract kind must be DeploymentContractV1")
        if self.profile == "controlled" and not self.control_approval_types:
            raise ValueError("controlled work requires control_approval_types")
        if self.control_approval_types and len(self.control_approval_types) != len(set(self.control_approval_types)):
            raise ValueError("control_approval_types must be unique")
        return self


class WorkGraphRefV1(StrictContract):
    """Identity of the exact work-graph bytes used for one queue evaluation."""

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=HEX_SHA256)
    design_revisions: tuple[str, ...] = ()
    spec_revisions: tuple[str, ...] = ()

    @field_validator("path")
    @classmethod
    def path_is_portable_repo_relative(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or ".." in path.parts or "\\" in value:
            raise ValueError("work-graph identity must be a portable repository-relative path")
        normalized = path.as_posix()
        if normalized in {"", "."}:
            raise ValueError("work-graph identity cannot be empty")
        return normalized


class BlockedUnitV1(StrictContract):
    """One non-eligible work unit and its deterministic blocker references."""

    unit_id: str = Field(min_length=1)
    blocker_refs: tuple[str, ...] = Field(min_length=1)


class ClaimQueueSnapshotV1(StrictContract):
    """Minimal immutable claim projection used by the queue evaluator."""

    session_id: str = Field(min_length=1)
    status: str = Field(min_length=1)
    goal_or_graph_scope: str = Field(min_length=1)
    work_unit_id: str | None = Field(default=None, min_length=1)
    work_graph_path: str | None = Field(default=None, min_length=1)
    work_graph_sha256: str | None = Field(default=None, pattern=HEX_SHA256)
    claimed_paths: tuple[str, ...] = ()

    @field_validator("claimed_paths")
    @classmethod
    def claimed_paths_are_portable(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for value in values:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts or "\\" in value or value in {"", "."}:
                raise ValueError("claimed paths must be portable repository-relative paths")
            normalized.append(path.as_posix())
        if len(normalized) != len(set(normalized)):
            raise ValueError("claimed_paths contains duplicates")
        return tuple(normalized)


class ReadyQueueEvaluationV1(StrictContract):
    """Revision-bound view of eligible, blocked, and actively owned work."""

    schema_version: Literal["1.0"] = "1.0"
    evaluation_id: str = Field(pattern=r"^ready_queue_[0-9a-f]{32}$")
    session_id: str = Field(min_length=1)
    goal_or_graph_scope: str = Field(min_length=1)
    work_graph_ref: WorkGraphRefV1 | None
    claim_snapshot_sha256: str = Field(pattern=HEX_SHA256)
    coverage: QueueCoverage
    eligible_unit_ids: tuple[str, ...]
    blocked_unit_ids: tuple[BlockedUnitV1, ...]
    terminal_unit_ids: tuple[str, ...]
    active_or_indeterminate_unit_ids: tuple[str, ...]
    active_conflict_unit_ids: tuple[str, ...]
    evaluated_at: AwareDatetime
    evidence_refs: tuple[str, ...] = ()

    @model_validator(mode="after")
    def queue_sets_are_internally_consistent(self) -> ReadyQueueEvaluationV1:
        """Fail closed on structurally impossible queue projections."""

        if self.coverage == "unavailable":
            if self.work_graph_ref is not None:
                raise ValueError("unavailable coverage cannot carry a trusted work_graph_ref")
            if self.eligible_unit_ids or self.terminal_unit_ids or self.active_or_indeterminate_unit_ids:
                raise ValueError("unavailable coverage cannot expose classified units")
        elif self.work_graph_ref is None:
            raise ValueError("complete or partial coverage requires a trusted work_graph_ref")

        eligible = set(self.eligible_unit_ids)
        blocked_ids = [item.unit_id for item in self.blocked_unit_ids if item.unit_id != "queue"]
        blocked = set(blocked_ids)
        terminal = set(self.terminal_unit_ids)
        indeterminate = set(self.active_or_indeterminate_unit_ids)
        conflicts = set(self.active_conflict_unit_ids)
        if len(eligible) != len(self.eligible_unit_ids):
            raise ValueError("eligible_unit_ids contains duplicates")
        if len(blocked) != len(blocked_ids):
            raise ValueError("blocked_unit_ids contains duplicate unit IDs")
        if len(terminal) != len(self.terminal_unit_ids):
            raise ValueError("terminal_unit_ids contains duplicates")
        if len(indeterminate) != len(self.active_or_indeterminate_unit_ids):
            raise ValueError("active_or_indeterminate_unit_ids contains duplicates")
        if len(conflicts) != len(self.active_conflict_unit_ids):
            raise ValueError("active_conflict_unit_ids contains duplicates")
        classifications = (eligible, blocked, terminal, indeterminate)
        if any(left & right for index, left in enumerate(classifications) for right in classifications[index + 1 :]):
            raise ValueError("queue classifications must be disjoint")
        if not conflicts <= eligible | blocked | terminal | indeterminate:
            raise ValueError("active conflicts must name a classified work unit")
        return self


class MailboxDependencyV1(StrictContract):
    """Delivery evidence required before one dependency wait may be certified."""

    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$")
    required_delivery_state: RequiredMailboxState


class MailboxEvidenceV1(StrictContract):
    """Current append-only delivery state for one exact mailbox message."""

    message_id: str = Field(pattern=r"^msg_[0-9a-f]{32}$")
    state: MailboxState
    evidence_refs: tuple[str, ...] = Field(min_length=1)


class BlockerRequestV1(StrictContract):
    """Evidence supplied by an agent asking for a blocker disposition."""

    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1)
    claim_scope: str = Field(min_length=1)
    blocked_scope: Literal["path", "unit", "goal"]
    blocked_item_refs: tuple[NonEmptyString, ...] = Field(min_length=1)
    blocker_class: BlockerClass
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    dependency_owner: str | None = Field(default=None, min_length=1)
    resume_event: str = Field(min_length=1)
    mailbox_dependency: MailboxDependencyV1 | None = None
    requested_claim_action: RequestedClaimAction

    @model_validator(mode="after")
    def path_scope_and_class_are_paired(self) -> BlockerRequestV1:
        if (self.blocked_scope == "path") != (self.blocker_class == "path_conflict"):
            raise ValueError("path blocked_scope is valid only with path_conflict blocker_class")
        if len(self.blocked_item_refs) != len(set(self.blocked_item_refs)):
            raise ValueError("blocked_item_refs must be unique")
        if self.blocked_scope == "path":
            for value in self.blocked_item_refs:
                path = PurePosixPath(value)
                normalized = path.as_posix()
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in value
                    or normalized in {"", "."}
                    or normalized != value
                ):
                    raise ValueError("blocked path refs must be canonical portable repository-relative paths")
        return self


class BlockerDispositionV1(StrictContract):
    """System-owned deterministic decision; never an ownership mutation."""

    schema_version: Literal["1.0"] = "1.0"
    disposition_id: str = Field(pattern=r"^blocker_disposition_[0-9a-f]{32}$")
    request_ref: str = Field(min_length=1)
    ready_queue_evaluation_ref: str = Field(pattern=r"^ready_queue_[0-9a-f]{32}$")
    decision: DispositionDecision
    alternative_unit_ids: tuple[str, ...]
    claim_action: DispositionClaimAction
    reason_codes: tuple[str, ...] = Field(min_length=1)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    resume_event: str = Field(min_length=1)
    recorded_at: AwareDatetime
    application_authorized: Literal[False] = False


class BlockerDecisionResultV1(StrictContract):
    """Replayable system result retaining both derived queue and disposition."""

    schema_version: Literal["1.0"] = "1.0"
    ready_queue: ReadyQueueEvaluationV1
    disposition: BlockerDispositionV1


class BlockerDecisionInputV1(StrictContract):
    """Portable evidence envelope for one provider-free blocker decision.

    The queue is intentionally absent: the deterministic decision boundary
    computes it from exact source bytes instead of trusting derived caller data.
    """

    schema_version: Literal["1.0"] = "1.0"
    request_ref: str = Field(min_length=1)
    request: BlockerRequestV1
    work_graph_ref_path: str = Field(min_length=1)
    expected_work_graph_sha256: str = Field(pattern=HEX_SHA256)
    claim_snapshots: tuple[ClaimQueueSnapshotV1, ...] = ()
    mailbox_evidence: tuple[MailboxEvidenceV1, ...] = ()

    @field_validator("work_graph_ref_path")
    @classmethod
    def work_graph_ref_is_portable(cls, value: str) -> str:
        return WorkGraphRefV1(
            path=value,
            sha256="0" * 64,
        ).path

    @model_validator(mode="after")
    def require_one_mailbox_evidence_row_per_message(self) -> BlockerDecisionInputV1:
        """Reject ambiguous duplicate message-state inputs."""

        ids = [item.message_id for item in self.mailbox_evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("mailbox_evidence contains duplicate message IDs")
        return self


def _now() -> datetime:
    return datetime.now(UTC)


def _stable_id(prefix: str, payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return f"{prefix}_{hashlib.sha256(encoded).hexdigest()[:32]}"


def _unique(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _claim_snapshot_digest(claims: tuple[ClaimQueueSnapshotV1, ...]) -> str:
    rows = [claim.model_dump(mode="json") for claim in claims]
    rows.sort(key=lambda row: json.dumps(row, sort_keys=True, separators=(",", ":")))
    encoded = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _parse_time(value: str) -> datetime:
    _require_aware_datetime_string(value, field_name="approval timestamp")
    return datetime.fromisoformat(value)


def _find_hard_cycle(units_by_id: dict[str, QueueWorkUnitV1]) -> list[str] | None:
    hard_edges = {
        unit_id: [
            dependency.unit_id
            for dependency in unit.dependencies
            if dependency.type == "hard" and dependency.unit_id in units_by_id
        ]
        for unit_id, unit in units_by_id.items()
    }
    visiting: set[str] = set()
    visited: set[str] = set()
    path: list[str] = []

    def visit(unit_id: str) -> list[str] | None:
        if unit_id in visiting:
            start = path.index(unit_id)
            return [*path[start:], unit_id]
        if unit_id in visited:
            return None
        visiting.add(unit_id)
        path.append(unit_id)
        for dependency_id in hard_edges[unit_id]:
            cycle = visit(dependency_id)
            if cycle:
                return cycle
        path.pop()
        visiting.remove(unit_id)
        visited.add(unit_id)
        return None

    for unit_id in units_by_id:
        cycle = visit(unit_id)
        if cycle:
            return cycle
    return None


def _graph_semantic_errors(
    units: tuple[QueueWorkUnitV1, ...],
    *,
    as_of: datetime,
) -> tuple[str, ...]:
    """Apply the canonical queue-relevant WorkUnitV1 graph invariants."""

    units_by_id = {unit.id: unit for unit in units}
    errors: list[str] = []
    for unit in units:
        criterion_ids = [criterion.id for criterion in unit.acceptance]
        if len(criterion_ids) != len(set(criterion_ids)):
            errors.append(f"{unit.id}:duplicate_acceptance_ids")
        for dependency in unit.dependencies:
            if dependency.unit_id not in units_by_id:
                errors.append(f"{unit.id}:unresolved_dependency:{dependency.unit_id}")

        if unit.execution_class in NONEXECUTABLE_CLASSES and unit.status in {
            "ready",
            "claimed",
            "in_progress",
            "released",
            "completion_review",
            "changes_requested",
        }:
            errors.append(f"{unit.id}:nonexecutable_active_state")
        if unit.claimability in AVAILABLE_CLAIMABILITY and (
            unit.execution_class != "independently_executable" or unit.status != "ready"
        ):
            errors.append(f"{unit.id}:available_not_independently_ready")
        if unit.claimability == "unavailable_active_claim" and unit.status not in {
            "claimed",
            "in_progress",
            "completion_review",
            "changes_requested",
        }:
            errors.append(f"{unit.id}:unavailable_active_claim_without_active_status")
        if unit.status == "claimed" and unit.claimability != "unavailable_active_claim":
            errors.append(f"{unit.id}:claimed_without_unavailable_active_claim")
        if unit.status == "in_progress" and unit.claimability not in {
            "unavailable_active_claim",
            "not_applicable",
        }:
            errors.append(f"{unit.id}:in_progress_claimability_invalid")
        if unit.status == "ready" and unit.claimability not in AVAILABLE_CLAIMABILITY:
            errors.append(f"{unit.id}:ready_not_queue_claimable")
        if unit.claimability == "blocked_dependencies" and unit.status != "blocked":
            errors.append(f"{unit.id}:blocked_claimability_without_blocked_status")
        if unit.claimability == "pending_approval" and unit.status not in {
            "draft",
            "decomposed",
            "readiness_review",
        }:
            errors.append(f"{unit.id}:pending_approval_status_invalid")
        if unit.execution_class == "named_owner" and unit.claimability == "available":
            errors.append(f"{unit.id}:named_owner_cannot_be_available")
        required_approvals = set(unit.readiness.required_approval_types)
        if unit.profile == "controlled" and unit.control_approval_types:
            missing_controls = set(unit.control_approval_types) - required_approvals
            if missing_controls:
                errors.append(
                    f"{unit.id}:controlled_approvals_missing_from_readiness:{','.join(sorted(missing_controls))}"
                )
        if unit.unit_class == "deployment" and "deployment" not in required_approvals:
            errors.append(f"{unit.id}:deployment_approval_not_required")

        for approval in unit.readiness.approvals:
            try:
                approved_at = _parse_time(approval.approved_at)
                expires_at = _parse_time(approval.expires_at) if approval.expires_at else None
            except ValueError:
                errors.append(f"{unit.id}:approval_timestamp_invalid")
                continue
            if approved_at > as_of:
                errors.append(f"{unit.id}:{approval.approval_type}_approval_future_dated")
            if expires_at is not None and expires_at <= as_of:
                errors.append(f"{unit.id}:{approval.approval_type}_approval_expired")

        if unit.claimability not in AVAILABLE_CLAIMABILITY:
            continue
        if unit.readiness.status != "ready":
            errors.append(f"{unit.id}:available_without_ready_readiness")
        if unit.readiness.failed_guards:
            errors.append(f"{unit.id}:ready_with_failed_guards")
        approvals_by_type: dict[str, list[ApprovalV1]] = {}
        for approval in unit.readiness.approvals:
            approvals_by_type.setdefault(approval.approval_type, []).append(approval)
        for approval_type in unit.readiness.required_approval_types:
            approvals = approvals_by_type.get(approval_type, [])
            if not approvals:
                errors.append(f"{unit.id}:missing_required_{approval_type}_approval")
                continue
            expected_revision = unit.design_revision if approval_type == "design" else unit.spec_revision
            if not any(approval.approved_revision == expected_revision for approval in approvals):
                errors.append(f"{unit.id}:stale_{approval_type}_approval")
        for dependency in unit.dependencies:
            if dependency.type != "hard" or dependency.unit_id not in units_by_id:
                continue
            blocker = _hard_dependency_blocker(dependency, units_by_id=units_by_id)
            if blocker:
                errors.append(f"{unit.id}:{blocker}")

    cycle = _find_hard_cycle(units_by_id)
    if cycle:
        errors.append(f"hard_dependency_cycle:{'->'.join(cycle)}")

    active_units = [
        unit
        for unit in units
        if (unit.claimability in AVAILABLE_CLAIMABILITY and unit.status == "ready")
        or unit.status in WRITE_HOLDING_STATUSES
    ]
    active_surfaces = [
        (unit.id, surface)
        for unit in active_units
        for surface in unit.conflict_surfaces
        if surface.access in {"write", "exclusive"}
    ]
    for index, (left_id, left) in enumerate(active_surfaces):
        for right_id, right in active_surfaces[index + 1 :]:
            if left_id == right_id or left.kind != right.kind:
                continue
            overlaps = left.target == right.target
            if left.kind == "repository_path":
                overlaps = left.repository == right.repository and (
                    _path_contains(left.target, right.target) or _path_contains(right.target, left.target)
                )
            if not overlaps:
                continue
            if left.coordination_key and left.coordination_key == right.coordination_key:
                integration_owned = any(
                    unit.unit_class == "integration"
                    and any(surface.coordination_key == left.coordination_key for surface in unit.conflict_surfaces)
                    for unit in units
                )
                if not integration_owned:
                    errors.append(f"coordination_key_without_integration_owner:{left.coordination_key}")
                continue
            errors.append(f"unresolved_{left.kind}_conflict:{left_id}:{left.target}:{right_id}:{right.target}")
    return tuple(errors)


def _unavailable_queue(
    *,
    session_id: str,
    goal_or_graph_scope: str,
    graph_ref_path: str,
    claim_snapshot_sha256: str,
    evaluated_at: datetime,
    reason: str,
) -> ReadyQueueEvaluationV1:
    payload = {
        "session_id": session_id,
        "goal_or_graph_scope": goal_or_graph_scope,
        "graph_ref_path": graph_ref_path,
        "claim_snapshot_sha256": claim_snapshot_sha256,
        "reason": reason,
    }
    return ReadyQueueEvaluationV1(
        evaluation_id=_stable_id("ready_queue", payload),
        session_id=session_id,
        goal_or_graph_scope=goal_or_graph_scope,
        work_graph_ref=None,
        claim_snapshot_sha256=claim_snapshot_sha256,
        coverage="unavailable",
        eligible_unit_ids=(),
        blocked_unit_ids=(BlockedUnitV1(unit_id="queue", blocker_refs=(reason,)),),
        terminal_unit_ids=(),
        active_or_indeterminate_unit_ids=(),
        active_conflict_unit_ids=(),
        evaluated_at=evaluated_at,
        evidence_refs=(
            reason,
            f"work-graph-ref:{graph_ref_path}",
            f"claim-snapshot-sha256:{claim_snapshot_sha256}",
        ),
    )


def _active_unit_conflicts(
    *,
    units: tuple[QueueWorkUnitV1, ...],
    claims: tuple[ClaimQueueSnapshotV1, ...],
    requesting_session_id: str,
    goal_or_graph_scope: str,
    graph_path: str,
    graph_sha256: str,
) -> set[str]:
    """Return exact-bound units actively owned by another session."""

    conflicts: set[str] = set()
    repository = goal_or_graph_scope.split("#", 1)[0]
    for claim in claims:
        if (
            claim.session_id == requesting_session_id
            or claim.status not in LIVE_CLAIM_STATUSES
            or claim.goal_or_graph_scope != goal_or_graph_scope
            or claim.work_graph_path != graph_path
            or claim.work_graph_sha256 != graph_sha256
        ):
            continue
        if claim.work_unit_id:
            conflicts.add(claim.work_unit_id)
            continue
        for unit in units:
            write_surfaces = (
                surface.target
                for surface in unit.conflict_surfaces
                if surface.kind == "repository_path"
                and surface.repository == repository
                and surface.access in {"write", "exclusive"}
            )
            if any(
                _path_contains(claimed_path, target) or _path_contains(target, claimed_path)
                for target in write_surfaces
                for claimed_path in claim.claimed_paths
            ):
                conflicts.add(unit.id)
    return conflicts


def _path_contains(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    return len(left_parts) <= len(right_parts) and right_parts[: len(left_parts)] == left_parts


def _work_graph_matches_numbered_scope(graph_ref_path: str, goal_or_graph_scope: str) -> bool:
    """Bind one plan-qualified scope to the numbered graph filename."""

    match = re.fullmatch(r"[^#]+#0*(\d+)", goal_or_graph_scope)
    if match is None:
        return False
    plan_number = int(match.group(1))
    filename = PurePosixPath(graph_ref_path).name
    return filename.startswith((f"{plan_number}_", f"plan{plan_number}_"))


def _verified_path_conflicts(decision_input: BlockerDecisionInputV1) -> tuple[str, ...]:
    """Match requested path blockers to an exact-bound other-session claim."""

    request = decision_input.request
    if request.blocker_class != "path_conflict" or request.blocked_scope != "path":
        return ()
    matches: list[str] = []
    for claim in decision_input.claim_snapshots:
        if (
            claim.session_id == request.session_id
            or claim.status not in LIVE_CLAIM_STATUSES
            or claim.goal_or_graph_scope != request.claim_scope
            or claim.work_graph_path != decision_input.work_graph_ref_path
            or claim.work_graph_sha256 != decision_input.expected_work_graph_sha256
        ):
            continue
        for requested_path in request.blocked_item_refs:
            for claimed_path in claim.claimed_paths:
                if _path_contains(requested_path, claimed_path) or _path_contains(claimed_path, requested_path):
                    matches.append(f"path-conflict:{claim.session_id}:{claimed_path}:{requested_path}")
    return _unique(matches)


def _hard_dependency_blocker(
    dependency: WorkDependencyV1,
    *,
    units_by_id: dict[str, QueueWorkUnitV1],
) -> str | None:
    """Return a blocker only for an unsatisfied canonical hard dependency."""

    if dependency.type != "hard":
        return None
    gate = dependency.gate
    if isinstance(gate, UnitStatusGateV1):
        observed = units_by_id[dependency.unit_id].status
        if observed != gate.required_status:
            return f"hard_dependency_status:{dependency.unit_id}:required={gate.required_status}:observed={observed}"
        return None
    if not gate.satisfied:
        return f"hard_dependency_gate_unsatisfied:{dependency.unit_id}:{gate.type}"
    return None


def evaluate_ready_queue(
    *,
    repository_root: Path,
    work_graph_ref_path: str,
    expected_sha256: str,
    session_id: str,
    goal_or_graph_scope: str,
    claim_snapshots: tuple[ClaimQueueSnapshotV1, ...] = (),
    evaluated_at: datetime | None = None,
) -> ReadyQueueEvaluationV1:
    """Evaluate one exact work graph without mutating any coordination state."""

    observed_at = evaluated_at or _now()
    claim_snapshot_sha256 = _claim_snapshot_digest(claim_snapshots)
    try:
        graph_ref_path = WorkGraphRefV1(
            path=work_graph_ref_path,
            sha256="0" * 64,
        ).path
    except ValueError as exc:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=work_graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"malformed_work_graph_ref:{type(exc).__name__}",
        )
    if not _work_graph_matches_numbered_scope(graph_ref_path, goal_or_graph_scope):
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason="work_graph_goal_scope_mismatch",
        )
    resolved_root = repository_root.resolve()
    work_graph_path = (resolved_root / graph_ref_path).resolve()
    if not work_graph_path.is_relative_to(resolved_root):
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason="work_graph_outside_repository_root",
        )
    try:
        raw = work_graph_path.read_bytes()
    except OSError as exc:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"work_graph_unreadable:{type(exc).__name__}",
        )

    actual_sha256 = hashlib.sha256(raw).hexdigest()
    if actual_sha256 != expected_sha256:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"stale_graph_digest:expected={expected_sha256}:actual={actual_sha256}",
        )
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"malformed_work_graph:{type(exc).__name__}",
        )
    if not isinstance(payload, dict) or set(payload) != {"units"} or not isinstance(payload.get("units"), list):
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason="malformed_work_graph:exact_units_list_required",
        )

    try:
        units = tuple(QueueWorkUnitV1.model_validate(unit) for unit in payload["units"])
    except (ValidationError, ValueError) as exc:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"malformed_work_graph:invalid_work_unit:{type(exc).__name__}",
        )
    unit_ids = [unit.id for unit in units]
    if len(unit_ids) != len(set(unit_ids)):
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason="malformed_work_graph:duplicate_unit_id",
        )
    semantic_errors = _graph_semantic_errors(units, as_of=observed_at)
    if semantic_errors:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"invalid_work_graph_semantics:{'|'.join(semantic_errors)}",
        )
    known_ids = set(unit_ids)
    invalid_scope_claim_bindings = sorted(
        {
            (
                claim.session_id,
                claim.work_unit_id or "root-claim",
                claim.work_graph_path or "missing-path",
                claim.work_graph_sha256 or "missing-sha256",
            )
            for claim in claim_snapshots
            if claim.status in LIVE_CLAIM_STATUSES
            and claim.goal_or_graph_scope == goal_or_graph_scope
            and (claim.work_graph_path != graph_ref_path or claim.work_graph_sha256 != actual_sha256)
        }
    )
    if invalid_scope_claim_bindings:
        details = ",".join(":".join(binding) for binding in invalid_scope_claim_bindings)
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"invalid_claim_snapshot_stale_or_unbound_units:{details}",
        )
    unknown_claim_units = sorted(
        {
            claim.work_unit_id
            for claim in claim_snapshots
            if claim.work_unit_id
            and claim.status in LIVE_CLAIM_STATUSES
            and claim.goal_or_graph_scope == goal_or_graph_scope
            and claim.work_graph_path == graph_ref_path
            and claim.work_graph_sha256 == actual_sha256
            and claim.work_unit_id not in known_ids
        }
    )
    if unknown_claim_units:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"invalid_claim_snapshot_unknown_units:{','.join(unknown_claim_units)}",
        )

    units_by_id = {unit.id: unit for unit in units}
    terminal_claim_units = sorted(
        {
            claim.work_unit_id
            for claim in claim_snapshots
            if claim.work_unit_id in known_ids
            and claim.status in LIVE_CLAIM_STATUSES
            and claim.goal_or_graph_scope == goal_or_graph_scope
            and claim.work_graph_path == graph_ref_path
            and claim.work_graph_sha256 == actual_sha256
            and units_by_id[claim.work_unit_id].status in TERMINAL_UNIT_STATUSES
        }
    )
    if terminal_claim_units:
        return _unavailable_queue(
            session_id=session_id,
            goal_or_graph_scope=goal_or_graph_scope,
            graph_ref_path=graph_ref_path,
            claim_snapshot_sha256=claim_snapshot_sha256,
            evaluated_at=observed_at,
            reason=f"invalid_claim_snapshot_terminal_units:{','.join(terminal_claim_units)}",
        )

    conflicts = _active_unit_conflicts(
        units=units,
        claims=claim_snapshots,
        requesting_session_id=session_id,
        goal_or_graph_scope=goal_or_graph_scope,
        graph_path=graph_ref_path,
        graph_sha256=actual_sha256,
    )
    eligible: list[str] = []
    blocked: list[BlockedUnitV1] = []
    terminal: list[str] = []
    active_or_indeterminate: list[str] = []
    partial = False
    design_revisions: list[str] = []
    spec_revisions: list[str] = []

    for unit in units:
        unit_id = unit.id
        design_revisions.append(unit.design_revision)
        spec_revisions.append(unit.spec_revision)

        reasons: list[str] = []
        if unit.status in TERMINAL_UNIT_STATUSES:
            terminal.append(unit_id)
            continue
        if unit.status == "blocked" or unit.readiness.status == "blocked":
            reasons.append(f"unit_blocked:{unit.status}:{unit.readiness.status}")
        elif unit.status != "ready" or unit.readiness.status != "ready":
            active_or_indeterminate.append(unit_id)
            continue

        for dependency in unit.dependencies:
            dependency_id = dependency.unit_id
            if dependency_id not in known_ids:
                reasons.append(f"dependency_missing:{dependency_id}")
                partial = True
                continue
            blocker = _hard_dependency_blocker(dependency, units_by_id=units_by_id)
            if blocker:
                reasons.append(blocker)

        if unit_id in conflicts:
            reasons.append("active_claim_conflict")
        if reasons:
            blocked.append(BlockedUnitV1(unit_id=unit_id, blocker_refs=_unique(reasons)))
        else:
            eligible.append(unit_id)

    graph_ref = WorkGraphRefV1(
        path=graph_ref_path,
        sha256=actual_sha256,
        design_revisions=tuple(sorted(set(design_revisions))),
        spec_revisions=tuple(sorted(set(spec_revisions))),
    )
    result_payload = {
        "session_id": session_id,
        "goal_or_graph_scope": goal_or_graph_scope,
        "graph_ref_path": graph_ref_path,
        "graph_sha256": actual_sha256,
        "claim_snapshot_sha256": claim_snapshot_sha256,
        "eligible": eligible,
        "blocked": [item.model_dump(mode="json") for item in blocked],
        "terminal": terminal,
        "active_or_indeterminate": active_or_indeterminate,
        "conflicts": sorted(conflicts),
    }
    return ReadyQueueEvaluationV1(
        evaluation_id=_stable_id("ready_queue", result_payload),
        session_id=session_id,
        goal_or_graph_scope=goal_or_graph_scope,
        work_graph_ref=graph_ref,
        claim_snapshot_sha256=claim_snapshot_sha256,
        coverage="partial" if partial else "complete",
        eligible_unit_ids=tuple(sorted(eligible)),
        blocked_unit_ids=tuple(blocked),
        terminal_unit_ids=tuple(sorted(terminal)),
        active_or_indeterminate_unit_ids=tuple(sorted(active_or_indeterminate)),
        active_conflict_unit_ids=tuple(sorted(conflicts)),
        evaluated_at=observed_at,
        evidence_refs=(
            f"work-graph-ref:{graph_ref_path}",
            f"work-graph-sha256:{actual_sha256}",
            f"claim-snapshot-sha256:{claim_snapshot_sha256}",
        ),
    )


def _mailbox_requirement_met(
    dependency: MailboxDependencyV1 | None,
    evidence: tuple[MailboxEvidenceV1, ...],
) -> tuple[bool, tuple[str, ...]]:
    if dependency is None:
        return True, ()
    match = next((item for item in evidence if item.message_id == dependency.message_id), None)
    if match is None:
        return False, ("mailbox_evidence_missing", dependency.message_id)
    rank = {"persisted": 0, "runtime_accepted": 1, "observed": 2, "acknowledged": 3, "expired": -1}
    met = rank[match.state] >= rank[dependency.required_delivery_state]
    reason = "mailbox_delivery_satisfied" if met else "mailbox_delivery_below_required"
    return met, _unique([reason, match.message_id, *match.evidence_refs])


def _mapped_claim_action(requested: RequestedClaimAction) -> DispositionClaimAction:
    return {
        "retain_narrow": "retain_narrow",
        "handoff": "handoff_scope",
        "session_end": "retire_goal_scope",
    }[requested]


def evaluate_blocker_request(
    decision_input: BlockerDecisionInputV1,
    *,
    repository_root: Path,
    recorded_at: datetime | None = None,
) -> BlockerDecisionResultV1:
    """Evaluate source graph bytes and retain queue plus disposition."""

    request = decision_input.request
    observed_at = recorded_at or _now()
    queue = evaluate_ready_queue(
        repository_root=repository_root,
        work_graph_ref_path=decision_input.work_graph_ref_path,
        expected_sha256=decision_input.expected_work_graph_sha256,
        session_id=request.session_id,
        goal_or_graph_scope=request.claim_scope,
        claim_snapshots=decision_input.claim_snapshots,
        evaluated_at=observed_at,
    )

    # Eligible work is system-derived.  A caller cannot hide it by also naming
    # it in blocked_item_refs.
    alternatives = queue.eligible_unit_ids
    known_unit_ids = {
        *queue.eligible_unit_ids,
        *(item.unit_id for item in queue.blocked_unit_ids if item.unit_id != "queue"),
        *queue.terminal_unit_ids,
        *queue.active_or_indeterminate_unit_ids,
        *queue.active_conflict_unit_ids,
    }
    unknown_blocked_items = (
        tuple(item for item in request.blocked_item_refs if item not in known_unit_ids)
        if request.blocked_scope == "unit"
        else ()
    )
    blocked_unit_ids = {item.unit_id for item in queue.blocked_unit_ids if item.unit_id != "queue"}
    requested_units_not_blocked = (
        tuple(item for item in request.blocked_item_refs if item not in blocked_unit_ids)
        if request.blocked_scope == "unit"
        else ()
    )
    mailbox_met, mailbox_refs = _mailbox_requirement_met(
        request.mailbox_dependency,
        decision_input.mailbox_evidence,
    )
    path_conflict_refs = _verified_path_conflicts(decision_input)

    if path_conflict_refs:
        decision: DispositionDecision = "integration_wait"
        claim_action: DispositionClaimAction = "none"
        reasons = ("path_conflict_verified_local",)
    elif request.blocker_class == "path_conflict":
        decision = "blocker_unverified_return_control"
        claim_action = "none"
        reasons = ("path_conflict_evidence_unverified",)
    elif alternatives:
        decision = "continue_ready_work"
        claim_action = "none"
        reasons = ("eligible_alternative_exists",)
    elif queue.active_conflict_unit_ids:
        decision = "integration_wait"
        claim_action = "none"
        reasons = ("active_unit_in_progress",)
    elif queue.coverage != "complete":
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("queue_coverage_unavailable",)
    elif unknown_blocked_items:
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("blocked_item_not_in_queue",)
    elif requested_units_not_blocked:
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("requested_unit_not_blocked_in_queue",)
    elif queue.active_or_indeterminate_unit_ids:
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("queue_contains_active_or_indeterminate_state",)
    elif not queue.blocked_unit_ids:
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("queue_has_no_blocked_units",)
    elif not mailbox_met:
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("mailbox_delivery_below_required",)
    elif request.blocker_class == "human_decision":
        decision = "human_decision_required"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("named_human_decision_required",)
    elif request.blocker_class in SUPPORTED_WHOLE_GOAL_BLOCKERS:
        decision = "goal_blocked_verified"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("complete_queue_no_eligible_unit", f"supported_blocker:{request.blocker_class}")
    else:
        decision = "blocker_unverified_return_control"
        claim_action = _mapped_claim_action(request.requested_claim_action)
        reasons = ("unsupported_or_unknown_blocker",)

    graph_refs = list(queue.evidence_refs)
    if queue.work_graph_ref is not None:
        graph_refs.append(f"work-graph-sha256:{queue.work_graph_ref.sha256}")
    evidence_refs = _unique([*request.evidence_refs, *graph_refs, *mailbox_refs, *path_conflict_refs])
    disposition_payload: dict[str, Any] = {
        "request_ref": decision_input.request_ref,
        "request": request.model_dump(mode="json"),
        "ready_queue_evaluation_ref": queue.evaluation_id,
        "decision": decision,
        "alternatives": alternatives,
        "claim_action": claim_action,
        "reasons": reasons,
        "evidence_refs": evidence_refs,
        "resume_event": request.resume_event,
        "application_authorized": False,
    }
    disposition = BlockerDispositionV1(
        disposition_id=_stable_id("blocker_disposition", disposition_payload),
        request_ref=decision_input.request_ref,
        ready_queue_evaluation_ref=queue.evaluation_id,
        decision=decision,
        alternative_unit_ids=alternatives,
        claim_action=claim_action,
        reason_codes=reasons,
        evidence_refs=evidence_refs,
        resume_event=request.resume_event,
        recorded_at=observed_at,
        application_authorized=False,
    )
    return BlockerDecisionResultV1(ready_queue=queue, disposition=disposition)


def decide_blocker_disposition(
    decision_input: BlockerDecisionInputV1,
    *,
    repository_root: Path,
    recorded_at: datetime | None = None,
) -> BlockerDispositionV1:
    """Compatibility API returning only the source-derived disposition."""

    return evaluate_blocker_request(
        decision_input,
        repository_root=repository_root,
        recorded_at=recorded_at,
    ).disposition
