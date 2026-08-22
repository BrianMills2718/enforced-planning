from __future__ import annotations

import hashlib
import io
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml  # type: ignore[import-untyped]
from pydantic import ValidationError

from enforced_planning import (
    coordination_claims,
    outcome_admission,
    outcome_admission_evaluation,
    prewrite_claim_projection,
    session_contracts,
    session_lifecycle,
)
from enforced_planning.outcome_admission import (
    OutcomeAdmissionBootstrapV1,
    OutcomeAdmissionDecisionV1,
    OutcomeAdmissionRequestV1,
    OutcomeAdmissionResultV1,
    bootstrap_admission_result,
    build_outcome_admission_receipt,
    decide_outcome_admission,
    evaluate_claim_bootstrap_admission,
    evaluate_first_consumer_bootstrap,
    evaluate_selected_outcome_admission,
    infer_first_consumer_bootstrap_plan,
    is_first_consumer_bootstrap_path,
    load_outcome_admission_mode,
    load_outcome_admission_receipts,
    record_outcome_admission,
)
from enforced_planning.outcome_admission_evaluation import (
    OutcomeAdmissionEvaluationSuiteV1,
    candidate_decision,
)
from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    EvidenceBindingV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeProgressReceiptV1,
    canonical_sha256,
    evaluate_scenario,
)
from enforced_planning.outcome_portfolio import (
    OutcomePortfolioAllocationRequestV1,
    allocate_outcome_portfolio,
)
from enforced_planning.outcome_selection import (
    OutcomeSelectionBindingV1,
    OutcomeSelectionError,
    ResolvedOutcomeSelectionV1,
    select_outcome_for_session,
)
from scripts import prewrite_claim_gate as prewrite_claim_gate_cli
from scripts import session_heartbeat as session_heartbeat_cli
from scripts import session_start as session_start_cli

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "evals" / "outcome_admission" / "plan121_cases.json"
CLI = ROOT / "scripts" / "outcome_admission.py"


def _frozen_suite() -> OutcomeAdmissionEvaluationSuiteV1:
    return OutcomeAdmissionEvaluationSuiteV1.model_validate_json(CASES.read_text(encoding="utf-8"))


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
        "allowed_scope": [
            "enforced_planning/outcome_admission.py",
            "docs/evidence/plan122_first_consumer_outcome_admission.json",
        ],
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
        if decision.disposition != case.expected_disposition or decision.reason_code != case.expected_reason_code:
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

    result = evaluate_first_consumer_bootstrap(OutcomeAdmissionBootstrapV1(plan_number=122, write_paths=paths))

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
    result = evaluate_first_consumer_bootstrap(OutcomeAdmissionBootstrapV1(plan_number=122, write_paths=()))

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


@pytest.mark.parametrize(
    ("configured", "expected"),
    [
        (None, "off"),
        ({"meta_process": {"claims": {}}}, "off"),
        (
            {"meta_process": {"claims": {"outcome_admission_mode": "off"}}},
            "off",
        ),
        (
            {"meta_process": {"claims": {"outcome_admission_mode": "enforce_selected"}}},
            "enforce_selected",
        ),
    ],
)
def test_outcome_admission_mode_is_strict_and_absent_off(
    tmp_path: Path,
    configured: dict[str, object] | None,
    expected: str,
) -> None:
    if configured is not None:
        (tmp_path / "meta-process.yaml").write_text(
            yaml.safe_dump(configured),
            encoding="utf-8",
        )

    assert load_outcome_admission_mode(tmp_path) == expected


@pytest.mark.parametrize(
    "configured",
    [
        [],
        {"meta_process": []},
        {"meta_process": {"claims": None}},
        {"meta_process": {"claims": {"outcome_admission_mode": "observe"}}},
    ],
)
def test_outcome_admission_mode_rejects_malformed_values(
    tmp_path: Path,
    configured: object,
) -> None:
    (tmp_path / "meta-process.yaml").write_text(
        yaml.safe_dump(configured),
        encoding="utf-8",
    )

    with pytest.raises((TypeError, ValueError), match="must be"):
        load_outcome_admission_mode(tmp_path)


