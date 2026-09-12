from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from enforced_planning.outcome_continuation import (
    CanonicalJourneyV1,
    ContinuationError,
    EvidenceBindingV1,
    OutcomeContractV1,
    OutcomeCriterionV1,
    OutcomeProgressReceiptV1,
    canonical_sha256,
    evaluate_review_readiness,
    issue_initial_lease,
    transition_lease,
)

NOW = datetime(2026, 9, 12, tzinfo=UTC)
ARTIFACT_A = "a" * 64
ARTIFACT_B = "b" * 64


def contract() -> OutcomeContractV1:
    return OutcomeContractV1(
        schema_version="1.2.0",
        outcome_id="company-work-dashboard",
        owner_class="contributor",
        project_id="initiative-roadmap-dashboard",
        lineage_id="company-work-dashboard-v1",
        portfolio_class="product",
        intended_consumer="Brian reviewing all company work in a browser",
        outcome="Two distinct maps expose company work and company purpose.",
        canonical_journey=CanonicalJourneyV1(
            starting_state="The previously rejected dashboard is not review eligible.",
            input="Open the two dashboard routes.",
            action="Inspect both rendered maps and their source-backed fields.",
            observable_result="Company Work flows top-to-bottom and Purpose Map remains separate.",
            failure_signal="A coverage grid, sideways graph, or rejected revision is offered instead.",
        ),
        baseline_revision="5641c8d",
        allowed_scope=["src/", "tests/", "public/index.html"],
        progress_dimensions=["company-work", "purpose-map"],
        success_criteria=[
            OutcomeCriterionV1(
                criterion_id="company-work-top-to-bottom",
                description="Company Work renders the project and task DAG top-to-bottom.",
            ),
            OutcomeCriterionV1(
                criterion_id="purpose-map-separate",
                description="Purpose Map is a distinct stakeholder-to-project causal map.",
            ),
        ],
    )


def evidence() -> EvidenceBindingV1:
    return EvidenceBindingV1(
        source_revision="deadbee",
        configuration_sha256="c" * 64,
        route="browser",
        command=["browser-check", "--local"],
        observation_sha256="d" * 64,
        artifact_refs=["screenshot.png"],
        observed_at=NOW,
    )


def receipt(
    *,
    receipt_id: str,
    prior: str | None,
    artifact: str,
    criteria: list[str],
    role: str = "independent",
) -> OutcomeProgressReceiptV1:
    return OutcomeProgressReceiptV1(
        receipt_id=receipt_id,
        outcome_contract_sha256=canonical_sha256(contract()),
        prior_receipt_sha256=prior,
        progress_kind="behavioral_advance",
        dimension="company-work",
        summary="Independent browser evidence closes frozen outcome criteria.",
        evidence=evidence(),
        discriminating_evidence=True,
        artifact_sha256=artifact,
        artifact_disposition="evidenced",
        criterion_ids=criteria,
        verifier_id="browser-verifier",
        verification_role=role,
    )


def test_v12_contract_requires_success_criteria() -> None:
    payload = contract().model_dump(mode="json")
    payload["success_criteria"] = []
    with pytest.raises(ValidationError, match="require success_criteria"):
        OutcomeContractV1.model_validate(payload)


def test_review_ready_requires_every_criterion_on_exact_artifact() -> None:
    selected = contract()
    lease = issue_initial_lease(selected)
    first = receipt(
        receipt_id="first-criterion",
        prior=None,
        artifact=ARTIFACT_A,
        criteria=["company-work-top-to-bottom"],
    )
    lease = transition_lease(selected, lease, first).lease

    denied = evaluate_review_readiness(selected, lease, artifact_sha256=ARTIFACT_A)
    assert denied.review_ready is False
    assert denied.reason_code == "criterion_evidence_missing"
    assert denied.missing_criterion_ids == ["purpose-map-separate"]

    second = receipt(
        receipt_id="second-criterion",
        prior=canonical_sha256(first),
        artifact=ARTIFACT_A,
        criteria=["purpose-map-separate"],
    )
    lease = transition_lease(selected, lease, second).lease
    allowed = evaluate_review_readiness(selected, lease, artifact_sha256=ARTIFACT_A)
    assert allowed.review_ready is True
    assert allowed.reason_code == "all_criteria_evidenced"


def test_producer_cannot_self_verify_behavioral_progress() -> None:
    selected = contract()
    with pytest.raises(ContinuationError, match="independent criterion evidence"):
        transition_lease(
            selected,
            issue_initial_lease(selected),
            receipt(
                receipt_id="self-certified",
                prior=None,
                artifact=ARTIFACT_A,
                criteria=["company-work-top-to-bottom"],
                role="producer",
            ),
        )


def test_new_artifact_cannot_inherit_old_artifact_criteria() -> None:
    selected = contract()
    first = receipt(
        receipt_id="artifact-a",
        prior=None,
        artifact=ARTIFACT_A,
        criteria=["company-work-top-to-bottom", "purpose-map-separate"],
    )
    lease = transition_lease(selected, issue_initial_lease(selected), first).lease
    assert evaluate_review_readiness(selected, lease, artifact_sha256=ARTIFACT_A).review_ready

    second = receipt(
        receipt_id="artifact-b",
        prior=canonical_sha256(first),
        artifact=ARTIFACT_B,
        criteria=["purpose-map-separate"],
    )
    lease = transition_lease(selected, lease, second).lease
    denied = evaluate_review_readiness(selected, lease, artifact_sha256=ARTIFACT_B)
    assert denied.missing_criterion_ids == ["company-work-top-to-bottom"]


def test_rejected_artifact_remains_ineligible() -> None:
    selected = contract()
    passing = receipt(
        receipt_id="candidate-before-rejection",
        prior=None,
        artifact=ARTIFACT_A,
        criteria=["company-work-top-to-bottom", "purpose-map-separate"],
    )
    lease = transition_lease(selected, issue_initial_lease(selected), passing).lease
    rejection = OutcomeProgressReceiptV1(
        receipt_id="human-rejected-artifact",
        outcome_contract_sha256=canonical_sha256(selected),
        prior_receipt_sha256=canonical_sha256(passing),
        progress_kind="non_outcome",
        dimension="company-work",
        summary="Contributor rejected this exact artifact as the requested outcome.",
        evidence=evidence(),
        failure_boundary="rejected user-visible artifact",
        artifact_sha256=ARTIFACT_A,
        artifact_disposition="rejected",
    )
    lease = transition_lease(selected, lease, rejection).lease

    decision = evaluate_review_readiness(selected, lease, artifact_sha256=ARTIFACT_A)
    assert decision.review_ready is False
    assert decision.reason_code == "artifact_rejected"
    with pytest.raises(ContinuationError, match="rejected artifact"):
        transition_lease(
            selected,
            lease,
            receipt(
                receipt_id="try-to-revive",
                prior=canonical_sha256(rejection),
                artifact=ARTIFACT_A,
                criteria=["company-work-top-to-bottom", "purpose-map-separate"],
            ),
        )


def test_legacy_contract_does_not_gain_implicit_review_authority() -> None:
    payload = contract().model_dump(mode="json")
    payload["schema_version"] = "1.1.0"
    payload["success_criteria"] = []
    legacy = OutcomeContractV1.model_validate(payload)
    decision = evaluate_review_readiness(
        legacy,
        issue_initial_lease(legacy),
        artifact_sha256=ARTIFACT_A,
    )
    assert decision.review_ready is False
    assert decision.reason_code == "criterion_contract_not_configured"
