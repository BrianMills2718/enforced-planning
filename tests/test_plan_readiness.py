"""Both-sign tests for the portable plan-start and resume gate."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from enforced_planning import plan_readiness


PLAN_ID = "project-meta#234"
GRAPH_REVISION = "a" * 64


def _payload(*, decision: str, qualified_plan_id: str = PLAN_ID) -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "qualified_plan_id": qualified_plan_id,
            "graph_revision": GRAPH_REVISION,
            "decision": decision,
            "blocker_ids": [],
            "evidence_refs": ["test"],
            "reason": f"{decision} fixture",
            "error_code": None,
        }
    )


def _gate(*, resume_requested: bool = False):
    return plan_readiness.check_plan_start_readiness(
        qualified_plan_id=PLAN_ID,
        execution_profile="coordinated",
        query_command="plan-graph",
        repository="project-meta",
        lane_id="plan-234-resume",
        branch="plan-234-resume",
        worktree_path="/tmp/project-meta/worktrees/plan-234-resume",
        claim_identity="codex:project-meta:plan-234-resume",
        session_identity="codex:test",
        resume_requested=resume_requested,
    )


def _patch_graph(monkeypatch: pytest.MonkeyPatch, *, decision: str, returncode: int = 0) -> None:
    monkeypatch.setattr(
        plan_readiness.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=returncode,
            stdout=_payload(decision=decision),
            stderr="",
        ),
    )


def test_ready_start_remains_allowed_without_claim_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graph(monkeypatch, decision="ready")
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "check_claims",
        lambda _project: pytest.fail("normal ready start must not inspect resume claims"),
    )

    result = _gate()

    assert result.allowed is True
    assert result.readiness is not None
    assert result.readiness.decision == "ready"


@pytest.mark.parametrize("profile", ["coordinated", "release"])
def test_governed_profiles_require_query_configuration(profile: str) -> None:
    with pytest.raises(ValueError, match="query command"):
        plan_readiness.check_plan_start_readiness(
            qualified_plan_id=PLAN_ID,
            execution_profile=profile,
            query_command=None,
            repository="project-meta",
            lane_id="plan-234-resume",
            branch="plan-234-resume",
            worktree_path="/tmp/project-meta/worktrees/plan-234-resume",
            claim_identity="codex:project-meta:plan-234-resume",
            session_identity="codex:test",
        )


def test_light_unplanned_profile_may_skip_query() -> None:
    result = plan_readiness.check_plan_start_readiness(
        qualified_plan_id=None,
        execution_profile="light",
        query_command=None,
        repository="project-meta",
        lane_id="maintenance",
        branch="maintenance",
        worktree_path="/tmp/project-meta/worktrees/maintenance",
        claim_identity="codex:project-meta:maintenance",
        session_identity="codex:test",
        allow_unplanned=True,
    )

    assert result.allowed is True
    assert result.readiness is None
    assert result.lane is None


def test_unknown_output_fields_fail_contract_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads(_payload(decision="ready"))
    payload["surprise"] = True
    monkeypatch.setattr(
        plan_readiness.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(payload), stderr=""
        ),
    )

    with pytest.raises(ValueError, match="invalid readiness payload"):
        _gate()


def test_graph_command_receives_exact_qualified_identity_and_json_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def capture(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.extend(command)
        return subprocess.CompletedProcess(args=command, returncode=0, stdout=_payload(decision="ready"))

    monkeypatch.setattr(plan_readiness.subprocess, "run", capture)

    _gate()

    assert observed == ["plan-graph", "check-ready", PLAN_ID, "--json"]


def test_already_active_requires_explicit_resume(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graph(monkeypatch, decision="already_active")

    with pytest.raises(ValueError, match="requires an explicit resume request"):
        _gate()


def test_explicit_resume_allows_no_matching_live_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graph(monkeypatch, decision="already_active")
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "list_claims",
        lambda _project, include_inactive: [],
    )

    result = _gate(resume_requested=True)

    assert result.allowed is True
    assert "provisionally allowed" in result.reason


def test_explicit_resume_accepts_documented_nonzero_already_active_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_graph(monkeypatch, decision="already_active", returncode=2)
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "list_claims",
        lambda _project, include_inactive: [],
    )

    result = _gate(resume_requested=True)

    assert result.allowed is True
    assert result.readiness is not None
    assert result.readiness.decision == "already_active"


@pytest.mark.parametrize("status", ["active", "blocked", "handoff", "session_ended"])
def test_explicit_resume_rejects_each_live_matching_claim(
    monkeypatch: pytest.MonkeyPatch,
    status: str,
) -> None:
    _patch_graph(monkeypatch, decision="already_active")
    matching_claim = SimpleNamespace(
        status=status,
        plan_ref="project-meta#234",
        scope=f"existing-{status}",
        primary_project=lambda: "project-meta",
        is_live=lambda: True,
    )
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "list_claims",
        lambda _project, include_inactive: [matching_claim],
    )

    with pytest.raises(ValueError, match=f"existing-{status}"):
        _gate(resume_requested=True)


@pytest.mark.parametrize("decision", ["blocked", "unknown"])
def test_non_actionable_graph_decisions_remain_rejected(
    monkeypatch: pytest.MonkeyPatch,
    decision: str,
) -> None:
    _patch_graph(monkeypatch, decision=decision)

    with pytest.raises(ValueError, match=decision):
        _gate(resume_requested=True)


def test_mismatched_graph_identity_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plan_readiness.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=_payload(decision="ready", qualified_plan_id="project-meta#235"),
            stderr="",
        ),
    )

    with pytest.raises(ValueError, match="identity mismatch"):
        _gate()


def test_nonzero_graph_response_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graph(monkeypatch, decision="blocked", returncode=2)

    with pytest.raises(ValueError, match="plan readiness rejected"):
        _gate(resume_requested=True)
