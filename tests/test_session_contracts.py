"""Tests for session bootstrap contract and tracker helpers."""

from __future__ import annotations

import stat
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from enforced_planning import coordination_claims, session_contracts


def test_session_contract_schema_distinguishes_claim_and_tracker_fields() -> None:
    """The formal schema should keep claim-critical and tracker-only fields separate."""

    schema = session_contracts.session_contract_schema()

    assert "broader_goal" in schema["claim_fields"]
    assert "tracker_path" in schema["claim_fields"]
    assert "current_phase" not in schema["claim_fields"]
    assert "current_phase" in schema["tracker_only_fields"]
    assert "intended_next_phases" in schema["tracker_only_fields"]


def test_session_contract_build_derives_name_from_broader_goal() -> None:
    """Session naming should track the broader goal, not a local task label."""

    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="Digimon_for_KG_application",
        scope="plan-31-hygiene-gate",
        intent="ground the controller on truthful benchmark iteration",
        plan_ref="Plan #31",
        repo_root="~/projects/Digimon_for_KG_application",
        worktree_path="~/projects/Digimon_for_KG_application_worktrees/plan-31-hygiene-gate",
        branch="plan-31-hygiene-gate",
        session_id="codex:abc123",
        broader_goal="DIGIMON Truthful Controller Grounding",
    )

    assert contract.session_name == "digimon-truthful-controller-grounding"


def test_session_contract_build_rejects_task_shaped_session_name() -> None:
    """Explicit session names must still match the broader-goal-derived slug."""

    try:
        session_contracts.SessionContract.build(
            agent="codex",
            project="Digimon_for_KG_application",
            scope="plan-31-hygiene-gate",
            intent="ground the controller on truthful benchmark iteration",
            plan_ref="Plan #31",
            repo_root="~/projects/Digimon_for_KG_application",
            worktree_path="~/projects/Digimon_for_KG_application_worktrees/plan-31-hygiene-gate",
            branch="plan-31-hygiene-gate",
            session_id="codex:abc123",
            broader_goal="DIGIMON Truthful Controller Grounding",
            session_name="plan-31-hygiene-gate",
        )
    except ValueError as exc:
        assert "broader-goal-derived canonical name" in str(exc)
    else:
        raise AssertionError("Expected a ValueError for a task-shaped session name")


def test_write_session_tracker_persists_nested_claim_and_tracker_sections(tmp_path: Path) -> None:
    """Tracker generation should produce one linked artifact with clear section boundaries."""

    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="session-bootstrap-contract",
        intent="define and implement the session bootstrap contract",
        plan_ref="Plan #30",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/plan-30-session-bootstrap-contract",
        branch="plan-30-session-bootstrap-contract",
        session_id="codex:019d-session",
        broader_goal="Cross-Project Session Contract Rollout",
    )
    tracker = session_contracts.build_session_tracker(
        contract=contract,
        current_phase="schema split and tracker artifact generation",
        intended_next_phases=[
            "wire session-start CLI",
            "enforce sanctioned repo entrypoints",
        ],
        depends_on_repos=["project-meta"],
        requires_shared_infra_changes=True,
        stop_conditions=["irreversible shared-state action"],
        notes="bootstrap slice in progress",
        now=datetime(2026, 4, 5, 18, 0, tzinfo=UTC),
    )

    path = session_contracts.write_session_tracker(tracker, tracker_dir=tmp_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))

    assert path.name.endswith("__cross-project-session-contract-rollout.yaml")
    assert payload["claim"]["session_name"] == "cross-project-session-contract-rollout"
    assert payload["claim"]["broader_goal"] == "Cross-Project Session Contract Rollout"
    assert payload["tracker"]["current_phase"] == "schema split and tracker artifact generation"
    assert payload["tracker"]["intended_next_phases"] == [
        "wire session-start CLI",
        "enforce sanctioned repo entrypoints",
    ]
    assert payload["tracker"]["depends_on_repos"] == ["project-meta"]
    assert payload["timestamps"]["created_at"] == "2026-04-05T18:00:00+00:00"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_tracker_update_preserves_outcome_selection_and_unrelated_fields(tmp_path: Path) -> None:
    """Lifecycle updates cannot erase the durable outcome selected by the session."""

    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="plan-117",
        intent="bind one exact outcome",
        plan_ref="enforced-planning#117",
        repo_root="/tmp/enforced-planning",
        worktree_path="/tmp/enforced-planning/worktrees/plan-117",
        branch="plan-117",
        session_id="codex:plan117",
        broader_goal="Bind One Exact Outcome",
    )
    record = session_contracts.build_session_tracker(
        contract=contract,
        current_phase="select outcome",
        notes="retain me",
    )
    path = session_contracts.write_session_tracker(record, tracker_dir=tmp_path)

    custody = {
        "outcome_selection": {"schema_version": "1.0.0", "binding_sha256": "a" * 64},
        "outcome_progress_transitions": [{"transition_sha256": "b" * 64}],
        "outcome_session_transfers": [{"transfer_sha256": "c" * 64}],
        "outcome_selection_transitions": [{"restart_sha256": "d" * 64}],
    }

    def add_custody(payload: dict[str, object]) -> None:
        tracker = payload["tracker"]
        assert isinstance(tracker, dict)
        tracker.update(custody)

    session_contracts.mutate_session_tracker(path, add_custody)
    session_contracts.update_session_tracker(
        path,
        current_phase="observe selected outcome",
        intended_next_phases=["retain evidence"],
    )

    payload = session_contracts.read_session_tracker(path)
    assert payload["tracker"]["current_phase"] == "observe selected outcome"
    for field, value in custody.items():
        assert payload["tracker"][field] == value
    assert payload["tracker"]["notes"] == "retain me"


