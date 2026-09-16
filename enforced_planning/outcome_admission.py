"""Production outcome-admission ordering for the first Enforced Planning consumer.

The pure decision owns policy ordering.  Live adapters must derive its state
from canonical claim, selection, portfolio, and continuation owners; callers
must not self-certify those states at an enforcement boundary.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, model_validator

from enforced_planning import coordination_claims, session_contracts
from enforced_planning.outcome_continuation import canonical_sha256, evaluate_scenario
from enforced_planning.outcome_selection import (
    OutcomeSelectionError,
    ResolvedOutcomeSelectionV1,
    resolve_selected_outcome_for_session,
)

OperationBoundary = Literal[
    "plan_create",
    "claim_create",
    "worktree_create",
    "session_start",
    "session_resume",
    "heartbeat",
    "prewrite",
    "commit",
    "portfolio_allocate",
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
]
EnforcementScope = Literal[
    "new_or_renewed",
    "grandfathered",
    "always_safe",
    "calibration_only",
]
PortfolioState = Literal[
    "active_exact",
    "missing",
    "occupied_by_other",
    "disposed",
    "digest_mismatch",
    "not_applicable",
]
ContinuationState = Literal[
    "active_in_scope",
    "out_of_scope",
    "recovery_required",
    "bounded_recovery_active",
    "stalled",
    "terminal",
    "missing",
]
AdmissionDisposition = Literal["allow", "deny", "defer"]
OutcomeAdmissionMode = Literal["off", "enforce_selected"]

SAFE_BOUNDARIES = frozenset(
    {
        "passive_inspection",
        "exact_replay",
        "evidence_preservation",
        "closeout",
    }
)
RENEWAL_BOUNDARIES = frozenset({"session_start", "session_resume", "heartbeat"})
PORTFOLIO_DENIALS: dict[PortfolioState, str] = {
    "missing": "portfolio_allocation_required",
    "occupied_by_other": "portfolio_slot_occupied",
    "disposed": "portfolio_allocation_inactive",
    "digest_mismatch": "portfolio_allocation_mismatch",
    "not_applicable": "portfolio_allocation_required",
}
CONTINUATION_DENIALS: dict[ContinuationState, str] = {
    "out_of_scope": "out_of_scope",
    "recovery_required": "recovery_required",
    "stalled": "outcome_stalled",
    "terminal": "outcome_terminal",
    "missing": "outcome_selection_required",
}

_PLAN_DOCUMENT_RE = re.compile(r"^docs/plans/(?P<plan>[1-9][0-9]*)_[a-z0-9_]+\.md$")
_PLAN_WORK_GRAPH_RE = re.compile(r"^docs/plans/(?P<plan>[1-9][0-9]*)_[a-z0-9_]+_work_graph\.json$")
_BOOTSTRAP_EXAMPLE_RE = re.compile(
    r"^examples/owner-real-outcome-admission/plan(?P<plan>[1-9][0-9]*)-[a-z0-9-]+\.json$"
)
_SHARED_BOOTSTRAP_PATHS = frozenset({"docs/plans/CLAUDE.md", "ROADMAP.md"})
DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH = Path.home() / ".claude" / "coordination" / "outcome-admission-v1.jsonl"
DEFAULT_SELECTION_PENDING_ACTIVATION_RECEIPT_PATH = (
    Path.home() / ".claude" / "coordination" / "selection-pending-activation-v1.jsonl"
)
HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"


def _mapping(value: object, *, field_name: str) -> dict[str, Any]:
    """Return one strict configuration mapping or fail visibly."""

    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def load_outcome_admission_mode(repo_root: Path) -> OutcomeAdmissionMode:
    """Load the strict repo-local outcome-admission mode.

    Absence is the compatibility state.  A present malformed configuration is
    never treated as off because that would turn a typo into an enforcement
    bypass.
    """

    config_path = repo_root.expanduser().resolve() / "meta-process.yaml"
    if not config_path.is_file():
        return "off"
    try:
        payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"unable to load {config_path}: {exc}") from exc
    if payload is None:
        return "off"
    root = _mapping(payload, field_name="meta-process.yaml")
    meta_process = _mapping(
        root.get("meta_process", root),
        field_name="meta-process.yaml meta_process",
    )
    if "claims" not in meta_process:
        return "off"
    claims_value = meta_process["claims"]
    claims = _mapping(claims_value, field_name="meta-process.yaml claims")
    mode = claims.get("outcome_admission_mode", "off")
    # PyYAML uses YAML 1.1 booleans, so the documented unquoted scalar ``off``
    # arrives here as False.  Normalize only that exact value; malformed
    # strings and every other type still fail closed below.
    if mode is False:
        mode = "off"
    if mode not in {"off", "enforce_selected"}:
        raise ValueError("claims.outcome_admission_mode must be one of: off, enforce_selected")
    return mode


class StrictModel(BaseModel):
    """Strict immutable base for admission contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomeAdmissionRequestV1(StrictModel):
    """One already-authorized operation classified for outcome admission."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    boundary: OperationBoundary
    enforcement_scope: EnforcementScope
    ordinary_allowed: bool
    portfolio_state: PortfolioState
    continuation_state: ContinuationState
    bootstrap_product_write_requested: bool = False

    @model_validator(mode="after")
    def validate_request(self) -> OutcomeAdmissionRequestV1:
        if self.bootstrap_product_write_requested and self.boundary != "portfolio_allocate":
            raise ValueError("bootstrap_product_write_requested is valid only for portfolio_allocate")
        if self.enforcement_scope == "always_safe" and self.boundary not in SAFE_BOUNDARIES:
            raise ValueError("always_safe scope requires a declared safe boundary")
        if self.boundary in SAFE_BOUNDARIES and self.enforcement_scope != "always_safe":
            raise ValueError("declared safe boundaries require always_safe scope")
        return self


class OutcomeAdmissionDecisionV1(StrictModel):
    """Stable production admission result."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    disposition: AdmissionDisposition
    reason_code: str = Field(min_length=3)


