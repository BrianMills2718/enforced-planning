from __future__ import annotations

from pathlib import Path

import pytest

from enforced_planning import coordination_claims, outcome_selection, prewrite_claim_projection
from enforced_planning.outcome_completion import (
    OutcomeCompletionError,
    evaluate_stop_for_session,
    load_outcome_completion_mode,
    record_selected_outcome_completion_for_session,
)
from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    OutcomeContinuationScenarioV1,
    canonical_sha256,
    evaluate_scenario,
)
from enforced_planning.outcome_selection import select_outcome_for_session
from tests.test_cross_client_execution_tracking import (
    completion_proposal,
    contract,
    evidence_receipt,
    projection,
)
from tests.test_outcome_selection import SESSION, TARGET, _fixture


def _selected_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    evidenced: bool,
):
    monkeypatch.setenv("CODEX_THREAD_ID", SESSION.removeprefix("codex:"))
    monkeypatch.setenv("ENFORCED_PLANNING_LOCK_DIR", str(tmp_path / "tracker-locks"))
    # Portfolio allocation is independently covered by its owner. This fixture
    # isolates the selected-completion persistence and Stop boundary.
    monkeypatch.setattr(
        outcome_selection,
        "_portfolio_allocation_for_scenario",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        outcome_selection,
        "_assert_binding_portfolio_allocation",
        lambda *_args, **_kwargs: None,
    )
    repo, worktree, claims_dir, _claim_path, scenario_path = _fixture(
        tmp_path,
        plan_ref="goal:cross-client-fixture",
    )
    selected_contract = contract().model_copy(
        update={
            "project_id": "enforced-planning",
            "allowed_scope": [TARGET],
            "baseline_revision": "fixture-baseline",
        }
    )
    receipts = []
    if evidenced:
        receipts = [
            evidence_receipt(
                receipt_id="all-criteria-evidence",
                prior=None,
                criteria=["criterion-one", "criterion-two"],
            ).model_copy(update={"outcome_contract_sha256": canonical_sha256(selected_contract)})
        ]
    scenario = OutcomeContinuationScenarioV1(
        scenario_id="completion-stop-fixture",
        contract=selected_contract,
        receipts=receipts,
        request=AdmissionRequestV1(operation="product_write", target_path=TARGET),
    )
    scenario_path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")
    select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref="goal:cross-client-fixture",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )
    green = projection(status="completed").model_copy(
        update={"outcome_contract_sha256": canonical_sha256(selected_contract)}
    )
    current = evaluate_scenario(scenario).lease
    proposal = completion_proposal(
        canonical_sha256(current),
        current.last_receipt_sha256 or "0" * 64,
        canonical_sha256(green),
    ).model_copy(update={"outcome_contract_sha256": canonical_sha256(selected_contract)})
    projection_path = worktree / "scenarios" / "completion-projection.json"
    proposal_path = worktree / "scenarios" / "completion-proposal.json"
    projection_path.write_text(green.model_dump_json(indent=2) + "\n", encoding="utf-8")
    proposal_path.write_text(proposal.model_dump_json(indent=2) + "\n", encoding="utf-8")
    claim = prewrite_claim_projection.build_projection(claims_dir=claims_dir).claims[0]
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    return repo, worktree, claims_dir, claim, projection_path, proposal_path


def _activate(worktree: Path) -> None:
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_completion_mode: enforce_selected\n",
        encoding="utf-8",
    )


def test_mode_is_isolated_and_strict(tmp_path: Path) -> None:
    assert load_outcome_completion_mode(tmp_path) == "off"
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_completion_mode: enforce_selected\n",
        encoding="utf-8",
    )
    assert load_outcome_completion_mode(tmp_path) == "enforce_selected"
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_completion_mode: observe\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="outcome_completion_mode"):
        load_outcome_completion_mode(tmp_path)


