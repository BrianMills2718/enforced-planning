"""Evaluate progress-bound coding-agent continuation without cost gating.

Plan 114 is a staged admission seam, not fleet enforcement. It keeps outcome
identity, evidence classification, lease transition, and operation admission
pure so later session and claim integrations can consume one deterministic
decision. Ordinary approval and cost/elapsed telemetry are accepted as context
but are intentionally absent from every transition and admission branch.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PORTABLE_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")
PROJECT_ID_RE = re.compile(r"^[a-z][a-z0-9]*(?:[-_][a-z0-9]+)*$")
PERSONAL_SENTINELS = (
    "/".join(("", "home", "brian")),
    "".join(("Brian", "Mills2718")),
)
HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"

ProgressKind = Literal[
    "behavioral_advance",
    "direct_blocker_removed",
    "decision_changing_learning",
    "non_outcome",
]
VerificationRole = Literal["producer", "independent"]
ArtifactDisposition = Literal["evidenced", "rejected"]
PortfolioClass = Literal["product", "maintenance", "external_obligation"]
LeaseState = Literal["active", "recovery_required", "stalled", "complete", "parked"]
OperationKind = Literal[
    "product_write",
    "claim_create",
    "worktree_create",
    "commit",
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
    "recovery_action",
]

PROGRESS_KINDS = {
    "behavioral_advance",
    "direct_blocker_removed",
    "decision_changing_learning",
}
PASSIVE_OPERATIONS = {
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
}
PRODUCT_OPERATIONS = {"product_write", "claim_create", "worktree_create", "commit"}
ACTIVE_NEXT_ACTIONS: tuple[str, ...] = (
    "product_write",
    "claim_create",
    "worktree_create",
    "commit",
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
)
RECOVERY_NEXT_ACTIONS: tuple[str, ...] = (
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
    "bounded_recovery_action",
)
TERMINAL_NEXT_ACTIONS: tuple[str, ...] = (
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
)


class ContinuationError(RuntimeError):
    """Fail-loud continuation contract or lineage error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        """Return a portable JSON error payload."""

        return {"code": self.code, "message": str(self)}


class StrictModel(BaseModel):
    """Strict base for durable Plan 114 contracts."""

    model_config = ConfigDict(extra="forbid")


def _portable_id(value: str, *, field_name: str) -> None:
    if not PORTABLE_ID_RE.fullmatch(value):
        raise ValueError(f"{field_name} must be a portable lowercase identifier")


def _project_id(value: str) -> None:
    if not PROJECT_ID_RE.fullmatch(value):
        raise ValueError("project_id must be a canonical lowercase Project Graph identifier")


def _portable_path(value: str, *, field_name: str, directory_allowed: bool = False) -> None:
    raw_path = value[:-1] if directory_allowed and value.endswith("/") else value
    path = PurePosixPath(raw_path)
    if (
        not raw_path
        or path.is_absolute()
        or raw_path in {".", ".."}
        or "." in path.parts
        or ".." in path.parts
        or "\\" in value
        or "//" in value
        or any(sentinel.casefold() in value.casefold() for sentinel in PERSONAL_SENTINELS)
    ):
        raise ValueError(f"{field_name} must contain portable root-relative paths")


def canonical_sha256(value: BaseModel | dict[str, Any]) -> str:
    """Hash a model or JSON-compatible mapping with stable serialization."""

    payload = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class CanonicalJourneyV1(StrictModel):
    """Stable user-visible journey against which progress is observed."""

    starting_state: str = Field(min_length=8)
    input: str = Field(min_length=3)
    action: str = Field(min_length=8)
    observable_result: str = Field(min_length=3)
    failure_signal: str = Field(min_length=8)


class OutcomeCriterionV1(StrictModel):
    """One non-substitutable condition of the user-visible outcome."""

    criterion_id: str
    description: str = Field(min_length=12)

    @model_validator(mode="after")
    def _validate_criterion_id(self) -> OutcomeCriterionV1:
        _portable_id(self.criterion_id, field_name="criterion_id")
        return self