def test_tracker_refresh_preserves_selection_and_rejects_identity_change(tmp_path: Path) -> None:
    """Session-start refresh cannot erase or move a create-once selection."""

    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="plan-117",
        intent="bind one exact outcome",
        plan_ref="goal:durable-outcome",
        repo_root="/tmp/enforced-planning",
        worktree_path="/tmp/enforced-planning/worktrees/plan-117",
        branch="plan-117",
        session_id="codex:plan117",
        broader_goal="Bind One Exact Outcome",
    )
    first = session_contracts.build_session_tracker(
        contract=contract,
        current_phase="select outcome",
        now=datetime(2026, 8, 21, 4, 0, tzinfo=UTC),
    )
    path = session_contracts.write_session_tracker(first, tracker_dir=tmp_path)
    custody = {
        "outcome_selection": {"schema_version": "1.0.0", "binding_sha256": "a" * 64},
        "outcome_progress_transitions": [{"transition_sha256": "b" * 64}],
        "outcome_session_transfers": [{"transfer_sha256": "c" * 64}],
        "outcome_selection_transitions": [{"restart_sha256": "d" * 64}],
    }

    def add_custody(payload: dict[str, object]) -> None:
        tracker = payload["tracker"]
        assert isinstance(tracker, dict)
        tracker.update(custody)

    session_contracts.mutate_session_tracker(path, add_custody)

    refreshed = session_contracts.build_session_tracker(
        contract=replace(
            contract,
            repo_root="/tmp/../tmp/enforced-planning",
            worktree_path="/tmp/../tmp/enforced-planning/worktrees/plan-117",
        ),
        current_phase="observe outcome",
        now=datetime(2026, 8, 21, 5, 0, tzinfo=UTC),
    )
    session_contracts.write_session_tracker(refreshed, tracker_dir=tmp_path)
    payload = session_contracts.read_session_tracker(path)
    assert payload["tracker"]["current_phase"] == "observe outcome"
    for field, value in custody.items():
        assert payload["tracker"][field] == value
    assert payload["timestamps"]["created_at"] == "2026-08-21T04:00:00+00:00"

    changed = session_contracts.build_session_tracker(
        contract=replace(contract, branch="replacement-branch"),
        current_phase="replace outcome",
    )
    with pytest.raises(ValueError, match="cannot change exact claim identity"):
        session_contracts.write_session_tracker(changed, tracker_dir=tmp_path)
    assert session_contracts.read_session_tracker(path) == payload


def test_tracker_mutations_are_serialized_without_lost_updates(tmp_path: Path) -> None:
    """Concurrent heartbeat-style mutations must not clobber selected state."""

    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="plan-117",
        intent="serialize tracker writes",
        plan_ref="enforced-planning#117",
        repo_root="/tmp/enforced-planning",
        worktree_path="/tmp/enforced-planning/worktrees/plan-117",
        branch="plan-117",
        session_id="codex:plan117",
        broader_goal="Serialize Tracker Writes",
    )
    path = session_contracts.write_session_tracker(
        session_contracts.build_session_tracker(contract=contract, current_phase="start"),
        tracker_dir=tmp_path,
    )
    session_contracts.mutate_session_tracker(
        path,
        lambda payload: payload["tracker"].__setitem__("mutation_count", 0),
    )

    def increment(_index: int) -> None:
        def mutation(payload: dict[str, object]) -> None:
            tracker = payload["tracker"]
            assert isinstance(tracker, dict)
            tracker["mutation_count"] = int(tracker["mutation_count"]) + 1

        session_contracts.mutate_session_tracker(path, mutation)

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(increment, range(24)))

    payload = session_contracts.read_session_tracker(path)
    assert payload["tracker"]["mutation_count"] == 24
    assert not list(path.parent.glob(f".{path.name}.*.tmp"))


def test_coordination_claims_accept_session_contract_fields() -> None:
    """Claim construction should preserve contract fields needed for later bootstrap wiring."""

    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="session-bootstrap-contract",
        intent="define and implement the session bootstrap contract",
        plan_ref="Plan #30",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/plan-30-session-bootstrap-contract",
        branch="plan-30-session-bootstrap-contract",
        session_id="codex:019d-session",
        broader_goal="Cross-Project Session Contract Rollout",
    ).with_tracker_path("~/.claude/coordination/sessions/enforced-planning/tracker.yaml")

    claim = coordination_claims.build_candidate_claim(
        agent=contract.agent,
        project=contract.project,
        scope=contract.scope,
        intent=contract.intent,
        plan_ref=contract.plan_ref,
        claim_type="write",
        write_paths=["docs/plans/30_session_bootstrap_contract_and_tracker.md"],
        repo_root=contract.repo_root,
        worktree_path=contract.worktree_path,
        branch=contract.branch,
        session_name=contract.session_name,
        broader_goal=contract.broader_goal,
        tracker_path=contract.tracker_path,
        session_id=contract.session_id,
    )

    assert claim.repo_root == "~/projects/enforced-planning"
    assert claim.session_name == "cross-project-session-contract-rollout"
    assert claim.broader_goal == "Cross-Project Session Contract Rollout"
    assert claim.tracker_path == "~/.claude/coordination/sessions/enforced-planning/tracker.yaml"
