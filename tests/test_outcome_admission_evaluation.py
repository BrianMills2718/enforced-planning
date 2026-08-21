from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning.outcome_admission_evaluation import (
    OutcomeAdmissionEvaluationCaseV1,
    OutcomeAdmissionEvaluationSuiteV1,
    baseline_decision,
    candidate_decision,
    evaluate_admission_suite,
    file_sha256,
    load_evaluation_inputs,
    result_sha256,
    run_corruption_control,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "outcome_admission" / "plan121_cases.json"
POPULATION = ROOT / "evals" / "outcome_admission" / "plan121_population_snapshot.json"
CANDIDATE_REVISION = "a" * 40


@pytest.fixture
def loaded():  # type: ignore[no-untyped-def]
    return load_evaluation_inputs(cases_path=CASES, population_path=POPULATION)


def test_frozen_inputs_load_with_exact_pre_registered_shape(loaded) -> None:  # type: ignore[no-untyped-def]
    assert loaded.suite_file_sha256 == (
        "2ca787a98645d28004dd5abdf02cb82c1dc1afc6462c0a66981ebd09b47a383f"
    )
    assert loaded.population_file_sha256 == (
        "cd773a78a412be6c09814dd712d0b745de10611a0b600dc7608b55938c94e55d"
    )
    assert len(loaded.suite.cases) == 30
    assert len(loaded.population.claims) == 11
    assert sum(case.split == "positive_control" for case in loaded.suite.cases) == 1
    assert sum(case.split == "negative_control" for case in loaded.suite.cases) == 1
    assert sum(case.split == "calibration" for case in loaded.suite.cases) == 1


def test_every_frozen_candidate_decision_matches_disposition_and_reason(loaded) -> None:  # type: ignore[no-untyped-def]
    mismatches = []
    for case in loaded.suite.cases:
        decision = candidate_decision(case)
        if (
            decision.disposition != case.expected_disposition
            or decision.reason_code != case.expected_reason_code
        ):
            mismatches.append(case.case_id)
    assert mismatches == []


def test_primary_readout_passes_exact_zero_error_thresholds(loaded) -> None:  # type: ignore[no-untyped-def]
    result = evaluate_admission_suite(
        loaded,
        candidate_revision=CANDIDATE_REVISION,
        candidate_source_sha256=file_sha256(
            ROOT / "enforced_planning" / "outcome_admission_evaluation.py"
        ),
    )

    assert result.promotion_thresholds_passed is True
    assert result.decision == "continue_to_independent_signoff"
    assert result.positive_control_passed is True
    assert result.negative_control_passed is True
    assert result.metrics.total_cases == 30
    assert result.metrics.scored_cases == 29
    assert result.metrics.calibration_cases == 1
    assert result.metrics.matched_scored_cases == 29
    assert result.metrics.mismatched_scored_cases == 0
    assert result.metrics.critical_false_blocks == 0
    assert result.metrics.critical_false_allows == 0
    assert result.metrics.unexpected_scored_defers == 0
    assert result.metrics.safe_operation_recall == 1.0
    assert result.metrics.circular_or_bypass_rejection == 1.0
    assert result.metrics.baseline_false_blocks == 0
    assert result.metrics.baseline_false_allows == 13


def test_primary_readout_is_canonical_and_reproducible(loaded) -> None:  # type: ignore[no-untyped-def]
    source_sha = file_sha256(ROOT / "enforced_planning" / "outcome_admission_evaluation.py")
    first = evaluate_admission_suite(
        loaded,
        candidate_revision=CANDIDATE_REVISION,
        candidate_source_sha256=source_sha,
    )
    second = evaluate_admission_suite(
        loaded,
        candidate_revision=CANDIDATE_REVISION,
        candidate_source_sha256=source_sha,
    )

    assert first == second
    assert result_sha256(first) == result_sha256(second)


def test_corruption_control_inverts_label_and_is_detected(loaded) -> None:  # type: ignore[no-untyped-def]
    control = run_corruption_control(loaded)

    assert control.control_case_id == "control-positive-active-product"
    assert control.original_expected_disposition == "allow"
    assert control.corrupted_expected_disposition == "deny"
    assert control.candidate_disposition == "allow"
    assert control.mismatch_detected is True


def test_ordinary_denial_cannot_be_overridden_by_active_outcome(loaded) -> None:  # type: ignore[no-untyped-def]
    case = next(
        case
        for case in loaded.suite.cases
        if case.case_id == "heldout-ordinary-authority-denial"
    )

    assert baseline_decision(case).reason_code == "ordinary_authority_denied"
    assert candidate_decision(case).reason_code == "ordinary_authority_denied"


@pytest.mark.parametrize(
    ("case_id", "reason_code"),
    [
        ("validation-passive-inspection-stalled", "safe_operation_allowed"),
        ("validation-exact-replay-stalled", "safe_operation_allowed"),
        ("validation-evidence-preservation-parked", "safe_operation_allowed"),
        ("validation-clean-closeout-stalled", "safe_operation_allowed"),
        ("heldout-bounded-recovery-action", "bounded_recovery_active"),
        ("heldout-grandfathered-healthy-prewrite", "grandfathered_until_renewal"),
    ],
)
def test_required_false_block_cases_remain_allowed(
    loaded,  # type: ignore[no-untyped-def]
    case_id: str,
    reason_code: str,
) -> None:
    case = next(case for case in loaded.suite.cases if case.case_id == case_id)

    decision = candidate_decision(case)

    assert decision.disposition == "allow"
    assert decision.reason_code == reason_code


@pytest.mark.parametrize(
    ("case_id", "reason_code"),
    [
        ("validation-competing-product", "portfolio_slot_occupied"),
        ("validation-competing-nonproduct", "portfolio_slot_occupied"),
        ("validation-unallocated-plan", "portfolio_allocation_required"),
        ("validation-disposed-allocation-renewal", "portfolio_allocation_inactive"),
        ("validation-tampered-binding-prewrite", "portfolio_allocation_mismatch"),
        ("validation-stalled-heartbeat-with-approval", "outcome_stalled"),
        ("heldout-active-but-out-of-scope", "out_of_scope"),
        ("heldout-unbounded-recovery-write", "recovery_required"),
        ("heldout-equivalent-successor-laundering", "outcome_stalled"),
        ("heldout-high-cost-approval-nonprogress", "recovery_required"),
    ],
)
def test_required_bypass_cases_are_denied(
    loaded,  # type: ignore[no-untyped-def]
    case_id: str,
    reason_code: str,
) -> None:
    case = next(case for case in loaded.suite.cases if case.case_id == case_id)

    decision = candidate_decision(case)

    assert decision.disposition == "deny"
    assert decision.reason_code == reason_code


def test_allocation_bootstrap_allows_only_control_action(loaded) -> None:  # type: ignore[no-untyped-def]
    allowed = next(
        case
        for case in loaded.suite.cases
        if case.case_id == "validation-allocation-bootstrap"
    )
    denied = next(
        case
        for case in loaded.suite.cases
        if case.case_id == "validation-bootstrap-smuggles-product-write"
    )

    assert candidate_decision(allowed).reason_code == "admission_bootstrap_allowed"
    assert candidate_decision(denied).reason_code == "admission_bootstrap_scope_violation"


def test_cross_repository_membership_is_explicitly_deferred(loaded) -> None:  # type: ignore[no-untyped-def]
    case = next(case for case in loaded.suite.cases if case.split == "calibration")

    decision = candidate_decision(case)

    assert decision.disposition == "defer"
    assert decision.reason_code == "cross_repository_membership_not_promoted"


def test_population_byte_change_invalidates_load(tmp_path: Path) -> None:
    changed = json.loads(POPULATION.read_text(encoding="utf-8"))
    changed["privacy_note"] += " Changed after freeze."
    changed_path = tmp_path / POPULATION.name
    changed_path.write_text(json.dumps(changed), encoding="utf-8")

    with pytest.raises(ValueError, match="file digest"):
        load_evaluation_inputs(cases_path=CASES, population_path=changed_path)


def test_suite_rejects_duplicate_case_ids() -> None:
    payload = json.loads(CASES.read_text(encoding="utf-8"))
    payload["cases"][1]["case_id"] = payload["cases"][0]["case_id"]

    with pytest.raises(ValidationError, match="case_id values must be unique"):
        OutcomeAdmissionEvaluationSuiteV1.model_validate(payload)


def test_case_rejects_defer_outside_calibration() -> None:
    payload = json.loads(CASES.read_text(encoding="utf-8"))["cases"][0]
    payload["expected_disposition"] = "defer"

    with pytest.raises(ValidationError, match="only calibration cases may expect defer"):
        OutcomeAdmissionEvaluationCaseV1.model_validate(payload)


def test_cli_emits_primary_and_corruption_receipts() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_outcome_admission.py"),
            "--cases",
            str(CASES),
            "--population",
            str(POPULATION),
            "--candidate-revision",
            CANDIDATE_REVISION,
            "--corruption-control",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["result"]["promotion_thresholds_passed"] is True
    assert payload["corruption_control"]["mismatch_detected"] is True
    assert len(payload["result_sha256"]) == 64


def test_cli_fails_loud_on_changed_population(tmp_path: Path) -> None:
    changed_path = tmp_path / POPULATION.name
    changed_path.write_text(POPULATION.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "evaluate_outcome_admission.py"),
            "--cases",
            str(CASES),
            "--population",
            str(changed_path),
            "--candidate-revision",
            CANDIDATE_REVISION,
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "evaluation_invalid"
