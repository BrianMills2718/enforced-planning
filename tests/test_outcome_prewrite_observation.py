"""Both-sign and compatibility tests for Plan 116 pre-write outcome observation."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    CanonicalJourneyV1,
    EvidenceBindingV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeProgressReceiptV1,
    canonical_sha256,
    evaluate_scenario,
    load_scenario,
)
from enforced_planning.outcome_prewrite_observation import (
    OutcomePreWriteObservationError,
    evaluate_and_record_outcome_prewrite,
    load_outcome_prewrite_observations,
)
from enforced_planning.prewrite_claim_fast import evaluate_prewrite_fast
from enforced_planning.prewrite_claim_projection import write_projection

ROOT = Path(__file__).resolve().parents[1]
SESSION = "codex:plan116-test"
TARGET = "docs/evidence/plan116_prewrite_outcome_correlation.json"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")

    worktree = tmp_path / "worktree"
    _git(repo, "worktree", "add", "-b", "plan116-lane", str(worktree))
    (worktree / "docs" / "evidence").mkdir(parents=True)
    (worktree / "scenarios").mkdir()

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    now = datetime.now(UTC)
    claim_path = claims_dir / "codex_projection-test_plan116-lane.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["projection-test"],
                "scope": "plan116-lane",
                "intent": "test outcome correlation",
                "claim_type": "write",
                "write_paths": [TARGET],
                "read_paths": [],
                "worktree_path": str(worktree),
                "repo_root": str(repo),
                "branch": "plan116-lane",
                "session_name": "plan116-test",
                "session_id": SESSION,
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
    return repo, worktree, claims_dir, projection_path, claim_path


def _payload(worktree: Path, target: str = TARGET) -> dict[str, object]:
    return {
        "session_id": "plan116-test",
        "cwd": str(worktree),
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "tool_input": {
            "command": f"*** Begin Patch\n*** Update File: {target}\n*** End Patch"
        },
    }


def _contract(target: str = TARGET) -> OutcomeContractV1:
    return OutcomeContractV1(
        outcome_id="plan116-correlation",
        owner_class="brian-agent-owner",
        project_id="projection-test",
        lineage_id="plan116-correlation-lineage",
        predecessor_lineage_ids=["plan115-owner-observation"],
        intended_consumer="Brian and his coding agents",
        outcome="Correlate progress authority to one ordinary claimed write.",
        canonical_journey=CanonicalJourneyV1(
            starting_state="A live claimed worktree owns one exact evidence path.",
            input="One supported native pre-write payload and one immutable scenario.",
            action="Evaluate ordinary claim admission, then observe continuation authority.",
            observable_result="The linked observation reports would_allow or would_deny.",
            failure_signal="The correlation changes ordinary admission or loses exact identity.",
        ),
        baseline_revision="abcdef1234567890",
        allowed_scope=[target],
        progress_dimensions=["owner behavior"],
    )


def _receipt(
    contract: OutcomeContractV1,
    *,
    receipt_id: str,
    progress_kind: str,
    prior_receipt_sha256: str | None = None,
) -> OutcomeProgressReceiptV1:
    return OutcomeProgressReceiptV1(
        receipt_id=receipt_id,
        outcome_contract_sha256=canonical_sha256(contract),
        prior_receipt_sha256=prior_receipt_sha256,
        progress_kind=progress_kind,
        dimension="owner behavior",
        summary="The bounded observation produced one auditable increment.",
        evidence=EvidenceBindingV1(
            source_revision="abcdef1234567890",
            configuration_sha256="a" * 64,
            route="plan116-test-observation",
            command=["python", "test-probe.py"],
            observation_sha256="b" * 64,
            artifact_refs=["docs/evidence/source.json"],
            observed_at=datetime(2026, 8, 21, tzinfo=UTC),
        ),
        failure_boundary="same-plan116-boundary" if progress_kind == "non_outcome" else None,
        discriminating_evidence=progress_kind != "non_outcome",
    )


def _scenarios(target: str = TARGET) -> tuple[OutcomeContinuationScenarioV1, OutcomeContinuationScenarioV1]:
    contract = _contract(target)
    request = AdmissionRequestV1(
        operation="product_write",
        target_path=target,
        ordinary_approval=True,
        approval_text="I approve, continue",
        cost_telemetry_usd=Decimal(1000000),
        elapsed_telemetry_seconds=999999,
    )
    positive = OutcomeContinuationScenarioV1(
        scenario_id="plan116-positive",
        contract=contract,
        receipts=[
            _receipt(
                contract,
                receipt_id="plan116-positive-progress",
                progress_kind="behavioral_advance",
            )
        ],
        request=request,
    )
    first = _receipt(
        contract,
        receipt_id="plan116-circular-one",
        progress_kind="non_outcome",
    )
    second = _receipt(
        contract,
        receipt_id="plan116-circular-two",
        progress_kind="non_outcome",
        prior_receipt_sha256=canonical_sha256(first),
    )
    circular = OutcomeContinuationScenarioV1(
        scenario_id="plan116-circular",
        contract=contract,
        receipts=[first, second],
        request=request,
    )
    return positive, circular


def _write_scenario(path: Path, scenario: OutcomeContinuationScenarioV1) -> None:
    path.write_text(scenario.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _ordinary_decision(
    *,
    tmp_path: Path,
    worktree: Path,
    claims_dir: Path,
    projection_path: Path,
    target: str = TARGET,
    mode: str = "observe",
) -> dict[str, object]:
    return evaluate_prewrite_fast(
        _payload(worktree, target),
        client="codex",
        mode=mode,
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_path=tmp_path / "prewrite.jsonl",
    )


def _run_cli(
    *,
    payload: dict[str, object],
    claims_dir: Path,
    projection_path: Path,
    prewrite_path: Path,
    scenario_path: Path | None = None,
    observation_path: Path | None = None,
    mode: str = "observe",
    json_output: bool = True,
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
        str(prewrite_path),
    ]
    if scenario_path is not None:
        command.extend(["--outcome-scenario", str(scenario_path)])
    if observation_path is not None:
        command.extend(["--outcome-observation-path", str(observation_path)])
    if json_output:
        command.append("--json")
    return subprocess.run(
        command,
        cwd=ROOT,
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


def test_typed_observations_bind_same_payload_both_signs(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, projection_path, _claim_path = _fixture(tmp_path)
    positive, circular = _scenarios()
    positive_path = worktree / "scenarios" / "positive.json"
    circular_path = worktree / "scenarios" / "circular.json"
    _write_scenario(positive_path, positive)
    _write_scenario(circular_path, circular)
    observation_path = tmp_path / "outcome-observations.jsonl"

    positive_observation = evaluate_and_record_outcome_prewrite(
        prewrite_decision=_ordinary_decision(
            tmp_path=tmp_path,
            worktree=worktree,
            claims_dir=claims_dir,
            projection_path=projection_path,
        ),
        scenario_path=positive_path,
        observation_path=observation_path,
    )
    circular_observation = evaluate_and_record_outcome_prewrite(
        prewrite_decision=_ordinary_decision(
            tmp_path=tmp_path,
            worktree=worktree,
            claims_dir=claims_dir,
            projection_path=projection_path,
        ),
        scenario_path=circular_path,
        observation_path=observation_path,
    )

    assert positive.contract == circular.contract
    assert positive.request == circular.request
    assert positive_observation.outcome.disposition == "would_allow"
    assert positive_observation.outcome.reason_code == "active_in_scope"
    assert circular_observation.outcome.disposition == "would_deny"
    assert circular_observation.outcome.reason_code == "recovery_required"
    assert positive_observation.prewrite.decision == "allow"
    assert circular_observation.prewrite.decision == "allow"
    assert positive_observation.ordinary_admission_unchanged is True
    assert load_outcome_prewrite_observations(observation_path) == [
        positive_observation,
        circular_observation,
    ]


def test_checked_in_scenarios_share_contract_request_and_produce_both_signs() -> None:
    scenario_root = ROOT / "examples" / "owner-real-outcome-observe"
    positive = load_scenario(str(scenario_root / "plan116-owner-progress.json"))
    circular = load_scenario(str(scenario_root / "plan116-circular.json"))

    positive_result = evaluate_scenario(positive)
    circular_result = evaluate_scenario(circular)

    assert positive.contract == circular.contract
    assert positive.request == circular.request
    assert positive_result.decision.allowed is True
    assert positive_result.decision.reason_code == "active_in_scope"
    assert circular_result.decision.allowed is False
    assert circular_result.decision.reason_code == "recovery_required"
    assert positive_result.outcome_contract_sha256 == (
        "359d455043abf42a0e7efc297e30b2cd96b74f9ca600e95e5486c5581c546927"
    )


def test_target_or_project_mismatch_is_visible_and_not_recorded(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, projection_path, _claim_path = _fixture(tmp_path)
    positive, _circular = _scenarios("docs/evidence/different.json")
    scenario_path = worktree / "scenarios" / "mismatch.json"
    _write_scenario(scenario_path, positive)
    observation_path = tmp_path / "outcome-observations.jsonl"
    decision = _ordinary_decision(
        tmp_path=tmp_path,
        worktree=worktree,
        claims_dir=claims_dir,
        projection_path=projection_path,
    )

    with pytest.raises(OutcomePreWriteObservationError, match="target"):
        evaluate_and_record_outcome_prewrite(
            prewrite_decision=decision,
            scenario_path=scenario_path,
            observation_path=observation_path,
        )

    assert not observation_path.exists()


def test_cli_without_outcome_option_preserves_existing_json_shape(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, projection_path, _claim_path = _fixture(tmp_path)
    completed = _run_cli(
        payload=_payload(worktree),
        claims_dir=claims_dir,
        projection_path=projection_path,
        prewrite_path=tmp_path / "prewrite.jsonl",
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["decision"] == "allow"
    assert payload["reason_code"] == "exact_live_claim"
    assert "prewrite_decision" not in payload
    assert "outcome_observation" not in payload


def test_cli_reports_both_signs_without_changing_ordinary_exit(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, projection_path, _claim_path = _fixture(tmp_path)
    positive, circular = _scenarios()
    positive_path = worktree / "scenarios" / "positive.json"
    circular_path = worktree / "scenarios" / "circular.json"
    _write_scenario(positive_path, positive)
    _write_scenario(circular_path, circular)
    observation_path = tmp_path / "outcome-observations.jsonl"

    results = [
        _run_cli(
            payload=_payload(worktree),
            claims_dir=claims_dir,
            projection_path=projection_path,
            prewrite_path=tmp_path / "prewrite.jsonl",
            scenario_path=scenario_path,
            observation_path=observation_path,
        )
        for scenario_path in (positive_path, circular_path)
    ]
    payloads = [json.loads(result.stdout) for result in results]

    assert [result.returncode for result in results] == [0, 0]
    assert [payload["prewrite_decision"]["decision"] for payload in payloads] == [
        "allow",
        "allow",
    ]
    assert [payload["outcome_observation"]["outcome"]["disposition"] for payload in payloads] == [
        "would_allow",
        "would_deny",
    ]
    observations = load_outcome_prewrite_observations(observation_path)
    ordinary_receipts = [
        json.loads(line)
        for line in (tmp_path / "prewrite.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert [item.prewrite.receipt_id for item in observations] == [
        payloads[0]["prewrite_decision"]["receipt_id"],
        payloads[1]["prewrite_decision"]["receipt_id"],
    ]
    assert [item.prewrite.receipt_id for item in observations] == [
        receipt["receipt_id"] for receipt in ordinary_receipts
    ]


def test_observation_failure_is_visible_but_ordinary_allow_remains(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, projection_path, _claim_path = _fixture(tmp_path)
    mismatch, _circular = _scenarios("docs/evidence/different.json")
    scenario_path = worktree / "scenarios" / "mismatch.json"
    _write_scenario(scenario_path, mismatch)

    completed = _run_cli(
        payload=_payload(worktree),
        claims_dir=claims_dir,
        projection_path=projection_path,
        prewrite_path=tmp_path / "prewrite.jsonl",
        scenario_path=scenario_path,
        observation_path=tmp_path / "outcome-observations.jsonl",
        json_output=False,
    )

    assert completed.returncode == 0
    notice = json.loads(completed.stdout)
    assert "outcome correlation failed" in notice["systemMessage"].lower()


def test_ordinary_deny_remains_authoritative_when_outcome_would_allow(tmp_path: Path) -> None:
    _repo, worktree, claims_dir, projection_path, claim_path = _fixture(tmp_path)
    denied_target = "docs/evidence/outside-claim.json"
    positive, _circular = _scenarios(denied_target)
    scenario_path = worktree / "scenarios" / "positive-outside.json"
    _write_scenario(scenario_path, positive)
    observation_path = tmp_path / "outcome-observations.jsonl"

    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert denied_target not in claim["write_paths"]
    completed = _run_cli(
        payload=_payload(worktree, denied_target),
        claims_dir=claims_dir,
        projection_path=projection_path,
        prewrite_path=tmp_path / "prewrite.jsonl",
        scenario_path=scenario_path,
        observation_path=observation_path,
        mode="enforce",
        json_output=False,
    )

    assert completed.returncode == 2
    assert "path_outside_claim" in completed.stderr
    observation = load_outcome_prewrite_observations(observation_path)[0]
    assert observation.prewrite.decision == "deny"
    assert observation.outcome.disposition == "would_allow"
    assert observation.ordinary_admission_unchanged is True
