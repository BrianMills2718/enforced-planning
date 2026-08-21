"""Correlate an immutable outcome scenario to one ordinary pre-write receipt.

Plan 116 is deliberately observation only.  The ordinary claim decision has
already been recorded when this module is called, and nothing here can alter
that decision or its native exit behavior.  Successful correlations and
failures are both strict append-only records so ambiguity is visible instead
of becoming a permissive fallback.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from enforced_planning.outcome_continuation import (
    ContinuationError,
    OutcomeContinuationScenarioV1,
    canonical_sha256,
    evaluate_scenario,
)
from enforced_planning.outcome_selection import (
    OutcomeSelectionError,
    ResolvedOutcomeSelectionV1,
    resolve_selected_outcome_for_prewrite,
)

DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH = (
    Path.home() / ".claude" / "coordination" / "outcome-prewrite-observations-v1.jsonl"
)
HEX_SHA256_PATTERN = r"^[0-9a-f]{64}$"

ObservationDisposition = Literal["would_allow", "would_deny"]
OrdinaryDecision = Literal["allow", "deny", "observe_violation"]
OrdinaryMode = Literal["off", "observe", "enforce"]


class OutcomePreWriteObservationError(RuntimeError):
    """Fail-loud observation error with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": str(self)}


class StrictModel(BaseModel):
    """Strict immutable-compatible base for Plan 116 receipt records."""

    model_config = ConfigDict(extra="forbid")


class OrdinaryPreWriteIdentityV1(StrictModel):
    """The complete non-content identity copied from one ordinary receipt."""

    receipt_schema_version: Literal["1.0"] = "1.0"
    receipt_id: str = Field(pattern=r"^prewrite_[0-9a-f]{32}$")
    decision: OrdinaryDecision
    mode: OrdinaryMode
    reason_code: str = Field(min_length=3)
    client: Literal["codex", "claude-code"]
    session_id: str = Field(min_length=3)
    repo_root: str = Field(min_length=1)
    worktree_path: str = Field(min_length=1)
    branch: str = Field(min_length=1)
    normalized_target_path: str = Field(min_length=1)
    claim_project: str = Field(min_length=1)
    claim_scope: str = Field(min_length=1)
    claim_source_file: str = Field(min_length=1)


