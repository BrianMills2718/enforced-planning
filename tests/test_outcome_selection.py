from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    outcome_selection,
    prewrite_claim_projection,
    session_contracts,
    session_lifecycle,
)
from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    EvidenceBindingV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeLeaseV1,
    OutcomeProgressReceiptV1,
    RestartDeltaV1,
    canonical_sha256,
    evaluate_scenario,
)
from enforced_planning.outcome_selection import (
    OutcomeSelectionError,
    resolve_selected_outcome_for_prewrite,
    restart_selected_outcome_for_session,
    select_outcome_for_session,
)

ROOT = Path(__file__).resolve().parents[1]
TARGET = "docs/evidence/plan117.json"
SESSION = "codex:plan117-test"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _scenario(
    *, scenario_id: str = "plan117-progress", outcome_id: str = "durable-outcome"
) -> OutcomeContinuationScenarioV1:
    contract = OutcomeContractV1(
        outcome_id=outcome_id,
        owner_class="brian-agent-owner",
        project_id="enforced-planning",
        lineage_id="plan-117-durable-selection",
        predecessor_lineage_ids=["plan-116-prewrite-correlation"],
        intended_consumer="Brian and his coding agents",
        outcome="One claimed session retains one exact outcome authority.",
        canonical_journey={
            "starting_state": "One live claimed session has no durable outcome selection.",
            "input": "One immutable progress scenario.",
            "action": "Select it once and resolve it from the exact session tracker.",
            "observable_result": "The selected pre-write path retains exact binding evidence.",
            "failure_signal": "The outcome can be switched or borrowed by another session.",
        },
        baseline_revision="a0c67cf11b073597de53a39423a4e0ab0e74df21",
        allowed_scope=[TARGET],
        progress_dimensions=["durable session binding"],
    )
    contract_sha256 = canonical_sha256(contract)
    receipt = OutcomeProgressReceiptV1(
        receipt_id=f"{scenario_id}-receipt",
        outcome_contract_sha256=contract_sha256,
        progress_kind="behavioral_advance",
        dimension="durable session binding",
        summary="The exact claimed session now owns one immutable outcome choice.",
        evidence=EvidenceBindingV1(
            source_revision="a0c67cf11b073597de53a39423a4e0ab0e74df21",
            configuration_sha256=hashlib.sha256(b"plan117-test").hexdigest(),
            route="plan117-test-selection",
            command=["python", "scripts/outcome_continuation.py", "select"],
            observation_sha256=hashlib.sha256(scenario_id.encode()).hexdigest(),
            artifact_refs=["docs/plans/117_durable_outcome_selection_binding_observe.md"],
            observed_at="2026-08-21T04:00:00Z",
        ),
        discriminating_evidence=True,
    )
    return OutcomeContinuationScenarioV1(
        scenario_id=scenario_id,
        contract=contract,
        receipts=[receipt],
        request=AdmissionRequestV1(operation="product_write", target_path=TARGET),
    )