class OutcomeAdmissionBootstrapV1(StrictModel):
    """Exact write scope requested for the first-consumer allocation bootstrap."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    plan_number: int = Field(gt=0)
    write_paths: tuple[str, ...]
    ordinary_allowed: bool = True

    @model_validator(mode="after")
    def validate_unique_paths(self) -> OutcomeAdmissionBootstrapV1:
        if len(set(self.write_paths)) != len(self.write_paths):
            raise ValueError("bootstrap write_paths must be unique")
        return self


class OutcomeAdmissionBootstrapResultV1(StrictModel):
    """Bootstrap classification plus the canonical production decision."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    bootstrap: OutcomeAdmissionBootstrapV1
    allowed_paths: tuple[str, ...]
    rejected_paths: tuple[str, ...]
    request: OutcomeAdmissionRequestV1
    decision: OutcomeAdmissionDecisionV1

    @model_validator(mode="after")
    def validate_classification(self) -> OutcomeAdmissionBootstrapResultV1:
        expected_allowed = tuple(
            path
            for path in self.bootstrap.write_paths
            if is_first_consumer_bootstrap_path(
                path,
                plan_number=self.bootstrap.plan_number,
            )
        )
        expected_rejected = tuple(path for path in self.bootstrap.write_paths if path not in expected_allowed)
        if self.allowed_paths != expected_allowed or self.rejected_paths != expected_rejected:
            raise ValueError("bootstrap path classification does not match the fixed source set")
        expected_request = OutcomeAdmissionRequestV1(
            boundary="portfolio_allocate",
            enforcement_scope="new_or_renewed",
            ordinary_allowed=self.bootstrap.ordinary_allowed,
            portfolio_state="not_applicable",
            continuation_state="missing",
            bootstrap_product_write_requested=(not self.bootstrap.write_paths or bool(expected_rejected)),
        )
        if self.request != expected_request:
            raise ValueError("bootstrap request does not match its classified write scope")
        if self.decision != decide_outcome_admission(expected_request):
            raise ValueError("bootstrap decision does not match the production decision")
        return self


class SelectedOutcomeAdmissionEvidenceV1(StrictModel):
    """Exact canonical state used to derive one selected admission request."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    agent: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    session_id: str = Field(min_length=3)
    claim_source_file: str = Field(min_length=1)
    selection_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    selection_schema_version: Literal["1.0.0", "1.1.0"]
    portfolio_allocation_id: str | None = None
    portfolio_allocation_sha256: str | None = Field(
        default=None,
        pattern=HEX_SHA256_PATTERN,
    )
    portfolio_ledger_path: str | None = None
    base_scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    effective_scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    current_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    current_lease_state: Literal[
        "active",
        "recovery_required",
        "stalled",
        "complete",
        "parked",
    ]
    continuation_reason_code: str = Field(min_length=3)
    progress_transition_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_portfolio_evidence(self) -> SelectedOutcomeAdmissionEvidenceV1:
        fields = (
            self.portfolio_allocation_id,
            self.portfolio_allocation_sha256,
            self.portfolio_ledger_path,
        )
        if self.selection_schema_version == "1.0.0" and any(value is not None for value in fields):
            raise ValueError("legacy selected evidence cannot retain portfolio fields")
        if self.selection_schema_version == "1.1.0" and not all(value is not None for value in fields):
            raise ValueError("classed selected evidence requires complete portfolio fields")
        return self


class SelectionPendingActivationEvidenceV1(StrictModel):
    """Exact current reservation allowed to create only its first session tracker."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    agent: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    session_id: str = Field(min_length=3)
    claim_source_file: str = Field(min_length=1)
    claim_reservation_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    claim_schema_version: Literal[4, 5, 6]
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    authority_ref: str | None = Field(default=None, min_length=1)
    work_unit_id: str | None = Field(default=None, min_length=1)
    work_graph_path: str | None = Field(default=None, min_length=1)
    work_graph_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    start_revision: str | None = Field(default=None, pattern=r"^[0-9a-f]{40}$")
    sole_health_issue: Literal["missing_tracker_path"] = "missing_tracker_path"

    @model_validator(mode="after")
    def validate_authority_shape(self) -> SelectionPendingActivationEvidenceV1:
        graph_fields = (self.work_unit_id, self.work_graph_path, self.work_graph_sha256)
        if self.authority_ref is None:
            if not all(value is not None for value in (*graph_fields, self.start_revision)):
                raise ValueError("plan pending activation requires complete work-unit identity")
        elif not coordination_claims.is_goal_authority_ref(self.authority_ref):
            raise ValueError("pending activation authority_ref must use exact goal:<id> syntax")
        elif any(value is not None for value in graph_fields):
            raise ValueError("goal pending activation cannot retain plan work-unit identity")
        return self


class SelectionPendingActivationResultV1(StrictModel):
    """A separately versioned tracker-attachment result, never selected admission."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    disposition: Literal["defer", "deny"]
    reason_code: str = Field(min_length=3)
    evidence: SelectionPendingActivationEvidenceV1 | None = None
    resolution_error_code: str | None = None
    resolution_error_message: str | None = None

    @model_validator(mode="after")
    def validate_result(self) -> SelectionPendingActivationResultV1:
        errors = (self.resolution_error_code, self.resolution_error_message)
        if self.disposition == "defer":
            if (
                self.reason_code != "selection_pending"
                or self.evidence is None
                or any(value is not None for value in errors)
            ):
                raise ValueError("selection-pending defer requires exact evidence and no resolution error")
        elif self.evidence is not None or not all(value is not None for value in errors):
            raise ValueError("selection-pending denial requires a complete error and no evidence")
        return self


class SelectionPendingActivationReceiptV1(StrictModel):
    """Append-only staged-activation receipt isolated from admission v1 readers."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["selection_pending_activation_receipt"] = "selection_pending_activation_receipt"
    receipt_id: str = Field(pattern=r"^spact-[0-9a-f]{32}$")
    observed_at: datetime
    result_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    result: SelectionPendingActivationResultV1

    @model_validator(mode="after")
    def validate_receipt(self) -> SelectionPendingActivationReceiptV1:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if canonical_sha256(self.result) != self.result_sha256:
            raise ValueError("result_sha256 does not match the retained result")
        return self


