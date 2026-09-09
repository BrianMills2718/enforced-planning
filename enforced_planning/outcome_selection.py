"""Bind one exact claimed session to one immutable outcome scenario.

Plan 117 stores selection in the existing claim-linked session tracker.  It is
manual and observe-only: selecting a scenario never grants write authority and
resolving it never changes the ordinary pre-write decision.
"""

from __future__ import annotations

import copy
import hashlib
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning import coordination_claims, session_contracts
from enforced_planning.outcome_continuation import (
    ContinuationError,
    OutcomeContinuationResultV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeLeaseV1,
    OutcomeProgressReceiptV1,
    RestartDeltaV1,
    canonical_sha256,
    evaluate_scenario,
    transition_lease,
)
from enforced_planning.outcome_portfolio import (
    DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH,
    OutcomePortfolioError,
    ResolvedOutcomePortfolioAllocationV1,
    require_active_portfolio_allocation,
)
from enforced_planning.plan_validation import (
    PlanningIntegrityError,
    validate_plan_integrity_at_revision,
)

HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"
UNPLANNED_PLAN_REF = session_contracts.UNPLANNED_PLAN_REF


class OutcomeSelectionError(RuntimeError):
    """Fail-loud selection error with one stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class StrictModel(BaseModel):
    """Strict frozen-compatible base for session selection records."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomeSelectionBindingV1(StrictModel):
    """Create-once outcome choice bound to one stable exact claim identity."""

    schema_version: Literal["1.0.0", "1.1.0"] = "1.0.0"
    record_type: Literal["outcome_selection_binding"] = "outcome_selection_binding"
    selected_at: datetime
    observe_only: Literal[True] = True
    execution_authority_ref: str = Field(min_length=3)
    claim_plan_ref: str | None = None
    agent: str = Field(min_length=1)
    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    session_id: str = Field(min_length=3)
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    tracker_path: str = Field(min_length=1)
    claim_source_file: str = Field(min_length=1)
    claim_identity_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_ref: str = Field(min_length=1)
    scenario_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_id: str = Field(min_length=3)
    scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_id: str = Field(min_length=3)
    outcome_lineage_id: str = Field(min_length=3)
    predecessor_lineage_ids: tuple[str, ...]
    target_path: str = Field(min_length=1)
    lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    lease_state: Literal["active", "recovery_required", "stalled", "complete", "parked"]
    outcome_allowed_at_selection: bool
    outcome_reason_code_at_selection: str = Field(min_length=3)
    portfolio_allocation_id: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    portfolio_allocation_sha256: str | None = Field(
        default=None,
        pattern=HEX_SHA256_PATTERN,
        exclude_if=lambda value: value is None,
    )
    portfolio_ledger_path: str | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @model_validator(mode="after")
    def validate_binding(self) -> OutcomeSelectionBindingV1:
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() is None:
            raise ValueError("selected_at must be timezone-aware")
        expected_goal = f"goal:{self.outcome_id}"
        if self.execution_authority_ref.startswith("goal:") and self.execution_authority_ref != expected_goal:
            raise ValueError("goal authority must equal goal:<outcome-id>")
        allocation_fields = (
            self.portfolio_allocation_id,
            self.portfolio_allocation_sha256,
            self.portfolio_ledger_path,
        )
        if self.schema_version == "1.0.0" and any(
            value is not None for value in allocation_fields
        ):
            raise ValueError("schema 1.0.0 selections cannot bind portfolio allocation")
        if self.schema_version == "1.1.0" and not all(
            value is not None for value in allocation_fields
        ):
            raise ValueError("schema 1.1.0 selections require complete portfolio allocation")
        return self


class OutcomeSelectionResultV1(StrictModel):
    """Operator-facing result for a selected or idempotently replayed choice."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["selected", "idempotent"]
    binding: OutcomeSelectionBindingV1
    binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    tracker_path: str = Field(min_length=1)


class OutcomeProgressTransitionV1(StrictModel):
    """Append-only exact receipt and lease transition for selected state."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_progress_transition"] = "outcome_progress_transition"
    recorded_at: datetime
    receipt_ref: str = Field(min_length=1)
    receipt_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    receipt_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    receipt: OutcomeProgressReceiptV1
    selection_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    selection_binding: OutcomeSelectionBindingV1
    prior_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    prior_lease: OutcomeLeaseV1
    successor_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    successor_lease: OutcomeLeaseV1

    @model_validator(mode="after")
    def validate_transition(self) -> OutcomeProgressTransitionV1:
        if self.recorded_at.tzinfo is None or self.recorded_at.utcoffset() is None:
            raise ValueError("recorded_at must be timezone-aware")
        checks = {
            "receipt_sha256": (canonical_sha256(self.receipt), self.receipt_sha256),
            "selection_binding_sha256": (
                canonical_sha256(self.selection_binding),
                self.selection_binding_sha256,
            ),
            "prior_lease_sha256": (canonical_sha256(self.prior_lease), self.prior_lease_sha256),
            "successor_lease_sha256": (
                canonical_sha256(self.successor_lease),
                self.successor_lease_sha256,
            ),
        }
        mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
        if mismatches:
            raise ValueError("progress transition digest mismatch: " + ", ".join(mismatches))
        contract_digests = {
            self.selection_binding.outcome_contract_sha256,
            self.receipt.outcome_contract_sha256,
            self.prior_lease.outcome_contract_sha256,
            self.successor_lease.outcome_contract_sha256,
        }
        if len(contract_digests) != 1:
            raise ValueError("progress transition contract digests must match")
        if self.receipt.prior_receipt_sha256 != self.prior_lease.last_receipt_sha256:
            raise ValueError("progress receipt parent must equal the retained prior lease head")
        if self.successor_lease.last_receipt_sha256 != self.receipt_sha256:
            raise ValueError("successor lease must end at the retained progress receipt")
        return self


class OutcomeProgressResultV1(StrictModel):
    """Operator-facing accepted or idempotently replayed progress append."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["recorded", "idempotent"]
    binding: OutcomeSelectionBindingV1
    binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    transition: OutcomeProgressTransitionV1
    transition_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    progress_transition_count: int = Field(ge=1)
    tracker_path: str = Field(min_length=1)


class ResolvedOutcomeSelectionV1(StrictModel):
    """Validated selected state ready for one exact pre-write correlation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    binding: OutcomeSelectionBindingV1
    binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_path: str = Field(min_length=1)
    base_scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    effective_scenario: OutcomeContinuationScenarioV1
    effective_scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    current_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    current_lease_state: Literal["active", "recovery_required", "stalled", "complete", "parked"]
    progress_transition_count: int = Field(ge=0)
    progress_head_transition_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    progress_head_receipt_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)

    @model_validator(mode="after")
    def validate_current_head(self) -> ResolvedOutcomeSelectionV1:
        if canonical_sha256(self.effective_scenario) != self.effective_scenario_sha256:
            raise ValueError("effective scenario digest does not match its payload")
        result = evaluate_scenario(self.effective_scenario)
        if result.lease_sha256 != self.current_lease_sha256:
            raise ValueError("current lease digest does not match the effective scenario")
        if result.lease.state != self.current_lease_state:
            raise ValueError("current lease state does not match the effective scenario")
        head_fields = (
            self.progress_head_transition_sha256,
            self.progress_head_receipt_sha256,
        )
        if self.progress_transition_count == 0 and any(value is not None for value in head_fields):
            raise ValueError("zero progress transitions cannot retain a progress head")
        if self.progress_transition_count > 0 and not all(value is not None for value in head_fields):
            raise ValueError("nonzero progress transitions require complete progress-head digests")
        return self


