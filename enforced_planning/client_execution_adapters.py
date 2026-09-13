"""Observe-only projections between canonical execution state and Claude Tasks."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enforced_planning.outcome_continuation import (
    ExecutionItemStatus,
    ExecutionProjectionV1,
    NativeProjectionObservationV1,
    canonical_sha256,
)

ClaudeTaskStatus = Literal["pending", "in_progress", "completed"]
ClaudeProjectionPhase = Literal["create", "update", "unavailable"]
ClaudeSnapshotOutcome = Literal["observed", "unavailable", "malformed"]
ClaudeProjectionDifferenceCode = Literal["task-set", "missing-task", "different-task"]
ClaudeProjectionReasonCode = Literal[
    "unsupported-canonical-status",
    "native-task-identities-required",
    "all-native-task-identities-bound",
]
ClaudeObservationReasonCode = Literal[
    "native-projection-matched",
    "native-projection-divergent",
    "native-snapshot-unavailable",
    "native-snapshot-malformed",
]


class ClaudeAdapterError(ValueError):
    """Typed adapter failure that cannot mutate canonical state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class StrictModel(BaseModel):
    """Forbid silent schema drift at the native adapter boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class ClaudeTaskBindingV1(StrictModel):
    """Identity assigned by Claude after one successful TaskCreate call."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    item_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    create_event_id: str = Field(min_length=1)


class ClaudeTaskCreateRequestV1(StrictModel):
    """One bounded TaskCreate request retaining neutral item identity."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    item_id: str = Field(min_length=1)
    subject: str = Field(min_length=3)
    description: str = Field(min_length=3)
    active_form: str = Field(min_length=3)

    def native_input(self) -> dict[str, object]:
        """Return exactly the TaskCreate payload, excluding adapter metadata."""

        return {
            "subject": self.subject,
            "description": self.description,
            "activeForm": self.active_form,
        }


class ClaudeTaskUpdateRequestV1(StrictModel):
    """One TaskUpdate request after every native task identity is known."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    item_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    subject: str = Field(min_length=3)
    description: str = Field(min_length=3)
    active_form: str = Field(min_length=3)
    status: ClaudeTaskStatus
    add_blocked_by: list[str] = Field(default_factory=list)

    def native_input(self) -> dict[str, object]:
        """Return exactly the TaskUpdate payload, excluding adapter metadata."""

        payload: dict[str, object] = {
            "taskId": self.task_id,
            "subject": self.subject,
            "description": self.description,
            "activeForm": self.active_form,
            "status": self.status,
        }
        if self.add_blocked_by:
            payload["addBlockedBy"] = self.add_blocked_by
        return payload


class ClaudeTaskProjectionPlanV1(StrictModel):
    """Create-first or update projection plan for Claude's assigned IDs."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    expected_projection_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    phase: ClaudeProjectionPhase
    reason_code: ClaudeProjectionReasonCode
    detail_item_ids: list[str] = Field(default_factory=list)
    create_requests: list[ClaudeTaskCreateRequestV1] = Field(default_factory=list)
    update_requests: list[ClaudeTaskUpdateRequestV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_phase_payload(self) -> ClaudeTaskProjectionPlanV1:
        if self.phase == "create" and (not self.create_requests or self.update_requests):
            raise ValueError("create phase requires only create_requests")
        if self.phase == "update" and (not self.update_requests or self.create_requests):
            raise ValueError("update phase requires only update_requests")
        if self.phase == "unavailable" and (self.create_requests or self.update_requests):
            raise ValueError("unavailable phase cannot emit native mutations")
        return self


class ClaudeTaskCreateResultV1(StrictModel):
    """Structured TaskCreate result; task identity comes from the result."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    subject: str = Field(min_length=3)


