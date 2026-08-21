from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    ContinuationError,
    EvidenceBindingV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeLeaseV1,
    OutcomeProgressReceiptV1,
    RecoveryLeaseV1,
    admit_operation,
    canonical_sha256,
    evaluate_scenario,
    issue_initial_lease,
    load_scenario,
    transition_lease,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILE_SHA256 = "9eeaa7d7a8dc7b9b674db585842ee7cfb90c327e75e222b0c970333cca3aca96"


def _contract() -> OutcomeContractV1:
    return OutcomeContractV1(
        outcome_id="status-cli-json-outcome",
        owner_class="brian",
        project_id="enforced-planning",
        lineage_id="status-cli-json-lineage",
        predecessor_lineage_ids=[],
        intended_consumer="A user running the configured status-cli task",
        outcome="The configured status CLI emits its independently verified JSON result.",
        canonical_journey={
            "starting_state": "The Plan 62 status-cli governed baseline is prepared.",
            "input": "python src/status_cli.py --json",
            "action": "Run the configured requested command through the governed task.",
            "observable_result": '{"project_id":"status-cli","status":"adapter-placeholder"}',
            "failure_signal": "The command fails or emits any other output.",
        },
        baseline_revision="c9d77fa68ffef727e0a334ade644859642dea766",
        allowed_scope=["src/status_cli.py", "README.md", "docs/plans/"],
        progress_dimensions=["behavior", "reachability", "decision_quality"],
    )


def _evidence(receipt_id: str) -> EvidenceBindingV1:
    return EvidenceBindingV1(
        source_revision="0c6eab42d4ba092391ed5418b62352475b29d7d8",
        configuration_sha256=PROFILE_SHA256,
        route="status-cli-json/requested-command",
        command=["python", "src/status_cli.py", "--json"],
        observation_sha256=hashlib.sha256(receipt_id.encode()).hexdigest(),
        artifact_refs=["docs/evidence/plan62_status_cli_delivery_receipt.json"],
        observed_at="2026-08-20T12:00:00Z",
    )


def _receipt(
    contract: OutcomeContractV1,
    receipt_id: str,
    progress_kind: str,
    *,
    prior_receipt_sha256: str | None = None,
    failure_boundary: str | None = None,
    discriminating_evidence: bool = False,
) -> OutcomeProgressReceiptV1:
    values: dict[str, object] = {
        "receipt_id": receipt_id,
        "outcome_contract_sha256": canonical_sha256(contract),
        "prior_receipt_sha256": prior_receipt_sha256,
        "progress_kind": progress_kind,
        "dimension": "behavior" if progress_kind != "decision_changing_learning" else "decision_quality",
        "summary": f"Observed {progress_kind} for the stable status-cli journey.",
        "evidence": _evidence(receipt_id),
        "failure_boundary": failure_boundary,
        "discriminating_evidence": discriminating_evidence,
    }
    if progress_kind == "decision_changing_learning":
        values["decision_delta"] = "Reject the current adapter and test the bounded replacement next."
    if progress_kind == "direct_blocker_removed":
        values["failure_boundary"] = "status-cli-json-output"
        values["exact_replay_result"] = "The same requested command now emits the exact expected JSON."
    return OutcomeProgressReceiptV1.model_validate(values)


@pytest.mark.parametrize(
    "progress_kind",
    ["behavioral_advance", "direct_blocker_removed", "decision_changing_learning"],
)
def test_each_progress_class_activates_and_resets_the_lease(progress_kind: str) -> None:
    contract = _contract()
    lease = OutcomeLeaseV1(
        lease_id="status-cli-json-lease",
        outcome_contract_sha256=canonical_sha256(contract),
        state="recovery_required",
        consecutive_non_outcome_increments=2,
        current_failure_boundary="status-cli-json-output",
        same_boundary_failures=2,
    )

    transitioned = transition_lease(contract, lease, _receipt(contract, "progress-1", progress_kind))

    assert transitioned.applied is True
    assert transitioned.lease.state == "active"
    assert transitioned.lease.consecutive_non_outcome_increments == 0
    assert transitioned.lease.same_boundary_failures == 0
    assert transitioned.lease.last_progress_receipt_sha256 == transitioned.receipt_sha256