def _restart_scenario(*, successor: bool = False) -> OutcomeContinuationScenarioV1:
    lineage = "plan-118-successor" if successor else "plan-117-stalled"
    contract = OutcomeContractV1(
        outcome_id="durable-outcome",
        owner_class="brian-agent-owner",
        project_id="enforced-planning",
        lineage_id=lineage,
        predecessor_lineage_ids=(
            ["plan-117-stalled"] if successor else ["plan-116-prewrite-correlation"]
        ),
        intended_consumer="Brian and his coding agents",
        outcome="One claimed session retains one exact outcome authority.",
        canonical_journey={
            "starting_state": "One selected outcome has repeatedly failed at runtime handoff.",
            "input": "One immutable selected-outcome scenario and exact claim identity.",
            "action": "Resume it and resolve the same outcome from the exact successor runtime.",
            "observable_result": "The selected pre-write path retains exact binding evidence.",
            "failure_signal": "A restart loses the outcome or erases predecessor failures.",
        },
        baseline_revision=(
            "6340ff80cb8c514d8f3170d7818b0b324a1d04cb"
            if successor
            else "a0c67cf11b073597de53a39423a4e0ab0e74df21"
        ),
        allowed_scope=[TARGET],
        progress_dimensions=["durable session binding"],
    )
    receipts: list[OutcomeProgressReceiptV1] = []
    if not successor:
        prior: str | None = None
        for index in range(1, 4):
            receipt = OutcomeProgressReceiptV1(
                receipt_id=f"plan-117-handoff-failure-{index}",
                outcome_contract_sha256=canonical_sha256(contract),
                prior_receipt_sha256=prior,
                progress_kind="non_outcome",
                dimension="durable session binding",
                summary="The runtime handoff again lost the exact selected outcome binding.",
                evidence=EvidenceBindingV1(
                    source_revision="a0c67cf11b073597de53a39423a4e0ab0e74df21",
                    configuration_sha256=hashlib.sha256(f"restart-{index}".encode()).hexdigest(),
                    route="plan118-restart/session-resume",
                    command=["python", "scripts/session_resume.py", "--json"],
                    observation_sha256=hashlib.sha256(f"failure-{index}".encode()).hexdigest(),
                    artifact_refs=[f"docs/evidence/plan117-resume-failure-{index}.json"],
                    observed_at=f"2026-08-21T04:0{index}:00Z",
                ),
                failure_boundary="selected-session-handoff",
            )
            receipts.append(receipt)
            prior = canonical_sha256(receipt)
    return OutcomeContinuationScenarioV1(
        scenario_id=("plan-118-active-successor" if successor else "plan-117-stalled-predecessor"),
        contract=contract,
        receipts=receipts,
        request=AdmissionRequestV1(operation="product_write", target_path=TARGET),
    )


def _fixture(
    tmp_path: Path,
    *,
    plan_ref: str | None = "goal:durable-outcome",
) -> tuple[Path, Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "-b", "plan117-test", str(worktree))
    (worktree / "scenarios").mkdir()
    (worktree / "docs" / "evidence").mkdir(parents=True)

    tracker_dir = tmp_path / "sessions"
    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        intent="exercise durable outcome selection",
        plan_ref=plan_ref,
        allow_unplanned=plan_ref is None,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan117-test",
        session_id=SESSION,
        broader_goal="Durable Outcome Selection Test",
    )
    tracker_path = session_contracts.session_tracker_path(contract, tracker_dir=tracker_dir)
    contract = contract.with_tracker_path(str(tracker_path))
    session_contracts.write_session_tracker(
        session_contracts.build_session_tracker(contract=contract, current_phase="select outcome"),
        tracker_dir=tracker_dir,
    )

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(UTC)
    claim_path = claims_dir / "codex_enforced-planning_plan117-test.yaml"
    claim_payload = {
        "schema_version": 3,
        "agent": "codex",
        "claimed_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "projects": ["enforced-planning"],
        "scope": "plan117-test",
        "intent": "exercise durable outcome selection",
        "claim_type": "program",
        "write_paths": [TARGET],
        "read_paths": [],
        "repo_root": str(repo),
        "worktree_path": str(worktree),
        "branch": "plan117-test",
        "session_id": SESSION,
        "session_name": "durable-outcome-selection-test",
        "broader_goal": "Durable Outcome Selection Test",
        "tracker_path": str(tracker_path),
        "heartbeat_at": now.isoformat(),
        "status": "active",
        "updated_at": now.isoformat(),
        "plan_ref": plan_ref,
        "work_unit_id": "osel-01" if plan_ref and not plan_ref.startswith("goal:") else None,
        "work_graph_path": "docs/plans/117_graph.json" if plan_ref and not plan_ref.startswith("goal:") else None,
        "work_graph_sha256": "a" * 64 if plan_ref and not plan_ref.startswith("goal:") else None,
        "approval_revisions": [],
    }
    claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")
    scenario_path = worktree / "scenarios" / "selected.json"
    scenario_path.write_text(_scenario().model_dump_json(indent=2) + "\n", encoding="utf-8")
    return repo, worktree, claims_dir, claim_path, scenario_path


def _select(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    plan_ref: str | None = "goal:durable-outcome",
    authority: str = "goal:durable-outcome",
):
    monkeypatch.setenv("CODEX_THREAD_ID", "plan117-test")
    repo, worktree, claims_dir, claim_path, scenario_path = _fixture(tmp_path, plan_ref=plan_ref)
    result = select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref=authority,
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )
    return result, repo, worktree, claims_dir, claim_path, scenario_path