class OutcomeSessionTransferV1(StrictModel):
    """Append-only receipt for a sanctioned exact-runtime handoff."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_session_transfer"] = "outcome_session_transfer"
    transferred_at: datetime
    reason: Literal["session_resume"] = "session_resume"
    prior_session_id: str = Field(min_length=3)
    successor_session_id: str = Field(min_length=3)
    prior_claim_identity_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    successor_claim_identity_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    prior_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    successor_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_id: str = Field(min_length=3)
    outcome_lineage_id: str = Field(min_length=3)
    target_path: str = Field(min_length=1)
    progress_transition_count: int = Field(default=0, ge=0)
    progress_head_transition_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    current_lease_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    current_lease_state: Literal["active", "recovery_required", "stalled", "complete", "parked"] | None = None

    @model_validator(mode="after")
    def validate_transfer(self) -> OutcomeSessionTransferV1:
        if self.transferred_at.tzinfo is None or self.transferred_at.utcoffset() is None:
            raise ValueError("transferred_at must be timezone-aware")
        if self.prior_session_id == self.successor_session_id:
            raise ValueError("session transfer requires distinct runtime identities")
        if self.prior_claim_identity_sha256 == self.successor_claim_identity_sha256:
            raise ValueError("session transfer must change the exact claim identity digest")
        if self.progress_transition_count == 0 and self.progress_head_transition_sha256 is not None:
            raise ValueError("zero progress transitions cannot retain a progress head")
        if self.progress_transition_count > 0 and self.progress_head_transition_sha256 is None:
            raise ValueError("retained progress transitions require a progress head")
        if (self.current_lease_sha256 is None) != (self.current_lease_state is None):
            raise ValueError("current lease digest and state must be complete or absent")
        return self


class OutcomeRestartTransitionV1(StrictModel):
    """Append-only retained predecessor and successor state for one restart."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_restart_transition"] = "outcome_restart_transition"
    restarted_at: datetime
    restart_delta_ref: str = Field(min_length=1)
    restart_delta_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    restart_delta_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    restart_delta: RestartDeltaV1
    predecessor_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    predecessor_binding: OutcomeSelectionBindingV1
    predecessor_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    predecessor_contract: OutcomeContractV1
    predecessor_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    predecessor_lease: OutcomeLeaseV1
    predecessor_failed_evidence_refs: tuple[str, ...]
    successor_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    successor_binding: OutcomeSelectionBindingV1

    @model_validator(mode="after")
    def validate_transition_bindings(self) -> OutcomeRestartTransitionV1:
        if self.restarted_at.tzinfo is None or self.restarted_at.utcoffset() is None:
            raise ValueError("restarted_at must be timezone-aware")
        checks = {
            "restart_delta_sha256": (canonical_sha256(self.restart_delta), self.restart_delta_sha256),
            "predecessor_binding_sha256": (
                canonical_sha256(self.predecessor_binding),
                self.predecessor_binding_sha256,
            ),
            "predecessor_contract_sha256": (
                canonical_sha256(self.predecessor_contract),
                self.predecessor_contract_sha256,
            ),
            "predecessor_lease_sha256": (
                canonical_sha256(self.predecessor_lease),
                self.predecessor_lease_sha256,
            ),
            "successor_binding_sha256": (
                canonical_sha256(self.successor_binding),
                self.successor_binding_sha256,
            ),
        }
        mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
        if mismatches:
            raise ValueError("restart transition digest mismatch: " + ", ".join(mismatches))
        if tuple(self.restart_delta.predecessor_failed_evidence_refs) != self.predecessor_failed_evidence_refs:
            raise ValueError("restart transition failed evidence differs from RestartDeltaV1")
        return self


