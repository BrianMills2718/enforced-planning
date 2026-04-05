"""Tests for session bootstrap contract and tracker helpers."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

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
        now=datetime(2026, 4, 5, 18, 0, tzinfo=timezone.utc),
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
