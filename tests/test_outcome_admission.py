from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from enforced_planning import outcome_admission, outcome_admission_evaluation, session_lifecycle
from enforced_planning.outcome_admission import (
    OutcomeAdmissionBootstrapV1,
    OutcomeAdmissionDecisionV1,
    OutcomeAdmissionRequestV1,
    OutcomeAdmissionResultV1,
    bootstrap_admission_result,
    build_outcome_admission_receipt,
    decide_outcome_admission,
    evaluate_first_consumer_bootstrap,
    evaluate_selected_outcome_admission,
    is_first_consumer_bootstrap_path,
    load_outcome_admission_receipts,
    record_outcome_admission,
)
from enforced_planning.outcome_admission_evaluation import (
    OutcomeAdmissionEvaluationSuiteV1,
    candidate_decision,
)
from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    canonical_sha256,
    evaluate_scenario,
)
from enforced_planning.outcome_selection import (
    OutcomeSelectionBindingV1,
    OutcomeSelectionError,
    ResolvedOutcomeSelectionV1,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "outcome_admission" / "plan121_cases.json"
CLI = ROOT / "scripts" / "outcome_admission.py"


def _frozen_suite() -> OutcomeAdmissionEvaluationSuiteV1:
    return OutcomeAdmissionEvaluationSuiteV1.model_validate_json(
        CASES.read_text(encoding="utf-8")
    )


def _resolved_selection(*, classed: bool = True) -> ResolvedOutcomeSelectionV1:
    contract_payload = {
        "schema_version": "1.1.0" if classed else "1.0.0",
        "outcome_id": "first-consumer-admission",
        "owner_class": "brian",
        "project_id": "enforced-planning",
        "lineage_id": "plan-122-admission",
        "predecessor_lineage_ids": ["plan-121-evaluation"],
        "intended_consumer": "Brian and his coding agents",
        "outcome": "One selected outcome controls supported continuation.",
        "canonical_journey": {
            "starting_state": "One exact live selected outcome is active.",
            "input": "One ordinary-authorized product write.",
            "action": "Resolve selected state and apply outcome admission.",
            "observable_result": "The active in-scope write is admitted.",
            "failure_signal": "Missing or stalled state still returns allow.",
        },
        "baseline_revision": "a" * 40,
        "allowed_scope": ["enforced_planning/outcome_admission.py"],
        "progress_dimensions": ["first-consumer admission"],
    }
    if classed:
        contract_payload["portfolio_class"] = "maintenance"
    contract = OutcomeContractV1.model_validate(contract_payload)
    scenario = OutcomeContinuationScenarioV1(
        scenario_id="plan122-active-admission",
        contract=contract,
        receipts=[],
        request=AdmissionRequestV1(
            operation="product_write",
            target_path="enforced_planning/outcome_admission.py",
        ),
    )
    evaluated = evaluate_scenario(scenario)
    binding = OutcomeSelectionBindingV1(
        schema_version="1.1.0" if classed else "1.0.0",
        selected_at=datetime(2026, 8, 21, 9, 30, tzinfo=UTC),
        execution_authority_ref="goal:first-consumer-admission",
        claim_plan_ref="goal:first-consumer-admission",
        agent="codex",
        project="enforced-planning",
        scope="plan122-test",
        session_id="codex:plan122-test",
        repo_root="/tmp/plan122-repo",
        worktree_path="/tmp/plan122-worktree",
        branch="plan122-test",
        tracker_path="/tmp/plan122-tracker.yaml",
        claim_source_file="/tmp/plan122-claim.yaml",
        claim_identity_sha256="b" * 64,
        scenario_ref="examples/plan122.json",
        scenario_file_sha256="c" * 64,
        scenario_id=scenario.scenario_id,
        scenario_sha256=evaluated.scenario_sha256,
        outcome_contract_sha256=evaluated.outcome_contract_sha256,
        outcome_id=contract.outcome_id,
        outcome_lineage_id=contract.lineage_id,
        predecessor_lineage_ids=tuple(contract.predecessor_lineage_ids),
        target_path="enforced_planning/outcome_admission.py",
        lease_sha256=evaluated.lease_sha256,
        lease_state=evaluated.lease.state,
        portfolio_allocation_id="plan122-maintenance" if classed else None,
        portfolio_allocation_sha256="d" * 64 if classed else None,
        portfolio_ledger_path="/tmp/plan122-ledger.json" if classed else None,
        outcome_allowed_at_selection=evaluated.decision.allowed,
        outcome_reason_code_at_selection=evaluated.decision.reason_code,
    )
    return ResolvedOutcomeSelectionV1(
        binding=binding,
        binding_sha256=canonical_sha256(binding),
        scenario_path="/tmp/plan122-worktree/examples/plan122.json",
        base_scenario_sha256=evaluated.scenario_sha256,
        effective_scenario=scenario,
        effective_scenario_sha256=evaluated.scenario_sha256,
        current_lease_sha256=evaluated.lease_sha256,
        current_lease_state=evaluated.lease.state,
        progress_transition_count=0,
    )


def _missing_selected_result() -> OutcomeAdmissionResultV1:
    return OutcomeAdmissionResultV1(
        source="selected",
        request=None,
        decision=OutcomeAdmissionDecisionV1(
            disposition="deny",
            reason_code="outcome_selection_required",
        ),
        resolution_error_code="selection_missing",
        resolution_error_message="exact session tracker has no selected outcome",
    )


def test_production_decision_reproduces_every_frozen_plan121_case() -> None:
    mismatches: list[str] = []
    for case in _frozen_suite().cases:
        decision = decide_outcome_admission(
            OutcomeAdmissionRequestV1(
                boundary=case.boundary,
                enforcement_scope=case.enforcement_scope,
                ordinary_allowed=case.ordinary_allowed,
                portfolio_state=case.portfolio_state,
                continuation_state=case.continuation_state,
                bootstrap_product_write_requested=case.bootstrap_product_write_requested,
            )
        )
        if (
            decision.disposition != case.expected_disposition
            or decision.reason_code != case.expected_reason_code
        ):
            mismatches.append(case.case_id)

    assert mismatches == []


def test_plan121_candidate_delegates_to_production_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[OutcomeAdmissionRequestV1] = []

    def fake_decision(request: OutcomeAdmissionRequestV1) -> OutcomeAdmissionDecisionV1:
        captured.append(request)
        return OutcomeAdmissionDecisionV1(
            disposition="deny",
            reason_code="delegated-production-decision",
        )

    monkeypatch.setattr(
        outcome_admission_evaluation,
        "decide_outcome_admission",
        fake_decision,
    )
    case = _frozen_suite().cases[0]

    decision = candidate_decision(case)

    assert len(captured) == 1
    assert captured[0].boundary == case.boundary
    assert decision.reason_code == "delegated-production-decision"


def test_first_consumer_bootstrap_allows_only_exact_plan_and_shared_paths() -> None:
    paths = (
        "docs/plans/122_first_consumer_outcome_admission.md",
        "docs/plans/122_first_consumer_outcome_admission_work_graph.json",
        "examples/owner-real-outcome-admission/plan122-maintenance-scenario.json",
        "docs/plans/CLAUDE.md",
        "ROADMAP.md",
    )

    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(plan_number=122, write_paths=paths)
    )

    assert result.allowed_paths == paths
    assert result.rejected_paths == ()
    assert result.decision.disposition == "allow"
    assert result.decision.reason_code == "admission_bootstrap_allowed"