def test_two_non_outcomes_require_recovery_and_ignore_ordinary_approval_and_cost() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")
    first = _receipt(contract, "motion-1", "non_outcome", failure_boundary="status-cli-json-output")
    after_first = transition_lease(contract, lease, first).lease
    second = _receipt(
        contract,
        "motion-2",
        "non_outcome",
        prior_receipt_sha256=canonical_sha256(first),
        failure_boundary="status-cli-json-output",
    )
    after_second = transition_lease(contract, after_first, second).lease

    assert after_first.state == "active"
    assert after_second.state == "recovery_required"
    assert after_second.consecutive_non_outcome_increments == 2

    plain = AdmissionRequestV1(operation="product_write", target_path="src/status_cli.py")
    approved = AdmissionRequestV1(
        operation="product_write",
        target_path="src/status_cli.py",
        ordinary_approval=True,
        approval_text="I approve, continue",
        cost_telemetry_usd=Decimal(1000000),
        elapsed_telemetry_seconds=999999,
    )
    plain_decision = admit_operation(contract, after_second, plain)
    approved_decision = admit_operation(contract, after_second, approved)

    assert plain_decision == approved_decision
    assert plain_decision.allowed is False
    assert plain_decision.reason_code == "recovery_required"
    assert "exact_replay" in plain_decision.permitted_next_actions
    assert "bounded_recovery_action" in plain_decision.permitted_next_actions


def test_third_same_boundary_failure_without_new_evidence_stalls() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")
    prior: str | None = None
    for index in range(1, 4):
        receipt = _receipt(
            contract,
            f"motion-{index}",
            "non_outcome",
            prior_receipt_sha256=prior,
            failure_boundary="status-cli-json-output",
        )
        transition = transition_lease(contract, lease, receipt)
        lease = transition.lease
        prior = transition.receipt_sha256

    assert lease.state == "stalled"
    assert lease.same_boundary_failures == 3
    decision = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(
            operation="claim_create",
            target_path="src/status_cli.py",
            ordinary_approval=True,
        ),
    )
    assert decision.allowed is False
    assert decision.reason_code == "outcome_stalled"


def test_new_discriminating_evidence_does_not_count_as_same_boundary_retry() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")
    first = _receipt(contract, "motion-1", "non_outcome", failure_boundary="status-cli-json-output")
    first_result = transition_lease(contract, lease, first)
    second = _receipt(
        contract,
        "motion-2",
        "non_outcome",
        prior_receipt_sha256=first_result.receipt_sha256,
        failure_boundary="status-cli-json-output",
        discriminating_evidence=True,
    )
    second_result = transition_lease(contract, first_result.lease, second)

    assert second_result.lease.state == "recovery_required"
    assert second_result.lease.same_boundary_failures == 1


def test_duplicate_receipt_is_a_noop_not_a_renewal() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")
    receipt = _receipt(contract, "progress-1", "behavioral_advance")
    first = transition_lease(contract, lease, receipt)
    replay = transition_lease(contract, first.lease, receipt)

    assert replay.applied is False
    assert replay.replayed is True
    assert replay.lease == first.lease


def test_broken_receipt_lineage_fails_loud() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")
    first = _receipt(contract, "motion-1", "non_outcome")
    after_first = transition_lease(contract, lease, first).lease
    broken = _receipt(
        contract,
        "motion-2",
        "non_outcome",
        prior_receipt_sha256="f" * 64,
    )

    with pytest.raises(ContinuationError, match="receipt lineage") as exc_info:
        transition_lease(contract, after_first, broken)
    assert exc_info.value.code == "receipt_lineage_mismatch"


def test_receipt_dimension_must_be_declared_by_the_contract() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")
    receipt = _receipt(contract, "progress-1", "behavioral_advance").model_copy(
        update={"dimension": "repository_count"}
    )

    with pytest.raises(ContinuationError, match="dimension") as exc_info:
        transition_lease(contract, lease, receipt)
    assert exc_info.value.code == "receipt_dimension_mismatch"