class OutcomeAdmissionResultV1(StrictModel):
    """One bootstrap or exact-selected result before an entrypoint mutation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    source: Literal["bootstrap", "selected"]
    request: OutcomeAdmissionRequestV1 | None
    decision: OutcomeAdmissionDecisionV1
    bootstrap_evidence: OutcomeAdmissionBootstrapResultV1 | None = None
    selected_evidence: SelectedOutcomeAdmissionEvidenceV1 | None = None
    resolution_error_code: str | None = None
    resolution_error_message: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> OutcomeAdmissionResultV1:
        errors = (self.resolution_error_code, self.resolution_error_message)
        if self.request is None and not all(value is not None for value in errors):
            raise ValueError("missing request requires a complete resolution error")
        if self.request is not None and any(value is not None for value in errors):
            raise ValueError("classified request cannot also retain a resolution error")
        if self.decision.disposition == "allow" and self.request is None:
            raise ValueError("allow requires a classified admission request")
        if self.request is not None and self.decision != decide_outcome_admission(self.request):
            raise ValueError("result decision does not match the production decision")
        if (self.source == "bootstrap") != (self.bootstrap_evidence is not None):
            raise ValueError("bootstrap source requires only bootstrap evidence")
        if self.source == "bootstrap" and self.selected_evidence is not None:
            raise ValueError("bootstrap result cannot retain selected evidence")
        if self.bootstrap_evidence is not None and (
            self.request != self.bootstrap_evidence.request or self.decision != self.bootstrap_evidence.decision
        ):
            raise ValueError("bootstrap result does not match its retained classification")
        if self.source == "selected" and self.bootstrap_evidence is not None:
            raise ValueError("selected result cannot retain bootstrap evidence")
        if self.source == "selected" and self.request is None and self.selected_evidence is not None:
            raise ValueError("unresolved selected result cannot retain derived evidence")
        if (
            self.source == "selected"
            and self.request is not None
            and self.request.ordinary_allowed
            and self.selected_evidence is None
        ):
            raise ValueError("ordinary-allowed selected result requires exact derived evidence")
        if (
            self.source == "selected"
            and self.request is not None
            and not self.request.ordinary_allowed
            and self.selected_evidence is not None
        ):
            raise ValueError("ordinary-denied selected result cannot retain derived evidence")
        return self


class OutcomeAdmissionReceiptV1(StrictModel):
    """Append-only exact admission receipt emitted before protected continuation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_admission_receipt"] = "outcome_admission_receipt"
    receipt_id: str = Field(pattern=r"^oadm-[0-9a-f]{32}$")
    observed_at: datetime
    result_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    result: OutcomeAdmissionResultV1

    @model_validator(mode="after")
    def validate_receipt(self) -> OutcomeAdmissionReceiptV1:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if canonical_sha256(self.result) != self.result_sha256:
            raise ValueError("result_sha256 does not match the retained result")
        return self


def decide_outcome_admission(
    request: OutcomeAdmissionRequestV1,
) -> OutcomeAdmissionDecisionV1:
    """Apply the signed-off first-consumer ordering to one typed request."""

    if request.enforcement_scope == "calibration_only":
        return OutcomeAdmissionDecisionV1(
            disposition="defer",
            reason_code="cross_repository_membership_not_promoted",
        )
    if not request.ordinary_allowed:
        return OutcomeAdmissionDecisionV1(
            disposition="deny",
            reason_code="ordinary_authority_denied",
        )
    if request.enforcement_scope == "always_safe":
        return OutcomeAdmissionDecisionV1(
            disposition="allow",
            reason_code="safe_operation_allowed",
        )
    if request.enforcement_scope == "grandfathered":
        return OutcomeAdmissionDecisionV1(
            disposition="allow",
            reason_code="grandfathered_until_renewal",
        )
    if request.boundary == "portfolio_allocate":
        if request.bootstrap_product_write_requested:
            return OutcomeAdmissionDecisionV1(
                disposition="deny",
                reason_code="admission_bootstrap_scope_violation",
            )
        if request.portfolio_state != "not_applicable":
            return OutcomeAdmissionDecisionV1(
                disposition="deny",
                reason_code="admission_bootstrap_state_invalid",
            )
        return OutcomeAdmissionDecisionV1(
            disposition="allow",
            reason_code="admission_bootstrap_allowed",
        )
    if request.portfolio_state != "active_exact":
        return OutcomeAdmissionDecisionV1(
            disposition="deny",
            reason_code=PORTFOLIO_DENIALS[request.portfolio_state],
        )
    if request.continuation_state == "active_in_scope":
        return OutcomeAdmissionDecisionV1(
            disposition="allow",
            reason_code="outcome_admission_active",
        )
    if request.continuation_state == "bounded_recovery_active":
        return OutcomeAdmissionDecisionV1(
            disposition="allow",
            reason_code="bounded_recovery_active",
        )
    return OutcomeAdmissionDecisionV1(
        disposition="deny",
        reason_code=CONTINUATION_DENIALS[request.continuation_state],
    )


def _portable_repo_path(value: str) -> str | None:
    """Return one canonical POSIX repository path or None for unsafe syntax."""

    if not value or "\\" in value:
        return None
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        return None
    normalized = path.as_posix()
    return normalized if normalized == value else None


def is_first_consumer_bootstrap_path(path: str, *, plan_number: int) -> bool:
    """Return whether one exact path belongs to the fixed source bootstrap set."""

    normalized = _portable_repo_path(path)
    if normalized is None:
        return False
    if normalized in _SHARED_BOOTSTRAP_PATHS:
        return True
    for pattern in (_PLAN_DOCUMENT_RE, _PLAN_WORK_GRAPH_RE, _BOOTSTRAP_EXAMPLE_RE):
        match = pattern.fullmatch(normalized)
        if match is not None and int(match.group("plan")) == plan_number:
            return True
    return False


def _bootstrap_path_plan(path: str) -> int | None:
    """Return the Plan number carried by one exact bootstrap path."""

    normalized = _portable_repo_path(path)
    if normalized is None or normalized in _SHARED_BOOTSTRAP_PATHS:
        return None
    for pattern in (_PLAN_DOCUMENT_RE, _PLAN_WORK_GRAPH_RE, _BOOTSTRAP_EXAMPLE_RE):
        match = pattern.fullmatch(normalized)
        if match is not None:
            return int(match.group("plan"))
    return None


