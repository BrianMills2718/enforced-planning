"""Tests for plan-owned lane inventory and atomic closeout."""

from __future__ import annotations

from dataclasses import replace

import yaml

from enforced_planning.coordination_claims import ClaimRecord
from enforced_planning.plan_close import close_plan_lanes


def _claim(
    *,
    scope: str,
    plan_ref: str = "alpha#12",
    status: str = "active",
) -> ClaimRecord:
    """Build one live plan-lane claim fixture."""
    return ClaimRecord(
        agent="codex",
        claimed_at="2026-07-27T00:00:00+00:00",
        expires_at="2099-07-28T00:00:00+00:00",
        projects=["alpha"],
        scope=scope,
        intent="fixture",
        claim_type="program",
        write_paths=[],
        read_paths=[],
        worktree_path=f"/repo/worktrees/{scope}",
        repo_root="/repo",
        branch=scope,
        session_name="alpha-plan-12",
        broader_goal="Alpha plan 12",
        tracker_path=f"/sessions/{scope}.yaml",
        session_id=f"codex:{scope}",
        heartbeat_at=None,
        status=status,
        updated_at=None,
        parent_scope=None,
        notes=None,
        plan_ref=plan_ref,
        source_file=None,
        schema_version=2,
    )


def test_preflight_failure_prevents_every_close_action():
    claims = [_claim(scope="merged"), _claim(scope="dirty")]
    closed: list[str] = []

    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=claims,
        preflight=lambda claim: (
            {"disposition": "merged"}
            if claim.scope == "merged"
            else ValueError("Worktree is dirty")
        ),
        closer=lambda claim: closed.append(claim.scope) or {"action": "closed"},
    )

    assert result.success is False
    assert closed == []
    assert result.actions_performed == []
    assert result.failures == ["dirty: Worktree is dirty"]


def test_all_preflighted_lanes_close_and_report_terminal_disposition():
    claims = [_claim(scope="lane-a"), _claim(scope="lane-b", plan_ref="Plan #12")]

    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=claims,
        preflight=lambda claim: {"disposition": "merged"},
        closer=lambda claim: {
            "action": "closed",
            "disposition": "merged",
            "worktree_action": "removed",
            "branch_action": "deleted",
        },
    )

    assert result.success is True
    assert [lane.lane_id for lane in result.lanes] == ["lane-a", "lane-b"]
    assert all(lane.terminal_disposition == "merged" for lane in result.lanes)
    assert result.actions_performed == [
        "lane-a: closed",
        "lane-b: closed",
    ]


def test_unrelated_and_nonlive_claims_are_not_owned_lanes():
    claims = [
        _claim(scope="owned"),
        replace(_claim(scope="other-plan"), plan_ref="alpha#13"),
        replace(_claim(scope="other-project"), projects=["beta"], plan_ref="beta#12"),
        _claim(scope="complete", status="completed"),
    ]

    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=claims,
        preflight=lambda claim: {"disposition": "merged"},
        closer=lambda claim: {"action": "closed", "disposition": "merged"},
    )

    assert [lane.lane_id for lane in result.lanes] == ["owned"]


def test_repeated_close_with_no_live_lanes_is_idempotent():
    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=[],
        preflight=lambda claim: ValueError("unreachable"),
        closer=lambda claim: {"action": "unreachable"},
    )

    assert result.success is True
    assert result.lanes == []
    assert result.actions_performed == []
    assert result.failures == []


def test_dry_run_preflights_without_closing():
    closed: list[str] = []
    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=[_claim(scope="lane-a")],
        preflight=lambda claim: {"disposition": "merged", "merged_to_default": True},
        closer=lambda claim: closed.append(claim.scope) or {"action": "closed"},
        dry_run=True,
    )

    assert result.success is True
    assert closed == []
    assert result.lanes[0].terminal_disposition == "merged"


def test_completed_claim_requires_recoverable_terminal_evidence(tmp_path):
    claim_file = tmp_path / "completed.yaml"
    claim_file.write_text(
        yaml.safe_dump(
            {
                "status": "completed",
                "disposition": "merged",
                "merged_to_default": True,
            }
        ),
        encoding="utf-8",
    )
    claim = replace(
        _claim(scope="closed", status="completed"),
        source_file=str(claim_file),
    )

    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=[claim],
    )

    assert result.success is True
    assert result.lanes[0].terminal_disposition == "merged"


def test_completed_claim_without_disposition_blocks_completion(tmp_path):
    claim_file = tmp_path / "completed.yaml"
    claim_file.write_text(yaml.safe_dump({"status": "completed"}), encoding="utf-8")
    claim = replace(
        _claim(scope="closed", status="completed"),
        source_file=str(claim_file),
    )

    result = close_plan_lanes(
        qualified_plan_id="alpha#12",
        submitted_revision="abc123",
        claims=[claim],
    )

    assert result.success is False
    assert result.failures == [
        "closed: Completed claim lacks an accepted recoverable disposition: missing."
    ]
