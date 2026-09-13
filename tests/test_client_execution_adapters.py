from __future__ import annotations

from datetime import UTC, datetime

import pytest

from enforced_planning.client_execution_adapters import (
    ClaudeAdapterError,
    ClaudeTaskBindingV1,
    ClaudeTaskCreateResultV1,
    ClaudeTaskRecordV1,
    ClaudeTaskSnapshotV1,
    bind_claude_task_create,
    correlate_claude_task_event,
    observe_claude_snapshot,
    project_claude_tasks,
)
from enforced_planning.outcome_continuation import (
    ExecutionItemV1,
    ExecutionProjectionV1,
    canonical_sha256,
)

NOW = datetime(2026, 9, 13, tzinfo=UTC)
CONFIGURATION = "c" * 64


def projection(*, first_status: str = "pending", second_status: str = "pending") -> ExecutionProjectionV1:
    return ExecutionProjectionV1(
        projection_id="claude-adapter-fixture",
        outcome_contract_sha256="a" * 64,
        projection_revision=1,
        items=[
            ExecutionItemV1(
                item_id="item-one",
                display_name="Inspect fixture",
                status=first_status,
                criterion_ids=["criterion-one"],
                owner_role="coordinator",
                source_kind="work-unit",
                source_ref="plan137:xcet-03:item-one",
            ),
            ExecutionItemV1(
                item_id="item-two",
                display_name="Verify fixture",
                status=second_status,
                criterion_ids=["criterion-two"],
                dependency_ids=["item-one"],
                owner_role="verifier",
                source_kind="work-unit",
                source_ref="plan137:xcet-03:item-two",
            ),
        ],
    )


def bindings() -> list[ClaudeTaskBindingV1]:
    return [
        ClaudeTaskBindingV1(item_id="item-one", task_id="1", create_event_id="create-1"),
        ClaudeTaskBindingV1(item_id="item-two", task_id="2", create_event_id="create-2"),
    ]


def snapshot(*, subject_two: str = "[item-two] Verify fixture") -> ClaudeTaskSnapshotV1:
    return ClaudeTaskSnapshotV1(
        observation_id="snapshot-1",
        client_version="2.1.269",
        configuration_sha256=CONFIGURATION,
        observed_at=NOW,
        event_id="task-list-1",
        outcome="observed",
        reason_code="task-list-observed",
        tasks=[
            ClaudeTaskRecordV1(
                task_id="1",
                subject="[item-one] Inspect fixture",
                status="pending",
            ),
            ClaudeTaskRecordV1(
                task_id="2",
                subject=subject_two,
                status="pending",
                blocked_by=["1"],
            ),
        ],
    )


def test_projection_creates_unbound_tasks_then_updates_assigned_ids() -> None:
    selected = projection(first_status="completed", second_status="in_progress")
    creates = project_claude_tasks(selected, [])

    assert creates.phase == "create"
    assert [request.item_id for request in creates.create_requests] == ["item-one", "item-two"]
    assert creates.create_requests[0].subject == "[item-one] Inspect fixture"
    assert "criterion-one" in creates.create_requests[0].description
    assert creates.create_requests[0].native_input() == {
        "subject": "[item-one] Inspect fixture",
        "description": "Source: work-unit:plan137:xcet-03:item-one; criteria: criterion-one",
        "activeForm": "Working: Inspect fixture",
    }

    first_binding = bind_claude_task_create(
        creates.create_requests[0],
        ClaudeTaskCreateResultV1(
            event_id="create-1",
            task_id="1",
            subject="[item-one] Inspect fixture",
        ),
    )
    updates = project_claude_tasks(selected, [first_binding, bindings()[1]])

    assert updates.phase == "update"
    assert [(request.task_id, request.status) for request in updates.update_requests] == [
        ("1", "completed"),
        ("2", "in_progress"),
    ]
    assert updates.update_requests[1].add_blocked_by == ["1"]
    assert updates.update_requests[1].native_input()["addBlockedBy"] == ["1"]