def infer_first_consumer_bootstrap_plan(write_paths: tuple[str, ...]) -> int | None:
    """Infer one unique Plan only when the complete claim is bootstrap-safe."""

    if not write_paths or len(set(write_paths)) != len(write_paths):
        return None
    plan_numbers = {plan_number for path in write_paths if (plan_number := _bootstrap_path_plan(path)) is not None}
    if len(plan_numbers) != 1:
        return None
    plan_number = next(iter(plan_numbers))
    if not all(is_first_consumer_bootstrap_path(path, plan_number=plan_number) for path in write_paths):
        return None
    return plan_number


def evaluate_claim_bootstrap_admission(
    claim: coordination_claims.ClaimRecord,
    *,
    target_path: str,
    ordinary_allowed: bool = True,
) -> OutcomeAdmissionResultV1 | None:
    """Return bootstrap admission only for an exact target in one safe claim.

    None means the claim is not a bootstrap claim and the caller must use
    selected-outcome admission.  The exact unplanned identity is required in
    addition to the path allowlist so a qualified planned work unit cannot
    acquire bootstrap authority merely by owning Plan-numbered transition
    artifacts.
    """

    if claim.plan_ref != session_contracts.UNPLANNED_PLAN_REF:
        return None
    write_paths = tuple(claim.write_paths)
    plan_number = infer_first_consumer_bootstrap_plan(write_paths)
    if plan_number is None or target_path not in write_paths:
        return None
    return bootstrap_admission_result(
        OutcomeAdmissionBootstrapV1(
            plan_number=plan_number,
            write_paths=write_paths,
            ordinary_allowed=ordinary_allowed,
        )
    )


