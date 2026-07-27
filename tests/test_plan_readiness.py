"""Tests for the portable canonical-plan readiness adapter."""

from __future__ import annotations

import json
import sys

import pytest

from enforced_planning.plan_readiness import (
    PlanLaneIdentityV1,
    check_plan_start_readiness,
)


def _query_command(tmp_path, *, decision: str, exit_code: int, error_code: str | None = None) -> str:
    """Create one deterministic stand-in for the ecosystem plan query."""
    script = tmp_path / "fake_plan_graph.py"
    payload = {
        "schema_version": "1.0.0",
        "qualified_plan_id": "alpha#12",
        "graph_revision": "a" * 64,
        "decision": decision,
        "blocker_ids": ["shared#8"] if decision == "blocked" else [],
        "evidence_refs": ["graph-sha256:" + ("a" * 64), "/plans/12.md"],
        "reason": f"fixture {decision}",
        "error_code": error_code,
    }
    script.write_text(
        "import json, sys\n"
        f"print(json.dumps({payload!r}))\n"
        f"raise SystemExit({exit_code})\n",
        encoding="utf-8",
    )
    return f"{sys.executable} {script}"


def test_ready_decision_builds_fully_qualified_lane_identity(tmp_path):
    result = check_plan_start_readiness(
        qualified_plan_id="alpha#12",
        execution_profile="coordinated",
        query_command=_query_command(tmp_path, decision="ready", exit_code=0),
        repository="alpha",
        lane_id="plan-12-feature",
        branch="plan-12-feature",
        worktree_path="/repo/worktrees/plan-12-feature",
        claim_identity="codex:alpha:plan-12-feature",
        session_identity="codex:thread-1",
    )

    assert result.allowed is True
    assert result.readiness.decision == "ready"
    assert result.lane == PlanLaneIdentityV1(
        schema_version="1.0.0",
        qualified_plan_id="alpha#12",
        lane_id="plan-12-feature",
        parent_lane_id=None,
        repository="alpha",
        branch="plan-12-feature",
        worktree_path="/repo/worktrees/plan-12-feature",
        claim_identity="codex:alpha:plan-12-feature",
        session_identity="codex:thread-1",
        creation_revision="a" * 64,
        execution_profile="coordinated",
    )


@pytest.mark.parametrize(
    ("decision", "exit_code", "error_code"),
    [
        ("blocked", 2, None),
        ("already_active", 2, None),
        ("unknown", 2, "missing_plan"),
    ],
)
def test_negative_decision_fails_before_lane_creation(
    tmp_path,
    decision,
    exit_code,
    error_code,
):
    with pytest.raises(ValueError, match=decision):
        check_plan_start_readiness(
            qualified_plan_id="alpha#12",
            execution_profile="coordinated",
            query_command=_query_command(
                tmp_path,
                decision=decision,
                exit_code=exit_code,
                error_code=error_code,
            ),
            repository="alpha",
            lane_id="plan-12-feature",
            branch="plan-12-feature",
            worktree_path="/repo/worktrees/plan-12-feature",
            claim_identity="codex:alpha:plan-12-feature",
            session_identity="codex:thread-1",
        )


@pytest.mark.parametrize("profile", ["coordinated", "release"])
def test_governed_profiles_require_query_configuration(profile):
    with pytest.raises(ValueError, match="query command"):
        check_plan_start_readiness(
            qualified_plan_id="alpha#12",
            execution_profile=profile,
            query_command=None,
            repository="alpha",
            lane_id="plan-12-feature",
            branch="plan-12-feature",
            worktree_path="/repo/worktrees/plan-12-feature",
            claim_identity="codex:alpha:plan-12-feature",
            session_identity="codex:thread-1",
        )


def test_light_unplanned_profile_may_skip_query():
    result = check_plan_start_readiness(
        qualified_plan_id=None,
        execution_profile="light",
        query_command=None,
        repository="alpha",
        lane_id="maintenance",
        branch="maintenance",
        worktree_path="/repo/worktrees/maintenance",
        claim_identity="codex:alpha:maintenance",
        session_identity="codex:thread-1",
        allow_unplanned=True,
    )

    assert result.allowed is True
    assert result.readiness is None
    assert result.lane is None


def test_unknown_output_fields_fail_contract_validation(tmp_path):
    command = _query_command(tmp_path, decision="ready", exit_code=0)
    script = tmp_path / "fake_plan_graph.py"
    raw = script.read_text(encoding="utf-8")
    script.write_text(raw.replace("'error_code': None", "'error_code': None, 'surprise': True"), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid readiness payload"):
        check_plan_start_readiness(
            qualified_plan_id="alpha#12",
            execution_profile="coordinated",
            query_command=command,
            repository="alpha",
            lane_id="plan-12-feature",
            branch="plan-12-feature",
            worktree_path="/repo/worktrees/plan-12-feature",
            claim_identity="codex:alpha:plan-12-feature",
            session_identity="codex:thread-1",
        )


def test_command_receives_exact_qualified_identity_and_json_flag(tmp_path):
    capture = tmp_path / "argv.json"
    script = tmp_path / "capture_query.py"
    payload = {
        "schema_version": "1.0.0",
        "qualified_plan_id": "alpha#12",
        "graph_revision": "b" * 64,
        "decision": "ready",
        "blocker_ids": [],
        "evidence_refs": [],
        "reason": "ready",
        "error_code": None,
    }
    script.write_text(
        "import json, sys\n"
        f"open({str(capture)!r}, 'w').write(json.dumps(sys.argv[1:]))\n"
        f"print(json.dumps({payload!r}))\n",
        encoding="utf-8",
    )

    check_plan_start_readiness(
        qualified_plan_id="alpha#12",
        execution_profile="coordinated",
        query_command=f"{sys.executable} {script}",
        repository="alpha",
        lane_id="plan-12-feature",
        branch="plan-12-feature",
        worktree_path="/repo/worktrees/plan-12-feature",
        claim_identity="codex:alpha:plan-12-feature",
        session_identity="codex:thread-1",
    )

    assert json.loads(capture.read_text(encoding="utf-8")) == [
        "check-ready",
        "alpha#12",
        "--json",
    ]