@pytest.mark.parametrize(
    "path",
    [
        "enforced_planning/outcome_admission.py",
        "scripts/outcome_admission.py",
        "tests/test_outcome_admission.py",
        "docs/evidence/plan122_first_consumer_outcome_admission.json",
        "docs/plans/121_outcome_admission_false_block_evaluation.md",
        "examples/owner-real-outcome-admission/plan121-foreign.json",
        "../docs/plans/122_escape.md",
        "/tmp/plan122.json",
        "docs//plans/122_wrong.md",
    ],
)
def test_first_consumer_bootstrap_rejects_product_foreign_and_unsafe_paths(
    path: str,
) -> None:
    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=(
                "docs/plans/122_first_consumer_outcome_admission.md",
                path,
            ),
        )
    )

    assert result.rejected_paths == (path,)
    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "admission_bootstrap_scope_violation"


def test_empty_bootstrap_is_denied() -> None:
    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(plan_number=122, write_paths=())
    )

    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "admission_bootstrap_scope_violation"


def test_ordinary_denial_precedes_bootstrap_scope_denial() -> None:
    result = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=("enforced_planning/outcome_admission.py",),
            ordinary_allowed=False,
        )
    )

    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "ordinary_authority_denied"


def test_safe_boundary_requires_safe_scope() -> None:
    with pytest.raises(ValidationError, match="safe boundaries require always_safe"):
        OutcomeAdmissionRequestV1(
            boundary="closeout",
            enforcement_scope="new_or_renewed",
            ordinary_allowed=True,
            portfolio_state="active_exact",
            continuation_state="active_in_scope",
        )