class OutcomeContractV1(StrictModel):
    """Immutable identity, scope, and canonical journey for one outcome lineage."""

    schema_version: Literal["1.0.0", "1.1.0", "1.2.0"] = "1.0.0"
    outcome_id: str
    owner_class: str
    project_id: str
    lineage_id: str
    portfolio_class: PortfolioClass | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    predecessor_lineage_ids: list[str] = Field(default_factory=list)
    intended_consumer: str = Field(min_length=8)
    outcome: str = Field(min_length=12)
    canonical_journey: CanonicalJourneyV1
    baseline_revision: str = Field(min_length=7)
    allowed_scope: list[str] = Field(min_length=1)
    progress_dimensions: list[str] = Field(min_length=1)
    success_criteria: list[OutcomeCriterionV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_identity_and_scope(self) -> OutcomeContractV1:
        if self.schema_version == "1.0.0" and self.portfolio_class is not None:
            raise ValueError("schema 1.0.0 contracts cannot declare portfolio_class")
        if self.schema_version == "1.1.0" and self.portfolio_class is None:
            raise ValueError("schema 1.1.0 contracts require portfolio_class")
        if self.schema_version == "1.2.0":
            if self.portfolio_class is None:
                raise ValueError("schema 1.2.0 contracts require portfolio_class")
            if not self.success_criteria:
                raise ValueError("schema 1.2.0 contracts require success_criteria")
        elif self.success_criteria:
            raise ValueError("success_criteria require schema 1.2.0")
        for field_name, value in (
            ("outcome_id", self.outcome_id),
            ("owner_class", self.owner_class),
            ("lineage_id", self.lineage_id),
        ):
            _portable_id(value, field_name=field_name)
        _project_id(self.project_id)
        for predecessor in self.predecessor_lineage_ids:
            _portable_id(predecessor, field_name="predecessor_lineage_ids")
        if len(set(self.predecessor_lineage_ids)) != len(self.predecessor_lineage_ids):
            raise ValueError("predecessor_lineage_ids must be unique")
        if self.lineage_id in self.predecessor_lineage_ids:
            raise ValueError("lineage_id cannot be its own predecessor")
        for path in self.allowed_scope:
            _portable_path(path, field_name="allowed_scope", directory_allowed=True)
        if len(set(self.allowed_scope)) != len(self.allowed_scope):
            raise ValueError("allowed_scope must be unique")
        if any(not dimension.strip() for dimension in self.progress_dimensions):
            raise ValueError("progress_dimensions must contain non-empty values")
        if len(set(self.progress_dimensions)) != len(self.progress_dimensions):
            raise ValueError("progress_dimensions must be unique")
        criterion_ids = [criterion.criterion_id for criterion in self.success_criteria]
        if len(set(criterion_ids)) != len(criterion_ids):
            raise ValueError("success_criteria criterion_id values must be unique")
        return self


class EvidenceBindingV1(StrictModel):
    """Exact source, configuration, route, command, and observation binding."""

    source_revision: str = Field(min_length=7)
    configuration_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    route: str = Field(min_length=3)
    command: list[str] = Field(min_length=1)
    observation_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    artifact_refs: list[str] = Field(default_factory=list)
    trace_ref: str | None = None
    observed_at: datetime

    @model_validator(mode="after")
    def _validate_command_and_refs(self) -> EvidenceBindingV1:
        if any(not item or "\n" in item or "\r" in item for item in self.command):
            raise ValueError("command must contain non-empty single-line arguments")
        if any(not ref.strip() for ref in self.artifact_refs):
            raise ValueError("artifact_refs must contain non-empty values")
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


class OutcomeProgressReceiptV1(StrictModel):
    """One independently bound progress or non-outcome observation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt_id: str
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    prior_receipt_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    progress_kind: ProgressKind
    dimension: str = Field(min_length=2)
    summary: str = Field(min_length=12)
    evidence: EvidenceBindingV1
    failure_boundary: str | None = None
    exact_replay_result: str | None = None
    decision_delta: str | None = None
    discriminating_evidence: bool = False
    artifact_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    artifact_disposition: ArtifactDisposition | None = None
    criterion_ids: list[str] = Field(default_factory=list)
    verifier_id: str | None = None
    verification_role: VerificationRole | None = None

    @model_validator(mode="after")
    def _validate_progress_claim(self) -> OutcomeProgressReceiptV1:
        _portable_id(self.receipt_id, field_name="receipt_id")
        if self.progress_kind == "decision_changing_learning" and not self.decision_delta:
            raise ValueError("decision_changing_learning requires decision_delta")
        if self.progress_kind == "direct_blocker_removed":
            if not self.failure_boundary:
                raise ValueError("direct_blocker_removed requires failure_boundary")
            if not self.exact_replay_result:
                raise ValueError("direct_blocker_removed requires exact_replay_result")
        for field_name, value in (
            ("failure_boundary", self.failure_boundary),
            ("exact_replay_result", self.exact_replay_result),
            ("decision_delta", self.decision_delta),
        ):
            if value is not None and len(value.strip()) < 8:
                raise ValueError(f"{field_name} must be specific enough to audit")
        artifact_fields = (self.artifact_sha256, self.artifact_disposition)
        if any(value is None for value in artifact_fields) != all(value is None for value in artifact_fields):
            raise ValueError("artifact_sha256 and artifact_disposition must be supplied together")
        verification_fields = (self.verifier_id, self.verification_role)
        if any(value is None for value in verification_fields) != all(value is None for value in verification_fields):
            raise ValueError("verifier_id and verification_role must be supplied together")
        for criterion_id in self.criterion_ids:
            _portable_id(criterion_id, field_name="criterion_ids")
        if len(set(self.criterion_ids)) != len(self.criterion_ids):
            raise ValueError("criterion_ids must be unique")
        if self.artifact_disposition == "rejected":
            if self.progress_kind != "non_outcome":
                raise ValueError("rejected artifacts must be recorded as non_outcome")
            if self.criterion_ids or self.verification_role is not None:
                raise ValueError("rejected artifacts cannot carry passing criterion evidence")
        return self


class OutcomeLeaseV1(StrictModel):
    """Replay-safe continuation state for one exact outcome contract digest."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    lease_id: str
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    state: LeaseState = "active"
    last_receipt_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    last_progress_receipt_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    consecutive_non_outcome_increments: int = Field(default=0, ge=0)
    current_failure_boundary: str | None = None
    same_boundary_failures: int = Field(default=0, ge=0)
    current_artifact_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    passed_criterion_ids: list[str] = Field(default_factory=list)
    rejected_artifact_sha256s: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_state_counters(self) -> OutcomeLeaseV1:
        _portable_id(self.lease_id, field_name="lease_id")
        if self.same_boundary_failures and not self.current_failure_boundary:
            raise ValueError("same_boundary_failures requires current_failure_boundary")
        if self.current_failure_boundary and not self.same_boundary_failures:
            raise ValueError("current_failure_boundary requires same_boundary_failures")
        if self.state == "active" and self.consecutive_non_outcome_increments >= 2:
            raise ValueError("active lease cannot retain two non-outcome increments")
        if self.state == "recovery_required" and self.consecutive_non_outcome_increments < 2:
            raise ValueError("recovery_required lease needs two non-outcome increments")
        if self.state == "stalled" and self.same_boundary_failures < 3:
            raise ValueError("stalled lease needs three same-boundary failures")
        if self.passed_criterion_ids and self.current_artifact_sha256 is None:
            raise ValueError("passed criteria require a current artifact")
        if len(set(self.passed_criterion_ids)) != len(self.passed_criterion_ids):
            raise ValueError("passed_criterion_ids must be unique")
        if len(set(self.rejected_artifact_sha256s)) != len(self.rejected_artifact_sha256s):
            raise ValueError("rejected_artifact_sha256s must be unique")
        if self.current_artifact_sha256 in self.rejected_artifact_sha256s:
            raise ValueError("a rejected artifact cannot remain current")
        return self


class ReviewReadinessDecisionV1(StrictModel):
    """Deterministic review gate for one exact candidate artifact."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    review_ready: bool
    reason_code: str = Field(min_length=3)
    artifact_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    missing_criterion_ids: list[str] = Field(default_factory=list)


class RecoveryLeaseV1(StrictModel):
    """One bounded recovery action bound to the exact current lease."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    recovery_lease_id: str
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    parent_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    failure_or_question: str = Field(min_length=12)
    changed_causal_hypothesis: str = Field(min_length=12)
    allowed_action: str = Field(min_length=8)
    allowed_paths: list[str] = Field(min_length=1)
    exact_replay_or_readout: str = Field(min_length=8)
    stopping_condition: str = Field(min_length=8)
    max_attempts: Literal[1] = 1

    @model_validator(mode="after")
    def _validate_recovery_scope(self) -> RecoveryLeaseV1:
        _portable_id(self.recovery_lease_id, field_name="recovery_lease_id")
        for path in self.allowed_paths:
            _portable_path(path, field_name="allowed_paths", directory_allowed=True)
        if len(set(self.allowed_paths)) != len(self.allowed_paths):
            raise ValueError("allowed_paths must be unique")
        return self


class RestartDeltaV1(StrictModel):
    """Exact causal difference required to restart a stalled or parked lineage."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["restart_delta"] = "restart_delta"
    delta_id: str
    recorded_at: datetime
    predecessor_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    predecessor_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    predecessor_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    predecessor_lineage_id: str
    predecessor_lease_state: Literal["stalled", "parked"]
    predecessor_non_outcome_count: int = Field(ge=0)
    predecessor_failure_boundary: str | None = None
    predecessor_failure_count: int = Field(ge=0)
    predecessor_failed_evidence_refs: list[str] = Field(default_factory=list)
    successor_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    successor_lineage_id: str
    prior_causal_hypothesis: str = Field(min_length=12)
    changed_causal_hypothesis: str = Field(min_length=12)
    prior_mechanism: str = Field(min_length=12)
    changed_mechanism: str = Field(min_length=12)
    bounded_action: str = Field(min_length=8)
    next_canonical_observation: str = Field(min_length=8)
    stopping_condition: str = Field(min_length=8)

    @model_validator(mode="after")
    def _validate_causal_difference(self) -> RestartDeltaV1:
        _portable_id(self.delta_id, field_name="delta_id")
        _portable_id(self.predecessor_lineage_id, field_name="predecessor_lineage_id")
        _portable_id(self.successor_lineage_id, field_name="successor_lineage_id")
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        if self.predecessor_lineage_id == self.successor_lineage_id:
            raise ValueError("restart successor lineage must differ from its predecessor")
        if self.prior_causal_hypothesis.strip().casefold() == self.changed_causal_hypothesis.strip().casefold():
            raise ValueError("changed_causal_hypothesis must differ from prior_causal_hypothesis")
        if self.prior_mechanism.strip().casefold() == self.changed_mechanism.strip().casefold():
            raise ValueError("changed_mechanism must differ from prior_mechanism")
        if any(not ref.strip() for ref in self.predecessor_failed_evidence_refs):
            raise ValueError("predecessor_failed_evidence_refs must contain non-empty values")
        if len(set(self.predecessor_failed_evidence_refs)) != len(self.predecessor_failed_evidence_refs):
            raise ValueError("predecessor_failed_evidence_refs must be unique")
        if self.predecessor_failure_count and not self.predecessor_failure_boundary:
            raise ValueError("predecessor_failure_count requires predecessor_failure_boundary")
        if self.predecessor_failure_boundary and not self.predecessor_failure_count:
            raise ValueError("predecessor_failure_boundary requires predecessor_failure_count")
        if self.predecessor_lease_state == "stalled":
            if self.predecessor_failure_count < 3 or not self.predecessor_failure_boundary:
                raise ValueError("stalled restart requires at least three failures at one named boundary")
            if not self.predecessor_failed_evidence_refs:
                raise ValueError("stalled restart requires retained failed evidence references")
        return self


class AdmissionRequestV1(StrictModel):
    """One requested supported operation plus decision-inert operator context."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    operation: OperationKind
    target_path: str | None = None
    recovery_action: str | None = None
    ordinary_approval: bool = False
    approval_text: str | None = None
    cost_telemetry_usd: Decimal | None = Field(default=None, ge=0)
    elapsed_telemetry_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _validate_operation_shape(self) -> AdmissionRequestV1:
        if self.operation in PRODUCT_OPERATIONS | {"recovery_action"} and not self.target_path:
            raise ValueError(f"{self.operation} requires target_path")
        if self.target_path:
            _portable_path(self.target_path, field_name="target_path", directory_allowed=True)
        if self.operation == "recovery_action" and not self.recovery_action:
            raise ValueError("recovery_action operation requires recovery_action")
        if self.operation != "recovery_action" and self.recovery_action is not None:
            raise ValueError("recovery_action is valid only for a recovery_action operation")
        return self


class LeaseTransitionV1(StrictModel):
    """Result of applying or replaying one receipt."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    receipt_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    applied: bool
    replayed: bool
    lease: OutcomeLeaseV1

    @model_validator(mode="after")
    def _one_transition_disposition(self) -> LeaseTransitionV1:
        if self.applied == self.replayed:
            raise ValueError("exactly one of applied or replayed must be true")
        return self


class ContinuationDecisionV1(StrictModel):
    """Deterministic allow/deny result for one supported operation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    allowed: bool
    reason_code: str
    lease_state: LeaseState
    operation: OperationKind
    permitted_next_actions: tuple[str, ...]
    ordinary_approval_ignored: Literal[True] = True
    cost_telemetry_ignored: Literal[True] = True
    elapsed_telemetry_ignored: Literal[True] = True


class OutcomeContinuationScenarioV1(StrictModel):
    """Complete deterministic input for the operator-facing evaluator."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scenario_id: str
    contract: OutcomeContractV1
    starting_lease: OutcomeLeaseV1 | None = None
    receipts: list[OutcomeProgressReceiptV1] = Field(default_factory=list)
    request: AdmissionRequestV1
    recovery_lease: RecoveryLeaseV1 | None = None

    @model_validator(mode="after")
    def _validate_scenario_id(self) -> OutcomeContinuationScenarioV1:
        _portable_id(self.scenario_id, field_name="scenario_id")
        return self


class OutcomeContinuationResultV1(StrictModel):
    """Lease and admission result emitted by the public JSON CLI."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    scenario_id: str
    scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    applied_receipt_sha256s: list[str]
    replayed_receipt_sha256s: list[str]
    lease: OutcomeLeaseV1
    lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    decision: ContinuationDecisionV1


def issue_initial_lease(
    contract: OutcomeContractV1,
    *,
    lease_id: str | None = None,
) -> OutcomeLeaseV1:
    """Issue the deterministic initial active lease for an accepted contract."""

    return OutcomeLeaseV1(
        lease_id=lease_id or f"{contract.outcome_id}-lease",
        outcome_contract_sha256=canonical_sha256(contract),
    )


def _assert_contract_binding(contract: OutcomeContractV1, lease: OutcomeLeaseV1) -> str:
    contract_sha256 = canonical_sha256(contract)
    if lease.outcome_contract_sha256 != contract_sha256:
        raise ContinuationError(
            "lease_contract_mismatch",
            "lease outcome contract digest does not match the supplied contract",
        )
    return contract_sha256


def transition_lease(
    contract: OutcomeContractV1,
    lease: OutcomeLeaseV1,
    receipt: OutcomeProgressReceiptV1,
) -> LeaseTransitionV1:
    """Apply one lineage-bound receipt without allowing evidence replay."""

    contract_sha256 = _assert_contract_binding(contract, lease)
    if receipt.outcome_contract_sha256 != contract_sha256:
        raise ContinuationError(
            "receipt_contract_mismatch",
            "receipt outcome contract digest does not match the supplied contract",
        )
    if receipt.dimension not in contract.progress_dimensions:
        raise ContinuationError(
            "receipt_dimension_mismatch",
            "receipt dimension is not declared by the outcome contract",
        )
    if contract.schema_version == "1.2.0":
        criterion_ids = {criterion.criterion_id for criterion in contract.success_criteria}
        unknown_criteria = sorted(set(receipt.criterion_ids) - criterion_ids)
        if unknown_criteria:
            raise ContinuationError(
                "receipt_criterion_mismatch",
                "receipt names criteria absent from the outcome contract: " + ", ".join(unknown_criteria),
            )
        if receipt.progress_kind == "behavioral_advance":
            if (
                receipt.artifact_disposition != "evidenced"
                or receipt.artifact_sha256 is None
                or not receipt.criterion_ids
                or receipt.verification_role != "independent"
                or receipt.verifier_id is None
                or not receipt.discriminating_evidence
            ):
                raise ContinuationError(
                    "criterion_evidence_required",
                    "schema 1.2.0 behavioral progress requires discriminating, "
                    "independent criterion evidence bound to one artifact",
                )
            if receipt.artifact_sha256 in lease.rejected_artifact_sha256s:
                raise ContinuationError(
                    "rejected_artifact_ineligible",
                    "a rejected artifact cannot receive new passing criterion evidence",
                )
    receipt_sha256 = canonical_sha256(receipt)
    if receipt_sha256 == lease.last_receipt_sha256:
        return LeaseTransitionV1(
            receipt_sha256=receipt_sha256,
            applied=False,
            replayed=True,
            lease=lease,
        )
    if receipt.prior_receipt_sha256 != lease.last_receipt_sha256:
        raise ContinuationError(
            "receipt_lineage_mismatch",
            "receipt lineage does not bind to the lease's last applied receipt",
        )
    if lease.state in {"complete", "parked"}:
        raise ContinuationError(
            "terminal_lease_transition",
            f"{lease.state} lease cannot accept another receipt without a reviewed restart",
        )

    update: dict[str, Any] = {
        "last_receipt_sha256": receipt_sha256,
    }
    if receipt.artifact_disposition == "rejected" and receipt.artifact_sha256:
        rejected = list(lease.rejected_artifact_sha256s)
        if receipt.artifact_sha256 not in rejected:
            rejected.append(receipt.artifact_sha256)
        update["rejected_artifact_sha256s"] = rejected
        if lease.current_artifact_sha256 == receipt.artifact_sha256:
            update["current_artifact_sha256"] = None
            update["passed_criterion_ids"] = []
    elif receipt.artifact_disposition == "evidenced" and receipt.artifact_sha256:
        same_artifact = lease.current_artifact_sha256 == receipt.artifact_sha256
        passed = list(lease.passed_criterion_ids) if same_artifact else []
        for criterion_id in receipt.criterion_ids:
            if criterion_id not in passed:
                passed.append(criterion_id)
        update["current_artifact_sha256"] = receipt.artifact_sha256
        update["passed_criterion_ids"] = passed
    if receipt.progress_kind in PROGRESS_KINDS:
        update.update(
            state="active",
            last_progress_receipt_sha256=receipt_sha256,
            consecutive_non_outcome_increments=0,
            current_failure_boundary=None,
            same_boundary_failures=0,
        )
    else:
        consecutive = lease.consecutive_non_outcome_increments + 1
        boundary = receipt.failure_boundary
        if boundary is None:
            same_boundary_failures = 0
        elif boundary == lease.current_failure_boundary and not receipt.discriminating_evidence:
            same_boundary_failures = lease.same_boundary_failures + 1
        else:
            same_boundary_failures = 1
        if same_boundary_failures >= 3:
            state: LeaseState = "stalled"
        elif consecutive >= 2:
            state = "recovery_required"
        else:
            state = "active"
        update.update(
            state=state,
            consecutive_non_outcome_increments=consecutive,
            current_failure_boundary=boundary,
            same_boundary_failures=same_boundary_failures,
        )

    transitioned = OutcomeLeaseV1.model_validate({**lease.model_dump(mode="json"), **update})
    return LeaseTransitionV1(
        receipt_sha256=receipt_sha256,
        applied=True,
        replayed=False,
        lease=transitioned,
    )


def evaluate_review_readiness(
    contract: OutcomeContractV1,
    lease: OutcomeLeaseV1,
    *,
    artifact_sha256: str,
) -> ReviewReadinessDecisionV1:
    """Refuse review until every frozen criterion passes on this exact artifact."""

    _assert_contract_binding(contract, lease)
    if contract.schema_version != "1.2.0":
        return ReviewReadinessDecisionV1(
            review_ready=False,
            reason_code="criterion_contract_not_configured",
            artifact_sha256=artifact_sha256,
        )
    if artifact_sha256 in lease.rejected_artifact_sha256s:
        return ReviewReadinessDecisionV1(
            review_ready=False,
            reason_code="artifact_rejected",
            artifact_sha256=artifact_sha256,
        )
    required = [criterion.criterion_id for criterion in contract.success_criteria]
    passed = set(lease.passed_criterion_ids) if lease.current_artifact_sha256 == artifact_sha256 else set()
    missing = [criterion_id for criterion_id in required if criterion_id not in passed]
    if missing:
        return ReviewReadinessDecisionV1(
            review_ready=False,
            reason_code="criterion_evidence_missing",
            artifact_sha256=artifact_sha256,
            missing_criterion_ids=missing,
        )
    return ReviewReadinessDecisionV1(
        review_ready=True,
        reason_code="all_criteria_evidenced",
        artifact_sha256=artifact_sha256,
    )


def _path_is_allowed(target_path: str, allowed_scope: list[str]) -> bool:
    for candidate in allowed_scope:
        if candidate.endswith("/"):
            if target_path.startswith(candidate) and target_path != candidate:
                return True
        elif target_path == candidate:
            return True
    return False


def _decision(
    *,
    allowed: bool,
    reason_code: str,
    lease: OutcomeLeaseV1,
    request: AdmissionRequestV1,
    permitted_next_actions: tuple[str, ...],
) -> ContinuationDecisionV1:
    return ContinuationDecisionV1(
        allowed=allowed,
        reason_code=reason_code,
        lease_state=lease.state,
        operation=request.operation,
        permitted_next_actions=permitted_next_actions,
    )


def admit_operation(
    contract: OutcomeContractV1,
    lease: OutcomeLeaseV1,
    request: AdmissionRequestV1,
    *,
    recovery_lease: RecoveryLeaseV1 | None = None,
) -> ContinuationDecisionV1:
    """Admit one supported operation from lease evidence, never approval/cost."""

    contract_sha256 = _assert_contract_binding(contract, lease)

    if request.operation in PASSIVE_OPERATIONS:
        next_actions: tuple[str, ...]
        if lease.state == "active":
            next_actions = ACTIVE_NEXT_ACTIONS
        elif lease.state in {"recovery_required", "stalled"}:
            next_actions = RECOVERY_NEXT_ACTIONS
        else:
            next_actions = TERMINAL_NEXT_ACTIONS
        return _decision(
            allowed=True,
            reason_code="passive_operation_allowed",
            lease=lease,
            request=request,
            permitted_next_actions=next_actions,
        )

    if lease.state == "active":
        if request.operation == "recovery_action":
            return _decision(
                allowed=False,
                reason_code="recovery_not_required",
                lease=lease,
                request=request,
                permitted_next_actions=ACTIVE_NEXT_ACTIONS,
            )
        if request.target_path is None or not _path_is_allowed(
            request.target_path,
            contract.allowed_scope,
        ):
            return _decision(
                allowed=False,
                reason_code="out_of_scope",
                lease=lease,
                request=request,
                permitted_next_actions=ACTIVE_NEXT_ACTIONS,
            )
        return _decision(
            allowed=True,
            reason_code="active_in_scope",
            lease=lease,
            request=request,
            permitted_next_actions=ACTIVE_NEXT_ACTIONS,
        )

    if request.operation == "recovery_action" and lease.state in {
        "recovery_required",
        "stalled",
    }:
        if recovery_lease is None:
            return _decision(
                allowed=False,
                reason_code="recovery_lease_missing",
                lease=lease,
                request=request,
                permitted_next_actions=RECOVERY_NEXT_ACTIONS,
            )
        if recovery_lease.outcome_contract_sha256 != contract_sha256:
            reason_code = "recovery_contract_mismatch"
        elif recovery_lease.parent_lease_sha256 != canonical_sha256(lease):
            reason_code = "recovery_parent_mismatch"
        elif request.recovery_action != recovery_lease.allowed_action:
            reason_code = "recovery_action_mismatch"
        elif request.target_path is None or not _path_is_allowed(
            request.target_path,
            recovery_lease.allowed_paths,
        ):
            reason_code = "recovery_path_mismatch"
        elif not _path_is_allowed(request.target_path, contract.allowed_scope):
            reason_code = "out_of_scope"
        else:
            return _decision(
                allowed=True,
                reason_code="bounded_recovery_allowed",
                lease=lease,
                request=request,
                permitted_next_actions=RECOVERY_NEXT_ACTIONS,
            )
        return _decision(
            allowed=False,
            reason_code=reason_code,
            lease=lease,
            request=request,
            permitted_next_actions=RECOVERY_NEXT_ACTIONS,
        )

    reason_by_state = {
        "recovery_required": "recovery_required",
        "stalled": "outcome_stalled",
        "complete": "outcome_complete",
        "parked": "outcome_parked",
    }
    next_actions = RECOVERY_NEXT_ACTIONS if lease.state in {"recovery_required", "stalled"} else TERMINAL_NEXT_ACTIONS
    return _decision(
        allowed=False,
        reason_code=reason_by_state[lease.state],
        lease=lease,
        request=request,
        permitted_next_actions=next_actions,
    )


def evaluate_scenario(scenario: OutcomeContinuationScenarioV1) -> OutcomeContinuationResultV1:
    """Apply an ordered scenario and return its final lease/admission result."""

    contract_sha256 = canonical_sha256(scenario.contract)
    lease = scenario.starting_lease or issue_initial_lease(scenario.contract)
    _assert_contract_binding(scenario.contract, lease)
    applied: list[str] = []
    replayed: list[str] = []
    for receipt in scenario.receipts:
        transition = transition_lease(scenario.contract, lease, receipt)
        lease = transition.lease
        target = applied if transition.applied else replayed
        target.append(transition.receipt_sha256)
    decision = admit_operation(
        scenario.contract,
        lease,
        scenario.request,
        recovery_lease=scenario.recovery_lease,
    )
    return OutcomeContinuationResultV1(
        scenario_id=scenario.scenario_id,
        scenario_sha256=canonical_sha256(scenario),
        outcome_contract_sha256=contract_sha256,
        applied_receipt_sha256s=applied,
        replayed_receipt_sha256s=replayed,
        lease=lease,
        lease_sha256=canonical_sha256(lease),
        decision=decision,
    )


def load_scenario(path: str) -> OutcomeContinuationScenarioV1:
    """Load one strict scenario JSON file."""

    try:
        return OutcomeContinuationScenarioV1.model_validate_json(Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        raise ContinuationError("scenario_read_failed", f"unable to read scenario: {exc}") from exc
