from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import claim_mutation_receipts, coordination_claims, session_contracts, session_lifecycle
from enforced_planning.outcome_continuation import (
    AdmissionRequestV1,
    EvidenceBindingV1,
    OutcomeContinuationScenarioV1,
    OutcomeContractV1,
    OutcomeProgressReceiptV1,
    canonical_sha256,
)
from enforced_planning.outcome_selection import (
    OutcomeSelectionError,
    resolve_selected_outcome_for_prewrite,
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


def _scenario(*, scenario_id: str = "plan117-progress", outcome_id: str = "durable-outcome") -> OutcomeContinuationScenarioV1:
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
    payload = yaml.safe_load(
        (claims_dir / "codex_enforced-planning_owner-week.yaml").read_text(encoding="utf-8")
    )
    assert payload["plan_ref"] == "goal:durable-outcome"
    assert payload["write_paths"] == [TARGET]
    assert payload["work_graph_path"] is None
    assert payload["work_unit_id"] is None
