"""Observe outcome-continuation authority after an ordinary pre-write decision.

Plan 116 deliberately keeps this boundary separate from
``prewrite_claim_fast``. The ordinary claim decision is authoritative and is
recorded first; this module only correlates an explicit immutable continuation
scenario to the same normalized payload and appends a non-authoritative
``would_allow`` or ``would_deny`` observation.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning.outcome_continuation import (
    ContinuationError,
    OutcomeContinuationScenarioV1,
    evaluate_scenario,
)

DEFAULT_OUTCOME_PREWRITE_OBSERVATION_PATH = (
    Path.home() / ".claude" / "coordination" / "outcome-prewrite-events-v1.jsonl"
)
HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"


class OutcomePreWriteObservationError(ValueError):
    """Fail-loud correlation or append error with a stable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictModel(BaseModel):
    """Strict base for durable Plan 116 observations."""

    model_config = ConfigDict(extra="forbid")


class PreWriteReceiptIdentityV1(StrictModel):
    """Non-content identity copied from one ordinary pre-write receipt."""

    schema_version: Literal["1.0"] = "1.0"
    receipt_id: str = Field(pattern=r"^prewrite_[0-9a-f]{32}$")
    decision: Literal["allow", "deny", "observe_violation"]
    mode: Literal["off", "observe", "enforce"]
    reason_code: str = Field(min_length=3)
    client: Literal["codex", "claude-code"]
    session_id: str = Field(min_length=3)
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    normalized_target_paths: list[str] = Field(min_length=1)
    claim_project: str = Field(min_length=1)
    claim_scope: str = Field(min_length=1)
    claim_source_file: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_targets(self) -> PreWriteReceiptIdentityV1:
        if any(not target.strip() for target in self.normalized_target_paths):
            raise ValueError("normalized_target_paths must be non-empty")
        if len(set(self.normalized_target_paths)) != len(self.normalized_target_paths):
            raise ValueError("normalized_target_paths must be unique")
        return self