def _restart_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    predecessor: OutcomeContinuationScenarioV1 | None = None,
    successor: OutcomeContinuationScenarioV1 | None = None,
):
    monkeypatch.setenv("CODEX_THREAD_ID", "plan117-test")
    repo, worktree, claims_dir, claim_path, predecessor_path = _fixture(tmp_path)
    predecessor = predecessor or _restart_scenario()
    predecessor_path.write_text(predecessor.model_dump_json(indent=2) + "\n", encoding="utf-8")
    selected = select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref="goal:durable-outcome",
        scenario_path=predecessor_path,
        claims_dir=claims_dir,
    )
    successor = successor or _restart_scenario(successor=True)
    successor_path = predecessor_path.with_name("successor.json")
    successor_path.write_text(successor.model_dump_json(indent=2) + "\n", encoding="utf-8")
    predecessor_result = evaluate_scenario(predecessor)
    successor_result = evaluate_scenario(successor)
    predecessor_lease = predecessor_result.lease
    failed_refs = [
        ref
        for receipt in predecessor.receipts
        if receipt.progress_kind == "non_outcome"
        for ref in receipt.evidence.artifact_refs
    ]
    delta = RestartDeltaV1(
        delta_id="plan-118-causal-restart",
        recorded_at="2026-08-21T05:45:00Z",
        predecessor_binding_sha256=selected.binding_sha256,
        predecessor_contract_sha256=predecessor_result.outcome_contract_sha256,
        predecessor_lease_sha256=predecessor_result.lease_sha256,
        predecessor_lineage_id=predecessor.contract.lineage_id,
        predecessor_lease_state=(
            predecessor_lease.state
            if predecessor_lease.state in {"stalled", "parked"}
            else "parked"
        ),
        predecessor_non_outcome_count=predecessor_lease.consecutive_non_outcome_increments,
        predecessor_failure_boundary=predecessor_lease.current_failure_boundary,
        predecessor_failure_count=predecessor_lease.same_boundary_failures,
        predecessor_failed_evidence_refs=failed_refs,
        successor_contract_sha256=successor_result.outcome_contract_sha256,
        successor_lineage_id=successor.contract.lineage_id,
        prior_causal_hypothesis="Refreshing only claim ownership would preserve selected outcome custody.",
        changed_causal_hypothesis="Claim and tracker identity must transition together with retained evidence.",
        prior_mechanism="Update the claim session ID while leaving selected tracker state untouched.",
        changed_mechanism="Preflight and rebind the selected tracker with append-only causal history.",
        bounded_action="Replace only the exact current selected binding.",
        next_canonical_observation="Resolve the successor selection through ordinary pre-write observation.",
        stopping_condition="Stop if identity differs or predecessor failure evidence is missing.",
    )
    delta_path = predecessor_path.with_name("restart-delta.json")
    delta_path.write_text(delta.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return (
        selected,
        repo,
        worktree,
        claims_dir,
        claim_path,
        predecessor_path,
        successor_path,
        delta_path,
    )


def test_planned_selection_is_create_once_and_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, _repo, _worktree, claims_dir, _claim_path, scenario_path = _select(
        tmp_path,
        monkeypatch,
        plan_ref="enforced-planning#117",
        authority="enforced-planning#117",
    )

    replay = select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref="enforced-planning#117",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )

    assert result.status == "selected"
    assert replay.status == "idempotent"
    assert replay.binding_sha256 == result.binding_sha256
    assert replay.binding.selected_at == result.binding.selected_at
    assert result.binding.execution_authority_ref == "enforced-planning#117"
    tracker = session_contracts.read_session_tracker(Path(result.tracker_path))
    assert tracker["claim"]["plan_ref"] == "enforced-planning#117"
    assert tracker["tracker"]["outcome_selection"]["claim_plan_ref"] == "enforced-planning#117"

    different_path = scenario_path.with_name("different.json")
    different_path.write_text(
        _scenario(scenario_id="plan117-different").model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(OutcomeSelectionError, match="already selected") as caught:
        select_outcome_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            execution_authority_ref="enforced-planning#117",
            scenario_path=different_path,
            claims_dir=claims_dir,
        )
    assert caught.value.code == "selection_conflict"