def test_contract_and_receipt_reject_unsafe_or_incomplete_inputs() -> None:
    with pytest.raises(ValidationError, match="portable root-relative"):
        _contract().model_copy(update={"allowed_scope": ["../outside.py"]}).model_dump()
        OutcomeContractV1.model_validate(
            {**_contract().model_dump(), "allowed_scope": ["../outside.py"]}
        )

    with pytest.raises(ValidationError, match="decision_delta"):
        OutcomeProgressReceiptV1(
            receipt_id="learning-1",
            outcome_contract_sha256=canonical_sha256(_contract()),
            progress_kind="decision_changing_learning",
            dimension="decision_quality",
            summary="The probe changed the decision but omitted the delta.",
            evidence=_evidence("learning-1"),
        )

    with pytest.raises(ValidationError, match="timezone-aware"):
        EvidenceBindingV1(
            source_revision="0c6eab42d4ba092391ed5418b62352475b29d7d8",
            configuration_sha256=PROFILE_SHA256,
            route="status-cli-json/requested-command",
            command=["python", "src/status_cli.py", "--json"],
            observation_sha256="a" * 64,
            observed_at="2026-08-20T12:00:00",
        )


def test_active_lease_allows_only_in_scope_product_operations() -> None:
    contract = _contract()
    lease = issue_initial_lease(contract, lease_id="status-cli-json-lease")

    allowed = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(operation="commit", target_path="docs/plans/07_feature.md"),
    )
    denied = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(operation="product_write", target_path="new-front-door/app.py"),
    )

    assert allowed.allowed is True
    assert allowed.reason_code == "active_in_scope"
    assert denied.allowed is False
    assert denied.reason_code == "out_of_scope"


def test_recovery_lease_allows_only_its_exact_action_path_and_parent_lease() -> None:
    contract = _contract()
    lease = OutcomeLeaseV1(
        lease_id="status-cli-json-lease",
        outcome_contract_sha256=canonical_sha256(contract),
        state="recovery_required",
        consecutive_non_outcome_increments=2,
        current_failure_boundary="status-cli-json-output",
        same_boundary_failures=2,
    )
    recovery = RecoveryLeaseV1(
        recovery_lease_id="status-cli-json-recovery-1",
        outcome_contract_sha256=canonical_sha256(contract),
        parent_lease_sha256=canonical_sha256(lease),
        failure_or_question="Why does the exact status-cli JSON replay still fail?",
        changed_causal_hypothesis="The serializer, not argument parsing, changes key ordering.",
        allowed_action="inspect-and-repair-serializer",
        allowed_paths=["src/status_cli.py"],
        exact_replay_or_readout="python src/status_cli.py --json",
        stopping_condition="Stop after one repair and the exact replay result.",
    )

    allowed = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(
            operation="recovery_action",
            target_path="src/status_cli.py",
            recovery_action="inspect-and-repair-serializer",
        ),
        recovery_lease=recovery,
    )
    wrong_path = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(
            operation="recovery_action",
            target_path="new-front-door/app.py",
            recovery_action="inspect-and-repair-serializer",
        ),
        recovery_lease=recovery,
    )
    general_write = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(operation="product_write", target_path="src/status_cli.py"),
        recovery_lease=recovery,
    )

    assert allowed.allowed is True
    assert allowed.reason_code == "bounded_recovery_allowed"
    assert wrong_path.allowed is False
    assert wrong_path.reason_code == "recovery_path_mismatch"
    assert general_write.allowed is False
    assert general_write.reason_code == "recovery_required"


