"""Evaluate the first-consumer outcome-admission ratchet against frozen cases.

This module is decision-only.  It composes existing ordinary authority with
the safe-operation, allocation-bootstrap, portfolio, and continuation states
that a later hard gate must consume.  It does not activate a lifecycle hook or
claim support outside the frozen first-consumer boundary.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enforced_planning.outcome_continuation import canonical_sha256

HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"
FULL_GIT_REVISION_PATTERN = r"^[0-9a-f]{40}$"
PORTABLE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")

CaseSplit = Literal[
    "positive_control",
    "negative_control",
    "validation",
    "held_out",
    "calibration",
]
CaseSeverity = Literal["critical", "boundary"]
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

SAFE_BOUNDARIES = {
    "passive_inspection",
    "exact_replay",
    "evidence_preservation",
    "closeout",
}
CIRCULAR_OR_BYPASS_CLASSES = {
    "circular_continuation",
    "owner_product_wip_overflow",
    "global_nonproduct_wip_overflow",
    "unallocated_new_plan",
    "allocation_digest_bypass",
    "approval_as_progress",
    "admission_bootstrap_bypass",
    "outcome_gate_overrides_ordinary_denial",
    "lease_scope_bypass",
    "unbounded_recovery_bypass",
    "legacy_never_migrates",
    "outcome_gate-revives-stale-claim",
    "restart_laundering",
    "cost_or_approval_as_progress",
}
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


class StrictModel(BaseModel):
    """Strict immutable base for frozen evaluation contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class PopulationClaimV1(StrictModel):
    """Minimal claim structure retained for admission calibration."""

    project: str = Field(min_length=1)
    scope: str = Field(min_length=1)
    claim_type: Literal["program", "write", "review", "research"]
    parent_scope: str | None = None
    broader_goal: str | None = None
    status: Literal["active", "blocked", "handoff", "session_ended"]
    health_status: Literal["healthy", "weak", "stale"]
    plan_ref: str | None = None
    branch: str = Field(min_length=1)