def test_unconfigured_repo_is_unaffected_and_activated_incomplete_outcome_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, worktree, _claims_dir, claim, _projection_path, _proposal_path = _selected_fixture(
        tmp_path, monkeypatch, evidenced=False
    )
    inactive = evaluate_stop_for_session(
        repo_root=worktree,
        agent="codex",
        project="enforced-planning",
        session_id=SESSION,
        active_claims=(claim,),
    )
    assert inactive.applicable is False
    assert inactive.allow_stop is True

    _activate(worktree)
    blocked = evaluate_stop_for_session(
        repo_root=worktree,
        agent="codex",
        project="enforced-planning",
        session_id=SESSION,
        active_claims=(claim,),
    )
    assert blocked.allow_stop is False
    assert blocked.reason_code == "canonical_outcome_incomplete"
    assert "native green items or an archived cursor are not completion" in blocked.summary


def test_all_green_projection_cannot_substitute_for_missing_criterion_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, worktree, claims_dir, _claim, projection_path, proposal_path = _selected_fixture(
        tmp_path, monkeypatch, evidenced=False
    )
    _activate(worktree)
    with pytest.raises(OutcomeCompletionError) as denied:
        record_selected_outcome_completion_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            claims_dir=claims_dir,
            projection_path=projection_path,
            proposal_path=proposal_path,
        )
    assert denied.value.code in {"completion_evidence_stale", "criterion_evidence_missing"}


def test_exact_accepted_completion_is_durable_idempotent_and_allows_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _repo, worktree, claims_dir, claim, projection_path, proposal_path = _selected_fixture(
        tmp_path, monkeypatch, evidenced=True
    )
    _activate(worktree)
    before = evaluate_stop_for_session(
        repo_root=worktree,
        agent="codex",
        project="enforced-planning",
        session_id=SESSION,
        active_claims=(claim,),
    )
    assert before.allow_stop is False

    recorded = record_selected_outcome_completion_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        claims_dir=claims_dir,
        projection_path=projection_path,
        proposal_path=proposal_path,
    )
    tracker_bytes = Path(recorded.tracker_path).read_bytes()
    replay = record_selected_outcome_completion_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        claims_dir=claims_dir,
        projection_path=projection_path,
        proposal_path=proposal_path,
    )
    assert recorded.status == "recorded"
    assert replay.status == "idempotent"
    assert replay.transition_sha256 == recorded.transition_sha256
    assert Path(recorded.tracker_path).read_bytes() == tracker_bytes

    allowed = evaluate_stop_for_session(
        repo_root=worktree,
        agent="codex",
        project="enforced-planning",
        session_id=SESSION,
        active_claims=(claim,),
    )
    assert allowed.allow_stop is True
    assert allowed.reason_code == "canonical_outcome_complete"
    assert allowed.completion_transition_sha256 == recorded.transition_sha256


