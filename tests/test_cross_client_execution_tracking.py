from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from enforced_planning.outcome_continuation import (
    CanonicalJourneyV1,
    ContinuationError,
    EvidenceBindingV1,
    ExecutionItemStatus,
    ExecutionItemUpdateV1,
    ExecutionItemV1,
    ExecutionProjectionTransitionV1,
    ExecutionProjectionV1,
    GoalCompletionProposalV1,
    NativeProjectionObservationV1,
    OutcomeContractV1,
    OutcomeCriterionV1,
    OutcomeProgressReceiptV1,
    apply_execution_projection_transition,
    canonical_sha256,
    issue_initial_lease,
    propose_goal_completion,
    transition_lease,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
ARTIFACT = "a" * 64


def contract() -> OutcomeContractV1:
    return OutcomeContractV1(
        schema_version="1.2.0",
        outcome_id="cross-client-fixture",
        owner_class="coordinator",
        project_id="enforced-planning",
        lineage_id="cross-client-fixture-v1",
        portfolio_class="product",
        intended_consumer="Brian reviewing cross-client execution state",
        outcome="Two stable execution items close two frozen outcome criteria.",
        canonical_journey=CanonicalJourneyV1(
            starting_state="Two client projections begin with the same pending items.",
            input="Complete both items through native client surfaces.",
            action="Attempt completion before and after current criterion evidence.",
            observable_result="Incomplete closure is denied and evidenced closure succeeds once.",
            failure_signal="A green checklist or replay closes the goal without current evidence.",
        ),
        baseline_revision="2266471",
        allowed_scope=["src/", "tests/"],
        progress_dimensions=["fixture"],
        success_criteria=[
            OutcomeCriterionV1(
                criterion_id="criterion-one",
                description="The first user-visible fixture condition is independently verified.",
            ),
            OutcomeCriterionV1(
                criterion_id="criterion-two",
                description="The second user-visible fixture condition is independently verified.",
            ),
        ],
    )


def projection(*, status: ExecutionItemStatus = "pending") -> ExecutionProjectionV1:
    selected = contract()
    return ExecutionProjectionV1(
        projection_id="cross-client-fixture-projection",
        outcome_contract_sha256=canonical_sha256(selected),
        projection_revision=1,
        items=[
            ExecutionItemV1(
                item_id="item-one",
                display_name="First visible item",
                status=status,
                criterion_ids=["criterion-one"],
                dependency_ids=[],
                owner_role="coordinator",
                source_kind="company-work-unit",
                source_ref="plan137:xcet-01:item-one",
            ),
            ExecutionItemV1(
                item_id="item-two",
                display_name="Second visible item",
                status=status,
                criterion_ids=["criterion-two"],
                dependency_ids=["item-one"],
                owner_role="coordinator",
                source_kind="company-work-unit",
                source_ref="plan137:xcet-01:item-two",
            ),
        ],
    )


def evidence_receipt(*, receipt_id: str, prior: str | None, criteria: list[str]) -> OutcomeProgressReceiptV1:
    selected = contract()
    return OutcomeProgressReceiptV1(
        receipt_id=receipt_id,
        outcome_contract_sha256=canonical_sha256(selected),
        prior_receipt_sha256=prior,
        progress_kind="behavioral_advance",
        dimension="fixture",
        summary="Independent evidence closes the named fixture criteria.",
        evidence=EvidenceBindingV1(
            source_revision="2266471",
            configuration_sha256="b" * 64,
            route="public-local-fixture",
            command=["fixture", "verify"],
            observation_sha256="c" * 64,
            artifact_refs=["fixture-result.json"],
            observed_at=NOW,
        ),
        discriminating_evidence=True,
        artifact_sha256=ARTIFACT,
        artifact_disposition="evidenced",
        criterion_ids=criteria,
        producer_id="fixture-producer",
        verifier_id="fixture-verifier",
        verification_role="independent",
    )


def completion_proposal(lease_sha256: str, evidence_revision: str, projection_sha256: str) -> GoalCompletionProposalV1:
    return GoalCompletionProposalV1(
        proposal_id="close-fixture-goal",
        outcome_contract_sha256=canonical_sha256(contract()),
        expected_lease_sha256=lease_sha256,
        execution_projection_sha256=projection_sha256,
        artifact_sha256=ARTIFACT,
        evidence_revision=evidence_revision,
        proposed_by="fixture-coordinator",
    )


def test_transition_keeps_identity_across_rename_reorder_and_exact_replay() -> None:
    starting = projection()
    first = ExecutionProjectionTransitionV1(
        transition_id="finish-first-item",
        expected_projection_sha256=canonical_sha256(starting),
        actor_id="fixture-coordinator",
        source_client="codex",
        item_updates=[ExecutionItemUpdateV1(item_id="item-one", status="completed")],
    )
    after_first = apply_execution_projection_transition(starting, first).projection
    second = ExecutionProjectionTransitionV1(
        transition_id="finish-and-reorder",
        expected_projection_sha256=canonical_sha256(after_first),
        actor_id="fixture-coordinator",
        source_client="claude",
        item_updates=[
            ExecutionItemUpdateV1(
                item_id="item-two",
                display_name="Renamed second item",
                status="completed",
            )
        ],
        display_order=["item-two", "item-one"],
    )

    applied = apply_execution_projection_transition(after_first, second)
    replayed = apply_execution_projection_transition(applied.projection, second)

    assert applied.applied is True
    assert replayed.replayed is True
    assert replayed.projection == applied.projection
    assert [item.item_id for item in applied.projection.items] == ["item-two", "item-one"]
    assert applied.projection.items[0].display_name == "Renamed second item"


def test_transition_rejects_stale_revision_collision_and_unmet_dependency() -> None:
    starting = projection()
    stale = ExecutionProjectionTransitionV1(
        transition_id="stale-transition",
        expected_projection_sha256="d" * 64,
        actor_id="fixture-coordinator",
        source_client="codex",
        item_updates=[ExecutionItemUpdateV1(item_id="item-one", status="completed")],
    )
    with pytest.raises(ContinuationError, match="expected projection"):
        apply_execution_projection_transition(starting, stale)

    dependency_violation = ExecutionProjectionTransitionV1(
        transition_id="skip-dependency",
        expected_projection_sha256=canonical_sha256(starting),
        actor_id="fixture-coordinator",
        source_client="claude",
        item_updates=[ExecutionItemUpdateV1(item_id="item-two", status="completed")],
    )
    with pytest.raises(ContinuationError, match="unresolved dependencies"):
        apply_execution_projection_transition(starting, dependency_violation)

    accepted = ExecutionProjectionTransitionV1(
        transition_id="same-identity",
        expected_projection_sha256=canonical_sha256(starting),
        actor_id="fixture-coordinator",
        source_client="codex",
        item_updates=[ExecutionItemUpdateV1(item_id="item-one", status="completed")],
    )
    current = apply_execution_projection_transition(starting, accepted).projection
    collision = accepted.model_copy(update={"source_client": "claude"})
    with pytest.raises(ContinuationError, match="idempotency collision"):
        apply_execution_projection_transition(current, collision)


def test_all_green_items_cannot_close_with_missing_or_stale_criterion_evidence() -> None:
    selected = contract()
    green = projection(status="completed")
    first = evidence_receipt(receipt_id="criterion-one-evidence", prior=None, criteria=["criterion-one"])
    lease = transition_lease(selected, issue_initial_lease(selected), first).lease
    proposal = completion_proposal(
        canonical_sha256(lease),
        canonical_sha256(first),
        canonical_sha256(green),
    )

    denied = propose_goal_completion(selected, lease, green, proposal)
    assert denied.accepted is False
    assert denied.reason_code == "criterion_evidence_missing"
    assert denied.missing_criterion_ids == ["criterion-two"]

    second = evidence_receipt(
        receipt_id="criterion-two-evidence",
        prior=canonical_sha256(first),
        criteria=["criterion-two"],
    )
    evidenced = transition_lease(selected, lease, second).lease
    stale = completion_proposal(
        canonical_sha256(evidenced),
        canonical_sha256(first),
        canonical_sha256(green),
    )
    stale_result = propose_goal_completion(selected, evidenced, green, stale)
    assert stale_result.accepted is False
    assert stale_result.reason_code == "completion_evidence_stale"


def test_current_evidenced_goal_closes_exactly_once() -> None:
    selected = contract()
    green = projection(status="completed")
    receipt = evidence_receipt(
        receipt_id="all-criteria-evidence",
        prior=None,
        criteria=["criterion-one", "criterion-two"],
    )
    lease = transition_lease(selected, issue_initial_lease(selected), receipt).lease
    proposal = completion_proposal(
        canonical_sha256(lease),
        canonical_sha256(receipt),
        canonical_sha256(green),
    )

    accepted = propose_goal_completion(selected, lease, green, proposal)
    replayed = propose_goal_completion(selected, accepted.lease, green, proposal)

    assert accepted.accepted is True
    assert accepted.applied is True
    assert accepted.lease.state == "complete"
    assert replayed.accepted is True
    assert replayed.applied is False
    assert replayed.replayed is True
    assert replayed.lease == accepted.lease

    collision = proposal.model_copy(update={"proposed_by": "replacement-coordinator"})
    collision_result = propose_goal_completion(selected, accepted.lease, green, collision)
    assert collision_result.accepted is False
    assert collision_result.reason_code == "completion_proposal_collision"


def test_completion_requires_every_criterion_to_remain_represented() -> None:
    selected = contract()
    green = projection(status="completed").model_copy(
        update={"items": [projection(status="completed").items[0]]}
    )
    receipt = evidence_receipt(
        receipt_id="all-criteria-evidence",
        prior=None,
        criteria=["criterion-one", "criterion-two"],
    )
    lease = transition_lease(selected, issue_initial_lease(selected), receipt).lease
    proposal = completion_proposal(
        canonical_sha256(lease),
        canonical_sha256(receipt),
        canonical_sha256(green),
    )

    denied = propose_goal_completion(selected, lease, green, proposal)
    assert denied.accepted is False
    assert denied.reason_code == "criterion_not_represented"
    assert denied.unrepresented_criterion_ids == ["criterion-two"]

    unknown_item = green.items[0].model_copy(
        update={"criterion_ids": ["criterion-one", "unknown-criterion"]}
    )
    unknown_projection = green.model_copy(update={"items": [unknown_item]})
    unknown_proposal = completion_proposal(
        canonical_sha256(lease),
        canonical_sha256(receipt),
        canonical_sha256(unknown_projection),
    )
    unknown = propose_goal_completion(selected, lease, unknown_projection, unknown_proposal)
    assert unknown.accepted is False
    assert unknown.reason_code == "execution_criterion_unknown"


def test_native_observation_distinguishes_match_divergence_and_unavailability() -> None:
    digest = canonical_sha256(projection())
    matched = NativeProjectionObservationV1(
        observation_id="codex-plan-event",
        source_client="codex",
        client_version="0.152.0",
        configuration_sha256="e" * 64,
        expected_projection_sha256=digest,
        native_projection_sha256=digest,
        native_event_id="turn-plan-updated-1",
        outcome="matched",
        reason_code="native_projection_matched",
        observed_at=NOW,
    )
    assert matched.outcome == "matched"

    divergent = matched.model_copy(
        update={
            "observation_id": "claude-task-divergence",
            "source_client": "claude",
            "native_projection_sha256": "f" * 64,
            "outcome": "divergent",
            "reason_code": "native_projection_differs",
        }
    )
    assert divergent.outcome == "divergent"

    with pytest.raises(ValidationError, match="matched observation"):
        NativeProjectionObservationV1(
            observation_id="false-native-match",
            source_client="codex",
            client_version="0.152.0",
            configuration_sha256="e" * 64,
            expected_projection_sha256=digest,
            native_projection_sha256="f" * 64,
            native_event_id="turn-plan-updated-2",
            outcome="matched",
            reason_code="native_projection_matched",
            observed_at=NOW,
        )

    unavailable = NativeProjectionObservationV1(
        observation_id="claude-tasks-unavailable",
        source_client="claude",
        client_version="unknown",
        configuration_sha256="e" * 64,
        expected_projection_sha256=digest,
        native_projection_sha256=None,
        native_event_id=None,
        outcome="unavailable",
        reason_code="task_tools_disabled",
        observed_at=NOW,
    )
    assert unavailable.native_projection_sha256 is None
