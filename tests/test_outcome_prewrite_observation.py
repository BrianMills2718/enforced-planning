from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import session_contracts
from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    EvidenceBindingV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeProgressReceiptV1,
    canonical_sha256,
    evaluate_scenario,
    load_scenario,
)
from enforced_planning.outcome_prewrite_observation import (
    OutcomePreWriteCorrelationV1,
    OutcomePreWriteObservationFailureV1,
    load_observation_records,
    observe_prewrite_outcome,
)
from enforced_planning.outcome_selection import select_outcome_for_session
from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast
from enforced_planning.prewrite_claim_projection import write_projection

ROOT = Path(__file__).resolve().parents[1]
TARGET = "docs/evidence/plan116_prewrite_outcome_correlation.json"
SESSION = "codex:plan116-test"
PROFILE_SHA256 = hashlib.sha256(b"plan116-test-profile").hexdigest()


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "-b", "plan116-test", str(worktree))
    (worktree / "docs" / "evidence").mkdir(parents=True)
    (worktree / "scenarios").mkdir()

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(UTC)
    tracker_dir = tmp_path / "sessions"
    session_contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="plan116-test",
        intent="exercise outcome pre-write observation",
        plan_ref="goal:owner-prewrite-correlation",
        repo_root=str(repo),
        worktree_path=str(worktree),
        branch="plan116-test",
        session_id=SESSION,
        broader_goal="Owner Prewrite Correlation",
    )
    tracker_path = session_contracts.session_tracker_path(session_contract, tracker_dir=tracker_dir)
    session_contract = session_contract.with_tracker_path(str(tracker_path))
    session_contracts.write_session_tracker(
        session_contracts.build_session_tracker(
            contract=session_contract,
            current_phase="observe outcome pre-write",
        ),
        tracker_dir=tracker_dir,
    )
    claim_path = claims_dir / "codex_plan116-test_plan116-test.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["enforced-planning"],
                "scope": "plan116-test",
                "intent": "exercise outcome pre-write observation",
                "claim_type": "program",
                "write_paths": [TARGET],
                "read_paths": [],
                "worktree_path": str(worktree),
                "repo_root": str(repo),
                "branch": "plan116-test",
                "session_name": "plan116-test",
                "session_id": SESSION,
                "broader_goal": "Owner Prewrite Correlation",
                "tracker_path": str(tracker_path),
                "plan_ref": "goal:owner-prewrite-correlation",
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    return repo, worktree, claims_dir, claim_path, projection_path


def _payload(worktree: Path, *, target: str = TARGET) -> dict[str, object]:
    return {
        "session_id": "plan116-test",
        "cwd": str(worktree),
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": f"*** Begin Patch\n*** Update File: {target}\n*** End Patch"},
    }


def _contract(*, target: str = TARGET, project_id: str = "enforced-planning") -> OutcomeContractV1:
    return OutcomeContractV1(
        outcome_id="owner-prewrite-correlation",
        owner_class="brian-agent-owner",
        project_id=project_id,
        lineage_id="plan-116-prewrite-correlation",
        predecessor_lineage_ids=["plan-115-owner-observation"],
        intended_consumer="Brian and his coding agents working on Enforced Planning",
        outcome="Link progress-bound continuation evidence to one exact claimed write.",
        canonical_journey={
            "starting_state": "One exact Plan 116 claimed write is ready for observation.",
            "input": "The native apply_patch payload and one immutable outcome scenario.",
            "action": "Record ordinary claim admission, then correlate the outcome decision.",
            "observable_result": "The ordinary receipt links to would_allow or would_deny.",
            "failure_signal": "Identity is lost or observation changes ordinary admission.",
        },
        baseline_revision="218394e0046770acb05b755553e36c7e7ccd136a",
        allowed_scope=[target],
        progress_dimensions=["owner continuation behavior"],
    )


def _evidence(receipt_id: str) -> EvidenceBindingV1:
    return EvidenceBindingV1(
        source_revision="218394e0046770acb05b755553e36c7e7ccd136a",
        configuration_sha256=PROFILE_SHA256,
        route="plan-116-prewrite-correlation-test",
        command=["python", "scripts/outcome_continuation.py", "evaluate"],
        observation_sha256=hashlib.sha256(receipt_id.encode()).hexdigest(),
        artifact_refs=["docs/evidence/plan115_owner_real_outcome_observation.json"],
        observed_at="2026-08-21T03:05:25Z",
    )