def test_bootstrap_path_classifier_is_plan_bound() -> None:
    assert is_first_consumer_bootstrap_path(
        "docs/plans/122_first_consumer_outcome_admission.md",
        plan_number=122,
    )
    assert not is_first_consumer_bootstrap_path(
        "docs/plans/122_first_consumer_outcome_admission.md",
        plan_number=123,
    )


def test_bootstrap_cli_allows_exact_scope(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "bootstrap",
            "--plan",
            "122",
            "--write-path",
            "docs/plans/122_first_consumer_outcome_admission.md",
            "--write-path",
            "examples/owner-real-outcome-admission/plan122-maintenance-scenario.json",
            "--receipt-path",
            str(tmp_path / "allow.jsonl"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["decision"]["reason_code"] == "admission_bootstrap_allowed"


def test_bootstrap_cli_denies_source_smuggling(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "bootstrap",
            "--plan",
            "122",
            "--write-path",
            "docs/plans/122_first_consumer_outcome_admission.md",
            "--write-path",
            "enforced_planning/outcome_admission.py",
            "--receipt-path",
            str(tmp_path / "deny.jsonl"),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["rejected_paths"] == ["enforced_planning/outcome_admission.py"]
    assert payload["decision"]["reason_code"] == "admission_bootstrap_scope_violation"


def test_selected_classed_state_is_derived_and_admitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = _resolved_selection(classed=True)
    monkeypatch.setattr(
        outcome_admission,
        "resolve_selected_outcome_for_session",
        lambda **_kwargs: resolved,
    )

    result = evaluate_selected_outcome_admission(
        agent="codex",
        project="enforced-planning",
        scope="plan122-test",
        session_id="codex:plan122-test",
        repo_root="/tmp/plan122-repo",
        worktree_path="/tmp/plan122-worktree",
        branch="plan122-test",
        claim_source_file="/tmp/plan122-claim.yaml",
        boundary="heartbeat",
        ordinary_allowed=True,
        renewal=True,
    )

    assert result.decision.disposition == "allow"
    assert result.decision.reason_code == "outcome_admission_active"
    assert result.request is not None
    assert result.request.portfolio_state == "active_exact"
    assert result.request.continuation_state == "active_in_scope"
    assert result.selected_evidence is not None
    assert result.selected_evidence.selection_binding_sha256 == resolved.binding_sha256
    assert result.selected_evidence.portfolio_allocation_id == "plan122-maintenance"


def test_selected_legacy_state_is_grandfathered_only_before_renewal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = _resolved_selection(classed=False)
    monkeypatch.setattr(
        outcome_admission,
        "resolve_selected_outcome_for_session",
        lambda **_kwargs: resolved,
    )
    prewrite = evaluate_selected_outcome_admission(
        agent="codex",
        project="enforced-planning",
        scope="plan122-test",
        session_id="codex:plan122-test",
        repo_root="/tmp/plan122-repo",
        worktree_path="/tmp/plan122-worktree",
        branch="plan122-test",
        claim_source_file="/tmp/plan122-claim.yaml",
        boundary="prewrite",
        ordinary_allowed=True,
        renewal=False,
    )
    renewal = evaluate_selected_outcome_admission(
        agent="codex",
        project="enforced-planning",
        scope="plan122-test",
        session_id="codex:plan122-test",
        repo_root="/tmp/plan122-repo",
        worktree_path="/tmp/plan122-worktree",
        branch="plan122-test",
        claim_source_file="/tmp/plan122-claim.yaml",
        boundary="heartbeat",
        ordinary_allowed=True,
        renewal=False,
    )

    assert prewrite.decision.reason_code == "grandfathered_until_renewal"
    assert renewal.decision.disposition == "deny"
    assert renewal.decision.reason_code == "portfolio_allocation_required"


def test_selected_missing_state_denies_with_visible_source_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(**_kwargs: object) -> ResolvedOutcomeSelectionV1:
        raise OutcomeSelectionError(
            "selection_missing",
            "exact session tracker has no selected outcome",
        )

    monkeypatch.setattr(
        outcome_admission,
        "resolve_selected_outcome_for_session",
        missing,
    )

    result = evaluate_selected_outcome_admission(
        agent="codex",
        project="enforced-planning",
        scope="plan122-test",
        session_id="codex:plan122-test",
        repo_root="/tmp/plan122-repo",
        worktree_path="/tmp/plan122-worktree",
        branch="plan122-test",
        claim_source_file="/tmp/plan122-claim.yaml",
        boundary="heartbeat",
        ordinary_allowed=True,
        renewal=True,
    )

    assert result.request is None
    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "outcome_selection_required"
    assert result.resolution_error_code == "selection_missing"


def test_ordinary_denial_does_not_resolve_or_revive_selected_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def should_not_resolve(**_kwargs: object) -> ResolvedOutcomeSelectionV1:
        raise AssertionError("ordinary denial must short-circuit selected resolution")

    monkeypatch.setattr(
        outcome_admission,
        "resolve_selected_outcome_for_session",
        should_not_resolve,
    )

    result = evaluate_selected_outcome_admission(
        agent="codex",
        project="enforced-planning",
        scope="plan122-test",
        session_id="codex:plan122-test",
        repo_root="/tmp/plan122-repo",
        worktree_path="/tmp/plan122-worktree",
        branch="plan122-test",
        claim_source_file="/tmp/plan122-claim.yaml",
        boundary="heartbeat",
        ordinary_allowed=False,
        renewal=True,
    )

    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "ordinary_authority_denied"


def test_admission_receipt_is_append_only_and_digest_validated(tmp_path: Path) -> None:
    path = tmp_path / "outcome-admission.jsonl"
    result = bootstrap_admission_result(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=("docs/plans/122_first_consumer_outcome_admission.md",),
        )
    )

    first = record_outcome_admission(result, receipt_path=path)
    second = record_outcome_admission(result, receipt_path=path)
    loaded = load_outcome_admission_receipts(path)

    assert [item.receipt_id for item in loaded] == [first.receipt_id, second.receipt_id]
    assert first.result_sha256 == second.result_sha256
    assert path.read_text(encoding="utf-8").count("\n") == 2

    payload = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    evidence = payload["result"]["bootstrap_evidence"]
    evidence["bootstrap"]["plan_number"] = 123
    evidence["bootstrap"]["write_paths"] = [
        "docs/plans/123_first_consumer_outcome_admission.md"
    ]
    evidence["allowed_paths"] = ["docs/plans/123_first_consumer_outcome_admission.md"]
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="result_sha256"):
        load_outcome_admission_receipts(path)


def test_receipt_builder_rejects_naive_result_tamper() -> None:
    result = bootstrap_admission_result(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=("docs/plans/122_first_consumer_outcome_admission.md",),
        )
    )
    receipt = build_outcome_admission_receipt(
        result,
        observed_at=datetime(2026, 8, 21, 9, 45, tzinfo=UTC),
        receipt_id="oadm-" + "1" * 32,
    )
    payload = receipt.model_dump(mode="json")
    evidence = payload["result"]["bootstrap_evidence"]
    evidence["bootstrap"]["plan_number"] = 123
    evidence["bootstrap"]["write_paths"] = [
        "docs/plans/123_first_consumer_outcome_admission.md"
    ]
    evidence["allowed_paths"] = ["docs/plans/123_first_consumer_outcome_admission.md"]

    with pytest.raises(ValidationError, match="result_sha256"):
        outcome_admission.OutcomeAdmissionReceiptV1.model_validate(payload)