class ClaudeTaskRecordV1(StrictModel):
    """One TaskList/TaskGet record normalized by the host adapter."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    task_id: str = Field(min_length=1)
    subject: str = Field(min_length=3)
    description: str = Field(min_length=3)
    active_form: str = Field(min_length=3)
    status: ClaudeTaskStatus
    blocked_by: list[str] = Field(default_factory=list)


class ClaudeNativeProjectionObservationV1(NativeProjectionObservationV1):
    """Native observation with stable categories and structured Claude detail."""

    reason_code: ClaudeObservationReasonCode
    source_reason_code: str | None = Field(default=None, min_length=3)
    difference_codes: list[ClaudeProjectionDifferenceCode] = Field(default_factory=list)
    detail_item_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_difference_detail(self) -> ClaudeNativeProjectionObservationV1:
        if len(self.difference_codes) != len(set(self.difference_codes)):
            raise ValueError("difference_codes must be unique")
        if len(self.detail_item_ids) != len(set(self.detail_item_ids)):
            raise ValueError("detail_item_ids must be unique")
        if self.outcome == "divergent" and not self.difference_codes:
            raise ValueError("divergent Claude observation requires difference_codes")
        if self.outcome != "divergent" and (self.difference_codes or self.detail_item_ids):
            raise ValueError("only divergent Claude observations may include difference detail")
        if self.outcome in {"unavailable", "malformed"} and self.source_reason_code is None:
            raise ValueError(f"{self.outcome} Claude observation requires source_reason_code")
        if self.outcome in {"matched", "divergent"} and self.source_reason_code is not None:
            raise ValueError("observed Claude projections cannot include source_reason_code")
        return self


class ClaudeTaskSnapshotV1(StrictModel):
    """Typed result of one tool or TaskCompleted-hook observation."""

    schema_version: Literal["1.1.0"] = "1.1.0"
    observation_id: str = Field(min_length=1)
    client_version: str = Field(min_length=1)
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_at: datetime
    event_id: str | None = None
    outcome: ClaudeSnapshotOutcome
    reason_code: str = Field(min_length=3)
    tasks: list[ClaudeTaskRecordV1] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_snapshot(self) -> ClaudeTaskSnapshotV1:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.outcome == "observed" and not self.tasks:
            raise ValueError("observed snapshot requires task records")
        if self.outcome != "observed" and self.tasks:
            raise ValueError(f"{self.outcome} snapshot cannot claim task records")
        task_ids = [task.task_id for task in self.tasks]
        if len(task_ids) != len(set(task_ids)):
            raise ValueError("snapshot task IDs must be unique")
        return self


class ClaudeTaskEventCorrelationV1(StrictModel):
    """Per-task native event correlation without goal-completion authority."""

    schema_version: Literal["1.0.0"] = "1.0.0"
    event_id: str = Field(min_length=1)
    event_kind: Literal["task_created", "task_updated", "task_completed_hook"]
    item_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    observed_at: datetime
    canonical_completion_authorized: Literal[False] = False

    @model_validator(mode="after")
    def _require_aware_time(self) -> ClaudeTaskEventCorrelationV1:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return self


def _subject(item_id: str, display_name: str) -> str:
    return f"[{item_id}] {display_name}"


def _active_form(display_name: str) -> str:
    return f"Working: {display_name}"


def _description(*, source_kind: str, source_ref: str, criterion_ids: list[str]) -> str:
    return f"Source: {source_kind}:{source_ref}; criteria: {', '.join(criterion_ids)}"


def _claude_status(status: ExecutionItemStatus) -> ClaudeTaskStatus | None:
    return {
        "pending": "pending",
        "in_progress": "in_progress",
        "completed": "completed",
    }.get(status)  # type: ignore[return-value]


def _binding_map(
    projection: ExecutionProjectionV1,
    bindings: list[ClaudeTaskBindingV1],
) -> dict[str, ClaudeTaskBindingV1]:
    by_item = {binding.item_id: binding for binding in bindings}
    if len(by_item) != len(bindings):
        raise ClaudeAdapterError("duplicate_item_binding", "Claude bindings must name each item once")
    task_ids = [binding.task_id for binding in bindings]
    if len(task_ids) != len(set(task_ids)):
        raise ClaudeAdapterError("duplicate_task_binding", "Claude task IDs must be unique")
    known = {item.item_id for item in projection.items}
    unknown = sorted(set(by_item) - known)
    if unknown:
        raise ClaudeAdapterError("unknown_item_binding", "Claude bindings name unknown items: " + ", ".join(unknown))
    return by_item


def project_claude_tasks(
    projection: ExecutionProjectionV1,
    bindings: list[ClaudeTaskBindingV1],
) -> ClaudeTaskProjectionPlanV1:
    """Return the next native projection phase without changing canonical state."""

    expected_sha256 = canonical_sha256(projection)
    unsupported = sorted(item.item_id for item in projection.items if _claude_status(item.status) is None)
    if unsupported:
        return ClaudeTaskProjectionPlanV1(
            expected_projection_sha256=expected_sha256,
            phase="unavailable",
            reason_code="unsupported-canonical-status",
            detail_item_ids=unsupported,
        )

    by_item = _binding_map(projection, bindings)
    unbound = [item for item in projection.items if item.item_id not in by_item]
    if unbound:
        return ClaudeTaskProjectionPlanV1(
            expected_projection_sha256=expected_sha256,
            phase="create",
            reason_code="native-task-identities-required",
            create_requests=[
                ClaudeTaskCreateRequestV1(
                    item_id=item.item_id,
                    subject=_subject(item.item_id, item.display_name),
                    description=_description(
                        source_kind=item.source_kind,
                        source_ref=item.source_ref,
                        criterion_ids=item.criterion_ids,
                    ),
                    active_form=_active_form(item.display_name),
                )
                for item in unbound
            ],
        )

    return ClaudeTaskProjectionPlanV1(
        expected_projection_sha256=expected_sha256,
        phase="update",
        reason_code="all-native-task-identities-bound",
        update_requests=[
            ClaudeTaskUpdateRequestV1(
                item_id=item.item_id,
                task_id=by_item[item.item_id].task_id,
                subject=_subject(item.item_id, item.display_name),
                description=_description(
                    source_kind=item.source_kind,
                    source_ref=item.source_ref,
                    criterion_ids=item.criterion_ids,
                ),
                active_form=_active_form(item.display_name),
                status=_claude_status(item.status),  # type: ignore[arg-type]
                add_blocked_by=[by_item[dependency].task_id for dependency in item.dependency_ids],
            )
            for item in projection.items
        ],
    )


def bind_claude_task_create(
    request: ClaudeTaskCreateRequestV1,
    result: ClaudeTaskCreateResultV1,
) -> ClaudeTaskBindingV1:
    """Bind neutral identity only from a matching structured TaskCreate result."""

    if result.subject != request.subject:
        raise ClaudeAdapterError("task_create_subject_mismatch", "TaskCreate result does not match its request")
    return ClaudeTaskBindingV1(
        item_id=request.item_id,
        task_id=result.task_id,
        create_event_id=result.event_id,
    )


def correlate_claude_task_event(
    *,
    event_id: str,
    event_kind: Literal["task_created", "task_updated", "task_completed_hook"],
    task_id: str,
    bindings: list[ClaudeTaskBindingV1],
    observed_at: datetime,
) -> ClaudeTaskEventCorrelationV1:
    """Correlate a per-task event while explicitly denying goal authority."""

    matches = [binding for binding in bindings if binding.task_id == task_id]
    if len(matches) != 1:
        raise ClaudeAdapterError("task_event_unbound", "native event must match exactly one task binding")
    return ClaudeTaskEventCorrelationV1(
        event_id=event_id,
        event_kind=event_kind,
        item_id=matches[0].item_id,
        task_id=task_id,
        observed_at=observed_at,
    )


def observe_claude_snapshot(
    projection: ExecutionProjectionV1,
    bindings: list[ClaudeTaskBindingV1],
    snapshot: ClaudeTaskSnapshotV1,
) -> ClaudeNativeProjectionObservationV1:
    """Compare one typed native snapshot without mutating canonical state."""

    expected_sha256 = canonical_sha256(projection)
    if snapshot.outcome != "observed":
        unavailable_reason: ClaudeObservationReasonCode
        if snapshot.outcome == "unavailable":
            unavailable_reason = "native-snapshot-unavailable"
        else:
            unavailable_reason = "native-snapshot-malformed"
        return ClaudeNativeProjectionObservationV1(
            observation_id=snapshot.observation_id,
            source_client="claude",
            client_version=snapshot.client_version,
            configuration_sha256=snapshot.configuration_sha256,
            expected_projection_sha256=expected_sha256,
            native_event_id=snapshot.event_id,
            outcome=snapshot.outcome,
            reason_code=unavailable_reason,
            source_reason_code=snapshot.reason_code,
            observed_at=snapshot.observed_at,
        )

    by_item = _binding_map(projection, bindings)
    by_task = {task.task_id: task for task in snapshot.tasks}
    expected_task_ids = {binding.task_id for binding in bindings}
    expected_tasks: list[ClaudeTaskRecordV1] = []
    difference_codes: set[ClaudeProjectionDifferenceCode] = set()
    detail_item_ids: set[str] = set()
    if set(by_task) != expected_task_ids or len(bindings) != len(projection.items):
        difference_codes.add("task-set")
    for item in projection.items:
        binding = by_item.get(item.item_id)
        task = by_task.get(binding.task_id) if binding else None
        expected_status = _claude_status(item.status)
        expected_blockers = [by_item[dependency].task_id for dependency in item.dependency_ids if dependency in by_item]
        if binding is None or expected_status is None:
            difference_codes.add("missing-task" if binding is None else "different-task")
            detail_item_ids.add(item.item_id)
            continue
        expected_task = ClaudeTaskRecordV1(
            task_id=binding.task_id,
            subject=_subject(item.item_id, item.display_name),
            description=_description(
                source_kind=item.source_kind,
                source_ref=item.source_ref,
                criterion_ids=item.criterion_ids,
            ),
            active_form=_active_form(item.display_name),
            status=expected_status,
            blocked_by=expected_blockers,
        )
        expected_tasks.append(expected_task)
        if task is None:
            difference_codes.add("missing-task")
            detail_item_ids.add(item.item_id)
        elif _native_task_projection(task) != _native_task_projection(expected_task):
            difference_codes.add("different-task")
            detail_item_ids.add(item.item_id)

    expected_native_sha256 = _native_tasks_sha256(expected_tasks)
    observed_native_sha256 = _native_tasks_sha256(snapshot.tasks)
    matched = not difference_codes and observed_native_sha256 == expected_native_sha256
    return ClaudeNativeProjectionObservationV1(
        observation_id=snapshot.observation_id,
        source_client="claude",
        client_version=snapshot.client_version,
        configuration_sha256=snapshot.configuration_sha256,
        expected_projection_sha256=expected_native_sha256,
        native_projection_sha256=observed_native_sha256,
        native_event_id=snapshot.event_id,
        outcome="matched" if matched else "divergent",
        reason_code="native-projection-matched" if matched else "native-projection-divergent",
        observed_at=snapshot.observed_at,
        difference_codes=sorted(difference_codes),
        detail_item_ids=sorted(detail_item_ids),
    )


def _native_task_projection(task: ClaudeTaskRecordV1) -> dict[str, object]:
    """Return only native-visible task content in a stable representation."""

    return {
        "task_id": task.task_id,
        "subject": task.subject,
        "description": task.description,
        "active_form": task.active_form,
        "status": task.status,
        "blocked_by": sorted(task.blocked_by),
    }


def _native_tasks_sha256(tasks: list[ClaudeTaskRecordV1]) -> str:
    """Hash normalized native task content, excluding observation metadata."""

    normalized = {
        "tasks": [
            _native_task_projection(task)
            for task in sorted(tasks, key=lambda candidate: candidate.task_id)
        ]
    }
    return canonical_sha256(normalized)