def _scenarios(
    *,
    target: str = TARGET,
    project_id: str = "enforced-planning",
) -> tuple[OutcomeContinuationScenarioV1, OutcomeContinuationScenarioV1]:
    contract = _contract(target=target, project_id=project_id)
    contract_sha256 = canonical_sha256(contract)
    positive_receipt = OutcomeProgressReceiptV1(
        receipt_id="plan-116-owner-progress",
        outcome_contract_sha256=contract_sha256,
        progress_kind="behavioral_advance",
        dimension="owner continuation behavior",
        summary="Plan 115 proved owner-real progress and selected this exact correlation seam.",
        evidence=_evidence("plan-116-owner-progress"),
        discriminating_evidence=True,
    )
    first_circular = OutcomeProgressReceiptV1(
        receipt_id="plan-116-motion-one",
        outcome_contract_sha256=contract_sha256,
        progress_kind="non_outcome",
        dimension="owner continuation behavior",
        summary="One supporting increment completed without advancing the stable owner outcome.",
        evidence=_evidence("plan-116-motion-one"),
        failure_boundary="owner-outcome-unchanged",
    )
    second_circular = OutcomeProgressReceiptV1(
        receipt_id="plan-116-motion-two",
        outcome_contract_sha256=contract_sha256,
        prior_receipt_sha256=canonical_sha256(first_circular),
        progress_kind="non_outcome",
        dimension="owner continuation behavior",
        summary="A second supporting increment completed while the owner outcome stayed unchanged.",
        evidence=_evidence("plan-116-motion-two"),
        failure_boundary="owner-outcome-unchanged",
    )
    request = AdmissionRequestV1(
        operation="product_write",
        target_path=target,
        ordinary_approval=True,
        approval_text="I approve, continue",
        cost_telemetry_usd=Decimal(1000000),
        elapsed_telemetry_seconds=999999,
    )
    return (
        OutcomeContinuationScenarioV1(
            scenario_id="plan-116-owner-progress",
            contract=contract,
            receipts=[positive_receipt],
            request=request,
        ),
        OutcomeContinuationScenarioV1(
            scenario_id="plan-116-circular",
            contract=contract,
            receipts=[first_circular, second_circular],
            request=request,
        ),
    )


def _write_scenario(path: Path, scenario: OutcomeContinuationScenarioV1) -> None:
    path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _ordinary_decision(
    tmp_path: Path,
    worktree: Path,
    claims_dir: Path,
    projection_path: Path,
    *,
    mode: str = "observe",
) -> dict[str, object]:
    return evaluate_prewrite_fast(
        _payload(worktree),
        client="codex",
        mode=mode,
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "ordinary.jsonl",
    )


def _invoke_cli(
    tmp_path: Path,
    worktree: Path,
    claims_dir: Path,
    projection_path: Path,
    *,
    scenario_path: Path | None = None,
    selected: bool = False,
    json_output: bool = True,
    mode: str = "observe",
) -> subprocess.CompletedProcess[str]:
    command = [
        sys.executable,
        str(ROOT / "scripts" / "prewrite_claim_gate.py"),
        "--client",
        "codex",
        "--mode",
        mode,
        "--claims-dir",
        str(claims_dir),
        "--projection-path",
        str(projection_path),
        "--receipt-path",
        str(tmp_path / "ordinary-cli.jsonl"),
    ]
    if scenario_path is not None:
        command.extend(
            [
                "--outcome-scenario",
                str(scenario_path),
                "--outcome-receipt-path",
                str(tmp_path / "outcome-cli.jsonl"),
            ]
        )
    if selected:
        command.extend(
            [
                "--outcome-selected",
                "--outcome-receipt-path",
                str(tmp_path / "outcome-cli.jsonl"),
            ]
        )
    if json_output:
        command.append("--json")
    return subprocess.run(
        command,
        cwd=worktree,
        input=json.dumps(_payload(worktree)),
        capture_output=True,
        text=True,
        check=False,
    )