def test_result_contract_rejects_caller_asserted_selected_allow() -> None:
    request = OutcomeAdmissionRequestV1(
        boundary="heartbeat",
        enforcement_scope="new_or_renewed",
        ordinary_allowed=True,
        portfolio_state="active_exact",
        continuation_state="active_in_scope",
    )

    with pytest.raises(ValidationError, match="requires exact derived evidence"):
        OutcomeAdmissionResultV1(
            source="selected",
            request=request,
            decision=decide_outcome_admission(request),
        )


def test_bootstrap_result_rejects_fabricated_path_classification() -> None:
    valid = evaluate_first_consumer_bootstrap(
        OutcomeAdmissionBootstrapV1(
            plan_number=122,
            write_paths=("enforced_planning/outcome_admission.py",),
        )
    )
    payload = valid.model_dump(mode="json")
    payload["allowed_paths"] = ["enforced_planning/outcome_admission.py"]
    payload["rejected_paths"] = []

    with pytest.raises(ValidationError, match="fixed source set"):
        outcome_admission.OutcomeAdmissionBootstrapResultV1.model_validate(payload)


def test_bootstrap_session_denial_precedes_tracker_or_claim_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker_dir = tmp_path / "sessions"
    receipt_path = tmp_path / "bootstrap-denial.jsonl"
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "resolve_session_id",
        lambda _agent, _session_id: "codex:plan122-test",
    )
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "validate_native_session_binding",
        lambda _agent, _session_id: None,
    )

    with pytest.raises(PermissionError, match="admission_bootstrap_scope_violation"):
        session_lifecycle.start_session(
            agent="codex",
            project="enforced-planning",
            scope="plan122-test",
            intent="prove bootstrap denial ordering",
            repo_root=str(tmp_path / "repo"),
            worktree_path=str(tmp_path / "repo" / "worktrees" / "plan122-test"),
            branch="plan122-test",
            broader_goal="Plan 122 admission",
            current_phase="bootstrap",
            plan_ref="enforced-planning#122",
            session_id="codex:plan122-test",
            write_paths=["enforced_planning/outcome_admission.py"],
            tracker_dir=tracker_dir,
            outcome_bootstrap_plan=122,
            outcome_admission_receipt_path=receipt_path,
        )

    assert not tracker_dir.exists()
    [receipt] = load_outcome_admission_receipts(receipt_path)
    assert receipt.result.decision.reason_code == "admission_bootstrap_scope_violation"