class OutcomeRestartResultV1(StrictModel):
    """Operator-facing accepted or idempotently replayed causal restart."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["restarted", "idempotent"]
    binding: OutcomeSelectionBindingV1
    binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    transition: OutcomeRestartTransitionV1
    transition_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    tracker_path: str = Field(min_length=1)


@dataclass(frozen=True)
class PreparedOutcomeSessionTransfer:
    """Validated in-memory tracker mutation prepared before claim ownership changes."""

    tracker_path: Path
    tracker_payload_sha256: str
    predecessor_binding: OutcomeSelectionBindingV1
    successor_binding: OutcomeSelectionBindingV1
    transfer: OutcomeSessionTransferV1


@dataclass(frozen=True)
class ResolvedOutcomeProgressHead:
    """Validated in-memory current head for one selected binding lineage."""

    base_scenario: OutcomeContinuationScenarioV1
    effective_scenario: OutcomeContinuationScenarioV1
    result: OutcomeContinuationResultV1
    transitions: tuple[OutcomeProgressTransitionV1, ...]
    head_transition_sha256: str | None


def _load_claim_records(claims_dir: Path) -> list[coordination_claims.ClaimRecord]:
    """Load live-claim candidates without coupling them to terminal residue.

    Outcome selection only consumes live claims. A legacy completed record may
    predate fields required by the current normalizer, and must not make an
    unrelated live claim unavailable. Live or status-ambiguous malformed
    records still fail closed.
    """

    records: list[coordination_claims.ClaimRecord] = []
    if not claims_dir.is_dir():
        return records
    for path in sorted(claims_dir.glob("*.yaml")):
        try:
            payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise OutcomeSelectionError(
                "claim_registry_invalid",
                f"unable to read canonical claim {path}: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise OutcomeSelectionError(
                "claim_registry_invalid",
                f"canonical claim {path} must be a YAML mapping",
            )
        if payload.get("status") in coordination_claims.COMPLETED_STATUSES:
            continue
        record = coordination_claims.normalize_claim(payload, source_file=str(path.resolve()))
        if record is None:
            raise OutcomeSelectionError(
                "claim_registry_invalid",
                f"canonical claim {path} cannot be normalized",
            )
        records.append(record)
    return records


def _exact_live_claim(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    claims_dir: Path,
) -> coordination_claims.ClaimRecord:
    claims = _load_claim_records(claims_dir)
    live = [claim for claim in claims if claim.is_live()]
    matches = [
        claim
        for claim in live
        if claim.agent == agent
        and claim.primary_project() == project
        and claim.scope == scope
        and claim.session_id == session_id
    ]
    if len(matches) != 1:
        raise OutcomeSelectionError(
            "exact_claim_unavailable",
            f"expected exactly one live claim for {agent}:{project}:{scope}:{session_id}; found {len(matches)}",
        )
    claim = matches[0]
    issues = coordination_claims.coordination_health_issues(claim, active_claims=live)
    if issues:
        raise OutcomeSelectionError(
            "claim_not_healthy",
            "exact live claim is not healthy: " + ", ".join(issues),
        )
    return claim


def _claim_from_source(path: Path) -> coordination_claims.ClaimRecord:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise OutcomeSelectionError(
            "claim_source_unavailable",
            f"unable to read exact claim source {path}: {exc}",
        ) from exc
    if not isinstance(payload, dict):
        raise OutcomeSelectionError(
            "claim_source_invalid",
            f"exact claim source {path} must be a YAML mapping",
        )
    claim = coordination_claims.normalize_claim(payload, source_file=str(path.resolve()))
    if claim is None:
        raise OutcomeSelectionError(
            "claim_source_invalid",
            f"exact claim source {path} cannot be normalized",
        )
    if not claim.is_live():
        raise OutcomeSelectionError(
            "claim_not_live",
            "selected outcome requires the exact claim source to remain live",
        )
    return claim


def _normalized_path(value: str) -> str:
    return str(Path(value).expanduser().resolve())


def _claim_identity_payload(claim: coordination_claims.ClaimRecord) -> dict[str, Any]:
    source_file = claim.source_file or ""
    tracker_path = claim.tracker_path or ""
    return {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "repo_root": _normalized_path(claim.repo_root or ""),
        "worktree_path": _normalized_path(claim.worktree_path or ""),
        "branch": claim.branch,
        "tracker_path": _normalized_path(tracker_path),
        "claim_source_file": _normalized_path(source_file),
        "claim_plan_ref": claim.plan_ref,
    }


def _claim_identity_sha256(claim: coordination_claims.ClaimRecord) -> str:
    return canonical_sha256(_claim_identity_payload(claim))


def _expected_tracker_plan_ref(claim: coordination_claims.ClaimRecord) -> str:
    return claim.plan_ref or UNPLANNED_PLAN_REF


def _validate_tracker_claim(
    payload: dict[str, Any],
    *,
    claim: coordination_claims.ClaimRecord,
    tracker_path: Path,
) -> dict[str, Any]:
    tracker_claim = payload.get("claim")
    tracker = payload.get("tracker")
    if not isinstance(tracker_claim, dict) or not isinstance(tracker, dict):
        raise OutcomeSelectionError(
            "tracker_invalid",
            f"session tracker {tracker_path} requires claim and tracker mappings",
        )
    expected = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "repo_root": _normalized_path(claim.repo_root or ""),
        "worktree_path": _normalized_path(claim.worktree_path or ""),
        "branch": claim.branch,
        "tracker_path": _normalized_path(claim.tracker_path or ""),
        "plan_ref": _expected_tracker_plan_ref(claim),
    }
    actual = {
        "agent": tracker_claim.get("agent"),
        "project": tracker_claim.get("project"),
        "scope": tracker_claim.get("scope"),
        "session_id": tracker_claim.get("session_id"),
        "repo_root": _normalized_path(str(tracker_claim.get("repo_root") or "")),
        "worktree_path": _normalized_path(str(tracker_claim.get("worktree_path") or "")),
        "branch": tracker_claim.get("branch"),
        "tracker_path": _normalized_path(str(tracker_claim.get("tracker_path") or "")),
        "plan_ref": tracker_claim.get("plan_ref"),
    }
    mismatches = [name for name, value in expected.items() if actual.get(name) != value]
    if mismatches:
        raise OutcomeSelectionError(
            "tracker_claim_mismatch",
            "session tracker does not match the exact live claim: " + ", ".join(mismatches),
        )
    return tracker


def _load_scenario_for_claim(
    scenario_path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
) -> tuple[OutcomeContinuationScenarioV1, str, str]:
    resolved = scenario_path.expanduser().resolve()
    worktree = Path(claim.worktree_path or "").expanduser().resolve()
    try:
        scenario_ref = resolved.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise OutcomeSelectionError(
            "scenario_outside_worktree",
            "selected outcome scenario must be inside the exact claim worktree",
        ) from exc
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OutcomeSelectionError(
            "scenario_unavailable",
            f"unable to read selected scenario {scenario_ref}: {exc}",
        ) from exc
    try:
        scenario = OutcomeContinuationScenarioV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "scenario_invalid",
            f"selected scenario is invalid: {exc}",
        ) from exc
    if scenario.contract.project_id != claim.primary_project():
        raise OutcomeSelectionError(
            "project_mismatch",
            "selected scenario project does not equal the exact claim project",
        )
    if scenario.request.operation != "product_write":
        raise OutcomeSelectionError(
            "unsupported_outcome_operation",
            "selected pre-write outcome requires a product_write request",
        )
    return scenario, hashlib.sha256(content).hexdigest(), scenario_ref


def _execution_authority(
    requested: str,
    *,
    claim: coordination_claims.ClaimRecord,
    scenario: OutcomeContinuationScenarioV1,
) -> str:
    authority = requested.strip()
    if not authority:
        raise OutcomeSelectionError("authority_invalid", "execution authority is required")
    if authority.startswith("goal:"):
        if not coordination_claims.is_goal_authority_ref(authority):
            raise OutcomeSelectionError(
                "authority_invalid",
                "goal authority must use exact goal:<portable-id> syntax",
            )
        expected = f"goal:{scenario.contract.outcome_id}"
        if authority != expected:
            raise OutcomeSelectionError(
                "authority_outcome_mismatch",
                f"goal authority must equal {expected}",
            )
        if claim.plan_ref not in {None, UNPLANNED_PLAN_REF, authority}:
            raise OutcomeSelectionError(
                "authority_claim_mismatch",
                "goal authority conflicts with the canonical claim authority",
            )
        return authority
    if coordination_claims.normalize_plan_identity(authority) is None:
        raise OutcomeSelectionError(
            "authority_invalid",
            "execution authority must be an exact goal:<outcome-id> or numbered plan ref",
        )
    if authority != claim.plan_ref:
        raise OutcomeSelectionError(
            "authority_claim_mismatch",
            "planned execution authority must exactly equal the canonical claim plan_ref",
        )
    return authority


def _validate_planned_outcome_baseline(
    *,
    authority: str,
    claim: coordination_claims.ClaimRecord,
    scenario: OutcomeContinuationScenarioV1,
) -> None:
    """Revalidate a planned selection at its immutable outcome baseline."""

    normalized = coordination_claims.normalize_plan_identity(authority)
    if normalized is None:
        return
    qualified_project, _, raw_plan_number = normalized.rpartition("#")
    plan_number = int(raw_plan_number)
    repository_id = claim.primary_project() or ""
    if qualified_project != "Plan ":
        expected_project = repository_id.lower().replace("_", "-")
        if qualified_project != expected_project:
            raise OutcomeSelectionError(
                "plan_identity_mismatch",
                "qualified plan repository does not equal the exact claim project",
            )
    if not claim.repo_root:
        raise OutcomeSelectionError(
            "plan_integrity_unavailable",
            "planned selection requires the exact claim repository root",
        )
    baseline_revision = scenario.contract.baseline_revision
    try:
        integrity = validate_plan_integrity_at_revision(
            repo_root=claim.repo_root,
            repository_id=repository_id,
            plan_number=plan_number,
            start_point=baseline_revision,
        )
    except PlanningIntegrityError as exc:
        raise OutcomeSelectionError(
            "plan_integrity_unavailable",
            f"unable to validate {authority} at outcome baseline {baseline_revision}: {exc}",
        ) from exc
    if integrity.mode != "enforce":
        return
    if integrity.source_revision != baseline_revision:
        raise OutcomeSelectionError(
            "baseline_revision_not_immutable",
            "enforced planned selection requires one full immutable Git commit baseline",
        )
    if integrity.disposition == "fail":
        finding_codes = ", ".join(item.code for item in integrity.findings)
        raise OutcomeSelectionError(
            "plan_integrity_rejected",
            f"Planning Integrity rejected {authority} at {baseline_revision}: {finding_codes}",
        )


def _portfolio_allocation_for_scenario(
    scenario: OutcomeContinuationScenarioV1,
    *,
    ledger_path: Path,
) -> ResolvedOutcomePortfolioAllocationV1 | None:
    try:
        return require_active_portfolio_allocation(
            scenario,
            ledger_path=ledger_path,
        )
    except OutcomePortfolioError as exc:
        raise OutcomeSelectionError(exc.code, str(exc)) from exc


def _assert_binding_portfolio_allocation(
    binding: OutcomeSelectionBindingV1,
    *,
    scenario: OutcomeContinuationScenarioV1,
) -> None:
    """Reopen the exact active allocation retained by a classed binding."""

    if scenario.contract.schema_version == "1.0.0":
        if binding.schema_version != "1.0.0":
            raise OutcomeSelectionError(
                "portfolio_binding_mismatch",
                "legacy scenario cannot carry a classed selection binding",
            )
        return
    if binding.schema_version != "1.1.0" or binding.portfolio_ledger_path is None:
        raise OutcomeSelectionError(
            "portfolio_binding_mismatch",
            "classed scenario requires a complete portfolio selection binding",
        )
    resolved = _portfolio_allocation_for_scenario(
        scenario,
        ledger_path=Path(binding.portfolio_ledger_path),
    )
    if resolved is None:
        raise OutcomeSelectionError(
            "portfolio_binding_mismatch",
            "classed scenario resolved without a portfolio allocation",
        )
    checks = {
        "portfolio_allocation_id": (
            resolved.allocation.allocation_id,
            binding.portfolio_allocation_id,
        ),
        "portfolio_allocation_sha256": (
            resolved.allocation_sha256,
            binding.portfolio_allocation_sha256,
        ),
        "portfolio_ledger_path": (
            resolved.ledger_path,
            _normalized_path(binding.portfolio_ledger_path),
        ),
    }
    mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
    if mismatches:
        raise OutcomeSelectionError(
            "portfolio_binding_mismatch",
            "selected portfolio allocation changed: " + ", ".join(mismatches),
        )


def _build_binding(
    *,
    claim: coordination_claims.ClaimRecord,
    tracker_path: Path,
    authority: str,
    scenario: OutcomeContinuationScenarioV1,
    scenario_ref: str,
    scenario_file_sha256: str,
    portfolio_ledger_path: Path,
) -> OutcomeSelectionBindingV1:
    result = evaluate_scenario(scenario)
    portfolio = _portfolio_allocation_for_scenario(
        scenario,
        ledger_path=portfolio_ledger_path,
    )
    target_path = scenario.request.target_path
    if target_path is None:
        raise OutcomeSelectionError(
            "unsupported_outcome_operation",
            "selected pre-write outcome requires a product_write target",
        )
    return OutcomeSelectionBindingV1(
        schema_version="1.1.0" if portfolio is not None else "1.0.0",
        selected_at=datetime.now(UTC),
        execution_authority_ref=authority,
        claim_plan_ref=claim.plan_ref,
        agent=claim.agent,
        project=claim.primary_project() or "",
        scope=claim.scope,
        session_id=claim.session_id or "",
        repo_root=_normalized_path(claim.repo_root or ""),
        worktree_path=_normalized_path(claim.worktree_path or ""),
        branch=claim.branch or "",
        tracker_path=str(tracker_path.resolve()),
        claim_source_file=_normalized_path(claim.source_file or ""),
        claim_identity_sha256=_claim_identity_sha256(claim),
        scenario_ref=scenario_ref,
        scenario_file_sha256=scenario_file_sha256,
        scenario_id=scenario.scenario_id,
        scenario_sha256=result.scenario_sha256,
        outcome_contract_sha256=result.outcome_contract_sha256,
        outcome_id=scenario.contract.outcome_id,
        outcome_lineage_id=scenario.contract.lineage_id,
        predecessor_lineage_ids=tuple(scenario.contract.predecessor_lineage_ids),
        target_path=target_path,
        lease_sha256=result.lease_sha256,
        lease_state=result.lease.state,
        outcome_allowed_at_selection=result.decision.allowed,
        outcome_reason_code_at_selection=result.decision.reason_code,
        portfolio_allocation_id=(
            portfolio.allocation.allocation_id if portfolio is not None else None
        ),
        portfolio_allocation_sha256=(
            portfolio.allocation_sha256 if portfolio is not None else None
        ),
        portfolio_ledger_path=(portfolio.ledger_path if portfolio is not None else None),
    )


def _assert_binding_matches_claim(
    binding: OutcomeSelectionBindingV1,
    *,
    claim: coordination_claims.ClaimRecord,
    tracker_path: Path,
) -> None:
    """Require every stored binding identity field to match its exact claim."""

    expected = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "repo_root": _normalized_path(claim.repo_root or ""),
        "worktree_path": _normalized_path(claim.worktree_path or ""),
        "branch": claim.branch,
        "tracker_path": str(tracker_path.resolve()),
        "claim_source_file": _normalized_path(claim.source_file or ""),
        "claim_plan_ref": claim.plan_ref,
        "claim_identity_sha256": _claim_identity_sha256(claim),
    }
    actual = {
        "agent": binding.agent,
        "project": binding.project,
        "scope": binding.scope,
        "session_id": binding.session_id,
        "repo_root": _normalized_path(binding.repo_root),
        "worktree_path": _normalized_path(binding.worktree_path),
        "branch": binding.branch,
        "tracker_path": _normalized_path(binding.tracker_path),
        "claim_source_file": _normalized_path(binding.claim_source_file),
        "claim_plan_ref": binding.claim_plan_ref,
        "claim_identity_sha256": binding.claim_identity_sha256,
    }
    mismatches = [name for name, value in expected.items() if actual.get(name) != value]
    if mismatches:
        raise OutcomeSelectionError(
            "selection_claim_identity_stale",
            "stored selection does not match the current exact claim identity: " + ", ".join(mismatches),
        )


def _validate_binding_scenario(
    binding: OutcomeSelectionBindingV1,
    *,
    claim: coordination_claims.ClaimRecord,
) -> OutcomeContinuationScenarioV1:
    """Reopen and evaluate the immutable scenario behind one stored binding."""

    scenario_path = Path(binding.worktree_path) / binding.scenario_ref
    scenario, file_sha256, scenario_ref = _load_scenario_for_claim(scenario_path, claim=claim)
    try:
        result = evaluate_scenario(scenario)
    except ContinuationError as exc:
        raise OutcomeSelectionError(
            "selection_evaluation_failed",
            f"selected scenario no longer evaluates: {exc}",
        ) from exc
    checks = {
        "scenario_ref": (scenario_ref, binding.scenario_ref),
        "scenario_file_sha256": (file_sha256, binding.scenario_file_sha256),
        "scenario_sha256": (result.scenario_sha256, binding.scenario_sha256),
        "outcome_contract_sha256": (
            result.outcome_contract_sha256,
            binding.outcome_contract_sha256,
        ),
        "outcome_id": (scenario.contract.outcome_id, binding.outcome_id),
        "outcome_lineage_id": (scenario.contract.lineage_id, binding.outcome_lineage_id),
        "target_path": (scenario.request.target_path, binding.target_path),
        "lease_sha256": (result.lease_sha256, binding.lease_sha256),
        "lease_state": (result.lease.state, binding.lease_state),
    }
    mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
    if mismatches:
        raise OutcomeSelectionError(
            "selection_scenario_stale",
            "selected scenario changed after selection: " + ", ".join(mismatches),
        )
    _assert_binding_portfolio_allocation(binding, scenario=scenario)
    return scenario


def _progress_history(tracker: dict[str, Any]) -> list[OutcomeProgressTransitionV1]:
    raw_history = tracker.get("outcome_progress_transitions", [])
    if not isinstance(raw_history, list):
        raise OutcomeSelectionError(
            "progress_history_invalid",
            "outcome_progress_transitions must be a list",
        )
    try:
        return [OutcomeProgressTransitionV1.model_validate(item) for item in raw_history]
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "progress_history_invalid",
            f"existing outcome progress transition is invalid: {exc}",
        ) from exc


def _session_transfer_history(tracker: dict[str, Any]) -> list[OutcomeSessionTransferV1]:
    raw_history = tracker.get("outcome_session_transfers", [])
    if not isinstance(raw_history, list):
        raise OutcomeSelectionError(
            "session_transfer_history_invalid",
            "outcome_session_transfers must be a list",
        )
    try:
        return [OutcomeSessionTransferV1.model_validate(item) for item in raw_history]
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "session_transfer_history_invalid",
            f"existing outcome session transfer is invalid: {exc}",
        ) from exc


def _binding_transfer_aliases(
    tracker: dict[str, Any],
    *,
    binding: OutcomeSelectionBindingV1,
) -> set[str]:
    """Resolve prior exact-runtime bindings sanctioned as the same selection."""

    transfers = _session_transfer_history(tracker)
    by_successor: dict[str, OutcomeSessionTransferV1] = {}
    for transfer in transfers:
        existing = by_successor.get(transfer.successor_binding_sha256)
        if existing is not None:
            raise OutcomeSelectionError(
                "session_transfer_history_invalid",
                "multiple transfer records target the same successor binding",
            )
        by_successor[transfer.successor_binding_sha256] = transfer

    aliases = {canonical_sha256(binding)}
    cursor = canonical_sha256(binding)
    invariant_fields = (
        "scenario_file_sha256",
        "scenario_sha256",
        "outcome_contract_sha256",
        "outcome_id",
        "outcome_lineage_id",
        "target_path",
    )
    while cursor in by_successor:
        transfer = by_successor[cursor]
        mismatches = [
            field
            for field in invariant_fields
            if getattr(transfer, field) != getattr(binding, field)
        ]
        if mismatches:
            raise OutcomeSelectionError(
                "session_transfer_history_invalid",
                "selected transfer changes immutable outcome fields: " + ", ".join(mismatches),
            )
        cursor = transfer.prior_binding_sha256
        if cursor in aliases:
            raise OutcomeSelectionError(
                "session_transfer_history_invalid",
                "selected transfer history contains a binding cycle",
            )
        aliases.add(cursor)
    return aliases


def _resolve_progress_head(
    tracker: dict[str, Any],
    *,
    binding: OutcomeSelectionBindingV1,
    scenario: OutcomeContinuationScenarioV1,
) -> ResolvedOutcomeProgressHead:
    """Replay accepted transitions for the current selection/transfer lineage."""

    aliases = _binding_transfer_aliases(tracker, binding=binding)
    history = _progress_history(tracker)
    base_result = evaluate_scenario(scenario)
    lease = base_result.lease
    matching: list[OutcomeProgressTransitionV1] = []
    appended_receipts: list[OutcomeProgressReceiptV1] = []
    invariant_fields = (
        "scenario_file_sha256",
        "scenario_sha256",
        "outcome_contract_sha256",
        "outcome_id",
        "outcome_lineage_id",
        "target_path",
        "lease_sha256",
    )
    for item in history:
        if item.selection_binding_sha256 not in aliases:
            continue
        mismatches = [
            field
            for field in invariant_fields
            if getattr(item.selection_binding, field) != getattr(binding, field)
        ]
        if mismatches:
            raise OutcomeSelectionError(
                "progress_history_invalid",
                "progress transition changes immutable selection fields: " + ", ".join(mismatches),
            )
        if item.prior_lease != lease:
            raise OutcomeSelectionError(
                "progress_history_invalid",
                "progress transition prior lease does not equal the reconstructed current head",
            )
        try:
            expected = transition_lease(scenario.contract, lease, item.receipt)
        except ContinuationError as exc:
            raise OutcomeSelectionError(
                "progress_history_invalid",
                f"retained progress transition no longer evaluates: {exc}",
            ) from exc
        if not expected.applied or expected.lease != item.successor_lease:
            raise OutcomeSelectionError(
                "progress_history_invalid",
                "retained progress transition does not match deterministic lease evolution",
            )
        lease = item.successor_lease
        matching.append(item)
        appended_receipts.append(item.receipt)

    effective_scenario = scenario.model_copy(
        deep=True,
        update={"receipts": [*scenario.receipts, *appended_receipts]},
    )
    try:
        result = evaluate_scenario(effective_scenario)
    except ContinuationError as exc:
        raise OutcomeSelectionError(
            "progress_history_invalid",
            f"effective selected scenario no longer evaluates: {exc}",
        ) from exc
    if result.lease != lease:
        raise OutcomeSelectionError(
            "progress_history_invalid",
            "effective selected scenario lease differs from retained transition history",
        )
    return ResolvedOutcomeProgressHead(
        base_scenario=scenario,
        effective_scenario=effective_scenario,
        result=result,
        transitions=tuple(matching),
        head_transition_sha256=canonical_sha256(matching[-1]) if matching else None,
    )


def _load_progress_receipt_for_claim(
    receipt_path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
) -> tuple[OutcomeProgressReceiptV1, str, str]:
    """Load one strict immutable progress receipt from the exact worktree."""

    resolved = receipt_path.expanduser().resolve()
    worktree = Path(claim.worktree_path or "").expanduser().resolve()
    try:
        receipt_ref = resolved.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise OutcomeSelectionError(
            "progress_receipt_outside_worktree",
            "selected progress receipt must be inside the exact claim worktree",
        ) from exc
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OutcomeSelectionError(
            "progress_receipt_unavailable",
            f"unable to read selected progress receipt {receipt_ref}: {exc}",
        ) from exc
    try:
        receipt = OutcomeProgressReceiptV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "progress_receipt_invalid",
            f"selected progress receipt is invalid: {exc}",
        ) from exc
    return receipt, hashlib.sha256(content).hexdigest(), receipt_ref


def prepare_outcome_session_transfer(
    *,
    claim: coordination_claims.ClaimRecord,
    successor_session_id: str,
    transferred_at: datetime | None = None,
) -> PreparedOutcomeSessionTransfer | None:
    """Validate selected state before a cross-session claim mutation begins."""

    if claim.session_id == successor_session_id:
        return None
    if not claim.session_id or not claim.tracker_path:
        return None
    tracker_path = Path(claim.tracker_path).expanduser().resolve()
    if not tracker_path.is_file():
        return None
    payload = session_contracts.read_session_tracker(tracker_path)
    tracker = _validate_tracker_claim(payload, claim=claim, tracker_path=tracker_path)
    raw_binding = tracker.get("outcome_selection")
    if raw_binding is None:
        return None
    try:
        predecessor = OutcomeSelectionBindingV1.model_validate(raw_binding)
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "selection_binding_invalid",
            f"existing outcome selection is invalid: {exc}",
        ) from exc
    _assert_binding_matches_claim(predecessor, claim=claim, tracker_path=tracker_path)
    scenario = _validate_binding_scenario(predecessor, claim=claim)
    progress_head = _resolve_progress_head(
        tracker,
        binding=predecessor,
        scenario=scenario,
    )

    successor_claim = replace(claim, session_id=successor_session_id)
    successor = OutcomeSelectionBindingV1.model_validate(
        {
            **predecessor.model_dump(mode="json"),
            "session_id": successor_session_id,
            "claim_identity_sha256": _claim_identity_sha256(successor_claim),
        }
    )
    transfer = OutcomeSessionTransferV1(
        transferred_at=transferred_at or datetime.now(UTC),
        prior_session_id=claim.session_id,
        successor_session_id=successor_session_id,
        prior_claim_identity_sha256=predecessor.claim_identity_sha256,
        successor_claim_identity_sha256=successor.claim_identity_sha256,
        prior_binding_sha256=canonical_sha256(predecessor),
        successor_binding_sha256=canonical_sha256(successor),
        scenario_file_sha256=predecessor.scenario_file_sha256,
        scenario_sha256=predecessor.scenario_sha256,
        outcome_contract_sha256=predecessor.outcome_contract_sha256,
        lease_sha256=predecessor.lease_sha256,
        outcome_id=predecessor.outcome_id,
        outcome_lineage_id=predecessor.outcome_lineage_id,
        target_path=predecessor.target_path,
        progress_transition_count=len(progress_head.transitions),
        progress_head_transition_sha256=progress_head.head_transition_sha256,
        current_lease_sha256=progress_head.result.lease_sha256,
        current_lease_state=progress_head.result.lease.state,
    )
    return PreparedOutcomeSessionTransfer(
        tracker_path=tracker_path,
        tracker_payload_sha256=canonical_sha256(payload),
        predecessor_binding=predecessor,
        successor_binding=successor,
        transfer=transfer,
    )


def build_prepared_outcome_session_transfer_payload(
    prepared: PreparedOutcomeSessionTransfer,
    *,
    tracker_payload: dict[str, Any],
    predecessor_claim: coordination_claims.ClaimRecord,
    successor_claim: coordination_claims.ClaimRecord,
    current_phase: str,
    notes: str,
    updated_at: str,
) -> dict[str, Any]:
    """Build one successor tracker payload without acquiring an external lock."""

    if _claim_identity_sha256(successor_claim) != prepared.transfer.successor_claim_identity_sha256:
        raise OutcomeSelectionError(
            "session_transfer_claim_mismatch",
            "resumed claim identity does not match the prepared successor binding",
        )

    payload = copy.deepcopy(tracker_payload)
    if canonical_sha256(payload) != prepared.tracker_payload_sha256:
        raise OutcomeSelectionError(
            "session_transfer_tracker_changed",
            "session tracker changed after transfer preflight",
        )
    tracker = _validate_tracker_claim(
        payload,
        claim=predecessor_claim,
        tracker_path=prepared.tracker_path,
    )
    try:
        current = OutcomeSelectionBindingV1.model_validate(tracker.get("outcome_selection"))
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "selection_binding_invalid",
            f"existing outcome selection is invalid: {exc}",
        ) from exc
    if current != prepared.predecessor_binding:
        raise OutcomeSelectionError(
            "session_transfer_selection_changed",
            "selected outcome changed after transfer preflight",
        )
    raw_history = tracker.get("outcome_session_transfers", [])
    if not isinstance(raw_history, list):
        raise OutcomeSelectionError(
            "session_transfer_history_invalid",
            "outcome_session_transfers must be a list",
        )
    try:
        history = [OutcomeSessionTransferV1.model_validate(item) for item in raw_history]
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "session_transfer_history_invalid",
            f"existing outcome session transfer is invalid: {exc}",
        ) from exc
    tracker_claim = payload.get("claim")
    timestamps = payload.get("timestamps")
    if not isinstance(tracker_claim, dict) or not isinstance(timestamps, dict):
        raise OutcomeSelectionError("tracker_invalid", "session tracker is missing claim or timestamp metadata")
    tracker_claim["session_id"] = successor_claim.session_id
    tracker["current_phase"] = current_phase.strip()
    tracker["notes"] = notes.strip()
    tracker["outcome_selection"] = prepared.successor_binding.model_dump(mode="json")
    tracker["outcome_session_transfers"] = [
        *[item.model_dump(mode="json") for item in history],
        prepared.transfer.model_dump(mode="json"),
    ]
    timestamps["updated_at"] = updated_at
    _validate_tracker_claim(
        payload,
        claim=successor_claim,
        tracker_path=prepared.tracker_path,
    )
    return payload


def apply_prepared_outcome_session_transfer(
    prepared: PreparedOutcomeSessionTransfer,
    *,
    predecessor_claim: coordination_claims.ClaimRecord,
    successor_claim: coordination_claims.ClaimRecord,
    current_phase: str,
    notes: str,
    updated_at: str,
) -> OutcomeSessionTransferV1:
    """Atomically rebind one prepared selection and append its transfer receipt."""

    def apply_transfer(payload: dict[str, Any]) -> None:
        successor_payload = build_prepared_outcome_session_transfer_payload(
            prepared,
            tracker_payload=payload,
            predecessor_claim=predecessor_claim,
            successor_claim=successor_claim,
            current_phase=current_phase,
            notes=notes,
            updated_at=updated_at,
        )
        payload.clear()
        payload.update(successor_payload)

    session_contracts.mutate_session_tracker(
        prepared.tracker_path,
        apply_transfer,
        updated_at=updated_at,
    )
    return prepared.transfer


def _binding_identity_sha256(binding: OutcomeSelectionBindingV1) -> str:
    """Hash the create-once choice while excluding its first-write timestamp."""

    payload = binding.model_dump(mode="json")
    payload.pop("selected_at", None)
    return canonical_sha256(payload)


def select_outcome_for_session(
    *,
    agent: str,
    project: str,
    scope: str,
    execution_authority_ref: str,
    scenario_path: Path,
    session_id: str | None = None,
    claims_dir: Path | None = None,
    portfolio_ledger_path: Path = DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH,
) -> OutcomeSelectionResultV1:
    """Create or idempotently replay one exact-session outcome selection."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise OutcomeSelectionError(
            "session_identity_unavailable",
            "selection requires an explicit or native exact session ID",
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        claim = _exact_live_claim(
            agent=agent,
            project=project,
            scope=scope,
            session_id=resolved_session_id,
            claims_dir=resolved_claims_dir,
        )
        if not claim.tracker_path:
            raise OutcomeSelectionError(
                "tracker_unavailable",
                "exact live claim does not link a session tracker",
            )
        tracker_path = Path(claim.tracker_path).expanduser().resolve()
        if not tracker_path.is_file():
            raise OutcomeSelectionError(
                "tracker_unavailable",
                f"exact live claim tracker is not a file: {tracker_path}",
            )
        scenario, scenario_file_sha256, scenario_ref = _load_scenario_for_claim(
            scenario_path,
            claim=claim,
        )
        authority = _execution_authority(
            execution_authority_ref,
            claim=claim,
            scenario=scenario,
        )
        _validate_planned_outcome_baseline(
            authority=authority,
            claim=claim,
            scenario=scenario,
        )
        binding = _build_binding(
            claim=claim,
            tracker_path=tracker_path,
            authority=authority,
            scenario=scenario,
            scenario_ref=scenario_ref,
            scenario_file_sha256=scenario_file_sha256,
            portfolio_ledger_path=portfolio_ledger_path,
        )
        binding_sha256 = canonical_sha256(binding)
        binding_identity_sha256 = _binding_identity_sha256(binding)
        status: Literal["selected", "idempotent"] = "selected"

        def store_binding(payload: dict[str, Any]) -> None:
            nonlocal binding, binding_sha256, status
            tracker = _validate_tracker_claim(payload, claim=claim, tracker_path=tracker_path)
            existing_payload = tracker.get("outcome_selection")
            if existing_payload is None:
                tracker["outcome_selection"] = binding.model_dump(mode="json")
                return
            try:
                existing = OutcomeSelectionBindingV1.model_validate(existing_payload)
            except ValidationError as exc:
                raise OutcomeSelectionError(
                    "selection_binding_invalid",
                    f"existing outcome selection is invalid: {exc}",
                ) from exc
            if _binding_identity_sha256(existing) != binding_identity_sha256:
                raise OutcomeSelectionError(
                    "selection_conflict",
                    "this exact session already selected a different outcome binding",
                )
            binding = existing
            binding_sha256 = canonical_sha256(existing)
            status = "idempotent"

        try:
            session_contracts.mutate_session_tracker(tracker_path, store_binding)
        except OutcomeSelectionError:
            raise
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise OutcomeSelectionError(
                "tracker_invalid",
                f"unable to mutate exact session tracker: {exc}",
            ) from exc
    return OutcomeSelectionResultV1(
        status=status,
        binding=binding,
        binding_sha256=binding_sha256,
        tracker_path=str(tracker_path),
    )