def test_same_payload_records_typed_would_allow_and_would_deny(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    positive, circular = _scenarios()
    positive_path = worktree / "scenarios" / "positive.json"
    circular_path = worktree / "scenarios" / "circular.json"
    _write_scenario(positive_path, positive)
    _write_scenario(circular_path, circular)
    observation_path = tmp_path / "outcome.jsonl"

    positive_ordinary = _ordinary_decision(tmp_path, worktree, claims_dir, projection_path)
    positive_record = observe_prewrite_outcome(
        positive_ordinary,
        scenario_path=positive_path,
        receipt_path=observation_path,
    )
    circular_ordinary = _ordinary_decision(tmp_path, worktree, claims_dir, projection_path)
    circular_record = observe_prewrite_outcome(
        circular_ordinary,
        scenario_path=circular_path,
        receipt_path=observation_path,
    )

    assert isinstance(positive_record, OutcomePreWriteCorrelationV1)
    assert isinstance(circular_record, OutcomePreWriteCorrelationV1)
    assert positive_record.disposition == "would_allow"
    assert positive_record.outcome_reason_code == "active_in_scope"
    assert circular_record.disposition == "would_deny"
    assert circular_record.outcome_reason_code == "recovery_required"
    assert positive_record.ordinary.normalized_target_path == TARGET
    assert circular_record.ordinary.normalized_target_path == TARGET
    assert positive_record.ordinary.receipt_id == positive_ordinary["receipt_id"]
    assert circular_record.ordinary.receipt_id == circular_ordinary["receipt_id"]
    assert positive_record.enforcement_applied is False
    assert circular_record.enforcement_applied is False
    assert positive.request == circular.request
    assert positive.contract == circular.contract
    assert load_observation_records(observation_path) == [positive_record, circular_record]


@pytest.mark.parametrize(
    ("scenario_target", "project_id", "error_code"),
    [
        ("docs/evidence/different.json", "enforced-planning", "target_mismatch"),
        (TARGET, "different-project", "project_mismatch"),
    ],
)
def test_binding_mismatch_is_typed_visible_and_does_not_mutate_ordinary_decision(
    tmp_path: Path,
    scenario_target: str,
    project_id: str,
    error_code: str,
) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    scenario, _circular = _scenarios(target=scenario_target, project_id=project_id)
    scenario_path = worktree / "scenarios" / "mismatch.json"
    _write_scenario(scenario_path, scenario)
    ordinary = _ordinary_decision(tmp_path, worktree, claims_dir, projection_path)
    before = json.loads(json.dumps(ordinary))

    record = observe_prewrite_outcome(
        ordinary,
        scenario_path=scenario_path,
        receipt_path=tmp_path / "outcome.jsonl",
    )

    assert isinstance(record, OutcomePreWriteObservationFailureV1)
    assert record.error_code == error_code
    assert record.ordinary is not None
    assert record.ordinary.receipt_id == ordinary["receipt_id"]
    assert ordinary == before
    assert load_observation_records(tmp_path / "outcome.jsonl") == [record]


def test_scenario_outside_the_claimed_worktree_is_rejected_and_receipted(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    scenario, _circular = _scenarios()
    outside_path = tmp_path / "outside-scenario.json"
    _write_scenario(outside_path, scenario)
    ordinary = _ordinary_decision(tmp_path, worktree, claims_dir, projection_path)

    record = observe_prewrite_outcome(
        ordinary,
        scenario_path=outside_path,
        receipt_path=tmp_path / "outcome.jsonl",
    )

    assert isinstance(record, OutcomePreWriteObservationFailureV1)
    assert record.error_code == "scenario_outside_worktree"
    assert record.ordinary is not None
    assert load_observation_records(tmp_path / "outcome.jsonl") == [record]


def test_multiple_prewrite_targets_cannot_share_one_outcome_authority(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    scenario, _circular = _scenarios()
    scenario_path = worktree / "scenarios" / "positive.json"
    _write_scenario(scenario_path, scenario)
    ordinary = _ordinary_decision(tmp_path, worktree, claims_dir, projection_path)
    ordinary["normalized_target_paths"] = [TARGET, "docs/evidence/other.json"]

    record = observe_prewrite_outcome(
        ordinary,
        scenario_path=scenario_path,
        receipt_path=tmp_path / "outcome.jsonl",
    )

    assert isinstance(record, OutcomePreWriteObservationFailureV1)
    assert record.error_code == "target_count_mismatch"
    assert record.ordinary is None


def test_cli_no_option_is_unchanged_and_both_signs_preserve_ordinary_allow(
    tmp_path: Path,
) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    positive, circular = _scenarios()
    positive_path = worktree / "scenarios" / "positive.json"
    circular_path = worktree / "scenarios" / "circular.json"
    _write_scenario(positive_path, positive)
    _write_scenario(circular_path, circular)

    ordinary = _invoke_cli(tmp_path, worktree, claims_dir, projection_path)
    positive_run = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        scenario_path=positive_path,
    )
    circular_run = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        scenario_path=circular_path,
    )

    assert ordinary.returncode == positive_run.returncode == circular_run.returncode == 0
    ordinary_payload = json.loads(ordinary.stdout)
    positive_payload = json.loads(positive_run.stdout)
    circular_payload = json.loads(circular_run.stdout)
    assert set(ordinary_payload) == {
        "schema_version",
        "receipt_id",
        "decision",
        "mode",
        "reason_code",
        "client",
        "session_id",
        "repo_root",
        "worktree_path",
        "branch",
        "normalized_target_paths",
        "claim_project",
        "claim_scope",
        "claim_source_file",
        "details",
        "recovery",
        "elapsed_ms",
        "cache_hit",
    }
    assert "outcome_observation" not in ordinary_payload
    assert (positive_payload["decision"], positive_payload["reason_code"]) == (
        "allow",
        "exact_live_claim",
    )
    assert (circular_payload["decision"], circular_payload["reason_code"]) == (
        "allow",
        "exact_live_claim",
    )
    assert positive_payload["outcome_observation"]["disposition"] == "would_allow"
    assert circular_payload["outcome_observation"]["disposition"] == "would_deny"
    ordinary_receipts = [
        json.loads(line) for line in (tmp_path / "ordinary-cli.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    observations = load_observation_records(tmp_path / "outcome-cli.jsonl")
    assert len(ordinary_receipts) == 3
    assert len(observations) == 2
    ordinary_by_id = {item["receipt_id"]: item for item in ordinary_receipts}
    for observation in observations:
        ordinary_record = ordinary_by_id[observation.ordinary.receipt_id]  # type: ignore[union-attr]
        assert datetime.fromisoformat(ordinary_record["recorded_at"]) <= observation.observed_at


def test_selected_cli_resolves_tracker_binding_and_preserves_ordinary_allow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "plan116-test")
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    positive, _circular = _scenarios()
    scenario_path = worktree / "scenarios" / "selected.json"
    _write_scenario(scenario_path, positive)
    selection = select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan116-test",
        session_id=SESSION,
        execution_authority_ref="goal:owner-prewrite-correlation",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )

    completed = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        selected=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert (payload["decision"], payload["reason_code"]) == ("allow", "exact_live_claim")
    observation = payload["outcome_observation"]
    assert observation["disposition"] == "would_allow"
    assert observation["selection_binding_sha256"] == selection.binding_sha256
    assert observation["selection_execution_authority_ref"] == "goal:owner-prewrite-correlation"
    assert observation["ordinary_authority_preserved"] is True
    assert observation["enforcement_applied"] is False


def test_selected_circular_control_would_deny_but_preserves_ordinary_allow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "plan116-test")
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    _positive, circular = _scenarios()
    scenario_path = worktree / "scenarios" / "selected-circular.json"
    _write_scenario(scenario_path, circular)
    select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan116-test",
        session_id=SESSION,
        execution_authority_ref="goal:owner-prewrite-correlation",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )

    completed = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        selected=True,
    )

    assert completed.returncode == 0
    payload = json.loads(completed.stdout)
    assert (payload["decision"], payload["reason_code"]) == ("allow", "exact_live_claim")
    assert payload["outcome_observation"]["disposition"] == "would_deny"
    assert payload["outcome_observation"]["outcome_reason_code"] == "recovery_required"