class OutcomePreWriteCorrelationV1(StrictModel):
    """Typed success receipt linking ordinary claim and outcome decisions."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_prewrite_correlation"] = "outcome_prewrite_correlation"
    correlation_receipt_id: str = Field(pattern=r"^ocor-[0-9a-f]{32}$")
    observed_at: datetime
    ordinary: OrdinaryPreWriteIdentityV1
    selection_binding_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    selection_tracker_path: str | None = None
    selection_execution_authority_ref: str | None = None
    selection_claim_identity_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    scenario_ref: str = Field(min_length=1)
    scenario_file_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    scenario_id: str = Field(min_length=3)
    scenario_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_contract_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    outcome_project_id: str = Field(min_length=1)
    outcome_id: str = Field(min_length=3)
    outcome_lineage_id: str = Field(min_length=3)
    scenario_target_path: str = Field(min_length=1)
    applied_receipt_sha256s: list[str]
    replayed_receipt_sha256s: list[str]
    lease_sha256: str = Field(pattern=HEX_SHA256_PATTERN)
    lease_state: Literal["active", "recovery_required", "stalled", "complete", "parked"]
    outcome_allowed: bool
    outcome_reason_code: str = Field(min_length=3)
    disposition: ObservationDisposition
    ordinary_approval_ignored: Literal[True] = True
    cost_telemetry_ignored: Literal[True] = True
    elapsed_telemetry_ignored: Literal[True] = True
    ordinary_authority_preserved: Literal[True] = True
    enforcement_applied: Literal[False] = False

    @model_validator(mode="after")
    def _validate_exact_correlation(self) -> OutcomePreWriteCorrelationV1:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.outcome_project_id != self.ordinary.claim_project:
            raise ValueError("outcome project must equal the ordinary claim project")
        if self.scenario_target_path != self.ordinary.normalized_target_path:
            raise ValueError("scenario target must equal the ordinary normalized target")
        expected = "would_allow" if self.outcome_allowed else "would_deny"
        if self.disposition != expected:
            raise ValueError("disposition must match the outcome decision")
        for digest in [*self.applied_receipt_sha256s, *self.replayed_receipt_sha256s]:
            if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ValueError("receipt digests must be lowercase SHA-256 values")
        selection_fields = (
            self.selection_binding_sha256,
            self.selection_tracker_path,
            self.selection_execution_authority_ref,
            self.selection_claim_identity_sha256,
        )
        if any(value is not None for value in selection_fields) and not all(
            value is not None for value in selection_fields
        ):
            raise ValueError("selected correlation metadata must be complete or absent")
        return self


class OutcomePreWriteObservationFailureV1(StrictModel):
    """Typed visible failure that leaves the ordinary decision authoritative."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    record_type: Literal["outcome_prewrite_observation_failure"] = "outcome_prewrite_observation_failure"
    correlation_receipt_id: str = Field(pattern=r"^ocor-[0-9a-f]{32}$")
    observed_at: datetime
    ordinary_receipt_id: str | None = None
    ordinary: OrdinaryPreWriteIdentityV1 | None = None
    selection_binding_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    selection_tracker_path: str | None = None
    selection_execution_authority_ref: str | None = None
    selection_claim_identity_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    scenario_path: str = Field(min_length=1)
    scenario_file_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    scenario_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    outcome_contract_sha256: str | None = Field(default=None, pattern=HEX_SHA256_PATTERN)
    error_code: str = Field(min_length=3)
    error_message: str = Field(min_length=3)
    disposition: Literal["observation_error"] = "observation_error"
    ordinary_authority_preserved: Literal[True] = True
    enforcement_applied: Literal[False] = False

    @model_validator(mode="after")
    def _validate_failure_identity(self) -> OutcomePreWriteObservationFailureV1:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.ordinary is not None and self.ordinary_receipt_id != self.ordinary.receipt_id:
            raise ValueError("ordinary_receipt_id must match the typed ordinary identity")
        selection_fields = (
            self.selection_binding_sha256,
            self.selection_tracker_path,
            self.selection_execution_authority_ref,
            self.selection_claim_identity_sha256,
        )
        if any(value is not None for value in selection_fields) and not all(
            value is not None for value in selection_fields
        ):
            raise ValueError("selected failure metadata must be complete or absent")
        return self


OutcomePreWriteObservationRecordV1: TypeAlias = OutcomePreWriteCorrelationV1 | OutcomePreWriteObservationFailureV1


def _correlation_receipt_id() -> str:
    return f"ocor-{uuid.uuid4().hex}"