def test_bootstrap_plan_inference_requires_one_complete_exact_plan() -> None:
    exact = (
        "docs/plans/123_source_outcome_admission_activation.md",
        "docs/plans/123_source_outcome_admission_activation_work_graph.json",
        "examples/owner-real-outcome-admission/plan123-maintenance-scenario.json",
        "docs/plans/CLAUDE.md",
        "ROADMAP.md",
    )

    assert infer_first_consumer_bootstrap_plan(exact) == 123
    assert infer_first_consumer_bootstrap_plan(("ROADMAP.md",)) is None
    assert (
        infer_first_consumer_bootstrap_plan(
            (
                exact[0],
                "docs/plans/124_foreign.md",
            )
        )
        is None
    )
    assert (
        infer_first_consumer_bootstrap_plan(
            (
                exact[0],
                "enforced_planning/outcome_admission.py",
            )
        )
        is None
    )


def test_claim_bootstrap_admission_requires_exact_claimed_target() -> None:
    claim = SimpleNamespace(
        write_paths=[
            "docs/plans/123_source_outcome_admission_activation.md",
            "docs/plans/CLAUDE.md",
        ]
    )

    allowed = evaluate_claim_bootstrap_admission(
        claim,
        target_path="docs/plans/123_source_outcome_admission_activation.md",
    )

    assert allowed is not None
    assert allowed.decision.reason_code == "admission_bootstrap_allowed"
    assert (
        evaluate_claim_bootstrap_admission(
            claim,
            target_path="enforced_planning/outcome_admission.py",
        )
        is None
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


def test_selected_prewrite_accepts_another_contract_scoped_target(
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
        boundary="prewrite",
        ordinary_allowed=True,
        renewal=False,
        target_path="docs/evidence/plan122_first_consumer_outcome_admission.json",
    )

    assert result.decision.disposition == "allow"
    assert result.decision.reason_code == "outcome_admission_active"


def test_selected_prewrite_denies_target_outside_contract_scope(
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
        boundary="prewrite",
        ordinary_allowed=True,
        renewal=False,
        target_path="scripts/outcome_admission.py",
    )

    assert result.request is None
    assert result.decision.disposition == "deny"
    assert result.decision.reason_code == "out_of_scope"
    assert result.resolution_error_code == "selection_target_mismatch"


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
    evidence["bootstrap"]["write_paths"] = ["docs/plans/123_first_consumer_outcome_admission.md"]
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
    evidence["bootstrap"]["write_paths"] = ["docs/plans/123_first_consumer_outcome_admission.md"]
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


def test_configured_session_start_requires_selection_without_a_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    tracker_dir = tmp_path / "sessions"
    receipt_path = tmp_path / "configured-start-denial.jsonl"
    claim = SimpleNamespace(session_id="codex:plan123-configured")
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "resolve_session_id",
        lambda _agent, _session_id: "codex:plan123-configured",
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
            scope="plan123-configured",
            intent="prove configured start admission",
            repo_root=str(tmp_path / "repo"),
            worktree_path=str(worktree),
            branch="plan123-configured",
            broader_goal="Plan 123 configured admission",
            current_phase="configured renewal",
            plan_ref="enforced-planning#123",
            session_id="codex:plan123-configured",
            tracker_dir=tracker_dir,
            outcome_admission_receipt_path=receipt_path,
        )

    assert not tracker_dir.exists()
    [receipt] = load_outcome_admission_receipts(receipt_path)
    assert receipt.result.resolution_error_code == "selection_missing"