def test_causal_restart_retains_stalled_failure_history_and_is_idempotent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        selected,
        repo,
        worktree,
        claims_dir,
        claim_path,
        _predecessor_path,
        successor_path,
        delta_path,
    ) = _restart_fixture(tmp_path, monkeypatch)

    with pytest.raises(OutcomeSelectionError) as direct_replacement:
        select_outcome_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            execution_authority_ref="goal:durable-outcome",
            scenario_path=successor_path,
            claims_dir=claims_dir,
        )
    assert direct_replacement.value.code == "selection_conflict"

    restarted = restart_selected_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        successor_scenario_path=successor_path,
        restart_delta_path=delta_path,
        claims_dir=claims_dir,
    )

    assert restarted.status == "restarted"
    assert restarted.binding.outcome_lineage_id == "plan-118-successor"
    assert restarted.binding.lease_state == "active"
    retained = restarted.transition
    assert retained.predecessor_binding_sha256 == selected.binding_sha256
    assert retained.predecessor_lease.state == "stalled"
    assert retained.predecessor_lease.consecutive_non_outcome_increments == 3
    assert retained.predecessor_lease.current_failure_boundary == "selected-session-handoff"
    assert retained.predecessor_lease.same_boundary_failures == 3
    assert retained.predecessor_failed_evidence_refs == tuple(
        f"docs/evidence/plan117-resume-failure-{index}.json" for index in range(1, 4)
    )
    tracker = session_contracts.read_session_tracker(Path(restarted.tracker_path))
    assert len(tracker["tracker"]["outcome_selection_transitions"]) == 1
    assert tracker["tracker"]["outcome_selection"]["outcome_lineage_id"] == "plan-118-successor"

    resolved = resolve_selected_outcome_for_prewrite(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan117-test",
        claim_source_file=str(claim_path),
        target_path=TARGET,
    )
    assert resolved.binding_sha256 == restarted.binding_sha256

    replay = restart_selected_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        successor_scenario_path=successor_path,
        restart_delta_path=delta_path,
        claims_dir=claims_dir,
    )
    assert replay.status == "idempotent"
    assert replay.transition_sha256 == restarted.transition_sha256
    tracker_after_replay = session_contracts.read_session_tracker(Path(restarted.tracker_path))
    assert len(tracker_after_replay["tracker"]["outcome_selection_transitions"]) == 1


def test_causal_restart_cli_emits_machine_readable_transition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        _selected,
        _repo,
        worktree,
        claims_dir,
        _claim_path,
        _predecessor_path,
        successor_path,
        delta_path,
    ) = _restart_fixture(tmp_path, monkeypatch)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "outcome_continuation.py"),
            "restart",
            "--successor-scenario",
            str(successor_path),
            "--restart-delta",
            str(delta_path),
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "plan117-test",
            "--session-id",
            SESSION,
            "--claims-dir",
            str(claims_dir),
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "restarted"
    assert payload["binding"]["outcome_lineage_id"] == "plan-118-successor"
    assert payload["transition"]["predecessor_lease"]["state"] == "stalled"
    assert payload["transition"]["restart_delta"]["changed_mechanism"].startswith("Preflight")


