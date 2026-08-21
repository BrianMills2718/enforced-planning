"""Bind one exact claimed session to one immutable outcome scenario.

Plan 117 stores selection in the existing claim-linked session tracker.  It is
manual and observe-only: selecting a scenario never grants write authority and
resolving it never changes the ordinary pre-write decision.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import yaml  # type: ignore[import-untyped]
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning import coordination_claims, session_contracts
from enforced_planning.outcome_continuation import (
    ContinuationError,
    OutcomeContinuationScenarioV1,
    canonical_sha256,
    evaluate_scenario,
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

    schema_version: Literal["1.0.0"] = "1.0.0"
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

    @model_validator(mode="after")
    def validate_binding(self) -> OutcomeSelectionBindingV1:
        if self.selected_at.tzinfo is None or self.selected_at.utcoffset() is None:
            raise ValueError("selected_at must be timezone-aware")
        expected_goal = f"goal:{self.outcome_id}"
        if self.execution_authority_ref.startswith("goal:") and self.execution_authority_ref != expected_goal:
            raise ValueError("goal authority must equal goal:<outcome-id>")
        return self


class OutcomeSelectionResultV1(StrictModel):
    """Operator-facing result for a selected or idempotently replayed choice."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    status: Literal["selected", "idempotent"]
    binding: OutcomeSelectionBindingV1
    binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    tracker_path: str = Field(min_length=1)


class ResolvedOutcomeSelectionV1(StrictModel):
    """Validated selected state ready for one exact pre-write correlation."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    binding: OutcomeSelectionBindingV1
    binding_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_path: str = Field(min_length=1)


def _load_claim_records(claims_dir: Path) -> list[coordination_claims.ClaimRecord]:
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


def _build_binding(
    *,
    claim: coordination_claims.ClaimRecord,
    tracker_path: Path,
    authority: str,
    scenario: OutcomeContinuationScenarioV1,
    scenario_ref: str,
    scenario_file_sha256: str,
) -> OutcomeSelectionBindingV1:
    result = evaluate_scenario(scenario)
    return OutcomeSelectionBindingV1(
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
        target_path=scenario.request.target_path,
        lease_sha256=result.lease_sha256,
        lease_state=result.lease.state,
        outcome_allowed_at_selection=result.decision.allowed,
        outcome_reason_code_at_selection=result.decision.reason_code,
    )


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
        scenario, scenario_file_sha256, scenario_ref = _load_scenario_for_claim(
            scenario_path,
            claim=claim,
        )
        authority = _execution_authority(
            execution_authority_ref,
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

        session_contracts.mutate_session_tracker(tracker_path, store_binding)
    return OutcomeSelectionResultV1(
        status=status,
        binding=binding,
        binding_sha256=binding_sha256,
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
    """Resolve and revalidate selected state for one ordinary pre-write receipt."""

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
        payload = session_contracts.read_session_tracker(tracker_path)
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
        if binding.target_path != target_path:
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
        binding_sha256 = canonical_sha256(binding)
    return ResolvedOutcomeSelectionV1(
        binding=binding,
        binding_sha256=binding_sha256,
        scenario_path=str(scenario_path.resolve()),
    )


__all__ = [
    "OutcomeSelectionBindingV1",
    "OutcomeSelectionError",
    "OutcomeSelectionResultV1",
    "ResolvedOutcomeSelectionV1",
    "resolve_selected_outcome_for_prewrite",
    "select_outcome_for_session",
]