def record_selected_outcome_progress_for_session(
    *,
    agent: str,
    project: str,
    scope: str,
    receipt_path: Path,
    session_id: str | None = None,
    claims_dir: Path | None = None,
) -> OutcomeProgressResultV1:
    """Append one exact current-head receipt to selected outcome custody."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise OutcomeSelectionError(
            "session_identity_unavailable",
            "progress recording requires an explicit or native exact session ID",
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        claim = _exact_live_claim(
            agent=agent,
            project=project,
            scope=scope,
            session_id=resolved_session_id,
            claims_dir=resolved_claims_dir,
        )
        if not claim.tracker_path:
            raise OutcomeSelectionError(
                "tracker_unavailable",
                "exact live claim does not link a session tracker",
            )
        tracker_path = Path(claim.tracker_path).expanduser().resolve()
        if not tracker_path.is_file():
            raise OutcomeSelectionError(
                "tracker_unavailable",
                f"exact live claim tracker is not a file: {tracker_path}",
            )
        receipt, receipt_file_sha256, receipt_ref = _load_progress_receipt_for_claim(
            receipt_path,
            claim=claim,
        )
        receipt_sha256 = canonical_sha256(receipt)
        status: Literal["recorded", "idempotent"] = "recorded"
        selected_binding: OutcomeSelectionBindingV1 | None = None
        selected_transition: OutcomeProgressTransitionV1 | None = None
        progress_transition_count = 0

        def apply_progress(payload: dict[str, Any]) -> None:
            nonlocal status, selected_binding, selected_transition, progress_transition_count
            tracker = _validate_tracker_claim(payload, claim=claim, tracker_path=tracker_path)
            raw_binding = tracker.get("outcome_selection")
            if raw_binding is None:
                raise OutcomeSelectionError(
                    "selection_missing",
                    "progress recording requires an existing selected outcome",
                )
            try:
                binding = OutcomeSelectionBindingV1.model_validate(raw_binding)
            except ValidationError as exc:
                raise OutcomeSelectionError(
                    "selection_binding_invalid",
                    f"existing outcome selection is invalid: {exc}",
                ) from exc
            _assert_binding_matches_claim(binding, claim=claim, tracker_path=tracker_path)
            scenario = _validate_binding_scenario(binding, claim=claim)
            head = _resolve_progress_head(tracker, binding=binding, scenario=scenario)
            history = _progress_history(tracker)

            for base_receipt in scenario.receipts:
                if base_receipt.receipt_id == receipt.receipt_id:
                    raise OutcomeSelectionError(
                        "progress_receipt_already_in_base",
                        "progress receipt ID is already retained by the immutable selected scenario",
                    )
            current_transition_digests = {
                canonical_sha256(item): item for item in head.transitions
            }
            for item in history:
                if item.receipt.receipt_id != receipt.receipt_id:
                    continue
                item_sha256 = canonical_sha256(item)
                if (
                    item_sha256 in current_transition_digests
                    and item.receipt_sha256 == receipt_sha256
                    and item.receipt_file_sha256 == receipt_file_sha256
                    and item.receipt_ref == receipt_ref
                ):
                    status = "idempotent"
                    selected_binding = binding
                    selected_transition = item
                    progress_transition_count = len(head.transitions)
                    return
                raise OutcomeSelectionError(
                    "progress_receipt_conflict",
                    "this outcome already retains a different receipt with the same receipt ID",
                )

            try:
                lease_transition = transition_lease(
                    scenario.contract,
                    head.result.lease,
                    receipt,
                )
            except ContinuationError as exc:
                raise OutcomeSelectionError(exc.code, str(exc)) from exc
            if not lease_transition.applied:
                raise OutcomeSelectionError(
                    "progress_receipt_already_applied",
                    "receipt is already present at the selected scenario or current lease head",
                )
            transition = OutcomeProgressTransitionV1(
                recorded_at=datetime.now(UTC),
                receipt_ref=receipt_ref,
                receipt_file_sha256=receipt_file_sha256,
                receipt_sha256=receipt_sha256,
                receipt=receipt,
                selection_binding_sha256=canonical_sha256(binding),
                selection_binding=binding,
                prior_lease_sha256=head.result.lease_sha256,
                prior_lease=head.result.lease,
                successor_lease_sha256=canonical_sha256(lease_transition.lease),
                successor_lease=lease_transition.lease,
            )
            raw_history = tracker.get("outcome_progress_transitions", [])
            if not isinstance(raw_history, list):
                raise OutcomeSelectionError(
                    "progress_history_invalid",
                    "outcome_progress_transitions must be a list",
                )
            tracker["outcome_progress_transitions"] = [
                *raw_history,
                transition.model_dump(mode="json"),
            ]
            selected_binding = binding
            selected_transition = transition
            progress_transition_count = len(head.transitions) + 1

        try:
            with session_contracts.session_tracker_lock(tracker_path):
                payload = session_contracts.read_session_tracker(tracker_path)
                apply_progress(payload)
                if status == "recorded":
                    timestamps = payload.get("timestamps")
                    if not isinstance(timestamps, dict):
                        raise TypeError(f"Session tracker at {tracker_path} is missing timestamps section")
                    timestamps["updated_at"] = datetime.now(UTC).isoformat()
                    session_contracts._atomic_write_session_tracker(tracker_path, payload)
        except OutcomeSelectionError:
            raise
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise OutcomeSelectionError(
                "tracker_invalid",
                f"unable to mutate exact session tracker for progress: {exc}",
            ) from exc

    if selected_binding is None or selected_transition is None:
        raise OutcomeSelectionError(
            "progress_internal_error",
            "progress recording completed without a selected transition",
        )
    return OutcomeProgressResultV1(
        status=status,
        binding=selected_binding,
        binding_sha256=canonical_sha256(selected_binding),
        transition=selected_transition,
        transition_sha256=canonical_sha256(selected_transition),
        progress_transition_count=progress_transition_count,
        tracker_path=str(tracker_path),
    )


def _load_restart_delta_for_claim(
    restart_delta_path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
) -> tuple[RestartDeltaV1, str, str]:
    """Load one strict restart delta from the exact claim worktree."""

    resolved = restart_delta_path.expanduser().resolve()
    worktree = Path(claim.worktree_path or "").expanduser().resolve()
    try:
        delta_ref = resolved.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise OutcomeSelectionError(
            "restart_delta_outside_worktree",
            "RestartDeltaV1 must be inside the exact claim worktree",
        ) from exc
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OutcomeSelectionError(
            "restart_delta_unavailable",
            f"unable to read restart delta {delta_ref}: {exc}",
        ) from exc
    try:
        delta = RestartDeltaV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomeSelectionError(
            "restart_delta_invalid",
            f"RestartDeltaV1 is invalid: {exc}",
        ) from exc
    return delta, hashlib.sha256(content).hexdigest(), delta_ref


def _failed_evidence_refs(scenario: OutcomeContinuationScenarioV1) -> tuple[str, ...]:
    """Return stable unique evidence refs retained from non-outcome receipts."""

    refs: list[str] = []
    for receipt in scenario.receipts:
        if receipt.progress_kind != "non_outcome":
            continue
        candidates = [*receipt.evidence.artifact_refs]
        if receipt.evidence.trace_ref:
            candidates.append(receipt.evidence.trace_ref)
        for ref in candidates:
            if ref not in refs:
                refs.append(ref)
    return tuple(refs)


def _assert_restart_contract(
    *,
    predecessor_binding: OutcomeSelectionBindingV1,
    predecessor_scenario: OutcomeContinuationScenarioV1,
    successor_binding: OutcomeSelectionBindingV1,
    successor_scenario: OutcomeContinuationScenarioV1,
    delta: RestartDeltaV1,
) -> tuple[OutcomeLeaseV1, tuple[str, ...]]:
    """Validate exact same-outcome custody and retained predecessor failure state."""

    predecessor_result = evaluate_scenario(predecessor_scenario)
    successor_result = evaluate_scenario(successor_scenario)
    predecessor_lease = predecessor_result.lease
    successor_lease = successor_result.lease
    if predecessor_lease.state not in {"stalled", "parked"}:
        raise OutcomeSelectionError(
            "restart_predecessor_state",
            "causal restart requires a stalled or parked selected predecessor",
        )
    if (
        successor_lease.state != "active"
        or successor_lease.consecutive_non_outcome_increments != 0
        or successor_lease.same_boundary_failures != 0
        or successor_lease.current_failure_boundary is not None
    ):
        raise OutcomeSelectionError(
            "restart_successor_lease_invalid",
            "restart successor must begin active with zero current failure counters",
        )

    predecessor = predecessor_scenario.contract
    successor = successor_scenario.contract
    retained_contract_fields = (
        "owner_class",
        "project_id",
        "outcome_id",
        "intended_consumer",
        "outcome",
        "canonical_journey",
        "progress_dimensions",
    )
    mismatches = [
        field
        for field in retained_contract_fields
        if getattr(predecessor, field) != getattr(successor, field)
    ]
    if mismatches:
        raise OutcomeSelectionError(
            "restart_outcome_mismatch",
            "restart successor changed retained outcome identity: " + ", ".join(mismatches),
        )
    if predecessor_binding.target_path != successor_binding.target_path:
        raise OutcomeSelectionError(
            "restart_target_mismatch",
            "restart successor changed the canonical write target",
        )
    if predecessor_binding.execution_authority_ref != successor_binding.execution_authority_ref:
        raise OutcomeSelectionError(
            "restart_authority_mismatch",
            "restart successor changed execution authority",
        )
    if successor.lineage_id == predecessor.lineage_id:
        raise OutcomeSelectionError(
            "restart_lineage_unchanged",
            "restart successor requires a distinct outcome lineage",
        )
    if predecessor.lineage_id not in successor.predecessor_lineage_ids:
        raise OutcomeSelectionError(
            "restart_predecessor_missing",
            "restart successor must directly list the selected predecessor lineage",
        )

    failed_refs = _failed_evidence_refs(predecessor_scenario)
    expected_delta = {
        "predecessor_binding_sha256": canonical_sha256(predecessor_binding),
        "predecessor_contract_sha256": predecessor_result.outcome_contract_sha256,
        "predecessor_lease_sha256": predecessor_result.lease_sha256,
        "predecessor_lineage_id": predecessor.lineage_id,
        "predecessor_lease_state": predecessor_lease.state,
        "predecessor_non_outcome_count": predecessor_lease.consecutive_non_outcome_increments,
        "predecessor_failure_boundary": predecessor_lease.current_failure_boundary,
        "predecessor_failure_count": predecessor_lease.same_boundary_failures,
        "predecessor_failed_evidence_refs": list(failed_refs),
        "successor_contract_sha256": successor_result.outcome_contract_sha256,
        "successor_lineage_id": successor.lineage_id,
    }
    actual_delta = delta.model_dump(mode="json")
    mismatches = [
        name for name, expected in expected_delta.items() if actual_delta.get(name) != expected
    ]
    if mismatches:
        raise OutcomeSelectionError(
            "restart_delta_mismatch",
            "RestartDeltaV1 does not bind exact predecessor/successor state: " + ", ".join(mismatches),
        )
    return predecessor_lease, failed_refs


def restart_selected_outcome_for_session(
    *,
    agent: str,
    project: str,
    scope: str,
    successor_scenario_path: Path,
    restart_delta_path: Path,
    session_id: str | None = None,
    claims_dir: Path | None = None,
    portfolio_ledger_path: Path = DEFAULT_OUTCOME_PORTFOLIO_LEDGER_PATH,
) -> OutcomeRestartResultV1:
    """Replace stalled selected state only through one exact causal restart."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise OutcomeSelectionError(
            "session_identity_unavailable",
            "restart requires an explicit or native exact session ID",
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        claim = _exact_live_claim(
            agent=agent,
            project=project,
            scope=scope,
            session_id=resolved_session_id,
            claims_dir=resolved_claims_dir,
        )
        if not claim.tracker_path:
            raise OutcomeSelectionError("tracker_unavailable", "exact live claim does not link a session tracker")
        tracker_path = Path(claim.tracker_path).expanduser().resolve()
        if not tracker_path.is_file():
            raise OutcomeSelectionError(
                "tracker_unavailable",
                f"exact live claim tracker is not a file: {tracker_path}",
            )
        successor_scenario, successor_file_sha256, successor_ref = _load_scenario_for_claim(
            successor_scenario_path,
            claim=claim,
        )
        delta, delta_file_sha256, delta_ref = _load_restart_delta_for_claim(
            restart_delta_path,
            claim=claim,
        )
        delta_sha256 = canonical_sha256(delta)
        status: Literal["restarted", "idempotent"] = "restarted"
        selected_binding: OutcomeSelectionBindingV1 | None = None
        selected_transition: OutcomeRestartTransitionV1 | None = None

        def apply_restart(payload: dict[str, Any]) -> None:
            nonlocal status, selected_binding, selected_transition
            tracker = _validate_tracker_claim(payload, claim=claim, tracker_path=tracker_path)
            raw_binding = tracker.get("outcome_selection")
            if raw_binding is None:
                raise OutcomeSelectionError(
                    "selection_missing",
                    "causal restart requires an existing selected predecessor",
                )
            try:
                current = OutcomeSelectionBindingV1.model_validate(raw_binding)
            except ValidationError as exc:
                raise OutcomeSelectionError(
                    "selection_binding_invalid",
                    f"existing outcome selection is invalid: {exc}",
                ) from exc
            _assert_binding_matches_claim(current, claim=claim, tracker_path=tracker_path)

            raw_history = tracker.get("outcome_selection_transitions", [])
            if not isinstance(raw_history, list):
                raise OutcomeSelectionError(
                    "restart_history_invalid",
                    "outcome_selection_transitions must be a list",
                )
            try:
                history = [OutcomeRestartTransitionV1.model_validate(item) for item in raw_history]
            except ValidationError as exc:
                raise OutcomeSelectionError(
                    "restart_history_invalid",
                    f"existing outcome restart transition is invalid: {exc}",
                ) from exc

            for prior in history:
                if (
                    prior.restart_delta_file_sha256 == delta_file_sha256
                    and prior.restart_delta_sha256 == delta_sha256
                ):
                    if (
                        current != prior.successor_binding
                        or prior.successor_binding.scenario_ref != successor_ref
                        or prior.successor_binding.scenario_file_sha256 != successor_file_sha256
                    ):
                        raise OutcomeSelectionError(
                            "restart_replay_conflict",
                            "accepted restart no longer matches the current selected successor",
                        )
                    status = "idempotent"
                    selected_binding = current
                    selected_transition = prior
                    return
                if prior.predecessor_binding_sha256 == delta.predecessor_binding_sha256:
                    raise OutcomeSelectionError(
                        "restart_conflict",
                        "the selected predecessor already has a different accepted restart transition",
                    )

            predecessor_scenario = _validate_binding_scenario(current, claim=claim)
            predecessor_head = _resolve_progress_head(
                tracker,
                binding=current,
                scenario=predecessor_scenario,
            )
            authority = _execution_authority(
                current.execution_authority_ref,
                claim=claim,
                scenario=successor_scenario,
            )
            successor_binding = _build_binding(
                claim=claim,
                tracker_path=tracker_path,
                authority=authority,
                scenario=successor_scenario,
                scenario_ref=successor_ref,
                scenario_file_sha256=successor_file_sha256,
                portfolio_ledger_path=portfolio_ledger_path,
            )
            predecessor_lease, failed_refs = _assert_restart_contract(
                predecessor_binding=current,
                predecessor_scenario=predecessor_head.effective_scenario,
                successor_binding=successor_binding,
                successor_scenario=successor_scenario,
                delta=delta,
            )
            transition = OutcomeRestartTransitionV1(
                restarted_at=datetime.now(UTC),
                restart_delta_ref=delta_ref,
                restart_delta_file_sha256=delta_file_sha256,
                restart_delta_sha256=delta_sha256,
                restart_delta=delta,
                predecessor_binding_sha256=canonical_sha256(current),
                predecessor_binding=current,
                predecessor_contract_sha256=canonical_sha256(predecessor_scenario.contract),
                predecessor_contract=predecessor_scenario.contract,
                predecessor_lease_sha256=canonical_sha256(predecessor_lease),
                predecessor_lease=predecessor_lease,
                predecessor_failed_evidence_refs=failed_refs,
                successor_binding_sha256=canonical_sha256(successor_binding),
                successor_binding=successor_binding,
            )
            tracker["outcome_selection"] = successor_binding.model_dump(mode="json")
            tracker["outcome_selection_transitions"] = [
                *[item.model_dump(mode="json") for item in history],
                transition.model_dump(mode="json"),
            ]
            selected_binding = successor_binding
            selected_transition = transition

        try:
            with session_contracts.session_tracker_lock(tracker_path):
                payload = session_contracts.read_session_tracker(tracker_path)
                apply_restart(payload)
                if status == "restarted":
                    timestamps = payload.get("timestamps")
                    if not isinstance(timestamps, dict):
                        raise TypeError(f"Session tracker at {tracker_path} is missing timestamps section")
                    timestamps["updated_at"] = datetime.now(UTC).isoformat()
                    session_contracts._atomic_write_session_tracker(tracker_path, payload)
        except OutcomeSelectionError:
            raise
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise OutcomeSelectionError(
                "tracker_invalid",
                f"unable to mutate exact session tracker for restart: {exc}",
            ) from exc

    if selected_binding is None or selected_transition is None:
        raise OutcomeSelectionError("restart_internal_error", "restart completed without a selected transition")
    return OutcomeRestartResultV1(
        status=status,
        binding=selected_binding,
        binding_sha256=canonical_sha256(selected_binding),
        transition=selected_transition,
        transition_sha256=canonical_sha256(selected_transition),
        tracker_path=str(tracker_path),
    )