class OutcomeAdmissionPopulationSnapshotV1(StrictModel):
    """Revision-bound structural sample of current coordination claims."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_admission_population_snapshot"]
    snapshot_id: str = Field(min_length=3)
    captured_at: str = Field(min_length=20)
    producer_revision: str = Field(pattern=FULL_GIT_REVISION_PATTERN)
    producer_command: tuple[str, ...] = Field(min_length=1)
    normalized_snapshot_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    claim_count: int = Field(ge=1)
    claims: tuple[PopulationClaimV1, ...] = Field(min_length=1)
    observed_structures: tuple[str, ...] = Field(min_length=1)
    privacy_note: str = Field(min_length=12)

    @model_validator(mode="after")
    def validate_population(self) -> OutcomeAdmissionPopulationSnapshotV1:
        if not PORTABLE_ID_PATTERN.fullmatch(self.snapshot_id):
            raise ValueError("snapshot_id must be a portable lowercase identifier")
        if self.claim_count != len(self.claims):
            raise ValueError("claim_count must equal the retained claims length")
        identities = [(claim.project, claim.scope) for claim in self.claims]
        if len(set(identities)) != len(identities):
            raise ValueError("population claim project/scope identities must be unique")
        if len(set(self.observed_structures)) != len(self.observed_structures):
            raise ValueError("observed_structures must be unique")
        return self


class MinimumUsefulQualityV1(StrictModel):
    """Frozen promotion thresholds."""

    critical_false_blocks: Literal[0]
    critical_false_allows: Literal[0]
    unexpected_scored_defers: Literal[0]
    safe_operation_recall: float = Field(ge=1.0, le=1.0)
    circular_or_bypass_rejection: float = Field(ge=1.0, le=1.0)
    positive_control_pass: Literal[True]
    negative_control_pass: Literal[True]
    corruption_control_rejected: Literal[True]


class OutcomeAdmissionEvaluationCaseV1(StrictModel):
    """One frozen expected operation decision."""

    case_id: str = Field(min_length=3)
    split: CaseSplit
    failure_class: str = Field(min_length=3)
    severity: CaseSeverity
    source_refs: tuple[str, ...] = Field(min_length=1)
    boundary: OperationBoundary
    enforcement_scope: EnforcementScope
    ordinary_allowed: bool
    portfolio_state: PortfolioState
    continuation_state: ContinuationState
    bootstrap_product_write_requested: bool = False
    expected_disposition: AdmissionDisposition
    expected_reason_code: str = Field(min_length=3)

    @model_validator(mode="after")
    def validate_case(self) -> OutcomeAdmissionEvaluationCaseV1:
        if not PORTABLE_ID_PATTERN.fullmatch(self.case_id):
            raise ValueError("case_id must be a portable lowercase identifier")
        if len(set(self.source_refs)) != len(self.source_refs):
            raise ValueError("source_refs must be unique")
        if self.bootstrap_product_write_requested and self.boundary != "portfolio_allocate":
            raise ValueError(
                "bootstrap_product_write_requested is valid only for portfolio_allocate"
            )
        if self.enforcement_scope == "always_safe" and self.boundary not in SAFE_BOUNDARIES:
            raise ValueError("always_safe scope requires a declared safe boundary")
        if self.enforcement_scope == "calibration_only" and self.split != "calibration":
            raise ValueError("calibration_only scope requires the calibration split")
        if self.split == "calibration" and self.enforcement_scope != "calibration_only":
            raise ValueError("calibration split requires calibration_only scope")
        if (self.expected_disposition == "defer") != (self.split == "calibration"):
            raise ValueError("only calibration cases may expect defer")
        return self


class OutcomeAdmissionEvaluationSuiteV1(StrictModel):
    """Frozen decision claim, thresholds, and representative cases."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_admission_evaluation_suite"]
    suite_id: str = Field(min_length=3)
    frozen_at: str = Field(min_length=20)
    system_revision: str = Field(pattern=FULL_GIT_REVISION_PATTERN)
    population_snapshot_ref: str = Field(min_length=1)
    population_snapshot_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    population_normalized_snapshot_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    claim: str = Field(min_length=20)
    decision: str = Field(min_length=20)
    baseline: str = Field(min_length=20)
    minimum_useful_quality: MinimumUsefulQualityV1
    non_claims: tuple[str, ...] = Field(min_length=1)
    cases: tuple[OutcomeAdmissionEvaluationCaseV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_suite(self) -> OutcomeAdmissionEvaluationSuiteV1:
        if not PORTABLE_ID_PATTERN.fullmatch(self.suite_id):
            raise ValueError("suite_id must be a portable lowercase identifier")
        case_ids = [case.case_id for case in self.cases]
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("case_id values must be unique")
        positive_controls = [case for case in self.cases if case.split == "positive_control"]
        negative_controls = [case for case in self.cases if case.split == "negative_control"]
        if len(positive_controls) != 1 or len(negative_controls) != 1:
            raise ValueError("suite requires exactly one positive and one negative control")
        if len(set(self.non_claims)) != len(self.non_claims):
            raise ValueError("non_claims must be unique")
        return self


class AdmissionDecisionV1(StrictModel):
    """Candidate or baseline decision for one case."""

    disposition: AdmissionDisposition
    reason_code: str = Field(min_length=3)


class OutcomeAdmissionCaseResultV1(StrictModel):
    """One baseline/candidate comparison against the frozen expectation."""

    case_id: str
    split: CaseSplit
    failure_class: str
    severity: CaseSeverity
    expected: AdmissionDecisionV1
    baseline: AdmissionDecisionV1
    candidate: AdmissionDecisionV1
    matched_expected: bool


class OutcomeAdmissionMetricsV1(StrictModel):
    """Decision-linked aggregate with critical failures kept explicit."""

    total_cases: int = Field(ge=1)
    scored_cases: int = Field(ge=1)
    calibration_cases: int = Field(ge=0)
    matched_scored_cases: int = Field(ge=0)
    mismatched_scored_cases: int = Field(ge=0)
    critical_false_blocks: int = Field(ge=0)
    critical_false_allows: int = Field(ge=0)
    unexpected_scored_defers: int = Field(ge=0)
    safe_operation_recall: float = Field(ge=0, le=1)
    circular_or_bypass_rejection: float = Field(ge=0, le=1)
    baseline_false_blocks: int = Field(ge=0)
    baseline_false_allows: int = Field(ge=0)


class OutcomeAdmissionEvaluationResultV1(StrictModel):
    """Deterministic primary readout for one exact candidate and suite."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_admission_evaluation_result"] = (
        "outcome_admission_evaluation_result"
    )
    suite_id: str
    suite_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    population_snapshot_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    population_normalized_snapshot_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    candidate_revision: str = Field(pattern=FULL_GIT_REVISION_PATTERN)
    candidate_source_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    build_adequacy_passed: Literal[True] = True
    positive_control_passed: bool
    negative_control_passed: bool
    cases: tuple[OutcomeAdmissionCaseResultV1, ...]
    metrics: OutcomeAdmissionMetricsV1
    promotion_thresholds_passed: bool
    decision: Literal["continue_to_independent_signoff", "revise_before_promotion"]
    non_claims: tuple[str, ...]


class CorruptionControlResultV1(StrictModel):
    """Proof that the scorer rejects an in-memory label corruption."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    control_case_id: str
    original_expected_disposition: AdmissionDisposition
    corrupted_expected_disposition: AdmissionDisposition
    candidate_disposition: AdmissionDisposition
    mismatch_detected: bool


class LoadedEvaluationInputsV1(StrictModel):
    """Strict loaded inputs plus their exact file digests."""

    suite: OutcomeAdmissionEvaluationSuiteV1
    population: OutcomeAdmissionPopulationSnapshotV1
    suite_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    population_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)


