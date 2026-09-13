"""Persist and enforce criterion-bound completion for one selected outcome.

The completion proposal remains a pure decision in ``outcome_continuation``.
This module supplies the missing durable seam: it binds that decision to the
exact selected session tracker and replays it before a native Stop may pass.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning import (
    coordination_claims,
    outcome_portfolio,
    outcome_selection,
    session_contracts,
)
from enforced_planning.outcome_continuation import (
    ExecutionProjectionV1,
    GoalCompletionDecisionV1,
    GoalCompletionProposalV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeLeaseV1,
    canonical_sha256,
    evaluate_scenario,
    propose_goal_completion,
)

HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"
OutcomeCompletionMode = Literal["off", "enforce_selected"]


class OutcomeCompletionError(RuntimeError):
    """Fail-loud completion error with one stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OutcomeCompletionTransitionV1(StrictModel):
    """One accepted completion bound to exact selected and evidence bytes."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_completion_transition"] = "outcome_completion_transition"
    completed_at: datetime
    selection_binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    selection_binding: outcome_selection.OutcomeSelectionBindingV1
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_contract: OutcomeContractV1
    prior_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    prior_lease: OutcomeLeaseV1
    projection_ref: str = Field(min_length=1)
    projection_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    projection_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    projection: ExecutionProjectionV1
    proposal_ref: str = Field(min_length=1)
    proposal_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    proposal_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    proposal: GoalCompletionProposalV1
    decision: GoalCompletionDecisionV1
    successor_lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    successor_lease: OutcomeLeaseV1

    @model_validator(mode="after")
    def validate_transition(self) -> OutcomeCompletionTransitionV1:
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        checks = {
            "selection_binding_sha256": (
                canonical_sha256(self.selection_binding),
                self.selection_binding_sha256,
            ),
            "prior_lease_sha256": (canonical_sha256(self.prior_lease), self.prior_lease_sha256),
            "outcome_contract_sha256": (
                canonical_sha256(self.outcome_contract),
                self.outcome_contract_sha256,
            ),
            "projection_sha256": (canonical_sha256(self.projection), self.projection_sha256),
            "proposal_sha256": (canonical_sha256(self.proposal), self.proposal_sha256),
            "successor_lease_sha256": (
                canonical_sha256(self.successor_lease),
                self.successor_lease_sha256,
            ),
        }
        mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
        if mismatches:
            raise ValueError("completion transition digest mismatch: " + ", ".join(mismatches))
        if self.outcome_contract_sha256 != self.selection_binding.outcome_contract_sha256:
            raise ValueError("completion contract must equal the selected outcome contract")
        expected = propose_goal_completion(
            self.outcome_contract,
            self.prior_lease,
            self.projection,
            self.proposal,
        )
        if expected != self.decision or expected.lease != self.successor_lease:
            raise ValueError("completion transition does not match deterministic completion evaluation")
        if not expected.accepted or not expected.applied:
            raise ValueError("completion transition must retain one newly accepted completion")
        return self


class OutcomeCompletionResultV1(StrictModel):
    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["recorded", "idempotent"]
    transition: OutcomeCompletionTransitionV1
    transition_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    tracker_path: str = Field(min_length=1)


class OutcomeCompletionStopDecisionV1(StrictModel):
    """Native Stop decision for an explicitly activated consumer."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    applicable: bool
    allow_stop: bool
    reason_code: str = Field(min_length=3)
    summary: str = Field(min_length=3)
    outcome_id: str | None = None
    current_lease_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    completion_transition_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)