def _assert_claim_matches_prewrite(
    claim: coordination_claims.ClaimRecord,
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    claim_source_file: str,
) -> None:
    expected = {
        "agent": agent,
        "project": project,
        "scope": scope,
        "session_id": session_id,
        "repo_root": _normalized_path(repo_root),
        "worktree_path": _normalized_path(worktree_path),
        "branch": branch,
        "claim_source_file": _normalized_path(claim_source_file),
    }
    actual = {
        "agent": claim.agent,
        "project": claim.primary_project(),
        "scope": claim.scope,
        "session_id": claim.session_id,
        "repo_root": _normalized_path(claim.repo_root or ""),
        "worktree_path": _normalized_path(claim.worktree_path or ""),
        "branch": claim.branch,
        "claim_source_file": _normalized_path(claim.source_file or ""),
    }
    mismatches = [name for name, value in expected.items() if actual.get(name) != value]
    if mismatches:
        raise OutcomeSelectionError(
            "prewrite_claim_identity_mismatch",
            "ordinary receipt no longer matches its exact claim source: " + ", ".join(mismatches),
        )


def _resolve_selected_outcome(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    claim_source_file: str,
    target_path: str | None,
) -> ResolvedOutcomeSelectionV1:
    """Resolve current selected state, with an optional exact target constraint."""

    source_path = Path(claim_source_file).expanduser().resolve()
    with coordination_claims.claim_registry_lock(source_path.parent):
        claim = _claim_from_source(source_path)
        live_claims = [item for item in _load_claim_records(source_path.parent) if item.is_live()]
        health_issues = coordination_claims.coordination_health_issues(
            claim,
            active_claims=live_claims,
        )
        if health_issues:
            raise OutcomeSelectionError(
                "claim_not_healthy",
                "exact claim source is not healthy: " + ", ".join(health_issues),
            )
        _assert_claim_matches_prewrite(
            claim,
            agent=agent,
            project=project,
            scope=scope,
            session_id=session_id,
            repo_root=repo_root,
            worktree_path=worktree_path,
            branch=branch,
            claim_source_file=claim_source_file,
        )
        if not claim.tracker_path:
            raise OutcomeSelectionError(
                "tracker_unavailable",
                "exact claim source does not link a session tracker",
            )
        tracker_path = Path(claim.tracker_path).expanduser().resolve()
        try:
            payload = session_contracts.read_session_tracker(tracker_path)
        except OSError as exc:
            raise OutcomeSelectionError(
                "tracker_unavailable",
                f"unable to read exact session tracker: {exc}",
            ) from exc
        except (TypeError, ValueError, yaml.YAMLError) as exc:
            raise OutcomeSelectionError(
                "tracker_invalid",
                f"exact session tracker is invalid: {exc}",
            ) from exc
        tracker = _validate_tracker_claim(payload, claim=claim, tracker_path=tracker_path)
        raw_binding = tracker.get("outcome_selection")
        if raw_binding is None:
            raise OutcomeSelectionError(
                "selection_missing",
                "exact session tracker has no selected outcome",
            )
        try:
            binding = OutcomeSelectionBindingV1.model_validate(raw_binding)
        except ValidationError as exc:
            raise OutcomeSelectionError(
                "selection_binding_invalid",
                f"stored outcome selection is invalid: {exc}",
            ) from exc
        current_identity = _claim_identity_sha256(claim)
        if binding.claim_identity_sha256 != current_identity:
            raise OutcomeSelectionError(
                "selection_claim_identity_stale",
                "stored selection does not match the current exact claim identity",
            )
        if target_path is not None and binding.target_path != target_path:
            raise OutcomeSelectionError(
                "selection_target_mismatch",
                "selected scenario target does not equal the ordinary pre-write target",
            )
        if binding.tracker_path != str(tracker_path):
            raise OutcomeSelectionError(
                "selection_tracker_mismatch",
                "stored selection points at a different session tracker",
            )
        scenario_path = Path(binding.worktree_path) / binding.scenario_ref
        scenario, file_sha256, scenario_ref = _load_scenario_for_claim(scenario_path, claim=claim)
        immutable_file_checks = {
            "scenario_ref": (scenario_ref, binding.scenario_ref),
            "scenario_file_sha256": (file_sha256, binding.scenario_file_sha256),
        }
        mismatches = [name for name, (actual, expected) in immutable_file_checks.items() if actual != expected]
        if mismatches:
            raise OutcomeSelectionError(
                "selection_scenario_stale",
                "selected scenario changed after selection: " + ", ".join(mismatches),
            )
        try:
            result = evaluate_scenario(scenario)
        except ContinuationError as exc:
            raise OutcomeSelectionError(
                "selection_evaluation_failed",
                f"selected scenario no longer evaluates: {exc}",
            ) from exc
        result_checks = {
            "scenario_sha256": (result.scenario_sha256, binding.scenario_sha256),
            "outcome_contract_sha256": (
                result.outcome_contract_sha256,
                binding.outcome_contract_sha256,
            ),
            "lease_sha256": (result.lease_sha256, binding.lease_sha256),
        }
        mismatches = [name for name, (actual, expected) in result_checks.items() if actual != expected]
        if mismatches:
            raise OutcomeSelectionError(
                "selection_scenario_stale",
                "selected scenario changed after selection: " + ", ".join(mismatches),
            )
        _assert_binding_portfolio_allocation(binding, scenario=scenario)
        progress_head = _resolve_progress_head(
            tracker,
            binding=binding,
            scenario=scenario,
        )
        binding_sha256 = canonical_sha256(binding)
    return ResolvedOutcomeSelectionV1(
        binding=binding,
        binding_sha256=binding_sha256,
        scenario_path=str(scenario_path.resolve()),
        base_scenario_sha256=result.scenario_sha256,
        effective_scenario=progress_head.effective_scenario,
        effective_scenario_sha256=progress_head.result.scenario_sha256,
        current_lease_sha256=progress_head.result.lease_sha256,
        current_lease_state=progress_head.result.lease.state,
        progress_transition_count=len(progress_head.transitions),
        progress_head_transition_sha256=progress_head.head_transition_sha256,
        progress_head_receipt_sha256=(
            progress_head.transitions[-1].receipt_sha256 if progress_head.transitions else None
        ),
    )