def test_completed_exact_portfolio_allocation_preserves_accepted_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime

    from enforced_planning.outcome_portfolio import (
        OutcomePortfolioAllocationRequestV1,
        OutcomePortfolioDispositionRequestV1,
        allocate_outcome_portfolio,
        dispose_outcome_portfolio_allocation,
    )
    from tests.test_outcome_selection import _project_graph_repo

    monkeypatch.setenv("CODEX_THREAD_ID", SESSION.removeprefix("codex:"))
    monkeypatch.setenv("ENFORCED_PLANNING_LOCK_DIR", str(tmp_path / "tracker-locks"))
    _repo, worktree, claims_dir, _claim_path, scenario_path = _fixture(
        tmp_path,
        plan_ref="goal:cross-client-fixture",
    )
    selected_contract = contract().model_copy(
        update={
            "owner_class": "brian",
            "allowed_scope": [TARGET],
            "baseline_revision": "fixture-baseline",
        }
    )
    scenario = OutcomeContinuationScenarioV1(
        scenario_id="completion-stop-classed-fixture",
        contract=selected_contract,
        receipts=[
            evidence_receipt(
                receipt_id="all-classed-criteria-evidence",
                prior=None,
                criteria=["criterion-one", "criterion-two"],
            ).model_copy(
                update={"outcome_contract_sha256": canonical_sha256(selected_contract)}
            )
        ],
        request=AdmissionRequestV1(operation="product_write", target_path=TARGET),
    )
    scenario_path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")
    graph_repo, graph_revision = _project_graph_repo(tmp_path)
    ledger_path = tmp_path / "portfolio-ledger.json"
    allocation_request = OutcomePortfolioAllocationRequestV1(
        allocation_id="completion-stop-allocation",
        requested_at=datetime(2026, 9, 13, 22, tzinfo=UTC),
        project_id="enforced-planning",
        scenario_id=scenario.scenario_id,
        outcome_contract_sha256=canonical_sha256(selected_contract),
        outcome_id=selected_contract.outcome_id,
        outcome_lineage_id=selected_contract.lineage_id,
        portfolio_class="product",
        decision_ref="decision:completion-stop-allocation",
        purpose="Exercise completion after exact allocation release.",
        stopping_condition="Complete after canonical outcome acceptance is retained.",
    )
    allocation_path = worktree / "scenarios" / "completion-allocation.json"
    allocation_path.write_text(
        allocation_request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    allocated = allocate_outcome_portfolio(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
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
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref="goal:cross-client-fixture",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
        portfolio_ledger_path=ledger_path,
    )
    green = projection(status="completed").model_copy(
        update={"outcome_contract_sha256": canonical_sha256(selected_contract)}
    )
    current = evaluate_scenario(scenario).lease
    proposal = completion_proposal(
        canonical_sha256(current),
        current.last_receipt_sha256 or "0" * 64,
        canonical_sha256(green),
    ).model_copy(update={"outcome_contract_sha256": canonical_sha256(selected_contract)})
    projection_path = worktree / "scenarios" / "completion-projection.json"
    proposal_path = worktree / "scenarios" / "completion-proposal.json"
    projection_path.write_text(green.model_dump_json(indent=2) + "\n", encoding="utf-8")
    proposal_path.write_text(proposal.model_dump_json(indent=2) + "\n", encoding="utf-8")
    recorded = record_selected_outcome_completion_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        claims_dir=claims_dir,
        projection_path=projection_path,
        proposal_path=proposal_path,
    )
    disposition_request = OutcomePortfolioDispositionRequestV1(
        disposition_id="completion-stop-allocation-complete",
        requested_at=datetime(2026, 9, 13, 22, 5, tzinfo=UTC),
        allocation_id=allocated.allocation.allocation_id,
        allocation_sha256=allocated.allocation_sha256,
        disposition="complete",
        decision_ref="decision:canonical-completion-retained",
        reason="Release the exact slot after canonical completion is retained.",
    )
    disposition_path = worktree / "scenarios" / "completion-disposition.json"
    disposition_path.write_text(
        disposition_request.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    dispose_outcome_portfolio_allocation(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        request_path=disposition_path,
        claims_dir=claims_dir,
        ledger_path=ledger_path,
    )
    _activate(worktree)
    claim = prewrite_claim_projection.build_projection(claims_dir=claims_dir).claims[0]

    allowed = evaluate_stop_for_session(
        repo_root=worktree,
        agent="codex",
        project="enforced-planning",
        session_id=SESSION,
        active_claims=(claim,),
    )

    assert allowed.allow_stop is True
    assert allowed.reason_code == "canonical_outcome_complete"
    assert allowed.completion_transition_sha256 == recorded.transition_sha256


def test_activated_repo_without_exact_native_claim_fails_closed(tmp_path: Path) -> None:
    _activate(tmp_path)
    decision = evaluate_stop_for_session(
        repo_root=tmp_path,
        agent="codex",
        project="dashboard",
        session_id="codex:missing",
        active_claims=(),
    )
    assert decision.allow_stop is False
    assert decision.reason_code == "exact_claim_unavailable"