def _mapping(value: object, *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a mapping")
    return value


def load_outcome_completion_mode(repo_root: Path) -> OutcomeCompletionMode:
    """Load the isolated first-consumer mode; absence remains compatible."""

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
    meta_process = _mapping(root.get("meta_process", root), field_name="meta-process.yaml meta_process")
    if "claims" not in meta_process:
        return "off"
    claims = _mapping(meta_process["claims"], field_name="meta-process.yaml claims")
    mode = claims.get("outcome_completion_mode", "off")
    if mode is False:  # YAML 1.1 parses the documented unquoted ``off`` as false.
        mode = "off"
    if mode not in {"off", "enforce_selected"}:
        raise ValueError("claims.outcome_completion_mode must be one of: off, enforce_selected")
    return mode


def _load_json_model_for_claim(
    path: Path,
    *,
    claim: coordination_claims.ClaimRecord,
    model: type[BaseModel],
    kind: str,
) -> tuple[BaseModel, str, str]:
    resolved = path.expanduser().resolve()
    worktree = Path(claim.worktree_path or "").expanduser().resolve()
    try:
        relative = resolved.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise OutcomeCompletionError(
            f"{kind}_outside_worktree",
            f"completion {kind} must be inside the exact claim worktree",
        ) from exc
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OutcomeCompletionError(
            f"{kind}_unavailable", f"unable to read completion {kind} {relative}: {exc}"
        ) from exc
    try:
        value = model.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomeCompletionError(f"{kind}_invalid", f"completion {kind} is invalid: {exc}") from exc
    return value, hashlib.sha256(content).hexdigest(), relative


def _completion_history(tracker: dict[str, Any]) -> list[OutcomeCompletionTransitionV1]:
    raw = tracker.get("outcome_completion_transitions", [])
    if not isinstance(raw, list):
        raise OutcomeCompletionError("completion_history_invalid", "outcome_completion_transitions must be a list")
    try:
        return [OutcomeCompletionTransitionV1.model_validate(item) for item in raw]
    except ValidationError as exc:
        raise OutcomeCompletionError(
            "completion_history_invalid", f"existing outcome completion is invalid: {exc}"
        ) from exc


def _validate_completed_portfolio_scenario(
    binding: outcome_selection.OutcomeSelectionBindingV1,
    *,
    claim: coordination_claims.ClaimRecord,
) -> OutcomeContinuationScenarioV1:
    """Reopen a classed scenario after its exact allocation completed.

    Selection and pre-write still require an active allocation.  Stop replay is
    later in the lifecycle: once canonical completion is retained, the exact
    allocation's append-only ``complete`` disposition is success evidence, not
    grounds to invalidate that completion.
    """

    scenario_path = Path(binding.worktree_path) / binding.scenario_ref
    scenario, file_sha256, scenario_ref = outcome_selection._load_scenario_for_claim(
        scenario_path,
        claim=claim,
    )
    result = evaluate_scenario(scenario)
    checks = {
        "scenario_ref": (scenario_ref, binding.scenario_ref),
        "scenario_file_sha256": (file_sha256, binding.scenario_file_sha256),
        "scenario_sha256": (result.scenario_sha256, binding.scenario_sha256),
        "outcome_contract_sha256": (
            result.outcome_contract_sha256,
            binding.outcome_contract_sha256,
        ),
        "outcome_id": (scenario.contract.outcome_id, binding.outcome_id),
        "outcome_lineage_id": (
            scenario.contract.lineage_id,
            binding.outcome_lineage_id,
        ),
    }
    mismatches = [name for name, (actual, expected) in checks.items() if actual != expected]
    if mismatches:
        raise OutcomeCompletionError(
            "portfolio_completion_invalid",
            "completed allocation scenario changed: " + ", ".join(mismatches),
        )
    if (
        binding.schema_version != "1.1.0"
        or binding.portfolio_ledger_path is None
        or binding.portfolio_allocation_id is None
        or binding.portfolio_allocation_sha256 is None
    ):
        raise OutcomeCompletionError(
            "portfolio_completion_invalid",
            "completed classed outcome requires an exact allocation binding",
        )
    ledger = outcome_portfolio.load_outcome_portfolio_ledger(
        Path(binding.portfolio_ledger_path)
    )
    allocations = [
        record
        for record in ledger.records
        if isinstance(record, outcome_portfolio.OutcomePortfolioAllocationV1)
        and record.allocation_id == binding.portfolio_allocation_id
    ]
    dispositions = [
        record
        for record in ledger.records
        if isinstance(record, outcome_portfolio.OutcomePortfolioDispositionV1)
        and record.allocation_id == binding.portfolio_allocation_id
    ]
    if len(allocations) != 1 or len(dispositions) != 1:
        raise OutcomeCompletionError(
            "portfolio_completion_invalid",
            "completed outcome requires one exact allocation and one disposition",
        )
    allocation = allocations[0]
    disposition = dispositions[0]
    allocation_sha256 = canonical_sha256(allocation)
    allocation_checks = {
        "allocation_sha256": (
            allocation_sha256,
            binding.portfolio_allocation_sha256,
        ),
        "disposition_allocation_sha256": (
            disposition.allocation_sha256,
            binding.portfolio_allocation_sha256,
        ),
        "allocation_contract": (
            allocation.outcome_contract_sha256,
            binding.outcome_contract_sha256,
        ),
        "allocation_scenario": (allocation.scenario_sha256, binding.scenario_sha256),
        "allocation_outcome": (allocation.outcome_id, binding.outcome_id),
        "allocation_lineage": (
            allocation.outcome_lineage_id,
            binding.outcome_lineage_id,
        ),
        "disposition": (disposition.disposition, "complete"),
    }
    allocation_mismatches = [
        name
        for name, (actual, expected) in allocation_checks.items()
        if actual != expected
    ]
    if allocation_mismatches:
        raise OutcomeCompletionError(
            "portfolio_completion_invalid",
            "completed allocation binding changed: " + ", ".join(allocation_mismatches),
        )
    return scenario


def record_selected_outcome_completion_for_session(
    *,
    agent: str,
    project: str,
    scope: str,
    projection_path: Path,
    proposal_path: Path,
    session_id: str | None = None,
    claims_dir: Path | None = None,
) -> OutcomeCompletionResultV1:
    """Validate and append one exact accepted completion to the session tracker."""

    resolved_session_id = coordination_claims.resolve_session_id(agent, session_id)
    if not resolved_session_id:
        raise OutcomeCompletionError(
            "session_identity_unavailable",
            "completion recording requires an explicit or native exact session ID",
        )
    coordination_claims.validate_native_session_binding(agent, resolved_session_id)
    resolved_claims_dir = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    with coordination_claims.claim_registry_lock(resolved_claims_dir):
        try:
            claim = outcome_selection._exact_live_claim(
                agent=agent,
                project=project,
                scope=scope,
                session_id=resolved_session_id,
                claims_dir=resolved_claims_dir,
            )
        except outcome_selection.OutcomeSelectionError as exc:
            raise OutcomeCompletionError(exc.code, str(exc)) from exc
        if not claim.tracker_path:
            raise OutcomeCompletionError("tracker_unavailable", "exact live claim has no session tracker")
        tracker_path = Path(claim.tracker_path).expanduser().resolve()
        projection_value, projection_file_sha256, projection_ref = _load_json_model_for_claim(
            projection_path,
            claim=claim,
            model=ExecutionProjectionV1,
            kind="projection",
        )
        proposal_value, proposal_file_sha256, proposal_ref = _load_json_model_for_claim(
            proposal_path,
            claim=claim,
            model=GoalCompletionProposalV1,
            kind="proposal",
        )
        projection = ExecutionProjectionV1.model_validate(projection_value)
        proposal = GoalCompletionProposalV1.model_validate(proposal_value)
        status: Literal["recorded", "idempotent"] = "recorded"
        selected: OutcomeCompletionTransitionV1 | None = None

        def apply_completion(payload: dict[str, Any]) -> None:
            nonlocal status, selected
            tracker = outcome_selection._validate_tracker_claim(payload, claim=claim, tracker_path=tracker_path)
            raw_binding = tracker.get("outcome_selection")
            if raw_binding is None:
                raise OutcomeCompletionError("selection_missing", "completion requires an existing selected outcome")
            try:
                binding = outcome_selection.OutcomeSelectionBindingV1.model_validate(raw_binding)
                outcome_selection._assert_binding_matches_claim(binding, claim=claim, tracker_path=tracker_path)
                scenario = outcome_selection._validate_binding_scenario(binding, claim=claim)
                head = outcome_selection._resolve_progress_head(tracker, binding=binding, scenario=scenario)
                aliases = outcome_selection._binding_transfer_aliases(tracker, binding=binding)
            except outcome_selection.OutcomeSelectionError as exc:
                raise OutcomeCompletionError(exc.code, str(exc)) from exc
            history = _completion_history(tracker)
            matching = [item for item in history if item.selection_binding_sha256 in aliases]
            if matching:
                prior = matching[-1]
                exact_replay = (
                    len(matching) == 1
                    and prior.prior_lease == head.result.lease
                    and prior.projection_file_sha256 == projection_file_sha256
                    and prior.proposal_file_sha256 == proposal_file_sha256
                    and prior.projection_ref == projection_ref
                    and prior.proposal_ref == proposal_ref
                    and prior.projection == projection
                    and prior.proposal == proposal
                )
                if exact_replay:
                    status = "idempotent"
                    selected = prior
                    return
                raise OutcomeCompletionError(
                    "completion_conflict",
                    "this selected outcome already retains a different completion",
                )
            decision = propose_goal_completion(scenario.contract, head.result.lease, projection, proposal)
            if not decision.accepted or not decision.applied:
                raise OutcomeCompletionError(
                    decision.reason_code,
                    "canonical goal completion was denied: " + decision.reason_code,
                )
            transition = OutcomeCompletionTransitionV1(
                completed_at=datetime.now(UTC),
                selection_binding_sha256=canonical_sha256(binding),
                selection_binding=binding,
                outcome_contract_sha256=canonical_sha256(scenario.contract),
                outcome_contract=scenario.contract,
                prior_lease_sha256=head.result.lease_sha256,
                prior_lease=head.result.lease,
                projection_ref=projection_ref,
                projection_file_sha256=projection_file_sha256,
                projection_sha256=canonical_sha256(projection),
                projection=projection,
                proposal_ref=proposal_ref,
                proposal_file_sha256=proposal_file_sha256,
                proposal_sha256=canonical_sha256(proposal),
                proposal=proposal,
                decision=decision,
                successor_lease_sha256=canonical_sha256(decision.lease),
                successor_lease=decision.lease,
            )
            raw_history = tracker.get("outcome_completion_transitions", [])
            if not isinstance(raw_history, list):
                raise OutcomeCompletionError(
                    "completion_history_invalid", "outcome_completion_transitions must be a list"
                )
            tracker["outcome_completion_transitions"] = [
                *raw_history,
                transition.model_dump(mode="json"),
            ]
            selected = transition

        try:
            with session_contracts.session_tracker_lock(tracker_path):
                payload = session_contracts.read_session_tracker(tracker_path)
                apply_completion(payload)
                if status == "recorded":
                    timestamps = payload.get("timestamps")
                    if not isinstance(timestamps, dict):
                        raise TypeError("session tracker is missing timestamps")
                    timestamps["updated_at"] = datetime.now(UTC).isoformat()
                    session_contracts._atomic_write_session_tracker(tracker_path, payload)
        except OutcomeCompletionError:
            raise
        except (OSError, TypeError, ValueError, yaml.YAMLError) as exc:
            raise OutcomeCompletionError(
                "tracker_invalid", f"unable to mutate exact tracker for completion: {exc}"
            ) from exc
    if selected is None:
        raise OutcomeCompletionError("completion_internal_error", "completion recording produced no transition")
    return OutcomeCompletionResultV1(
        status=status,
        transition=selected,
        transition_sha256=canonical_sha256(selected),
        tracker_path=str(tracker_path),
    )


def _decision(
    *,
    applicable: bool,
    allow_stop: bool,
    reason_code: str,
    summary: str,
    outcome_id: str | None = None,
    current_lease_sha256: str | None = None,
    completion_transition_sha256: str | None = None,
) -> OutcomeCompletionStopDecisionV1:
    return OutcomeCompletionStopDecisionV1(
        applicable=applicable,
        allow_stop=allow_stop,
        reason_code=reason_code,
        summary=summary,
        outcome_id=outcome_id,
        current_lease_sha256=current_lease_sha256,
        completion_transition_sha256=completion_transition_sha256,
    )


def evaluate_stop_for_session(
    *,
    repo_root: Path,
    agent: str,
    project: str,
    session_id: str,
    active_claims: tuple[coordination_claims.ClaimRecord, ...],
) -> OutcomeCompletionStopDecisionV1:
    """Allow Stop only after the activated repo's exact outcome is complete."""

    try:
        mode = load_outcome_completion_mode(repo_root)
    except (OSError, TypeError, ValueError) as exc:
        return _decision(
            applicable=True,
            allow_stop=False,
            reason_code="outcome_completion_mode_invalid",
            summary=f"Outcome completion configuration is invalid: {exc}",
        )
    if mode == "off":
        return _decision(
            applicable=False,
            allow_stop=True,
            reason_code="outcome_completion_not_configured",
            summary="Outcome completion enforcement is not configured for this repository.",
        )
    root = repo_root.expanduser().resolve()
    claim_matches = [
        claim
        for claim in active_claims
        if claim.agent == agent
        and claim.session_id == session_id
        and claim.projects
        and claim.projects[0] == project
        and claim.worktree_path
        and Path(claim.worktree_path).expanduser().resolve() == root
    ]
    if len(claim_matches) != 1:
        return _decision(
            applicable=True,
            allow_stop=False,
            reason_code="exact_claim_unavailable",
            summary=(
                "Outcome completion blocked: the activated repository requires exactly one "
                f"live claim for this native session; found {len(claim_matches)}."
            ),
        )
    projected_claim = claim_matches[0]
    try:
        claim_path = Path(projected_claim.source_file).expanduser().resolve()
        if hasattr(projected_claim, "source_sha256") and (
            hashlib.sha256(claim_path.read_bytes()).hexdigest() != projected_claim.source_sha256
        ):
            raise OutcomeCompletionError(
                "claim_projection_stale",
                "projected claim bytes changed before outcome completion evaluation",
            )
        claim = outcome_selection._claim_from_source(claim_path)
        outcome_selection._assert_claim_matches_prewrite(
            claim,
            agent=agent,
            project=project,
            scope=projected_claim.scope,
            session_id=session_id,
            repo_root=projected_claim.repo_root,
            worktree_path=projected_claim.worktree_path,
            branch=projected_claim.branch,
            claim_source_file=projected_claim.source_file,
        )
        tracker = session_contracts.read_session_tracker(Path(claim.tracker_path or ""))
        tracker_body = outcome_selection._validate_tracker_claim(
            tracker,
            claim=claim,
            tracker_path=Path(claim.tracker_path or "").expanduser().resolve(),
        )
        raw_binding = tracker_body.get("outcome_selection")
        if raw_binding is None:
            raise OutcomeCompletionError("selection_missing", "exact session tracker has no selected outcome")
        binding = outcome_selection.OutcomeSelectionBindingV1.model_validate(raw_binding)
        outcome_selection._assert_binding_matches_claim(
            binding,
            claim=claim,
            tracker_path=Path(claim.tracker_path or "").expanduser().resolve(),
        )
        history = _completion_history(tracker_body)
        try:
            scenario = outcome_selection._validate_binding_scenario(binding, claim=claim)
        except outcome_selection.OutcomeSelectionError as exc:
            completion_bound_to_allocation = any(
                item.outcome_contract_sha256 == binding.outcome_contract_sha256
                and item.selection_binding.portfolio_allocation_id
                == binding.portfolio_allocation_id
                and item.selection_binding.portfolio_allocation_sha256
                == binding.portfolio_allocation_sha256
                for item in history
            )
            if exc.code != "portfolio_allocation_inactive" or not completion_bound_to_allocation:
                raise
            scenario = _validate_completed_portfolio_scenario(binding, claim=claim)
        head = outcome_selection._resolve_progress_head(
            tracker_body,
            binding=binding,
            scenario=scenario,
        )
        aliases = outcome_selection._binding_transfer_aliases(tracker_body, binding=binding)
        completion_matches = [
            item for item in history if item.selection_binding_sha256 in aliases
        ]
        if len(completion_matches) != 1:
            return _decision(
                applicable=True,
                allow_stop=False,
                reason_code="canonical_outcome_incomplete",
                summary=(
                    f"Outcome completion blocked for {binding.outcome_id}: the canonical "
                    "selected outcome has no single accepted completion. Continue against its "
                    "frozen success criteria; native green items or an archived cursor are not completion."
                ),
                outcome_id=binding.outcome_id,
                current_lease_sha256=head.result.lease_sha256,
            )
        completion = completion_matches[0]
        if completion.prior_lease_sha256 != head.result.lease_sha256:
            return _decision(
                applicable=True,
                allow_stop=False,
                reason_code="completion_evidence_stale",
                summary=(
                    f"Outcome completion blocked for {binding.outcome_id}: canonical progress "
                    "changed after the retained completion evidence. Re-verify the current artifact."
                ),
                outcome_id=binding.outcome_id,
                current_lease_sha256=head.result.lease_sha256,
            )
        expected = propose_goal_completion(
            head.effective_scenario.contract,
            completion.prior_lease,
            completion.projection,
            completion.proposal,
        )
        if (
            completion.outcome_contract != head.effective_scenario.contract
            or completion.outcome_contract_sha256 != binding.outcome_contract_sha256
            or not expected.accepted
            or not expected.applied
            or expected != completion.decision
            or expected.lease != completion.successor_lease
        ):
            raise OutcomeCompletionError(
                "completion_history_invalid",
                "retained completion no longer matches deterministic evaluation",
            )
        return _decision(
            applicable=True,
            allow_stop=True,
            reason_code="canonical_outcome_complete",
            summary=f"Canonical selected outcome {binding.outcome_id} is complete.",
            outcome_id=binding.outcome_id,
            current_lease_sha256=head.result.lease_sha256,
            completion_transition_sha256=canonical_sha256(completion),
        )
    except (outcome_selection.OutcomeSelectionError, OutcomeCompletionError, OSError, ValueError) as exc:
        code = getattr(exc, "code", "outcome_completion_unavailable")
        return _decision(
            applicable=True,
            allow_stop=False,
            reason_code=str(code),
            summary=f"Outcome completion blocked: {exc}",
        )


__all__ = [
    "OutcomeCompletionError",
    "OutcomeCompletionResultV1",
    "OutcomeCompletionStopDecisionV1",
    "OutcomeCompletionTransitionV1",
    "evaluate_stop_for_session",
    "load_outcome_completion_mode",
    "record_selected_outcome_completion_for_session",
]