@pytest.mark.parametrize("state", ["active", "recovery_required", "complete"])
def test_causal_restart_rejects_non_restartable_predecessor_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    state: str,
) -> None:
    base = _restart_scenario()
    if state == "active":
        payload = base.model_dump(mode="json")
        payload["receipts"] = payload["receipts"][:1]
        predecessor = OutcomeContinuationScenarioV1.model_validate(payload)
    elif state == "recovery_required":
        payload = base.model_dump(mode="json")
        payload["receipts"] = payload["receipts"][:2]
        predecessor = OutcomeContinuationScenarioV1.model_validate(payload)
    else:
        predecessor = OutcomeContinuationScenarioV1(
            scenario_id="plan-117-complete-predecessor",
            contract=base.contract,
            starting_lease=OutcomeLeaseV1(
                lease_id="plan-117-complete-lease",
                outcome_contract_sha256=canonical_sha256(base.contract),
                state="complete",
            ),
            request=base.request,
        )
    *_, claims_dir, _claim_path, _predecessor_path, successor_path, delta_path = _restart_fixture(
        tmp_path,
        monkeypatch,
        predecessor=predecessor,
    )

    with pytest.raises(OutcomeSelectionError) as caught:
        restart_selected_outcome_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            successor_scenario_path=successor_path,
            restart_delta_path=delta_path,
            claims_dir=claims_dir,
        )
    assert caught.value.code == "restart_predecessor_state"


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("outcome", "authority_outcome_mismatch"),
        ("journey", "restart_outcome_mismatch"),
        ("target", "restart_target_mismatch"),
        ("predecessor", "restart_predecessor_missing"),
    ],
)
def test_causal_restart_rejects_successor_identity_laundering(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    expected_code: str,
) -> None:
    payload = _restart_scenario(successor=True).model_dump(mode="json")
    if mutation == "outcome":
        payload["contract"]["outcome_id"] = "laundered-outcome"
    elif mutation == "journey":
        payload["contract"]["canonical_journey"]["observable_result"] = (
            "A different local artifact exists without preserving runtime custody."
        )
    elif mutation == "target":
        payload["contract"]["allowed_scope"].append("docs/evidence/different.json")
        payload["request"]["target_path"] = "docs/evidence/different.json"
    else:
        payload["contract"]["predecessor_lineage_ids"] = ["unrelated-lineage"]
    successor = OutcomeContinuationScenarioV1.model_validate(payload)
    *_, claims_dir, _claim_path, _predecessor_path, successor_path, delta_path = _restart_fixture(
        tmp_path,
        monkeypatch,
        successor=successor,
    )

    with pytest.raises(OutcomeSelectionError) as caught:
        restart_selected_outcome_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            successor_scenario_path=successor_path,
            restart_delta_path=delta_path,
            claims_dir=claims_dir,
        )
    assert caught.value.code == expected_code


def test_causal_restart_rejects_mismatched_delta_without_mutating_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        selected,
        _repo,
        _worktree,
        claims_dir,
        _claim_path,
        _predecessor_path,
        successor_path,
        delta_path,
    ) = _restart_fixture(tmp_path, monkeypatch)
    delta_payload = json.loads(delta_path.read_text(encoding="utf-8"))
    delta_payload["predecessor_binding_sha256"] = "f" * 64
    delta_path.write_text(json.dumps(delta_payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(OutcomeSelectionError) as caught:
        restart_selected_outcome_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            successor_scenario_path=successor_path,
            restart_delta_path=delta_path,
            claims_dir=claims_dir,
        )
    assert caught.value.code == "restart_delta_mismatch"
    tracker = session_contracts.read_session_tracker(Path(selected.tracker_path))
    assert tracker["tracker"]["outcome_selection"]["outcome_lineage_id"] == "plan-117-stalled"
    assert "outcome_selection_transitions" not in tracker["tracker"]


def test_unplanned_claim_requires_exact_goal_authority_not_plan_inference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "plan117-test")
    _repo, _worktree, claims_dir, _claim_path, scenario_path = _fixture(tmp_path, plan_ref=None)

    with pytest.raises(OutcomeSelectionError) as caught:
        select_outcome_for_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            execution_authority_ref="enforced-planning#117",
            scenario_path=scenario_path,
            claims_dir=claims_dir,
        )
    assert caught.value.code == "authority_claim_mismatch"

    result = select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref="goal:durable-outcome",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )
    assert result.binding.execution_authority_ref == "goal:durable-outcome"
    assert result.binding.claim_plan_ref is None