@pytest.mark.parametrize("state", ["complete", "parked"])
def test_terminal_states_cannot_use_a_recovery_lease(state: str) -> None:
    contract = _contract()
    lease = OutcomeLeaseV1(
        lease_id="status-cli-json-lease",
        outcome_contract_sha256=canonical_sha256(contract),
        state=state,
    )
    recovery = RecoveryLeaseV1(
        recovery_lease_id="status-cli-json-recovery-1",
        outcome_contract_sha256=canonical_sha256(contract),
        parent_lease_sha256=canonical_sha256(lease),
        failure_or_question="Why should a terminal lease accept more implementation?",
        changed_causal_hypothesis="It should not; restart review owns any later implementation.",
        allowed_action="repair-terminal-state",
        allowed_paths=["src/status_cli.py"],
        exact_replay_or_readout="python src/status_cli.py --json",
        stopping_condition="Stop without changing the terminal lineage.",
    )

    decision = admit_operation(
        contract,
        lease,
        AdmissionRequestV1(
            operation="recovery_action",
            target_path="src/status_cli.py",
            recovery_action="repair-terminal-state",
        ),
        recovery_lease=recovery,
    )

    assert decision.allowed is False
    assert decision.reason_code == f"outcome_{state}"


@pytest.mark.parametrize("state", ["recovery_required", "stalled", "complete", "parked"])
@pytest.mark.parametrize(
    "operation",
    ["passive_inspection", "exact_replay", "evidence_preservation", "closeout"],
)
def test_non_active_states_preserve_passive_and_closeout_actions(state: str, operation: str) -> None:
    contract = _contract()
    values = {
        "lease_id": "status-cli-json-lease",
        "outcome_contract_sha256": canonical_sha256(contract),
        "state": state,
        "consecutive_non_outcome_increments": 2 if state == "recovery_required" else 0,
        "current_failure_boundary": "status-cli-json-output" if state == "recovery_required" else None,
        "same_boundary_failures": 2 if state == "recovery_required" else 0,
    }
    if state == "stalled":
        values.update(
            consecutive_non_outcome_increments=3,
            current_failure_boundary="status-cli-json-output",
            same_boundary_failures=3,
        )
    lease = OutcomeLeaseV1.model_validate(values)

    decision = admit_operation(contract, lease, AdmissionRequestV1(operation=operation))

    assert decision.allowed is True
    assert decision.reason_code == "passive_operation_allowed"


def test_scenario_evaluation_and_cli_are_machine_readable(tmp_path: Path) -> None:
    contract = _contract()
    receipt = _receipt(contract, "progress-1", "behavioral_advance")
    scenario = OutcomeContinuationScenarioV1(
        scenario_id="progress-scenario",
        contract=contract,
        starting_lease=issue_initial_lease(contract, lease_id="status-cli-json-lease"),
        receipts=[receipt],
        request=AdmissionRequestV1(
            operation="product_write",
            target_path="src/status_cli.py",
            cost_telemetry_usd=Decimal(5000),
        ),
    )
    result = evaluate_scenario(scenario)
    assert result.decision.allowed is True
    assert result.decision.reason_code == "active_in_scope"

    scenario_path = tmp_path / "scenario.json"
    scenario_path.write_text(scenario.model_dump_json(indent=2), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "outcome_continuation.py"),
            "evaluate",
            "--scenario",
            str(scenario_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["decision"]["allowed"] is True
    assert payload["lease_sha256"] == canonical_sha256(result.lease)


@pytest.mark.parametrize(
    ("filename", "allowed", "reason_code", "returncode"),
    [
        ("outcome-continuation-progress.json", True, "active_in_scope", 0),
        ("outcome-continuation-circular.json", False, "recovery_required", 1),
    ],
)
def test_checked_in_both_sign_scenarios(
    filename: str,
    allowed: bool,
    reason_code: str,
    returncode: int,
) -> None:
    scenario_path = ROOT / "examples" / "cleanroom-ecosystem" / filename
    result = evaluate_scenario(load_scenario(str(scenario_path)))

    assert result.decision.allowed is allowed
    assert result.decision.reason_code == reason_code
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "outcome_continuation.py"),
            "evaluate",
            "--scenario",
            str(scenario_path),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == returncode
    assert json.loads(completed.stdout)["decision"]["reason_code"] == reason_code