def resolve_selected_outcome_for_session(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    claim_source_file: str,
) -> ResolvedOutcomeSelectionV1:
    """Resolve and revalidate selected state for one exact live session claim."""

    return _resolve_selected_outcome(
        agent=agent,
        project=project,
        scope=scope,
        session_id=session_id,
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch=branch,
        claim_source_file=claim_source_file,
        target_path=None,
    )


def resolve_selected_outcome_for_prewrite(
    *,
    agent: str,
    project: str,
    scope: str,
    session_id: str,
    repo_root: str,
    worktree_path: str,
    branch: str,
    claim_source_file: str,
    target_path: str,
) -> ResolvedOutcomeSelectionV1:
    """Resolve selected state and require one exact ordinary pre-write target."""

    return _resolve_selected_outcome(
        agent=agent,
        project=project,
        scope=scope,
        session_id=session_id,
        repo_root=repo_root,
        worktree_path=worktree_path,
        branch=branch,
        claim_source_file=claim_source_file,
        target_path=target_path,
    )


__all__ = [
    "OutcomeProgressResultV1",
    "OutcomeProgressTransitionV1",
    "OutcomeSelectionBindingV1",
    "OutcomeSelectionError",
    "OutcomeSelectionResultV1",
    "ResolvedOutcomeSelectionV1",
    "record_selected_outcome_progress_for_session",
    "resolve_selected_outcome_for_prewrite",
    "resolve_selected_outcome_for_session",
    "select_outcome_for_session",
]