def _required_string(payload: dict[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise OutcomePreWriteObservationError(
            "ordinary_identity_invalid",
            f"ordinary pre-write decision requires non-empty {field!r}",
        )
    return value.strip()


def _ordinary_identity(decision: dict[str, Any]) -> OrdinaryPreWriteIdentityV1:
    targets = decision.get("normalized_target_paths")
    if not isinstance(targets, list) or len(targets) != 1 or not isinstance(targets[0], str) or not targets[0].strip():
        raise OutcomePreWriteObservationError(
            "target_count_mismatch",
            "outcome correlation requires exactly one normalized pre-write target",
        )
    try:
        return OrdinaryPreWriteIdentityV1.model_validate(
            {
                "receipt_schema_version": _required_string(decision, "schema_version"),
                "receipt_id": _required_string(decision, "receipt_id"),
                "decision": _required_string(decision, "decision"),
                "mode": _required_string(decision, "mode"),
                "reason_code": _required_string(decision, "reason_code"),
                "client": _required_string(decision, "client"),
                "session_id": _required_string(decision, "session_id"),
                "repo_root": _required_string(decision, "repo_root"),
                "worktree_path": _required_string(decision, "worktree_path"),
                "branch": _required_string(decision, "branch"),
                "normalized_target_path": targets[0].strip(),
                "claim_project": _required_string(decision, "claim_project"),
                "claim_scope": _required_string(decision, "claim_scope"),
                "claim_source_file": _required_string(decision, "claim_source_file"),
            }
        )
    except ValidationError as exc:
        raise OutcomePreWriteObservationError(
            "ordinary_identity_invalid",
            f"ordinary pre-write identity is invalid: {exc}",
        ) from exc


def _load_scenario(
    path: Path,
    *,
    worktree_path: str,
) -> tuple[OutcomeContinuationScenarioV1, str, str]:
    resolved = path.expanduser().resolve()
    worktree = Path(worktree_path).expanduser().resolve()
    try:
        scenario_ref = resolved.relative_to(worktree).as_posix()
    except ValueError as exc:
        raise OutcomePreWriteObservationError(
            "scenario_outside_worktree",
            "outcome scenario must be inside the ordinary pre-write worktree",
        ) from exc
    if not resolved.is_file():
        raise OutcomePreWriteObservationError(
            "scenario_unavailable",
            f"outcome scenario is not a file: {scenario_ref}",
        )
    try:
        content = resolved.read_bytes()
    except OSError as exc:
        raise OutcomePreWriteObservationError(
            "scenario_read_failed",
            f"unable to read outcome scenario: {exc}",
        ) from exc
    file_sha256 = hashlib.sha256(content).hexdigest()
    try:
        scenario = OutcomeContinuationScenarioV1.model_validate_json(content)
    except ValidationError as exc:
        raise OutcomePreWriteObservationError(
            "scenario_invalid",
            f"outcome scenario is invalid: {exc}",
        ) from exc
    return scenario, file_sha256, scenario_ref


def _append_record(path: Path, record: OutcomePreWriteObservationRecordV1) -> None:
    resolved = path.expanduser()
    resolved.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(resolved, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            handle.write(
                json.dumps(
                    record.model_dump(mode="json"),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _selection_fields(selection: ResolvedOutcomeSelectionV1 | None) -> dict[str, str | None]:
    if selection is None:
        return {
            "selection_binding_sha256": None,
            "selection_tracker_path": None,
            "selection_execution_authority_ref": None,
            "selection_claim_identity_sha256": None,
        }
    return {
        "selection_binding_sha256": selection.binding_sha256,
        "selection_tracker_path": selection.binding.tracker_path,
        "selection_execution_authority_ref": selection.binding.execution_authority_ref,
        "selection_claim_identity_sha256": selection.binding.claim_identity_sha256,
    }


def observe_prewrite_outcome(
    ordinary_decision: dict[str, Any],
    *,
    scenario_path: Path,
    receipt_path: Path = DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
    _selection: ResolvedOutcomeSelectionV1 | None = None,
) -> OutcomePreWriteObservationRecordV1:
    """Append one non-authoritative correlation after ordinary admission.

    Expected scenario/binding failures become typed failure receipts.  Storage
    failures still raise because claiming a durable observation without a
    durable append would be false.
    """

    ordinary: OrdinaryPreWriteIdentityV1 | None = None
    scenario: OutcomeContinuationScenarioV1 | None = None
    scenario_file_sha256: str | None = None
    scenario_ref: str | None = None
    scenario_sha256: str | None = None
    outcome_contract_sha256: str | None = None
    try:
        ordinary = _ordinary_identity(ordinary_decision)
        scenario, scenario_file_sha256, scenario_ref = _load_scenario(
            scenario_path,
            worktree_path=ordinary.worktree_path,
        )
        scenario_sha256 = canonical_sha256(scenario)
        outcome_contract_sha256 = canonical_sha256(scenario.contract)
        if _selection is not None:
            if scenario_path.expanduser().resolve() != Path(_selection.scenario_path).expanduser().resolve():
                raise OutcomePreWriteObservationError(
                    "selection_scenario_path_mismatch",
                    "resolved selection and observer scenario paths differ",
                )
            selection_checks = {
                "scenario_file_sha256": (
                    scenario_file_sha256,
                    _selection.binding.scenario_file_sha256,
                ),
                "scenario_sha256": (scenario_sha256, _selection.binding.scenario_sha256),
                "outcome_contract_sha256": (
                    outcome_contract_sha256,
                    _selection.binding.outcome_contract_sha256,
                ),
            }
            mismatches = [
                name
                for name, (actual, expected) in selection_checks.items()
                if actual != expected
            ]
            if mismatches:
                raise OutcomePreWriteObservationError(
                    "selection_scenario_stale",
                    "selected scenario changed before observation: " + ", ".join(mismatches),
                )
        if scenario.request.operation != "product_write":
            raise OutcomePreWriteObservationError(
                "unsupported_outcome_operation",
                "pre-write outcome correlation requires a product_write scenario request",
            )
        if scenario.request.target_path != ordinary.normalized_target_path:
            raise OutcomePreWriteObservationError(
                "target_mismatch",
                "scenario request target does not equal the normalized pre-write target",
            )
        if scenario.contract.project_id != ordinary.claim_project:
            raise OutcomePreWriteObservationError(
                "project_mismatch",
                "scenario outcome project does not equal the ordinary claim project",
            )
        result = evaluate_scenario(scenario)
        record: OutcomePreWriteObservationRecordV1 = OutcomePreWriteCorrelationV1(
            correlation_receipt_id=_correlation_receipt_id(),
            observed_at=datetime.now(UTC),
            ordinary=ordinary,
            **_selection_fields(_selection),
            scenario_ref=scenario_ref,
            scenario_file_sha256=scenario_file_sha256,
            scenario_id=scenario.scenario_id,
            scenario_sha256=result.scenario_sha256,
            outcome_contract_sha256=result.outcome_contract_sha256,
            outcome_project_id=scenario.contract.project_id,
            outcome_id=scenario.contract.outcome_id,
            outcome_lineage_id=scenario.contract.lineage_id,
            scenario_target_path=scenario.request.target_path,
            applied_receipt_sha256s=result.applied_receipt_sha256s,
            replayed_receipt_sha256s=result.replayed_receipt_sha256s,
            lease_sha256=result.lease_sha256,
            lease_state=result.lease.state,
            outcome_allowed=result.decision.allowed,
            outcome_reason_code=result.decision.reason_code,
            disposition="would_allow" if result.decision.allowed else "would_deny",
            ordinary_approval_ignored=result.decision.ordinary_approval_ignored,
            cost_telemetry_ignored=result.decision.cost_telemetry_ignored,
            elapsed_telemetry_ignored=result.decision.elapsed_telemetry_ignored,
        )
    except OutcomePreWriteObservationError as exc:
        raw_receipt_id = ordinary_decision.get("receipt_id")
        ordinary_receipt_id = (
            ordinary.receipt_id
            if ordinary is not None
            else raw_receipt_id
            if isinstance(raw_receipt_id, str) and raw_receipt_id.strip()
            else None
        )
        record = OutcomePreWriteObservationFailureV1(
            correlation_receipt_id=_correlation_receipt_id(),
            observed_at=datetime.now(UTC),
            ordinary_receipt_id=ordinary_receipt_id,
            ordinary=ordinary,
            **_selection_fields(_selection),
            scenario_path=str(scenario_path),
            scenario_file_sha256=scenario_file_sha256,
            scenario_sha256=scenario_sha256,
            outcome_contract_sha256=outcome_contract_sha256,
            error_code=exc.code,
            error_message=str(exc),
        )
    except (ContinuationError, ValidationError) as exc:
        code = exc.code if isinstance(exc, ContinuationError) else "scenario_evaluation_invalid"
        record = OutcomePreWriteObservationFailureV1(
            correlation_receipt_id=_correlation_receipt_id(),
            observed_at=datetime.now(UTC),
            ordinary_receipt_id=ordinary.receipt_id if ordinary is not None else None,
            ordinary=ordinary,
            **_selection_fields(_selection),
            scenario_path=str(scenario_path),
            scenario_file_sha256=scenario_file_sha256,
            scenario_sha256=scenario_sha256,
            outcome_contract_sha256=outcome_contract_sha256,
            error_code=code,
            error_message=str(exc),
        )
    _append_record(receipt_path, record)
    return record


def observe_selected_prewrite_outcome(
    ordinary_decision: dict[str, Any],
    *,
    receipt_path: Path = DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH,
) -> OutcomePreWriteObservationRecordV1:
    """Resolve exact-session selected state and append one observe-only result."""

    ordinary: OrdinaryPreWriteIdentityV1 | None = None
    try:
        ordinary = _ordinary_identity(ordinary_decision)
        selection = resolve_selected_outcome_for_prewrite(
            agent=ordinary.client,
            project=ordinary.claim_project,
            scope=ordinary.claim_scope,
            session_id=ordinary.session_id,
            repo_root=ordinary.repo_root,
            worktree_path=ordinary.worktree_path,
            branch=ordinary.branch,
            claim_source_file=ordinary.claim_source_file,
            target_path=ordinary.normalized_target_path,
        )
    except (OutcomePreWriteObservationError, OutcomeSelectionError) as exc:
        raw_receipt_id = ordinary_decision.get("receipt_id")
        ordinary_receipt_id = (
            ordinary.receipt_id
            if ordinary is not None
            else raw_receipt_id
            if isinstance(raw_receipt_id, str) and raw_receipt_id.strip()
            else None
        )
        record = OutcomePreWriteObservationFailureV1(
            correlation_receipt_id=_correlation_receipt_id(),
            observed_at=datetime.now(UTC),
            ordinary_receipt_id=ordinary_receipt_id,
            ordinary=ordinary,
            scenario_path="<selected-outcome>",
            error_code=exc.code,
            error_message=str(exc),
        )
        _append_record(receipt_path, record)
        return record
    return observe_prewrite_outcome(
        ordinary_decision,
        scenario_path=Path(selection.scenario_path),
        receipt_path=receipt_path,
        _selection=selection,
    )


def load_observation_records(path: Path) -> list[OutcomePreWriteObservationRecordV1]:
    """Parse an append-only observation log into strict typed records."""

    try:
        lines = path.expanduser().read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise OutcomePreWriteObservationError(
            "observation_log_read_failed",
            f"unable to read outcome observation log: {exc}",
        ) from exc
    records: list[OutcomePreWriteObservationRecordV1] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise TypeError("record must be a JSON object")
            record_type = payload.get("record_type")
            record: OutcomePreWriteObservationRecordV1
            if record_type == "outcome_prewrite_correlation":
                record = OutcomePreWriteCorrelationV1.model_validate(payload)
            elif record_type == "outcome_prewrite_observation_failure":
                record = OutcomePreWriteObservationFailureV1.model_validate(payload)
            else:
                raise ValueError(f"unsupported record_type {record_type!r}")
        except (json.JSONDecodeError, TypeError, ValidationError, ValueError) as exc:
            raise OutcomePreWriteObservationError(
                "observation_log_invalid",
                f"invalid outcome observation record at line {line_number}: {exc}",
            ) from exc
        records.append(record)
    return records


__all__ = [
    "DEFAULT_OUTCOME_PREWRITE_RECEIPT_PATH",
    "OrdinaryPreWriteIdentityV1",
    "OutcomePreWriteCorrelationV1",
    "OutcomePreWriteObservationError",
    "OutcomePreWriteObservationFailureV1",
    "OutcomePreWriteObservationRecordV1",
    "load_observation_records",
    "observe_prewrite_outcome",
    "observe_selected_prewrite_outcome",
]