class OutcomeDecisionObservationV1(StrictModel):
    """Immutable continuation result correlated to the ordinary payload."""

    scenario_ref: str = Field(min_length=1)
    scenario_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    applied_receipt_sha256s: list[str]
    replayed_receipt_sha256s: list[str]
    lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    lease_state: Literal["active", "recovery_required", "stalled", "complete", "parked"]
    operation: Literal[
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
    target_path: str = Field(min_length=1)
    disposition: Literal["would_allow", "would_deny"]
    allowed: bool
    reason_code: str = Field(min_length=3)

    @model_validator(mode="after")
    def _validate_disposition(self) -> OutcomeDecisionObservationV1:
        expected = "would_allow" if self.allowed else "would_deny"
        if self.disposition != expected:
            raise ValueError("outcome disposition must match allowed")
        for digest in [*self.applied_receipt_sha256s, *self.replayed_receipt_sha256s]:
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("receipt digests must be lowercase SHA-256 values")
        return self


class OutcomePreWriteObservationV1(StrictModel):
    """One typed non-authoritative outcome observation for a pre-write receipt."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_prewrite_observation"] = "outcome_prewrite_observation"
    observation_id: str = Field(pattern=r"^outcome_prewrite_[0-9a-f]{32}$")
    recorded_at: AwareDatetime
    delivery_classification: Literal["explicit_manual_observe"] = "explicit_manual_observe"
    ordinary_admission_unchanged: Literal[True] = True
    prewrite: PreWriteReceiptIdentityV1
    outcome: OutcomeDecisionObservationV1


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OutcomePreWriteObservationError(
            "prewrite_identity_incomplete",
            f"ordinary pre-write decision requires non-empty {field}",
        )
    return value.strip()


def _prewrite_identity(decision: dict[str, Any]) -> PreWriteReceiptIdentityV1:
    targets = decision.get("normalized_target_paths")
    if not isinstance(targets, list) or not targets or not all(isinstance(item, str) for item in targets):
        raise OutcomePreWriteObservationError(
            "prewrite_identity_incomplete",
            "ordinary pre-write decision requires normalized target paths",
        )
    try:
        return PreWriteReceiptIdentityV1(
            receipt_id=_required_string(decision, "receipt_id"),
            decision=_required_string(decision, "decision"),
            mode=_required_string(decision, "mode"),
            reason_code=_required_string(decision, "reason_code"),
            client=_required_string(decision, "client"),
            session_id=_required_string(decision, "session_id"),
            repo_root=_required_string(decision, "repo_root"),
            worktree_path=_required_string(decision, "worktree_path"),
            branch=_required_string(decision, "branch"),
            normalized_target_paths=targets,
            claim_project=_required_string(decision, "claim_project"),
            claim_scope=_required_string(decision, "claim_scope"),
            claim_source_file=_required_string(decision, "claim_source_file"),
        )
    except ValidationError as exc:
        raise OutcomePreWriteObservationError(
            "prewrite_identity_invalid",
            f"ordinary pre-write identity is invalid: {exc}",
        ) from exc


def _scenario_ref(*, scenario_path: Path, worktree_path: str) -> tuple[Path, str]:
    resolved = scenario_path.expanduser().resolve()
    worktree = Path(worktree_path).expanduser().resolve()
    try:
        relative = resolved.relative_to(worktree)
    except ValueError as exc:
        raise OutcomePreWriteObservationError(
            "scenario_outside_worktree",
            "outcome scenario must be inside the ordinary pre-write worktree",
        ) from exc
    if not resolved.is_file():
        raise OutcomePreWriteObservationError(
            "scenario_unavailable",
            f"outcome scenario is not a file: {relative.as_posix()}",
        )
    return resolved, relative.as_posix()


def append_outcome_prewrite_observation(
    observation: OutcomePreWriteObservationV1,
    *,
    path: Path = DEFAULT_OUTCOME_PREWRITE_OBSERVATION_PATH,
) -> None:
    """Append one strict observation under a filesystem lock."""

    resolved = path.expanduser()
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor = os.open(resolved, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            handle.write(
                json.dumps(
                    observation.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError as exc:
        raise OutcomePreWriteObservationError(
            "observation_append_failed",
            f"unable to append outcome pre-write observation: {exc}",
        ) from exc


def load_outcome_prewrite_observations(path: Path) -> list[OutcomePreWriteObservationV1]:
    """Load and validate every non-empty observation ledger line."""

    try:
        lines = path.expanduser().read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OutcomePreWriteObservationError(
            "observation_read_failed",
            f"unable to read outcome pre-write observations: {exc}",
        ) from exc
    observations: list[OutcomePreWriteObservationV1] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            observations.append(OutcomePreWriteObservationV1.model_validate_json(line))
        except ValidationError as exc:
            raise OutcomePreWriteObservationError(
                "observation_invalid",
                f"invalid outcome pre-write observation at line {line_number}: {exc}",
            ) from exc
    return observations


def evaluate_and_record_outcome_prewrite(
    *,
    prewrite_decision: dict[str, Any],
    scenario_path: Path,
    observation_path: Path = DEFAULT_OUTCOME_PREWRITE_OBSERVATION_PATH,
) -> OutcomePreWriteObservationV1:
    """Correlate one immutable scenario after the ordinary decision and append it."""

    prewrite = _prewrite_identity(prewrite_decision)
    resolved_scenario, scenario_ref = _scenario_ref(
        scenario_path=scenario_path,
        worktree_path=prewrite.worktree_path,
    )
    try:
        scenario_bytes = resolved_scenario.read_bytes()
        scenario = OutcomeContinuationScenarioV1.model_validate_json(scenario_bytes)
        result = evaluate_scenario(scenario)
    except (ContinuationError, ValidationError, OSError, ValueError) as exc:
        raise OutcomePreWriteObservationError(
            "scenario_evaluation_failed",
            f"outcome scenario could not be evaluated: {exc}",
        ) from exc

    if scenario.request.operation != "product_write" or not scenario.request.target_path:
        raise OutcomePreWriteObservationError(
            "unsupported_outcome_operation",
            "pre-write outcome observation requires one product_write target",
        )
    if prewrite.normalized_target_paths != [scenario.request.target_path]:
        raise OutcomePreWriteObservationError(
            "target_mismatch",
            "outcome scenario target must exactly match the ordinary pre-write target",
        )
    if prewrite.claim_project != scenario.contract.project_id:
        raise OutcomePreWriteObservationError(
            "project_mismatch",
            "outcome scenario project must exactly match the ordinary claim project",
        )

    scenario_file_sha256 = hashlib.sha256(scenario_bytes).hexdigest()
    try:
        observation = OutcomePreWriteObservationV1(
            observation_id=f"outcome_prewrite_{uuid.uuid4().hex}",
            recorded_at=datetime.now(UTC),
            prewrite=prewrite,
            outcome=OutcomeDecisionObservationV1(
                scenario_ref=scenario_ref,
                scenario_file_sha256=scenario_file_sha256,
                scenario_sha256=result.scenario_sha256,
                outcome_contract_sha256=result.outcome_contract_sha256,
                applied_receipt_sha256s=result.applied_receipt_sha256s,
                replayed_receipt_sha256s=result.replayed_receipt_sha256s,
                lease_sha256=result.lease_sha256,
                lease_state=result.lease.state,
                operation=result.decision.operation,
                target_path=scenario.request.target_path,
                disposition="would_allow" if result.decision.allowed else "would_deny",
                allowed=result.decision.allowed,
                reason_code=result.decision.reason_code,
            ),
        )
    except ValidationError as exc:
        raise OutcomePreWriteObservationError(
            "observation_invalid",
            f"outcome pre-write observation is invalid: {exc}",
        ) from exc
    append_outcome_prewrite_observation(observation, path=observation_path)
    return observation


__all__ = [
    "DEFAULT_OUTCOME_PREWRITE_OBSERVATION_PATH",
    "OutcomePreWriteObservationError",
    "OutcomePreWriteObservationV1",
    "append_outcome_prewrite_observation",
    "evaluate_and_record_outcome_prewrite",
    "load_outcome_prewrite_observations",
]