def test_configured_session_start_completes_explicit_unplanned_maintenance_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Maintenance bootstrap may enrich its claim before a selected outcome exists."""

    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "maintenance-fixture"
    worktree.mkdir(parents=True)
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    claims_dir = tmp_path / "claims"
    tracker_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        coordination_claims,
        "validate_native_session_binding",
        lambda _agent, _session_id: None,
    )

    created, _message = coordination_claims.create_claim(
        agent="codex",
        project="enforced-planning",
        scope="maintenance-fixture",
        intent="repair a bounded maintenance defect",
        claim_type="write",
        write_paths=["enforced_planning/example.py"],
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="maintenance-fixture",
        session_id="codex:maintenance-fixture",
        session_name="repair-maintenance-bootstrap",
    )
    assert created

    payload = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="maintenance-fixture",
        intent="repair a bounded maintenance defect",
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="maintenance-fixture",
        broader_goal="Repair Maintenance Bootstrap",
        current_phase="bootstrap",
        session_id="codex:maintenance-fixture",
        claim_type="write",
        write_paths=["enforced_planning/example.py"],
        tracker_dir=tracker_dir,
        allow_unplanned=True,
    )

    assert payload["plan_ref"] == "UNPLANNED"
    assert Path(payload["tracker_path"]).is_file()
    [claim] = coordination_claims.check_claims("enforced-planning")
    assert claim.plan_ref == "UNPLANNED"
    assert claim.tracker_path == payload["tracker_path"]
    assert claim.broader_goal == "Repair Maintenance Bootstrap"
    assert coordination_claims.claim_runtime_status(claim) == "healthy"


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


def test_configured_heartbeat_requires_selection_without_a_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    receipt_path = tmp_path / "configured-heartbeat-denial.jsonl"
    claim = SimpleNamespace(
        session_id="codex:plan123-configured",
        worktree_path=str(worktree),
        repo_root=str(tmp_path / "repo"),
    )
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "resolve_session_id",
        lambda _agent, _session_id: "codex:plan123-configured",
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
        raise AssertionError("heartbeat mutation ran after configured admission denial")

    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "heartbeat_claims",
        forbidden_heartbeat,
    )

    with pytest.raises(PermissionError, match="outcome_selection_required"):
        session_lifecycle.heartbeat_session(
            agent="codex",
            project="enforced-planning",
            scope="plan123-configured",
            branch="plan123-configured",
            session_id="codex:plan123-configured",
            outcome_admission_receipt_path=receipt_path,
        )

    [receipt] = load_outcome_admission_receipts(receipt_path)
    assert receipt.result.decision.disposition == "deny"


def test_opted_in_heartbeat_cli_returns_structured_denial(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deny(**_kwargs: object) -> dict[str, object]:
        raise session_lifecycle.OutcomeAdmissionDeniedError("Outcome admission denied (outcome_selection_required)")

    monkeypatch.setattr(session_heartbeat_cli.session_lifecycle, "heartbeat_session", deny)

    exit_code = session_heartbeat_cli.main(
        [
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "plan122-test",
            "--outcome-selected",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "outcome_admission_denied"


def test_configured_heartbeat_cli_returns_structured_denial_without_flag(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deny(**_kwargs: object) -> dict[str, object]:
        raise session_lifecycle.OutcomeAdmissionDeniedError("Outcome admission denied (outcome_selection_required)")

    monkeypatch.setattr(session_heartbeat_cli.session_lifecycle, "heartbeat_session", deny)

    exit_code = session_heartbeat_cli.main(
        [
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "plan123-configured",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"]["code"] == "outcome_admission_denied"


def test_opted_in_session_start_cli_returns_structured_denial(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def deny(**_kwargs: object) -> dict[str, object]:
        raise session_lifecycle.OutcomeAdmissionDeniedError("Outcome admission denied (outcome_selection_required)")

    monkeypatch.setattr(session_start_cli.session_lifecycle, "start_session", deny)

    exit_code = session_start_cli.main(
        [
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "plan122-test",
            "--intent",
            "prove denial output",
            "--repo-root",
            "/tmp/plan122-repo",
            "--worktree-path",
            "/tmp/plan122-worktree",
            "--branch",
            "plan122-test",
            "--broader-goal",
            "Plan 122 admission",
            "--current-phase",
            "selected renewal",
            "--outcome-selected",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "outcome_admission_denied"


def test_hard_prewrite_consumes_exactly_one_canonical_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_path = tmp_path / "claim.yaml"
    claim_path.write_text("{}\n", encoding="utf-8")
    claim = SimpleNamespace(scope="plan122-test")
    captured: list[str] = []
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "normalize_claim",
        lambda _payload, *, source_file: claim,
    )

    def evaluate(
        _claim: object,
        *,
        boundary: str,
        ordinary_allowed: bool,
        renewal: bool,
        target_path: str,
    ) -> OutcomeAdmissionResultV1:
        assert boundary == "prewrite"
        assert ordinary_allowed is True
        assert renewal is False
        captured.append(target_path)
        return _missing_selected_result()

    monkeypatch.setattr(outcome_admission, "evaluate_selected_claim_admission", evaluate)

    receipt = prewrite_claim_gate_cli._enforce_selected_outcome(
        {
            "decision": "allow",
            "claim_source_file": str(claim_path),
            "normalized_target_paths": ["enforced_planning/outcome_admission.py"],
        },
        receipt_path=tmp_path / "admission.jsonl",
    )

    assert captured == ["enforced_planning/outcome_admission.py"]
    assert receipt["result"]["decision"]["reason_code"] == "outcome_selection_required"


def test_configured_prewrite_allows_only_an_exact_bootstrap_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_path = tmp_path / "claim.yaml"
    claim_path.write_text("{}\n", encoding="utf-8")
    claim = SimpleNamespace(
        write_paths=[
            "docs/plans/123_source_outcome_admission_activation.md",
            "docs/plans/CLAUDE.md",
        ]
    )
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "normalize_claim",
        lambda _payload, *, source_file: claim,
    )

    def forbidden_selected(*_args: object, **_kwargs: object) -> OutcomeAdmissionResultV1:
        raise AssertionError("exact bootstrap unexpectedly required selected state")

    monkeypatch.setattr(
        outcome_admission,
        "evaluate_selected_claim_admission",
        forbidden_selected,
    )

    receipt = prewrite_claim_gate_cli._enforce_selected_outcome(
        {
            "decision": "allow",
            "claim_source_file": str(claim_path),
            "normalized_target_paths": ["docs/plans/123_source_outcome_admission_activation.md"],
        },
        receipt_path=tmp_path / "admission.jsonl",
        allow_bootstrap=True,
    )

    assert receipt["result"]["source"] == "bootstrap"
    assert receipt["result"]["decision"]["reason_code"] == "admission_bootstrap_allowed"


def test_configured_prewrite_rejects_bootstrap_source_smuggling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    claim_path = tmp_path / "claim.yaml"
    claim_path.write_text("{}\n", encoding="utf-8")
    claim = SimpleNamespace(
        write_paths=[
            "docs/plans/123_source_outcome_admission_activation.md",
            "enforced_planning/outcome_admission.py",
        ]
    )
    monkeypatch.setattr(
        session_lifecycle.coordination_claims,
        "normalize_claim",
        lambda _payload, *, source_file: claim,
    )
    monkeypatch.setattr(
        outcome_admission,
        "evaluate_selected_claim_admission",
        lambda *_args, **_kwargs: _missing_selected_result(),
    )

    receipt = prewrite_claim_gate_cli._enforce_selected_outcome(
        {
            "decision": "allow",
            "claim_source_file": str(claim_path),
            "normalized_target_paths": ["enforced_planning/outcome_admission.py"],
        },
        receipt_path=tmp_path / "admission.jsonl",
        allow_bootstrap=True,
    )

    assert receipt["result"]["decision"]["disposition"] == "deny"
    assert receipt["result"]["decision"]["reason_code"] == "outcome_selection_required"


def test_configured_prewrite_cannot_be_disabled_by_explicit_ordinary_off(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        prewrite_claim_gate_cli,
        "_configured_outcome_mode",
        lambda _payload: "enforce_selected",
    )
    monkeypatch.setattr(
        prewrite_claim_gate_cli,
        "evaluate_prewrite_fast",
        lambda *_args, **_kwargs: {"decision": "allow"},
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))

    exit_code = prewrite_claim_gate_cli.main(["--client", "codex", "--mode", "off", "--json"])

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["reason_code"] == "outcome_admission_mode_invalid"


def test_hard_prewrite_rejects_ambiguous_target_cardinality(tmp_path: Path) -> None:
    claim_path = tmp_path / "claim.yaml"
    claim_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        prewrite_claim_gate_cli.FastPreWriteError,
        match="exactly one normalized_target_paths entry",
    ):
        prewrite_claim_gate_cli._enforce_selected_outcome(
            {
                "decision": "allow",
                "claim_source_file": str(claim_path),
                "normalized_target_paths": [
                    "enforced_planning/outcome_admission.py",
                    "scripts/outcome_admission.py",
                ],
            },
            receipt_path=tmp_path / "admission.jsonl",
        )


def test_public_selected_and_configured_prewrite_deny_circular_live_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "codex:plan122-circular-test"
    target = "enforced_planning/outcome_admission.py"

    def git(repo: Path, *args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()

    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.name", "Plan 122 Test")
    git(repo, "config", "user.email", "plan122@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    git(repo, "add", "README.md")
    git(repo, "commit", "-m", "seed")
    baseline_revision = git(repo, "rev-parse", "HEAD")
    worktree = tmp_path / "worktree"
    git(repo, "worktree", "add", "-b", "plan122-circular-test", str(worktree))
    target_path = worktree / target
    target_path.parent.mkdir(parents=True)
    target_path.write_text("original\n", encoding="utf-8")
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    prewrite_mode: enforce\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )
    scenarios_dir = worktree / "scenarios"
    scenarios_dir.mkdir()

    contract = OutcomeContractV1(
        schema_version="1.1.0",
        outcome_id="plan122-circular-test",
        owner_class="brian",
        project_id="enforced-planning",
        lineage_id="plan122-circular-test",
        portfolio_class="maintenance",
        predecessor_lineage_ids=["plan121-evaluation"],
        intended_consumer="Brian and his coding agents",
        outcome="A circular selected outcome must not renew or authorize another write.",
        canonical_journey={
            "starting_state": "Three same-boundary non-outcome increments are retained.",
            "input": "One ordinary-authorized exact claimed write.",
            "action": "Invoke selected and pre-write outcome admission.",
            "observable_result": "Both public commands deny outcome_stalled.",
            "failure_signal": "Approval text or an active allocation revives the stalled lease.",
        },
        baseline_revision=baseline_revision,
        allowed_scope=[target],
        progress_dimensions=["circular continuation denial"],
    )
    contract_sha256 = canonical_sha256(contract)
    receipts: list[OutcomeProgressReceiptV1] = []
    prior_receipt_sha256: str | None = None
    for index in range(1, 4):
        receipt = OutcomeProgressReceiptV1(
            receipt_id=f"plan122-circular-{index}",
            outcome_contract_sha256=contract_sha256,
            prior_receipt_sha256=prior_receipt_sha256,
            progress_kind="non_outcome",
            dimension="circular continuation denial",
            summary="The same admission boundary failed without discriminating evidence.",
            evidence=EvidenceBindingV1(
                source_revision=baseline_revision,
                configuration_sha256=hashlib.sha256(f"config-{index}".encode()).hexdigest(),
                route="plan122-circular-public-command",
                command=["python3", "scripts/prewrite_claim_gate.py"],
                observation_sha256=hashlib.sha256(f"failure-{index}".encode()).hexdigest(),
                artifact_refs=[f"evidence/plan122-circular-{index}.json"],
                observed_at=f"2026-08-21T09:0{index}:00Z",
            ),
            failure_boundary="selected-prewrite-admission",
            discriminating_evidence=False,
        )
        receipts.append(receipt)
        prior_receipt_sha256 = canonical_sha256(receipt)
    scenario = OutcomeContinuationScenarioV1(
        scenario_id="plan122-circular-public-command",
        contract=contract,
        receipts=receipts,
        request=AdmissionRequestV1(
            operation="product_write",
            target_path=target,
            ordinary_approval=True,
            approval_text="I approve, continue",
            cost_telemetry_usd="1000000",
            elapsed_telemetry_seconds=999999,
        ),
    )
    assert evaluate_scenario(scenario).decision.reason_code == "outcome_stalled"
    scenario_path = scenarios_dir / "circular.json"
    scenario_path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")

    tracker_dir = tmp_path / "sessions"
    session_contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="plan122-circular-test",
        intent="prove circular outcome admission denial",
        plan_ref="goal:plan122-circular-test",
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan122-circular-test",
        session_id=session_id,
        broader_goal="Plan 122 circular denial",
    )
    tracker_path = session_contracts.session_tracker_path(
        session_contract,
        tracker_dir=tracker_dir,
    )
    session_contract = session_contract.with_tracker_path(str(tracker_path))
    session_contracts.write_session_tracker(
        session_contracts.build_session_tracker(
            contract=session_contract,
            current_phase="exercise circular denial",
        ),
        tracker_dir=tracker_dir,
    )
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(UTC)
    claim_path = claims_dir / "codex_enforced-planning_plan122-circular-test.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["enforced-planning"],
                "scope": "plan122-circular-test",
                "intent": "prove circular outcome admission denial",
                "claim_type": "program",
                "write_paths": [target],
                "read_paths": [],
                "repo_root": str(repo),
                "worktree_path": str(worktree),
                "branch": "plan122-circular-test",
                "session_id": session_id,
                "session_name": "plan122-circular-test",
                "broader_goal": "Plan 122 circular denial",
                "tracker_path": str(tracker_path),
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
                "plan_ref": "goal:plan122-circular-test",
                "approval_revisions": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    graph_repo = tmp_path / "project-meta"
    graph_repo.mkdir()
    git(graph_repo, "init", "-b", "main")
    git(graph_repo, "config", "user.name", "Plan 122 Test")
    git(graph_repo, "config", "user.email", "plan122@example.com")
    (graph_repo / "PROJECT_GRAPH.json").write_text(
        json.dumps(
            [
                {
                    "id": "enforced-planning",
                    "record_kind": "repository",
                    "status": "active",
                    "repository_governance": {
                        "owner_class": "brian",
                        "approved_remote_owners": ["BrianMills2718"],
                        "mutation_authority": "normal_push",
                        "publication_authority": "recoverable_git",
                        "review": {
                            "reviewed_by": "Brian Mills",
                            "reviewed_at": "2026-08-21",
                            "evidence": ["Approved Plan 122 synthetic control governance."],
                        },
                    },
                    "supersedes": [],
                }
            ],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    git(graph_repo, "add", "PROJECT_GRAPH.json")
    git(graph_repo, "commit", "-m", "graph")
    graph_revision = git(graph_repo, "rev-parse", "HEAD")

    allocation_request = OutcomePortfolioAllocationRequestV1(
        allocation_id="plan122-circular-maintenance",
        requested_at=datetime(2026, 8, 21, 9, 10, tzinfo=UTC),
        project_id="enforced-planning",
        scenario_id=scenario.scenario_id,
        outcome_contract_sha256=contract_sha256,
        outcome_id=contract.outcome_id,
        outcome_lineage_id=contract.lineage_id,
        portfolio_class="maintenance",
        decision_ref="goal:plan122-circular-test",
        purpose="Prove active allocation cannot revive circular selected state.",
        stopping_condition="End after both public denial commands return nonzero.",
    )
    allocation_path = scenarios_dir / "allocation.json"
    allocation_path.write_text(
        allocation_request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    ledger_path = tmp_path / "portfolio.json"
    monkeypatch.setenv("CODEX_THREAD_ID", "plan122-circular-test")
    allocate_outcome_portfolio(
        agent="codex",
        project="enforced-planning",
        scope="plan122-circular-test",
        session_id=session_id,
        scenario_path=scenario_path,
        request_path=allocation_path,
        project_graph_repo=graph_repo,
        project_graph_revision=graph_revision,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )
    select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan122-circular-test",
        session_id=session_id,
        execution_authority_ref="goal:plan122-circular-test",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
        portfolio_ledger_path=ledger_path,
    )

    admission_receipts = tmp_path / "admission.jsonl"
    selected = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "selected",
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "plan122-circular-test",
            "--session-id",
            session_id,
            "--boundary",
            "heartbeat",
            "--renewal",
            "--claims-dir",
            str(claims_dir),
            "--receipt-path",
            str(admission_receipts),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert selected.returncode == 2
    selected_payload = json.loads(selected.stdout)
    assert selected_payload["decision"]["reason_code"] == "outcome_stalled"

    projection_path = tmp_path / "projection.json"
    prewrite_claim_projection.write_projection(
        claims_dir=claims_dir,
        projection_path=projection_path,
    )
    prewrite = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "prewrite_claim_gate.py"),
            "--client",
            "codex",
            "--mode",
            "enforce",
            "--claims-dir",
            str(claims_dir),
            "--projection-path",
            str(projection_path),
            "--receipt-path",
            str(tmp_path / "ordinary.jsonl"),
            "--outcome-receipt-path",
            str(admission_receipts),
            "--json",
        ],
        cwd=ROOT,
        input=json.dumps(
            {
                "session_id": "plan122-circular-test",
                "cwd": str(worktree),
                "hook_event_name": "PreToolUse",
                "tool_name": "apply_patch",
                "tool_input": {"command": (f"*** Begin Patch\n*** Update File: {target}\n*** End Patch")},
            }
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert prewrite.returncode == 2
    prewrite_payload = json.loads(prewrite.stdout)
    assert prewrite_payload["decision"] == "allow"
    assert prewrite_payload["outcome_admission"]["result"]["decision"]["reason_code"] == "outcome_stalled"
    assert target_path.read_text(encoding="utf-8") == "original\n"