def has_sanctioned_maintenance_claim_identity(claim: coordination_claims.ClaimRecord) -> bool:
    """Return whether claim-side fields retain canonical maintenance identity."""

    branch = claim.branch
    if (
        claim.plan_ref != session_contracts.UNPLANNED_PLAN_REF
        or claim.claim_type != "program"
        or not isinstance(branch, str)
        or not branch.strip()
        or claim.parent_scope is not None
        or claim.parallel_root_authorized
        or not claim.tracker_path
        or not claim.session_id
        or not claim.repo_root
        or not claim.worktree_path
        or len(claim.projects) != 1
        or not claim.source_file
        or not isinstance(claim.start_revision, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", claim.start_revision) is None
        or any(
            value is not None
            for value in (
                claim.plan_repo_root,
                claim.plan_revision,
                claim.plan_sha256,
                claim.work_unit_id,
                claim.work_graph_path,
                claim.work_graph_sha256,
            )
        )
        or claim.approval_revisions
    ):
        return False

    assert isinstance(branch, str)
    goal = f"Unplanned maintenance: {branch.replace('-', ' ').replace('/', ' ')}"
    return not (
        claim.intent != goal
        or claim.broader_goal != goal
        or claim.session_name != session_contracts.derive_session_name(goal)
    )


def has_sanctioned_delegated_maintenance_claim_identity(
    claim: coordination_claims.ClaimRecord,
) -> bool:
    """Return whether a child claim retains the exact delegated identity."""

    branch = claim.branch
    parent_scope = claim.parent_scope
    session_id = claim.session_id
    if (
        claim.plan_ref != session_contracts.UNPLANNED_PLAN_REF
        or claim.claim_type != "write"
        or not isinstance(branch, str)
        or not branch.strip()
        or claim.scope != branch
        or not isinstance(parent_scope, str)
        or not parent_scope.strip()
        or parent_scope != parent_scope.strip()
        or parent_scope == claim.scope
        or not claim.write_paths
        or "." in claim.write_paths
        or claim.read_paths
        or not isinstance(claim.start_revision, str)
        or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", claim.start_revision) is None
        or claim.parallel_root_authorized
        or claim.broad_scope_mode is not None
        or claim.broad_scope_reason is not None
        or claim.target_worktree_path is not None
        or not claim.tracker_path
        or not isinstance(session_id, str)
        or re.fullmatch(rf"{re.escape(claim.agent)}:[^:]+", session_id) is None
        or not claim.repo_root
        or not claim.worktree_path
        or len(claim.projects) != 1
        or not claim.source_file
        or any(
            value is not None
            for value in (
                claim.plan_repo_root,
                claim.plan_revision,
                claim.plan_sha256,
                claim.work_unit_id,
                claim.work_graph_path,
                claim.work_graph_sha256,
            )
        )
        or claim.approval_revisions
    ):
        return False

    goal = f"Delegated maintenance: {branch.replace('-', ' ').replace('/', ' ')}"
    return not (
        claim.intent != goal
        or claim.broader_goal != goal
        or claim.session_name != session_contracts.derive_session_name(goal)
    )


def is_sanctioned_maintenance_claim_payload(
    claim: coordination_claims.ClaimRecord,
    payload: object,
    *,
    tracker_path: Path | None = None,
) -> bool:
    """Classify typed maintenance provenance from one already-read tracker payload.

    ``UNPLANNED`` alone is not an exemption from selected-outcome admission.
    The claim must retain the exact identity written by the sanctioned
    ``maintenance_worktree`` transaction and its linked session tracker must
    retain the same claim identity.  Ordinary prewrite admission remains
    responsible for proving the live session, repository, branch, worktree,
    and target path before this narrower policy classifier is consulted.
    """

    if not has_sanctioned_maintenance_claim_identity(claim):
        return False

    branch = claim.branch
    assert isinstance(branch, str)
    assert claim.tracker_path is not None
    assert claim.session_id is not None
    assert claim.repo_root is not None
    assert claim.worktree_path is not None
    assert claim.session_name is not None
    assert claim.broader_goal is not None
    resolved_tracker_path = (
        tracker_path if tracker_path is not None else Path(claim.tracker_path)
    ).expanduser().resolve()
    if not isinstance(payload, dict):
        return False
    tracker_claim = payload.get("claim")
    tracker = payload.get("tracker")
    if not isinstance(tracker_claim, dict) or not isinstance(tracker, dict):
        return False
    expected_identity = {
        "agent": claim.agent,
        "project": claim.projects[0],
        "scope": claim.scope,
        "intent": claim.intent,
        "plan_ref": session_contracts.UNPLANNED_PLAN_REF,
        "repo_root": claim.repo_root,
        "worktree_path": claim.worktree_path,
        "branch": branch,
        "session_id": claim.session_id,
        "session_name": claim.session_name,
        "broader_goal": claim.broader_goal,
        "tracker_path": str(resolved_tracker_path),
        "start_revision": claim.start_revision,
    }
    current_phase = tracker.get("current_phase")
    return (
        isinstance(current_phase, str)
        and bool(current_phase.strip())
        and all(tracker_claim.get(field) == value for field, value in expected_identity.items())
    )


def is_sanctioned_delegated_maintenance_claim_payload(
    claim: coordination_claims.ClaimRecord,
    payload: object,
    *,
    tracker_path: Path | None = None,
) -> bool:
    """Classify a delegated child from one already-read tracker payload."""

    if not has_sanctioned_delegated_maintenance_claim_identity(claim):
        return False
    assert claim.tracker_path is not None
    resolved_tracker_path = (
        tracker_path if tracker_path is not None else Path(claim.tracker_path)
    ).expanduser().resolve()
    if not isinstance(payload, dict):
        return False
    tracker_claim = payload.get("claim")
    tracker = payload.get("tracker")
    if not isinstance(tracker_claim, dict) or not isinstance(tracker, dict):
        return False
    expected_identity = {
        "agent": claim.agent,
        "project": claim.projects[0],
        "scope": claim.scope,
        "intent": claim.intent,
        "plan_ref": session_contracts.UNPLANNED_PLAN_REF,
        "repo_root": claim.repo_root,
        "worktree_path": claim.worktree_path,
        "branch": claim.branch,
        "session_id": claim.session_id,
        "session_name": claim.session_name,
        "broader_goal": claim.broader_goal,
        "tracker_path": str(resolved_tracker_path),
        "start_revision": claim.start_revision,
    }
    current_phase = tracker.get("current_phase")
    return (
        isinstance(current_phase, str)
        and bool(current_phase.strip())
        and all(tracker_claim.get(field) == value for field, value in expected_identity.items())
    )


def is_sanctioned_maintenance_claim(claim: coordination_claims.ClaimRecord) -> bool:
    """Read and classify one claim's linked tracker without a caller-held lock."""

    if not claim.tracker_path:
        return False
    tracker_path = Path(claim.tracker_path).expanduser().resolve()
    try:
        tracker_bytes = tracker_path.read_bytes()
        payload = yaml.safe_load(tracker_bytes)
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return False
    return is_sanctioned_maintenance_claim_payload(
        claim,
        payload,
        tracker_path=tracker_path,
    )


def is_sanctioned_delegated_maintenance_claim(
    claim: coordination_claims.ClaimRecord,
) -> bool:
    """Read and classify one exact delegated child claim fail-closed."""

    if not claim.tracker_path:
        return False
    tracker_path = Path(claim.tracker_path).expanduser().resolve()
    try:
        payload = yaml.safe_load(tracker_path.read_bytes())
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return False
    return is_sanctioned_delegated_maintenance_claim_payload(
        claim,
        payload,
        tracker_path=tracker_path,
    )


def evaluate_first_consumer_bootstrap(
    bootstrap: OutcomeAdmissionBootstrapV1,
) -> OutcomeAdmissionBootstrapResultV1:
    """Classify and decide one bounded source-repository allocation bootstrap."""

    allowed_paths = tuple(
        path
        for path in bootstrap.write_paths
        if is_first_consumer_bootstrap_path(path, plan_number=bootstrap.plan_number)
    )
    rejected_paths = tuple(path for path in bootstrap.write_paths if path not in allowed_paths)
    request = OutcomeAdmissionRequestV1(
        boundary="portfolio_allocate",
        enforcement_scope="new_or_renewed",
        ordinary_allowed=bootstrap.ordinary_allowed,
        portfolio_state="not_applicable",
        continuation_state="missing",
        bootstrap_product_write_requested=(not bootstrap.write_paths or bool(rejected_paths)),
    )
    return OutcomeAdmissionBootstrapResultV1(
        bootstrap=bootstrap,
        allowed_paths=allowed_paths,
        rejected_paths=rejected_paths,
        request=request,
        decision=decide_outcome_admission(request),
    )


def bootstrap_admission_result(
    bootstrap: OutcomeAdmissionBootstrapV1,
) -> OutcomeAdmissionResultV1:
    """Return the canonical receipt-ready result for one bootstrap request."""

    result = evaluate_first_consumer_bootstrap(bootstrap)
    return OutcomeAdmissionResultV1(
        source="bootstrap",
        request=result.request,
        decision=result.decision,
        bootstrap_evidence=result,
    )


def _selection_error_reason(code: str) -> str:
    """Map exact selection-owner failures to stable admission denial reasons."""

    if code == "selection_missing":
        return "outcome_selection_required"
    if code in {
        "portfolio_allocation_missing",
        "portfolio_allocation_required",
    }:
        return "portfolio_allocation_required"
    if code in {
        "portfolio_allocation_inactive",
        "portfolio_allocation_already_disposed",
    }:
        return "portfolio_allocation_inactive"
    if code in {
        "portfolio_allocation_conflict",
        "portfolio_slot_occupied",
    }:
        return "portfolio_slot_occupied"
    if code in {
        "portfolio_allocation_mismatch",
        "portfolio_binding_mismatch",
    }:
        return "portfolio_allocation_mismatch"
    if code == "selection_target_mismatch":
        return "out_of_scope"
    return "outcome_admission_state_invalid"


def _target_is_in_selected_scope(target_path: str, allowed_scope: list[str]) -> bool:
    """Require a pre-write target to remain inside the selected outcome contract."""

    for candidate in allowed_scope:
        if candidate.endswith("/"):
            if target_path.startswith(candidate) and target_path != candidate:
                return True
        elif target_path == candidate:
            return True
    return False


def _continuation_state(
    resolved: ResolvedOutcomeSelectionV1,
) -> tuple[ContinuationState, str]:
    """Translate the exact current continuation owner result into policy state."""

    evaluated = evaluate_scenario(resolved.effective_scenario)
    reason = evaluated.decision.reason_code
    if evaluated.decision.allowed:
        if reason == "active_in_scope":
            return "active_in_scope", reason
        if reason == "bounded_recovery_allowed":
            return "bounded_recovery_active", reason
        raise ValueError(f"unsupported allowed continuation reason: {reason}")
    if reason == "out_of_scope":
        return "out_of_scope", reason
    if reason == "outcome_stalled":
        return "stalled", reason
    if reason in {"outcome_complete", "outcome_parked"}:
        return "terminal", reason
    if reason == "recovery_required" or reason.startswith("recovery_"):
        return "recovery_required", reason
    raise ValueError(f"unsupported denied continuation reason: {reason}")


def evaluate_selected_outcome_admission(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    claim_source_file: str,
    boundary: OperationBoundary,
    ordinary_allowed: bool,
    renewal: bool,
    target_path: str | None = None,
) -> OutcomeAdmissionResultV1:
    """Derive and decide exact selected admission without trusting state labels."""

    if boundary in SAFE_BOUNDARIES or boundary == "portfolio_allocate":
        raise ValueError("selected admission requires a mutation or renewal boundary")
    if not ordinary_allowed:
        request = OutcomeAdmissionRequestV1(
            boundary=boundary,
            enforcement_scope="new_or_renewed",
            ordinary_allowed=False,
            portfolio_state="missing",
            continuation_state="missing",
        )
        return OutcomeAdmissionResultV1(
            source="selected",
            request=request,
            decision=decide_outcome_admission(request),
        )

    try:
        resolved = resolve_selected_outcome_for_session(
            agent=agent,
            project=project,
            scope=scope,
            session_id=session_id,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            claim_source_file=claim_source_file,
        )
    except OutcomeSelectionError as exc:
        return OutcomeAdmissionResultV1(
            source="selected",
            request=None,
            decision=OutcomeAdmissionDecisionV1(
                disposition="deny",
                reason_code=_selection_error_reason(exc.code),
            ),
            resolution_error_code=exc.code,
            resolution_error_message=str(exc),
        )

    if target_path is not None and not _target_is_in_selected_scope(
        target_path,
        resolved.effective_scenario.contract.allowed_scope,
    ):
        return OutcomeAdmissionResultV1(
            source="selected",
            request=None,
            decision=OutcomeAdmissionDecisionV1(
                disposition="deny",
                reason_code="out_of_scope",
            ),
            resolution_error_code="selection_target_mismatch",
            resolution_error_message=("ordinary pre-write target is outside the selected outcome allowed_scope"),
        )

    try:
        continuation_state, continuation_reason = _continuation_state(resolved)
    except ValueError as exc:
        return OutcomeAdmissionResultV1(
            source="selected",
            request=None,
            decision=OutcomeAdmissionDecisionV1(
                disposition="deny",
                reason_code="outcome_admission_state_invalid",
            ),
            resolution_error_code="continuation_state_unsupported",
            resolution_error_message=str(exc),
        )

    is_classed = resolved.binding.schema_version == "1.1.0"
    renewal_required = renewal or boundary in RENEWAL_BOUNDARIES
    enforcement_scope: EnforcementScope = "new_or_renewed" if is_classed or renewal_required else "grandfathered"
    request = OutcomeAdmissionRequestV1(
        boundary=boundary,
        enforcement_scope=enforcement_scope,
        ordinary_allowed=True,
        portfolio_state="active_exact" if is_classed else "not_applicable",
        continuation_state=continuation_state,
    )
    evidence = SelectedOutcomeAdmissionEvidenceV1(
        agent=agent,
        project=project,
        scope=scope,
        session_id=session_id,
        claim_source_file=str(Path(claim_source_file).expanduser().resolve()),
        selection_binding_sha256=resolved.binding_sha256,
        selection_schema_version=resolved.binding.schema_version,
        portfolio_allocation_id=resolved.binding.portfolio_allocation_id,
        portfolio_allocation_sha256=resolved.binding.portfolio_allocation_sha256,
        portfolio_ledger_path=resolved.binding.portfolio_ledger_path,
        base_scenario_sha256=resolved.base_scenario_sha256,
        effective_scenario_sha256=resolved.effective_scenario_sha256,
        current_lease_sha256=resolved.current_lease_sha256,
        current_lease_state=resolved.current_lease_state,
        continuation_reason_code=continuation_reason,
        progress_transition_count=resolved.progress_transition_count,
    )
    return OutcomeAdmissionResultV1(
        source="selected",
        request=request,
        decision=decide_outcome_admission(request),
        selected_evidence=evidence,
    )


def evaluate_selected_claim_admission(
    claim: coordination_claims.ClaimRecord,
    *,
    boundary: OperationBoundary,
    ordinary_allowed: bool = True,
    renewal: bool,
    target_path: str | None = None,
) -> OutcomeAdmissionResultV1:
    """Evaluate one normalized exact claim through selected admission."""

    required = {
        "project": claim.primary_project(),
        "session_id": claim.session_id,
        "repo_root": claim.repo_root,
        "worktree_path": claim.worktree_path,
        "branch": claim.branch,
        "claim_source_file": claim.source_file,
    }
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        message = "exact claim lacks selected-admission identity: " + ", ".join(missing)
        return OutcomeAdmissionResultV1(
            source="selected",
            request=None,
            decision=OutcomeAdmissionDecisionV1(
                disposition="deny",
                reason_code="outcome_admission_state_invalid",
            ),
            resolution_error_code="claim_identity_incomplete",
            resolution_error_message=message,
        )
    return evaluate_selected_outcome_admission(
        agent=claim.agent,
        project=str(required["project"]),
        scope=claim.scope,
        session_id=str(required["session_id"]),
        repo_root=str(required["repo_root"]),
        worktree_path=str(required["worktree_path"]),
        branch=str(required["branch"]),
        claim_source_file=str(required["claim_source_file"]),
        boundary=boundary,
        ordinary_allowed=ordinary_allowed,
        renewal=renewal,
        target_path=target_path,
    )


def _selection_pending_failure(code: str, message: str) -> SelectionPendingActivationResultV1:
    """Return one fail-closed staged-activation result."""

    return SelectionPendingActivationResultV1(
        disposition="deny",
        reason_code="outcome_admission_state_invalid",
        resolution_error_code=code,
        resolution_error_message=message,
    )


def evaluate_selection_pending_session_activation(
    claim: coordination_claims.ClaimRecord,
) -> SelectionPendingActivationResultV1:
    """Validate one exact pre-tracker v4/v5/v6 reservation without selecting an outcome.

    This is intentionally narrower than selected admission. It can justify
    only the first tracker write at ``session_start``; every later protected
    boundary continues through the selected-outcome resolver.
    """

    project = claim.primary_project()
    goal_authority = coordination_claims.is_goal_authority_ref(claim.plan_ref)
    plan_authority = coordination_claims.requires_work_graph(claim.plan_ref)
    required = {
        "project": project,
        "session_id": claim.session_id,
        "repo_root": claim.repo_root,
        "worktree_path": claim.worktree_path,
        "branch": claim.branch,
        "claim_source_file": claim.source_file,
        "plan_ref": claim.plan_ref,
    }
    if plan_authority:
        required.update(
            {
                "work_unit_id": claim.work_unit_id,
                "work_graph_path": claim.work_graph_path,
                "work_graph_sha256": claim.work_graph_sha256,
                "start_revision": claim.start_revision,
            }
        )
    missing = sorted(name for name, value in required.items() if not value)
    if missing:
        return _selection_pending_failure(
            "selection_pending_identity_incomplete",
            "staged reservation lacks required identity: " + ", ".join(missing),
        )
    if claim.schema_version not in {4, 5, 6}:
        return _selection_pending_failure(
            "selection_pending_claim_version_invalid",
            "staged session activation requires an exact schema-v4, schema-v5, or schema-v6 claim",
        )
    if claim.claim_type != "write" or not claim.write_paths:
        return _selection_pending_failure(
            "selection_pending_write_scope_missing",
            "staged session activation requires bounded write ownership",
        )
    if claim.tracker_path is not None:
        return _selection_pending_failure(
            "selection_pending_tracker_already_linked",
            "staged session activation is valid only before the first tracker is linked",
        )
    if not goal_authority and not plan_authority:
        return _selection_pending_failure(
            "selection_pending_plan_authority_invalid",
            "staged session activation requires exact goal or numbered-plan authority",
        )
    graph_fields = (claim.work_unit_id, claim.work_graph_path, claim.work_graph_sha256)
    if goal_authority and any(value is not None for value in graph_fields):
        return _selection_pending_failure(
            "selection_pending_goal_authority_mixed",
            "goal staged activation cannot mix in numbered-plan work-unit identity",
        )
    if plan_authority and re.fullmatch(r"[0-9a-f]{40}", str(claim.start_revision)) is None:
        return _selection_pending_failure(
            "selection_pending_start_revision_invalid",
            "staged session activation requires one bare 40-hex Git commit",
        )

    source_path = Path(str(claim.source_file)).expanduser().resolve()
    try:
        payload = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        return _selection_pending_failure(
            "selection_pending_claim_source_unavailable",
            f"unable to resolve exact staged claim source: {exc}",
        )
    current = (
        coordination_claims.normalize_claim(payload, source_file=str(source_path))
        if isinstance(payload, dict)
        else None
    )
    if current is None or current != claim:
        return _selection_pending_failure(
            "selection_pending_claim_source_changed",
            "staged claim source no longer matches the evaluated reservation",
        )
    active_claims = coordination_claims.check_claims(
        str(project),
        claims_dir=source_path.parent,
    )
    if current not in active_claims:
        return _selection_pending_failure(
            "selection_pending_claim_not_live",
            "staged claim source is not an active live reservation",
        )
    health_issues = coordination_claims.coordination_health_issues(
        current,
        active_claims=active_claims,
    )
    if health_issues != ["missing_tracker_path"]:
        return _selection_pending_failure(
            "selection_pending_claim_invariants_invalid",
            "staged claim must be healthy except for its absent tracker: "
            + (", ".join(health_issues) if health_issues else "no missing-tracker invariant"),
        )

    binding = None
    if plan_authority:
        assert claim.repo_root is not None
        assert claim.work_graph_path is not None
        assert claim.work_unit_id is not None
        assert claim.plan_ref is not None
        assert claim.start_revision is not None
        try:
            binding = coordination_claims.coerce_canonical_work_unit_binding(
                coordination_claims.resolve_canonical_work_unit_binding(
                    repo_root=claim.repo_root,
                    plan_ref=claim.plan_ref,
                    work_graph_path=claim.work_graph_path,
                    work_unit_id=claim.work_unit_id,
                    start_point=claim.start_revision,
                    plan_repo_root=claim.plan_repo_root,
                    plan_start_point=claim.plan_revision,
                    target_repository_id=str(project),
                )
            )
            coordination_claims.validate_start_revision_targets(
                repo_root=claim.repo_root,
                start_revision=claim.start_revision,
                branch=claim.branch,
                worktree_path=claim.worktree_path,
                require_branch=True,
                require_worktree=True,
            )
        except (OSError, TypeError, ValueError) as exc:
            return _selection_pending_failure(
                "selection_pending_binding_unresolvable",
                f"unable to resolve staged work-unit custody: {exc}",
            )
        if (
            binding.work_graph_sha256 != claim.work_graph_sha256
            or binding.approval_revisions != claim.approval_revisions
            or binding.start_revision != claim.start_revision
            or binding.plan_repo_root != claim.plan_repo_root
            or binding.plan_revision != claim.plan_revision
            or binding.plan_sha256 != claim.plan_sha256
        ):
            return _selection_pending_failure(
                "selection_pending_binding_mismatch",
                "staged work-unit evidence does not match the exact claim binding",
            )

    evidence = SelectionPendingActivationEvidenceV1(
        agent=claim.agent,
        project=str(project),
        scope=claim.scope,
        session_id=str(claim.session_id),
        claim_source_file=str(source_path),
        claim_reservation_sha256=canonical_sha256(claim.to_dict()),
        claim_schema_version=claim.schema_version,
        repo_root=str(Path(claim.repo_root).expanduser().resolve()),
        worktree_path=str(Path(str(claim.worktree_path)).expanduser().resolve()),
        branch=str(claim.branch),
        authority_ref=claim.plan_ref if goal_authority else None,
        work_unit_id=claim.work_unit_id,
        work_graph_path=claim.work_graph_path,
        work_graph_sha256=binding.work_graph_sha256 if binding is not None else None,
        start_revision=claim.start_revision,
    )
    return SelectionPendingActivationResultV1(
        disposition="defer",
        reason_code="selection_pending",
        evidence=evidence,
    )


def selection_pending_activation_receipt_path(outcome_receipt_path: Path) -> Path:
    """Route staged activation away from the shared admission-v1 stream."""

    path = outcome_receipt_path.expanduser().resolve()
    if path == DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH.expanduser().resolve():
        return DEFAULT_SELECTION_PENDING_ACTIVATION_RECEIPT_PATH
    suffix = path.suffix or ".jsonl"
    return path.with_name(f"{path.stem}-selection-pending-v1{suffix}")


def build_selection_pending_activation_receipt(
    result: SelectionPendingActivationResultV1,
    *,
    observed_at: datetime | None = None,
    receipt_id: str | None = None,
) -> SelectionPendingActivationReceiptV1:
    """Build one separately framed staged-activation receipt."""

    return SelectionPendingActivationReceiptV1(
        receipt_id=receipt_id or f"spact-{uuid.uuid4().hex}",
        observed_at=observed_at or datetime.now(UTC),
        result_sha256=canonical_sha256(result),
        result=result,
    )


def append_selection_pending_activation_receipt(
    receipt: SelectionPendingActivationReceiptV1,
    *,
    receipt_path: Path,
) -> None:
    """Append one staged-activation receipt under its own sibling lock."""

    path = receipt_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    serialized = json.dumps(
        receipt.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "r+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def record_selection_pending_activation(
    result: SelectionPendingActivationResultV1,
    *,
    outcome_receipt_path: Path = DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
) -> SelectionPendingActivationReceiptV1:
    """Record staged activation without contaminating admission-v1 framing."""

    receipt = build_selection_pending_activation_receipt(result)
    append_selection_pending_activation_receipt(
        receipt,
        receipt_path=selection_pending_activation_receipt_path(outcome_receipt_path),
    )
    return receipt


def load_selection_pending_activation_receipts(
    path: Path,
) -> list[SelectionPendingActivationReceiptV1]:
    """Strictly load the separately versioned staged-activation stream."""

    records: list[SelectionPendingActivationReceiptV1] = []
    for line_number, line in enumerate(path.expanduser().read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(SelectionPendingActivationReceiptV1.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"invalid selection-pending receipt at line {line_number}: {exc}") from exc
    return records


def build_outcome_admission_receipt(
    result: OutcomeAdmissionResultV1,
    *,
    observed_at: datetime | None = None,
    receipt_id: str | None = None,
) -> OutcomeAdmissionReceiptV1:
    """Build one digest-bound receipt without writing it."""

    return OutcomeAdmissionReceiptV1(
        receipt_id=receipt_id or f"oadm-{uuid.uuid4().hex}",
        observed_at=observed_at or datetime.now(UTC),
        result_sha256=canonical_sha256(result),
        result=result,
    )


def append_outcome_admission_receipt(
    receipt: OutcomeAdmissionReceiptV1,
    *,
    receipt_path: Path = DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
) -> None:
    """Append one canonical JSON receipt under a sibling file lock."""

    path = receipt_path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    serialized = json.dumps(
        receipt.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    with os.fdopen(lock_fd, "r+", encoding="utf-8") as lock_handle:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(serialized + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def record_outcome_admission(
    result: OutcomeAdmissionResultV1,
    *,
    receipt_path: Path = DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH,
) -> OutcomeAdmissionReceiptV1:
    """Build and append one admission receipt before protected continuation."""

    receipt = build_outcome_admission_receipt(result)
    append_outcome_admission_receipt(receipt, receipt_path=receipt_path)
    return receipt


def load_outcome_admission_receipts(path: Path) -> list[OutcomeAdmissionReceiptV1]:
    """Strictly load an append-only admission receipt stream."""

    records: list[OutcomeAdmissionReceiptV1] = []
    for line_number, line in enumerate(path.expanduser().read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(OutcomeAdmissionReceiptV1.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(f"invalid outcome-admission receipt at line {line_number}: {exc}") from exc
    return records


__all__ = [
    "DEFAULT_OUTCOME_ADMISSION_RECEIPT_PATH",
    "DEFAULT_SELECTION_PENDING_ACTIVATION_RECEIPT_PATH",
    "RENEWAL_BOUNDARIES",
    "SAFE_BOUNDARIES",
    "AdmissionDisposition",
    "ContinuationState",
    "EnforcementScope",
    "OperationBoundary",
    "OutcomeAdmissionBootstrapResultV1",
    "OutcomeAdmissionBootstrapV1",
    "OutcomeAdmissionDecisionV1",
    "OutcomeAdmissionMode",
    "OutcomeAdmissionReceiptV1",
    "OutcomeAdmissionRequestV1",
    "OutcomeAdmissionResultV1",
    "PortfolioState",
    "SelectedOutcomeAdmissionEvidenceV1",
    "SelectionPendingActivationEvidenceV1",
    "SelectionPendingActivationReceiptV1",
    "SelectionPendingActivationResultV1",
    "append_outcome_admission_receipt",
    "append_selection_pending_activation_receipt",
    "bootstrap_admission_result",
    "build_outcome_admission_receipt",
    "build_selection_pending_activation_receipt",
    "decide_outcome_admission",
    "evaluate_claim_bootstrap_admission",
    "evaluate_first_consumer_bootstrap",
    "evaluate_selected_claim_admission",
    "evaluate_selected_outcome_admission",
    "evaluate_selection_pending_session_activation",
    "has_sanctioned_delegated_maintenance_claim_identity",
    "has_sanctioned_maintenance_claim_identity",
    "infer_first_consumer_bootstrap_plan",
    "is_first_consumer_bootstrap_path",
    "is_sanctioned_delegated_maintenance_claim",
    "is_sanctioned_delegated_maintenance_claim_payload",
    "is_sanctioned_maintenance_claim",
    "is_sanctioned_maintenance_claim_payload",
    "load_outcome_admission_mode",
    "load_outcome_admission_receipts",
    "load_selection_pending_activation_receipts",
    "record_outcome_admission",
    "record_selection_pending_activation",
    "selection_pending_activation_receipt_path",
]
