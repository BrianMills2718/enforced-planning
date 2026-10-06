"""Both-sign tests for the portable plan-start and resume gate."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from enforced_planning import plan_readiness, plan_validation
from enforced_planning.plan_validation import PlanIntegrityFindingV1, PlanIntegrityResultV1

PLAN_ID = "project-meta#234"
GRAPH_REVISION = "a" * 64
START_REVISION = "b" * 40


def _integrity_result(
    *,
    mode: str = "off",
    disposition: str = "not_applicable",
    source_revision: str = START_REVISION,
    finding_codes: tuple[str, ...] = (),
) -> PlanIntegrityResultV1:
    """Build one typed integrity result so nested gate serialization is exercised."""

    return PlanIntegrityResultV1(
        contract_version="1.0.0",
        disposition=disposition,
        repository_id="project-meta",
        plan_number=234,
        plan_path="docs/plans/234_fixture.md",
        plan_sha256="c" * 64,
        config_sha256="d" * 64,
        source_revision=source_revision,
        validator_source_sha256="e" * 64,
        mode=mode,
        minimum_plan_number=1,
        findings=[PlanIntegrityFindingV1(code=code, message=f"fixture {code}") for code in finding_codes],
        warnings=[],
        frontier=[],
        user_outcome=None,
        canonical_example=None,
        critical_path_classifications=[],
        capability_disposition=None,
        acceptance_criteria=[],
        reassessment=None,
    )


@pytest.fixture(autouse=True)
def _default_integrity_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "_resolve_commit",
        lambda _root, point, **_kwargs: START_REVISION if point == "HEAD" else point,
    )
    monkeypatch.setattr(plan_validation, "detect_repository_id", lambda root: Path(root).name)
    monkeypatch.setattr(
        plan_readiness,
        "validate_plan_integrity_at_revision",
        lambda **_kwargs: _integrity_result(),
    )
    monkeypatch.setattr(
        plan_readiness,
        "resolve_method_conformance_binding",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "resolve_default_integration_revision",
        lambda _root: START_REVISION,
    )


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
        repo_root="/tmp/project-meta",
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
            repo_root="/tmp/project-meta",
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


def test_enforced_integrity_denies_before_graph_query(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plan_readiness,
        "validate_plan_integrity_at_revision",
        lambda **_kwargs: _integrity_result(
            mode="enforce",
            disposition="fail",
            finding_codes=("missing_epistemic_frontier",),
        ),
    )
    monkeypatch.setattr(
        plan_readiness.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("graph query must not run after integrity denial"),
    )

    with pytest.raises(ValueError, match="missing_epistemic_frontier"):
        _gate()


def test_observed_integrity_reports_without_denial(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_graph(monkeypatch, decision="ready")
    monkeypatch.setattr(
        plan_readiness,
        "validate_plan_integrity_at_revision",
        lambda **_kwargs: _integrity_result(
            mode="observe",
            disposition="fail",
            finding_codes=("missing_epistemic_frontier",),
        ),
    )

    result = _gate()

    assert result.readiness is not None
    assert result.readiness.decision == "ready"
    assert result.planning_integrity is not None
    assert result.planning_integrity.disposition == "fail"
    assert result.planning_integrity.findings[0].code == "missing_epistemic_frontier"


def test_qualified_plan_repository_mismatch_fails_before_integrity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        plan_readiness,
        "validate_plan_integrity_at_revision",
        lambda **_kwargs: pytest.fail("mismatched repository must fail before validation"),
    )

    with pytest.raises(ValueError, match="explicit --plan-repo-root and --plan-start-point"):
        plan_readiness.check_plan_start_readiness(
            qualified_plan_id="other-repo#234",
            execution_profile="coordinated",
            query_command="plan-graph",
            repository="project-meta",
            lane_id="lane",
            branch="lane",
            worktree_path="/tmp/lane",
            claim_identity="codex:project-meta:lane",
            session_identity="codex:test",
            repo_root="/tmp/project-meta",
        )


def test_external_plan_readiness_keeps_target_lane_revision_separate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plan decision belongs to Project Meta while execution remains in AES."""

    plan_revision = "f" * 40
    calls: list[dict] = []
    monkeypatch.setattr(
        plan_readiness.coordination_claims,
        "resolve_default_integration_revision",
        lambda root: plan_revision if Path(root).name == "project-meta" else START_REVISION,
    )

    def _validate(**kwargs):
        calls.append(kwargs)
        return _integrity_result(source_revision=plan_revision)

    monkeypatch.setattr(plan_readiness, "validate_plan_integrity_at_revision", _validate)
    _patch_graph(monkeypatch, decision="ready")
    result = plan_readiness.check_plan_start_readiness(
        qualified_plan_id=PLAN_ID,
        execution_profile="coordinated",
        query_command="plan-graph",
        repository="aes",
        lane_id="external-plan",
        branch="external-plan",
        worktree_path="/tmp/aes/worktrees/external-plan",
        claim_identity="codex:aes:external-plan",
        session_identity="codex:test",
        repo_root="/tmp/aes",
        start_point=START_REVISION,
        plan_repo_root="/tmp/project-meta",
        plan_start_point=plan_revision,
    )

    assert result.allowed is True
    assert result.lane is not None
    assert result.lane.repository == "aes"
    assert result.lane.start_revision == START_REVISION
    assert result.planning_integrity is not None
    assert result.planning_integrity.source_revision == plan_revision
    assert calls == [
        {
            "repo_root": Path("/tmp/project-meta"),
            "repository_id": "project-meta",
            "plan_number": 234,
            "start_point": plan_revision,
        }
    ]


def test_gate_forwards_method_receipt_and_refuses_when_binding_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Company Planning Plan #48: the plan-start gate re-resolves the cited receipt."""
    from enforced_planning.coordination_claims import MethodConformanceRefusal

    _patch_graph(monkeypatch, decision="ready")
    seen: dict[str, object] = {}

    def refuse(**kwargs: object) -> None:
        seen.update(kwargs)
        raise MethodConformanceRefusal("method_receipt_digest_mismatch", "fixture")

    monkeypatch.setattr(plan_readiness, "resolve_method_conformance_binding", refuse)
    with pytest.raises(ValueError, match="method_receipt_digest_mismatch"):
        plan_readiness.check_plan_start_readiness(
            qualified_plan_id=PLAN_ID,
            execution_profile="coordinated",
            query_command="plan-graph",
            repository="project-meta",
            lane_id="lane",
            branch="plan-234",
            worktree_path="/tmp/project-meta/worktrees/plan-234",
            claim_identity="codex:project-meta:plan-234",
            session_identity="codex:test",
            repo_root="/tmp/project-meta",
            method_receipt_ref="docs/plans/234.receipt.json",
            method_receipt_sha256="0" * 64,
        )
    assert seen["receipt_ref"] == "docs/plans/234.receipt.json"
    assert seen["plan_number"] == 234