def test_selected_cli_records_missing_and_tampered_binding_without_changing_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_THREAD_ID", "plan116-test")
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)

    missing = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        selected=True,
    )
    assert missing.returncode == 0
    missing_payload = json.loads(missing.stdout)
    assert missing_payload["decision"] == "allow"
    assert missing_payload["outcome_observation"]["error_code"] == "selection_missing"

    positive, _circular = _scenarios()
    scenario_path = worktree / "scenarios" / "selected.json"
    _write_scenario(scenario_path, positive)
    select_outcome_for_session(
        agent="codex",
        project="enforced-planning",
        scope="plan116-test",
        session_id=SESSION,
        execution_authority_ref="goal:owner-prewrite-correlation",
        scenario_path=scenario_path,
        claims_dir=claims_dir,
    )
    scenario_path.write_text(scenario_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    tampered = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        selected=True,
    )
    assert tampered.returncode == 0
    tampered_payload = json.loads(tampered.stdout)
    assert tampered_payload["decision"] == "allow"
    assert tampered_payload["outcome_observation"]["error_code"] == "selection_scenario_stale"


def test_selected_and_explicit_scenario_flags_are_mutually_exclusive(
    tmp_path: Path,
) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    positive, _circular = _scenarios()
    scenario_path = worktree / "scenarios" / "selected.json"
    _write_scenario(scenario_path, positive)
    completed = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        scenario_path=scenario_path,
        selected=True,
    )
    assert completed.returncode == 2
    assert "not allowed with argument" in completed.stderr