class CandidateSourceBindingV1(StrictModel):
    """Exact executable source loaded from one verified Git commit."""

    candidate_revision: str = Field(pattern=FULL_GIT_REVISION_PATTERN)
    source_ref: str = Field(min_length=1)
    source_sha256: str = Field(pattern=HEX_SHA256_PATTERN)


def file_sha256(path: Path) -> str:
    """Hash exact file bytes."""

    return hashlib.sha256(path.read_bytes()).hexdigest()


def resolve_candidate_source_binding(
    *,
    repo_root: Path,
    candidate_revision: str,
    source_ref: str,
) -> CandidateSourceBindingV1:
    """Verify one full commit and prove the executed source matches its Git blob."""

    if not re.fullmatch(FULL_GIT_REVISION_PATTERN, candidate_revision):
        raise ValueError("candidate_revision must be a full lowercase Git object id")
    if not source_ref or source_ref.startswith("/") or ".." in Path(source_ref).parts:
        raise ValueError("source_ref must be a portable repository-relative path")
    resolved = subprocess.run(
        ["git", "rev-parse", "--verify", f"{candidate_revision}^{{commit}}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != candidate_revision:
        raise ValueError("candidate_revision does not resolve to that exact commit")
    blob = subprocess.run(
        ["git", "show", f"{candidate_revision}:{source_ref}"],
        cwd=repo_root,
        check=False,
        capture_output=True,
    )
    if blob.returncode != 0:
        raise ValueError("candidate source is unavailable at the exact commit")
    source_sha256 = hashlib.sha256(blob.stdout).hexdigest()
    working_source = repo_root / source_ref
    if not working_source.is_file():
        raise ValueError("candidate source is unavailable in the executing checkout")
    if file_sha256(working_source) != source_sha256:
        raise ValueError("executing candidate source differs from the exact committed source")
    return CandidateSourceBindingV1(
        candidate_revision=candidate_revision,
        source_ref=source_ref,
        source_sha256=source_sha256,
    )


def load_evaluation_inputs(
    *,
    cases_path: Path,
    population_path: Path,
) -> LoadedEvaluationInputsV1:
    """Load strict frozen fixtures and reject any digest or reference drift."""

    suite_file_sha256 = file_sha256(cases_path)
    population_file_sha256 = file_sha256(population_path)
    suite = OutcomeAdmissionEvaluationSuiteV1.model_validate_json(
        cases_path.read_text(encoding="utf-8")
    )
    population = OutcomeAdmissionPopulationSnapshotV1.model_validate_json(
        population_path.read_text(encoding="utf-8")
    )
    if suite.population_snapshot_file_sha256 != population_file_sha256:
        raise ValueError("population snapshot file digest does not match the frozen suite")
    if (
        suite.population_normalized_snapshot_sha256
        != population.normalized_snapshot_sha256
    ):
        raise ValueError("population normalized snapshot digest does not match the suite")
    if Path(suite.population_snapshot_ref).name != population_path.name:
        raise ValueError("population snapshot reference does not identify the supplied file")
    return LoadedEvaluationInputsV1(
        suite=suite,
        population=population,
        suite_file_sha256=suite_file_sha256,
        population_file_sha256=population_file_sha256,
    )


def baseline_decision(case: OutcomeAdmissionEvaluationCaseV1) -> AdmissionDecisionV1:
    """Represent the current ordinary-authority-only baseline."""

    if case.ordinary_allowed:
        return AdmissionDecisionV1(
            disposition="allow",
            reason_code="ordinary_authority_allowed",
        )
    return AdmissionDecisionV1(
        disposition="deny",
        reason_code="ordinary_authority_denied",
    )


def candidate_decision(case: OutcomeAdmissionEvaluationCaseV1) -> AdmissionDecisionV1:
    """Apply the pre-registered first-consumer outcome-admission overlay."""

    if case.enforcement_scope == "calibration_only":
        return AdmissionDecisionV1(
            disposition="defer",
            reason_code="cross_repository_membership_not_promoted",
        )
    if not case.ordinary_allowed:
        return AdmissionDecisionV1(
            disposition="deny",
            reason_code="ordinary_authority_denied",
        )
    if case.enforcement_scope == "always_safe":
        return AdmissionDecisionV1(
            disposition="allow",
            reason_code="safe_operation_allowed",
        )
    if case.enforcement_scope == "grandfathered":
        return AdmissionDecisionV1(
            disposition="allow",
            reason_code="grandfathered_until_renewal",
        )
    if case.boundary == "portfolio_allocate":
        if case.bootstrap_product_write_requested:
            return AdmissionDecisionV1(
                disposition="deny",
                reason_code="admission_bootstrap_scope_violation",
            )
        if case.portfolio_state != "not_applicable":
            return AdmissionDecisionV1(
                disposition="deny",
                reason_code="admission_bootstrap_state_invalid",
            )
        return AdmissionDecisionV1(
            disposition="allow",
            reason_code="admission_bootstrap_allowed",
        )
    if case.portfolio_state != "active_exact":
        return AdmissionDecisionV1(
            disposition="deny",
            reason_code=PORTFOLIO_DENIALS[case.portfolio_state],
        )
    if case.continuation_state == "active_in_scope":
        return AdmissionDecisionV1(
            disposition="allow",
            reason_code="outcome_admission_active",
        )
    if case.continuation_state == "bounded_recovery_active":
        return AdmissionDecisionV1(
            disposition="allow",
            reason_code="bounded_recovery_active",
        )
    return AdmissionDecisionV1(
        disposition="deny",
        reason_code=CONTINUATION_DENIALS[case.continuation_state],
    )


def _evaluate_case(case: OutcomeAdmissionEvaluationCaseV1) -> OutcomeAdmissionCaseResultV1:
    expected = AdmissionDecisionV1(
        disposition=case.expected_disposition,
        reason_code=case.expected_reason_code,
    )
    baseline = baseline_decision(case)
    candidate = candidate_decision(case)
    return OutcomeAdmissionCaseResultV1(
        case_id=case.case_id,
        split=case.split,
        failure_class=case.failure_class,
        severity=case.severity,
        expected=expected,
        baseline=baseline,
        candidate=candidate,
        matched_expected=candidate == expected,
    )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        raise ValueError("evaluation taxonomy produced an empty required metric class")
    return numerator / denominator


def _metrics(results: tuple[OutcomeAdmissionCaseResultV1, ...]) -> OutcomeAdmissionMetricsV1:
    scored = tuple(result for result in results if result.split != "calibration")
    calibration = tuple(result for result in results if result.split == "calibration")
    false_blocks = tuple(
        result
        for result in scored
        if result.expected.disposition == "allow"
        and result.candidate.disposition != "allow"
        and result.severity == "critical"
    )
    false_allows = tuple(
        result
        for result in scored
        if result.expected.disposition == "deny"
        and result.candidate.disposition != "deny"
        and result.severity == "critical"
    )
    safe = tuple(result for result in scored if result.failure_class == "safe_operation_false_block")
    circular_or_bypass = tuple(
        result for result in scored if result.failure_class in CIRCULAR_OR_BYPASS_CLASSES
    )
    baseline_false_blocks = sum(
        result.expected.disposition == "allow" and result.baseline.disposition != "allow"
        for result in scored
    )
    baseline_false_allows = sum(
        result.expected.disposition == "deny" and result.baseline.disposition != "deny"
        for result in scored
    )
    return OutcomeAdmissionMetricsV1(
        total_cases=len(results),
        scored_cases=len(scored),
        calibration_cases=len(calibration),
        matched_scored_cases=sum(result.matched_expected for result in scored),
        mismatched_scored_cases=sum(not result.matched_expected for result in scored),
        critical_false_blocks=len(false_blocks),
        critical_false_allows=len(false_allows),
        unexpected_scored_defers=sum(
            result.candidate.disposition == "defer" for result in scored
        ),
        safe_operation_recall=_ratio(
            sum(result.candidate.disposition == "allow" for result in safe),
            len(safe),
        ),
        circular_or_bypass_rejection=_ratio(
            sum(result.candidate.disposition == "deny" for result in circular_or_bypass),
            len(circular_or_bypass),
        ),
        baseline_false_blocks=baseline_false_blocks,
        baseline_false_allows=baseline_false_allows,
    )


def evaluate_admission_suite(
    loaded: LoadedEvaluationInputsV1,
    *,
    candidate_revision: str,
    candidate_source_sha256: str,
) -> OutcomeAdmissionEvaluationResultV1:
    """Execute all frozen cases and apply the exact promotion thresholds."""

    if not re.fullmatch(FULL_GIT_REVISION_PATTERN, candidate_revision):
        raise ValueError("candidate_revision must be a full lowercase Git object id")
    if not re.fullmatch(HEX_SHA256_PATTERN, candidate_source_sha256):
        raise ValueError("candidate_source_sha256 must be a lowercase SHA-256 digest")
    results = tuple(_evaluate_case(case) for case in loaded.suite.cases)
    metrics = _metrics(results)
    positive = next(result for result in results if result.split == "positive_control")
    negative = next(result for result in results if result.split == "negative_control")
    positive_control_passed = positive.matched_expected
    negative_control_passed = negative.matched_expected
    thresholds_passed = (
        metrics.mismatched_scored_cases == 0
        and metrics.critical_false_blocks == 0
        and metrics.critical_false_allows == 0
        and metrics.unexpected_scored_defers == 0
        and metrics.safe_operation_recall == 1.0
        and metrics.circular_or_bypass_rejection == 1.0
        and positive_control_passed
        and negative_control_passed
    )
    return OutcomeAdmissionEvaluationResultV1(
        suite_id=loaded.suite.suite_id,
        suite_file_sha256=loaded.suite_file_sha256,
        population_snapshot_file_sha256=loaded.population_file_sha256,
        population_normalized_snapshot_sha256=(
            loaded.population.normalized_snapshot_sha256
        ),
        candidate_revision=candidate_revision,
        candidate_source_sha256=candidate_source_sha256,
        positive_control_passed=positive_control_passed,
        negative_control_passed=negative_control_passed,
        cases=results,
        metrics=metrics,
        promotion_thresholds_passed=thresholds_passed,
        decision=(
            "continue_to_independent_signoff"
            if thresholds_passed
            else "revise_before_promotion"
        ),
        non_claims=loaded.suite.non_claims,
    )


def run_corruption_control(
    loaded: LoadedEvaluationInputsV1,
) -> CorruptionControlResultV1:
    """Invert the positive-control label in memory and prove a mismatch appears."""

    control = next(case for case in loaded.suite.cases if case.split == "positive_control")
    corrupted_disposition: AdmissionDisposition = (
        "deny" if control.expected_disposition == "allow" else "allow"
    )
    corrupted = control.model_copy(
        update={"expected_disposition": corrupted_disposition}
    )
    candidate = candidate_decision(corrupted)
    mismatch_detected = candidate.disposition != corrupted.expected_disposition
    return CorruptionControlResultV1(
        control_case_id=control.case_id,
        original_expected_disposition=control.expected_disposition,
        corrupted_expected_disposition=corrupted_disposition,
        candidate_disposition=candidate.disposition,
        mismatch_detected=mismatch_detected,
    )


def result_sha256(result: OutcomeAdmissionEvaluationResultV1) -> str:
    """Return the canonical deterministic readout digest."""

    return canonical_sha256(result)