def test_task_identity_comes_from_matching_create_result() -> None:
    request = project_claude_tasks(projection(), []).create_requests[0]

    with pytest.raises(ClaudeAdapterError, match="does not match") as caught:
        bind_claude_task_create(
            request,
            ClaudeTaskCreateResultV1(
                event_id="create-wrong",
                task_id="99",
                subject="[other-item] Different task",
            ),
        )

    assert caught.value.code == "task_create_subject_mismatch"


def test_snapshot_matches_by_stable_binding_and_detects_visible_drift() -> None:
    selected = projection()
    matched = observe_claude_snapshot(selected, bindings(), snapshot())
    divergent = observe_claude_snapshot(
        selected,
        bindings(),
        snapshot(subject_two="[item-two] Stale display name"),
    )

    assert matched.outcome == "matched"
    assert matched.native_projection_sha256 == canonical_sha256(selected)
    assert divergent.outcome == "divergent"
    assert divergent.native_projection_sha256 != canonical_sha256(selected)
    assert "different:item-two" in divergent.reason_code


def test_rename_reorder_keeps_native_identity_from_bindings() -> None:
    selected = projection()
    first, second = selected.items
    renamed = first.model_copy(update={"display_name": "Inspect renamed fixture"})
    reordered = selected.model_copy(
        update={"projection_revision": 2, "items": [second, renamed]}
    )
    plan = project_claude_tasks(reordered, bindings())
    observed = ClaudeTaskSnapshotV1(
        observation_id="snapshot-reordered",
        client_version="2.1.269",
        configuration_sha256=CONFIGURATION,
        observed_at=NOW,
        event_id="task-list-reordered",
        outcome="observed",
        reason_code="task-list-observed",
        tasks=[
            ClaudeTaskRecordV1(
                task_id="2",
                subject="[item-two] Verify fixture",
                status="pending",
                blocked_by=["1"],
            ),
            ClaudeTaskRecordV1(
                task_id="1",
                subject="[item-one] Inspect renamed fixture",
                status="pending",
            ),
        ],
    )

    assert [request.task_id for request in plan.update_requests] == ["2", "1"]
    assert observe_claude_snapshot(reordered, bindings(), observed).outcome == "matched"


def test_unavailable_snapshot_is_explicit_and_cannot_claim_native_digest() -> None:
    selected = projection()
    observation = observe_claude_snapshot(
        selected,
        bindings(),
        ClaudeTaskSnapshotV1(
            observation_id="snapshot-unavailable",
            client_version="2.1.269",
            configuration_sha256=CONFIGURATION,
            observed_at=NOW,
            outcome="unavailable",
            reason_code="task-tools-disabled",
        ),
    )

    assert observation.outcome == "unavailable"
    assert observation.native_projection_sha256 is None
    assert observation.reason_code == "task-tools-disabled"


def test_task_completed_hook_is_correlated_but_never_authorizes_goal_completion() -> None:
    correlation = correlate_claude_task_event(
        event_id="hook-1",
        event_kind="task_completed_hook",
        task_id="2",
        bindings=bindings(),
        observed_at=NOW,
    )

    assert correlation.item_id == "item-two"
    assert correlation.canonical_completion_authorized is False


def test_unsupported_canonical_status_emits_no_native_mutation() -> None:
    plan = project_claude_tasks(projection(first_status="blocked"), bindings())

    assert plan.phase == "unavailable"
    assert plan.reason_code == "unsupported-canonical-status:item-one"
    assert plan.create_requests == []
    assert plan.update_requests == []


def test_duplicate_or_unknown_bindings_fail_before_projection() -> None:
    with pytest.raises(ClaudeAdapterError, match="unique") as duplicate:
        project_claude_tasks(
            projection(),
            [
                ClaudeTaskBindingV1(item_id="item-one", task_id="1", create_event_id="a"),
                ClaudeTaskBindingV1(item_id="item-two", task_id="1", create_event_id="b"),
            ],
        )
    assert duplicate.value.code == "duplicate_task_binding"

    with pytest.raises(ClaudeAdapterError, match="unknown") as unknown:
        project_claude_tasks(
            projection(),
            [ClaudeTaskBindingV1(item_id="unknown", task_id="3", create_event_id="c")],
        )
    assert unknown.value.code == "unknown_item_binding"