def test_native_ordinary_deny_and_observation_error_keep_original_exit_authority(
    tmp_path: Path,
) -> None:
    _repo, worktree, claims_dir, claim_path, projection_path = _fixture(tmp_path)
    positive, _circular = _scenarios()
    positive_path = worktree / "scenarios" / "positive.json"
    _write_scenario(positive_path, positive)
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim["write_paths"] = ["docs/evidence/other.json"]
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    denied = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        scenario_path=positive_path,
        json_output=False,
        mode="enforce",
    )

    assert denied.returncode == 2
    assert "Pre-write claim denied (path_outside_claim)" in denied.stderr
    assert "would_allow" in denied.stdout
    records = load_observation_records(tmp_path / "outcome-cli.jsonl")
    assert len(records) == 1
    assert isinstance(records[0], OutcomePreWriteCorrelationV1)
    assert records[0].ordinary.decision == "deny"
    assert records[0].disposition == "would_allow"


def test_native_observation_failure_is_visible_but_does_not_change_allow_exit(
    tmp_path: Path,
) -> None:
    _repo, worktree, claims_dir, _claim_path, projection_path = _fixture(tmp_path)
    mismatch, _circular = _scenarios(target="docs/evidence/different.json")
    mismatch_path = worktree / "scenarios" / "mismatch.json"
    _write_scenario(mismatch_path, mismatch)

    completed = _invoke_cli(
        tmp_path,
        worktree,
        claims_dir,
        projection_path,
        scenario_path=mismatch_path,
        json_output=False,
        mode="enforce",
    )

    assert completed.returncode == 0
    assert "observation_error" in completed.stdout
    assert "target_mismatch" in completed.stdout
    assert completed.stderr == ""


def test_checked_in_controls_share_context_and_differ_only_on_progress_receipts() -> None:
    scenario_root = ROOT / "examples" / "owner-real-outcome-observe"
    positive_path = scenario_root / "plan116-owner-progress.json"
    circular_path = scenario_root / "plan116-circular.json"
    positive = load_scenario(str(positive_path))
    circular = load_scenario(str(circular_path))

    positive_result = evaluate_scenario(positive)
    circular_result = evaluate_scenario(circular)

    assert positive.contract == circular.contract
    assert positive.request == circular.request
    assert positive.request.approval_text == "I approve, continue"
    assert positive.request.cost_telemetry_usd == Decimal(1000000)
    assert positive.request.elapsed_telemetry_seconds == 999999
    assert positive_result.decision.allowed is True
    assert positive_result.decision.reason_code == "active_in_scope"
    assert circular_result.decision.allowed is False
    assert circular_result.decision.reason_code == "recovery_required"


def test_retained_plan116_evidence_matches_scenarios_and_correlation_results() -> None:
    evidence = json.loads(
        (ROOT / "docs" / "evidence" / "plan116_prewrite_outcome_correlation.json").read_text(encoding="utf-8")
    )
    scenario_root = ROOT / "examples" / "owner-real-outcome-observe"
    cases = (
        (
            "owner_progress_positive",
            scenario_root / "plan116-owner-progress.json",
            "would_allow",
            "active_in_scope",
        ),
        (
            "synthetic_circular_negative",
            scenario_root / "plan116-circular.json",
            "would_deny",
            "recovery_required",
        ),
    )

    scenarios = []
    for evidence_key, scenario_path, disposition, reason_code in cases:
        scenario = load_scenario(str(scenario_path))
        result = evaluate_scenario(scenario)
        retained = evidence[evidence_key]
        scenarios.append(scenario)
        assert retained["scenario_file_sha256"] == hashlib.sha256(scenario_path.read_bytes()).hexdigest()
        assert retained["scenario_sha256"] == result.scenario_sha256
        assert retained["outcome_contract_sha256"] == result.outcome_contract_sha256
        assert retained["correlation"]["disposition"] == disposition
        assert retained["correlation"]["reason_code"] == reason_code
        assert retained["correlation"]["lease_sha256"] == result.lease_sha256
        assert retained["correlation"]["applied_receipt_sha256s"] == result.applied_receipt_sha256s
        assert datetime.fromisoformat(retained["ordinary"]["recorded_at"]) < datetime.fromisoformat(
            retained["correlation"]["recorded_at"]
        )

    assert scenarios[0].contract == scenarios[1].contract
    assert scenarios[0].request == scenarios[1].request
    assert evidence["execution"]["candidate_revision"] == "686be2a14ddeb01b329edbd503040cc6fde9922c"
    assert evidence["execution"]["enforcement_applied"] is False
    assert evidence["ordinary_boundary"]["ordinary_decision_remained_authoritative"] is True
    assert "not outcome-based blocking" in evidence["limitations"][-1]
