"""Production outcome-admission ordering for the first Enforced Planning consumer.

The pure decision owns policy ordering.  Live adapters must derive its state
from canonical claim, selection, portfolio, and continuation owners; callers
must not self-certify those states at an enforcement boundary.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

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

SAFE_BOUNDARIES = frozenset(
    {
        "passive_inspection",
        "exact_replay",
        "evidence_preservation",
        "closeout",
    }
)
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
_PLAN_WORK_GRAPH_RE = re.compile(
    r"^docs/plans/(?P<plan>[1-9][0-9]*)_[a-z0-9_]+_work_graph\.json$"
)
_BOOTSTRAP_EXAMPLE_RE = re.compile(
    r"^examples/owner-real-outcome-admission/plan(?P<plan>[1-9][0-9]*)-[a-z0-9-]+\.json$"
)
_SHARED_BOOTSTRAP_PATHS = frozenset({"docs/plans/CLAUDE.md", "ROADMAP.md"})


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
            raise ValueError(
                "bootstrap_product_write_requested is valid only for portfolio_allocate"
            )
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


__all__ = [
    "SAFE_BOUNDARIES",
    "AdmissionDisposition",
    "ContinuationState",
    "EnforcementScope",
    "OperationBoundary",
    "OutcomeAdmissionBootstrapResultV1",
    "OutcomeAdmissionBootstrapV1",
    "OutcomeAdmissionDecisionV1",
    "OutcomeAdmissionRequestV1",
    "PortfolioState",
    "decide_outcome_admission",
    "evaluate_first_consumer_bootstrap",
    "is_first_consumer_bootstrap_path",
]