def test_selected_session_denial_precedes_tracker_or_claim_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tracker_dir = tmp_path / "sessions"
    receipt_path = tmp_path / "session-denial.jsonl"
    claim = SimpleNamespace(session_id="codex:plan122-test")
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "resolve_session_id",
        lambda _agent, _session_id: "codex:plan122-test",
    )
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "validate_native_session_binding",
        lambda _agent, _session_id: None,
    )
    monkeypatch.setattr(session_lifecycle, "_single_matching_live_claim", lambda **_kwargs: claim)
    monkeypatch.setattr(
        outcome_admission,
        "evaluate_selected_claim_admission",
        lambda *_args, **_kwargs: _missing_selected_result(),
    )

    with pytest.raises(PermissionError, match="outcome_selection_required"):
        session_lifecycle.start_session(
            agent="codex",
            project="enforced-planning",
            scope="plan122-test",
            intent="prove selected denial ordering",
            repo_root=str(tmp_path / "repo"),
            worktree_path=str(tmp_path / "repo" / "worktrees" / "plan122-test"),
            branch="plan122-test",
            broader_goal="Plan 122 admission",
            current_phase="selected renewal",
            plan_ref="enforced-planning#122",
            session_id="codex:plan122-test",
            tracker_dir=tracker_dir,
            outcome_selected=True,
            outcome_admission_receipt_path=receipt_path,
        )

    assert not tracker_dir.exists()
    [receipt] = load_outcome_admission_receipts(receipt_path)
    assert receipt.result.resolution_error_code == "selection_missing"


def test_selected_heartbeat_denial_precedes_heartbeat_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt_path = tmp_path / "heartbeat-denial.jsonl"
    claim = SimpleNamespace(session_id="codex:plan122-test")
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "resolve_session_id",
        lambda _agent, _session_id: "codex:plan122-test",
    )
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "validate_native_session_binding",
        lambda _agent, _session_id: None,
    )
    monkeypatch.setattr(
        session_lifecycle,
        "_iter_matching_live_claims",
        lambda **_kwargs: [claim],
    )
    monkeypatch.setattr(
        outcome_admission,
        "evaluate_selected_claim_admission",
        lambda *_args, **_kwargs: _missing_selected_result(),
    )

    def forbidden_heartbeat(**_kwargs: object) -> tuple[int, list[str], str, datetime]:
        raise AssertionError("heartbeat mutation ran after admission denial")

    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "heartbeat_claims",
        forbidden_heartbeat,
    )

    with pytest.raises(PermissionError, match="outcome_selection_required"):
        session_lifecycle.heartbeat_session(
            agent="codex",
            project="enforced-planning",
            scope="plan122-test",
            branch="plan122-test",
            session_id="codex:plan122-test",
            outcome_selected=True,
            outcome_admission_receipt_path=receipt_path,
        )

    [receipt] = load_outcome_admission_receipts(receipt_path)
    assert receipt.result.decision.disposition == "deny"