def test_selected_resolution_survives_heartbeat_but_rejects_tamper_and_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, repo, worktree, _claims_dir, claim_path, scenario_path = _select(tmp_path, monkeypatch)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["heartbeat_at"] = datetime.now(UTC).isoformat()
    claim["expires_at"] = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")

    resolved = resolve_selected_outcome_for_prewrite(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan117-test",
        claim_source_file=str(claim_path),
        target_path=TARGET,
    )
    assert resolved.binding_sha256 == result.binding_sha256

    original = scenario_path.read_text(encoding="utf-8")
    scenario_path.write_text(original + "\n", encoding="utf-8")
    with pytest.raises(OutcomeSelectionError) as tampered:
        resolve_selected_outcome_for_prewrite(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch="plan117-test",
            claim_source_file=str(claim_path),
            target_path=TARGET,
        )
    assert tampered.value.code == "selection_scenario_stale"

    scenario_path.write_text(original, encoding="utf-8")
    claim["session_id"] = "codex:replacement"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    with pytest.raises(OutcomeSelectionError) as replaced:
        resolve_selected_outcome_for_prewrite(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch="plan117-test",
            claim_source_file=str(claim_path),
            target_path=TARGET,
        )
    assert replaced.value.code == "prewrite_claim_identity_mismatch"


def test_selection_cli_persists_machine_readable_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "plan117-test")
    _repo, worktree, claims_dir, _claim_path, scenario_path = _fixture(tmp_path)
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "outcome_continuation.py"),
            "select",
            "--scenario",
            str(scenario_path),
            "--execution-authority",
            "goal:durable-outcome",
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            "plan117-test",
            "--session-id",
            SESSION,
            "--claims-dir",
            str(claims_dir),
        ],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "selected"
    assert payload["binding"]["execution_authority_ref"] == "goal:durable-outcome"
    assert len(payload["binding_sha256"]) == 64


def test_session_start_refresh_preserves_create_once_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refreshing the same sanctioned session cannot erase selected state."""

    result, repo, worktree, claims_dir, _claim_path, scenario_path = _select(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    refreshed = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        intent="exercise durable outcome selection",
        plan_ref="goal:durable-outcome",
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan117-test",
        session_id=SESSION,
        broader_goal="Durable Outcome Selection Test",
        current_phase="observe selected outcome",
        claim_type="program",
        write_paths=[TARGET],
        tracker_dir=Path(result.tracker_path).parents[1],
    )

    assert refreshed["action"] == "updated"
    tracker = session_contracts.read_session_tracker(Path(result.tracker_path))
    assert tracker["tracker"]["outcome_selection"]["scenario_ref"] == "scenarios/selected.json"
    replay = select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=SESSION,
        execution_authority_ref="goal:durable-outcome",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )
    assert replay.status == "idempotent"
    assert replay.binding_sha256 == result.binding_sha256


def test_cross_session_resume_transfers_selected_outcome_without_reset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A sanctioned runtime handoff must preserve and rebind selected state."""

    selected, repo, worktree, claims_dir, claim_path, _scenario_path = _select(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    prior_tracker = session_contracts.read_session_tracker(Path(selected.tracker_path))
    prior_binding = prior_tracker["tracker"]["outcome_selection"]

    handed_off = session_lifecycle.handoff_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        note="transfer the interrupted outcome without resetting its evidence",
    )
    assert handed_off["action"] == "handoff"

    successor_session = "codex:plan118-successor"
    resumed = session_lifecycle.resume_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        worktree_path=str(worktree),
        branch="plan117-test",
        current_phase="continue the retained selected outcome",
        session_id=successor_session,
    )

    assert resumed["action"] == "resumed"
    assert resumed["outcome_session_transfer"]["reason"] == "session_resume"
    tracker = session_contracts.read_session_tracker(Path(selected.tracker_path))
    rebound = tracker["tracker"]["outcome_selection"]
    transfers = tracker["tracker"]["outcome_session_transfers"]
    assert len(transfers) == 1
    assert transfers[0] == resumed["outcome_session_transfer"]
    assert rebound["session_id"] == successor_session
    assert rebound["scenario_sha256"] == prior_binding["scenario_sha256"]
    assert rebound["outcome_contract_sha256"] == prior_binding["outcome_contract_sha256"]
    assert rebound["lease_sha256"] == prior_binding["lease_sha256"]
    assert rebound["outcome_lineage_id"] == prior_binding["outcome_lineage_id"]

    resolved = resolve_selected_outcome_for_prewrite(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        session_id=successor_session,
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan117-test",
        claim_source_file=str(claim_path),
        target_path=TARGET,
    )
    assert resolved.binding.session_id == successor_session
    with pytest.raises(OutcomeSelectionError) as predecessor_runtime:
        resolve_selected_outcome_for_prewrite(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=SESSION,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch="plan117-test",
            claim_source_file=str(claim_path),
            target_path=TARGET,
        )
    assert predecessor_runtime.value.code == "prewrite_claim_identity_mismatch"


def test_legacy_claim_only_resume_reproduces_selected_tracker_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-Plan-118 claim-only identity change strands selected state."""

    _selected, repo, worktree, _claims_dir, claim_path, _scenario_path = _select(
        tmp_path,
        monkeypatch,
    )
    successor_session = "codex:legacy-claim-only-successor"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["session_id"] = successor_session
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")

    with pytest.raises(OutcomeSelectionError) as caught:
        resolve_selected_outcome_for_prewrite(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            session_id=successor_session,
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch="plan117-test",
            claim_source_file=str(claim_path),
            target_path=TARGET,
        )
    assert caught.value.code == "tracker_claim_mismatch"


def test_cross_session_resume_restores_exact_preflight_state_when_tracker_transfer_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected, _repo, worktree, claims_dir, claim_path, _scenario_path = _select(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    session_lifecycle.handoff_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        note="preserve these exact preflight bytes",
    )
    claim_before = claim_path.read_bytes()
    tracker_path = Path(selected.tracker_path)
    tracker_before = tracker_path.read_bytes()

    def fail_tracker_transfer(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected tracker replacement failure")

    monkeypatch.setattr(
        outcome_selection,
        "apply_prepared_outcome_session_transfer",
        fail_tracker_transfer,
    )
    with pytest.raises(OSError, match="injected tracker replacement failure"):
        session_lifecycle.resume_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            worktree_path=str(worktree),
            branch="plan117-test",
            current_phase="this phase must roll back",
            session_id="codex:plan118-failed-successor",
        )

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)


def test_cross_session_resume_reports_typed_incomplete_transition_if_rollback_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _selected, _repo, worktree, claims_dir, _claim_path, _scenario_path = _select(
        tmp_path,
        monkeypatch,
    )
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    session_lifecycle.handoff_session(
        agent="codex",
        project="enforced-planning",
        scope="plan117-test",
        note="exercise typed incomplete transfer reporting",
    )

    def fail_tracker_transfer(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected tracker replacement failure")

    def fail_rollback(**_kwargs: object) -> None:
        raise OSError("injected rollback failure")

    monkeypatch.setattr(
        outcome_selection,
        "apply_prepared_outcome_session_transfer",
        fail_tracker_transfer,
    )
    monkeypatch.setattr(session_lifecycle, "_rollback_outcome_session_transfer", fail_rollback)

    with pytest.raises(session_lifecycle.SessionTransferIncompleteError) as caught:
        session_lifecycle.resume_session(
            agent="codex",
            project="enforced-planning",
            scope="plan117-test",
            worktree_path=str(worktree),
            branch="plan117-test",
            current_phase="incomplete transition must be visible",
            session_id="codex:plan118-incomplete-successor",
        )
    assert caught.value.code == "session_transfer_incomplete"
    assert "rollback was incomplete" in str(caught.value)


def test_session_upsert_keeps_goal_on_actual_write_claim_without_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sanctioned session path must not recreate an UNPLANNED child claim."""

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )
    monkeypatch.setenv("CODEX_THREAD_ID", "plan117-test")
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "owner-week"
    worktree.mkdir(parents=True)

    action = session_lifecycle._upsert_session_claim(
        agent="codex",
        project="enforced-planning",
        scope="owner-week",
        intent="advance one sequential owner outcome",
        plan_ref="goal:durable-outcome",
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="owner-week",
        session_id=SESSION,
        broader_goal="Durable Outcome",
        session_name="durable-outcome",
        tracker_path=str(tmp_path / "tracker.yaml"),
        claim_type="program",
        write_paths=[TARGET],
    )

    assert action == "created"
    payload = yaml.safe_load((claims_dir / "codex_enforced-planning_owner-week.yaml").read_text(encoding="utf-8"))
    assert payload["plan_ref"] == "goal:durable-outcome"
    assert payload["write_paths"] == [TARGET]
    assert payload["work_graph_path"] is None
    assert payload["work_unit_id"] is None
