"""Both-sign tests for Plan 110's provider-free blocker policy."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from enforced_planning.blocker_policy import (
    BlockerDecisionInputV1,
    BlockerRequestV1,
    ClaimQueueSnapshotV1,
    MailboxDependencyV1,
    MailboxEvidenceV1,
    QueueWorkUnitV1,
    ReadyQueueEvaluationV1,
    decide_blocker_disposition,
    evaluate_ready_queue,
)
from scripts import evaluate_blocker as blocker_cli

NOW = datetime(2026, 8, 21, 5, 30, tzinfo=UTC)
SESSION_ID = "codex:owner-real-session"
OTHER_SESSION_ID = "codex:other-owner-session"
GRAPH_SCOPE = "enforced-planning#110"
GRAPH_REF = "tests/fixtures/plan110_npw02_work_graph.json"
MESSAGE_ID = "msg_" + "a" * 32


def _dependency(
    unit_id: str,
    *,
    dependency_type: str = "hard",
    gate: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "unit_id": unit_id,
        "type": dependency_type,
        "gate": gate or {"type": "unit_status", "required_status": "accepted"},
        "rationale": f"{unit_id} supplies the required predecessor state.",
    }


def _unit(
    unit_id: str,
    status: str,
    *,
    dependencies: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    readiness_status = "ready" if status not in {"blocked", "draft"} else status
    claimability = {
        "ready": "ready_for_execution",
        "blocked": "blocked_dependencies",
        "in_progress": "unavailable_active_claim",
    }.get(status, "not_applicable")
    return {
        "schema_version": "1.0",
        "record_type": "work_unit",
        "id": unit_id,
        "initiative_id": "plan110-fixture",
        "goal_id": "provider-free-blocker-decision",
        "design_revision": "design-v1",
        "spec_revision": f"{unit_id}-v1",
        "title": f"Fixture unit {unit_id}",
        "class": "implementation",
        "objective": f"Exercise blocker behavior for {unit_id}.",
        "profile": "small",
        "execution_class": "independently_executable",
        "claimability": claimability,
        "scope": {"included": [f"fixture:{unit_id}"], "excluded": []},
        "inputs": [],
        "outputs": [f"fixture-output:{unit_id}"],
        "dependencies": list(dependencies),
        "conflict_surfaces": [],
        "acceptance": [
            {
                "id": f"{unit_id}-A1",
                "criterion": f"The {unit_id} fixture is classified deterministically.",
                "evidence_required": ["focused provider-free test"],
            }
        ],
        "readiness": {
            "status": readiness_status,
            "required_approval_types": [],
            "approvals": [],
            "failed_guards": [],
        },
        "claim_policy": {
            "eligibility_rule": "One exact fixture claimant.",
            "lease_policy": "renewable",
            "lease_duration_minutes": 60,
            "max_active_per_claimant": 1,
            "named_owner_id": None,
        },
        "authorization_mode": "registry_claim",
        "status": status,
        "record_version": 1,
    }


def _write_graph(tmp_path: Path, units: list[dict[str, object]]) -> tuple[Path, str]:
    path = tmp_path / GRAPH_REF
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"units": units}, sort_keys=True), encoding="utf-8")
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class QueueCase:
    repository_root: Path
    path: Path
    digest: str
    claims: tuple[ClaimQueueSnapshotV1, ...]
    queue: ReadyQueueEvaluationV1


def _queue(
    tmp_path: Path,
    units: list[dict[str, object]],
    *,
    claims: tuple[ClaimQueueSnapshotV1, ...] = (),
) -> QueueCase:
    graph_path, digest = _write_graph(tmp_path, units)
    queue = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=GRAPH_REF,
        expected_sha256=digest,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        claim_snapshots=claims,
        evaluated_at=NOW,
    )
    return QueueCase(tmp_path, graph_path, digest, claims, queue)


def _request(
    *,
    blocker_class: str = "hard_dependency",
    blocked_scope: str = "unit",
    blocked_items: tuple[str, ...] = ("A",),
    mailbox_dependency: MailboxDependencyV1 | None = None,
    requested_claim_action: str = "session_end",
    resume_event: str = "The dependency revision becomes canonical.",
) -> BlockerRequestV1:
    return BlockerRequestV1(
        session_id=SESSION_ID,
        claim_scope=GRAPH_SCOPE,
        blocked_scope=blocked_scope,
        blocked_item_refs=blocked_items,
        blocker_class=blocker_class,
        evidence_refs=("git:fixture@abc123",),
        dependency_owner="another-session",
        resume_event=resume_event,
        mailbox_dependency=mailbox_dependency,
        requested_claim_action=requested_claim_action,
    )


def _decision(
    case: QueueCase,
    request: BlockerRequestV1 | None = None,
    mailbox_evidence: tuple[MailboxEvidenceV1, ...] = (),
    *,
    request_ref: str = "blocker_request_fixture",
):
    envelope = BlockerDecisionInputV1(
        request_ref=request_ref,
        request=request or _request(),
        work_graph_ref_path=GRAPH_REF,
        expected_work_graph_sha256=case.digest,
        claim_snapshots=case.claims,
        mailbox_evidence=mailbox_evidence,
    )
    return decide_blocker_disposition(
        envelope,
        repository_root=case.repository_root,
        recorded_at=NOW,
    )


def test_fixture_factory_is_a_strict_work_unit_contract() -> None:
    result = QueueWorkUnitV1.model_validate(_unit("A", "ready"))
    assert result.id == "A"
    assert result.status == "ready"


def test_ready_alternative_prevents_whole_goal_block(tmp_path: Path) -> None:
    case = _queue(
        tmp_path,
        [
            _unit("A", "blocked"),
            _unit("B", "ready"),
            _unit("C", "blocked", dependencies=(_dependency("A"),)),
        ],
    )
    result = _decision(case)
    assert case.queue.coverage == "complete"
    assert case.queue.eligible_unit_ids == ("B",)
    assert result.decision == "continue_ready_work"
    assert result.alternative_unit_ids == ("B",)
    assert result.claim_action == "none"


def test_blocked_refs_cannot_hide_a_ready_alternative(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked"), _unit("B", "ready")])
    result = _decision(case, _request(blocked_items=("A", "B")))
    assert result.decision == "continue_ready_work"
    assert result.alternative_unit_ids == ("B",)


def test_path_collision_remains_local_even_with_compatible_work(tmp_path: Path) -> None:
    _path, digest = _write_graph(tmp_path, [_unit("A", "blocked"), _unit("B", "ready")])
    claim = ClaimQueueSnapshotV1(
        session_id=OTHER_SESSION_ID,
        status="active",
        goal_or_graph_scope=GRAPH_SCOPE,
        work_unit_id="A",
        work_graph_path=GRAPH_REF,
        work_graph_sha256=digest,
        claimed_paths=("shared/component.py",),
    )
    case = _queue(
        tmp_path,
        [_unit("A", "blocked"), _unit("B", "ready")],
        claims=(claim,),
    )
    result = _decision(
        case,
        _request(
            blocker_class="path_conflict",
            blocked_scope="path",
            blocked_items=("shared/component.py",),
        ),
    )
    assert result.decision == "integration_wait"
    assert result.alternative_unit_ids == ("B",)
    assert result.claim_action == "none"


def test_unverified_path_collision_cannot_create_an_integration_wait(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked"), _unit("B", "ready")])
    result = _decision(
        case,
        _request(
            blocker_class="path_conflict",
            blocked_scope="path",
            blocked_items=("shared/component.py",),
        ),
    )
    assert result.decision == "blocker_unverified_return_control"
    assert result.alternative_unit_ids == ("B",)
    assert result.reason_codes == ("path_conflict_evidence_unverified",)


def test_complete_queue_and_supported_blocker_can_verify_goal_block(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    result = _decision(case)
    assert case.queue.coverage == "complete"
    assert result.decision == "goal_blocked_verified"
    assert result.claim_action == "retire_goal_scope"
    assert result.application_authorized is False


def test_missing_dependency_makes_queue_partial_and_block_unverified(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "ready", dependencies=(_dependency("missing"),))])
    result = _decision(case)
    assert case.queue.coverage == "unavailable"
    assert result.decision == "blocker_unverified_return_control"
    assert result.reason_codes == ("queue_coverage_unavailable",)


def test_hard_dependency_honors_the_exact_required_status(tmp_path: Path) -> None:
    accepted = _queue(
        tmp_path,
        [_unit("A", "accepted"), _unit("B", "ready", dependencies=(_dependency("A"),))],
    )
    assert accepted.queue.eligible_unit_ids == ("B",)
    deployed_gate = _dependency("A", gate={"type": "unit_status", "required_status": "deployed"})
    unmet = _queue(
        tmp_path,
        [_unit("A", "accepted"), _unit("B", "ready", dependencies=(deployed_gate,))],
    )
    assert unmet.queue.coverage == "unavailable"
    assert unmet.queue.eligible_unit_ids == ()
    assert "required=deployed" in unmet.queue.evidence_refs[0]


def test_optional_dependency_cannot_block_ready_work(tmp_path: Path) -> None:
    optional = _dependency("A", dependency_type="optional")
    case = _queue(
        tmp_path,
        [_unit("A", "blocked"), _unit("B", "ready", dependencies=(optional,))],
    )
    assert case.queue.eligible_unit_ids == ("B",)


@pytest.mark.parametrize(
    "gate",
    [
        {
            "type": "approval_current",
            "approval_type": "design",
            "approved_revision": "r1",
            "satisfied": False,
            "evidence_ref": "approval:r1",
        },
        {
            "type": "artifact_exists",
            "artifact_id": "artifact-a",
            "revision": "r1",
            "satisfied": False,
            "evidence_ref": "artifact:r1",
        },
        {
            "type": "contract_status",
            "contract_id": "contract-a",
            "revision": "r1",
            "required_status": "accepted",
            "satisfied": False,
            "evidence_ref": "contract:r1",
        },
        {
            "type": "external_event",
            "event_id": "event-a",
            "required_state": "observed",
            "satisfied": False,
            "evidence_ref": "event:r1",
        },
    ],
)
def test_hard_boolean_gates_use_satisfied(gate: dict[str, object], tmp_path: Path) -> None:
    dependency = _dependency("A", gate=gate)
    case = _queue(
        tmp_path,
        [_unit("A", "accepted"), _unit("B", "ready", dependencies=(dependency,))],
    )
    assert case.queue.coverage == "unavailable"
    assert case.queue.eligible_unit_ids == ()
    assert "unsatisfied" in case.queue.evidence_refs[0]


@pytest.mark.parametrize(
    ("contents", "expected_reason"),
    [
        ("not-json", "malformed_work_graph"),
        (json.dumps({"wrong": []}), "exact_units_list_required"),
        (json.dumps({"units": [{"id": "incomplete"}]}), "invalid_work_unit"),
    ],
)
def test_malformed_graph_returns_unavailable_coverage(tmp_path: Path, contents: str, expected_reason: str) -> None:
    path = tmp_path / GRAPH_REF
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=GRAPH_REF,
        expected_sha256=digest,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        evaluated_at=NOW,
    )
    assert result.coverage == "unavailable"
    assert result.work_graph_ref is None
    assert expected_reason in result.evidence_refs[0]


def test_missing_graph_returns_unavailable_coverage(tmp_path: Path) -> None:
    result = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=GRAPH_REF,
        expected_sha256="0" * 64,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        evaluated_at=NOW,
    )
    assert result.coverage == "unavailable"
    assert result.evidence_refs[0].startswith("work_graph_unreadable:")


def test_stale_graph_digest_returns_unavailable_coverage(tmp_path: Path) -> None:
    _path, _digest = _write_graph(tmp_path, [_unit("B", "ready")])
    result = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=GRAPH_REF,
        expected_sha256="0" * 64,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        evaluated_at=NOW,
    )
    assert result.coverage == "unavailable"
    assert result.eligible_unit_ids == ()


def test_graph_filename_must_match_numbered_goal_scope(tmp_path: Path) -> None:
    unrelated_ref = "docs/plans/106_unrelated_work_graph.json"
    path = tmp_path / unrelated_ref
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"units": [_unit("B", "ready")]}), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    result = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=unrelated_ref,
        expected_sha256=digest,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        evaluated_at=NOW,
    )
    assert result.coverage == "unavailable"
    assert result.evidence_refs[0] == "work_graph_goal_scope_mismatch"


def test_persisted_mailbox_message_cannot_verify_dependency_wait(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    dependency = MailboxDependencyV1(message_id=MESSAGE_ID, required_delivery_state="observed")
    request = _request(mailbox_dependency=dependency)
    persisted = (MailboxEvidenceV1(message_id=MESSAGE_ID, state="persisted", evidence_refs=("mailbox:message-only",)),)
    observed = (
        MailboxEvidenceV1(message_id=MESSAGE_ID, state="observed", evidence_refs=("mailbox:observed-receipt",)),
    )
    assert _decision(case, request, persisted).decision == "blocker_unverified_return_control"
    after = _decision(case, request, observed)
    assert after.decision == "goal_blocked_verified"
    assert "mailbox:observed-receipt" in after.evidence_refs


def test_human_decision_has_explicit_non_blocked_disposition(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    result = _decision(case, _request(blocker_class="human_decision"))
    assert result.decision == "human_decision_required"


def _claim(*, session_id: str, digest: str, scope: str = GRAPH_SCOPE) -> ClaimQueueSnapshotV1:
    return ClaimQueueSnapshotV1(
        session_id=session_id,
        status="active",
        goal_or_graph_scope=scope,
        work_unit_id="B",
        work_graph_path=GRAPH_REF,
        work_graph_sha256=digest,
    )


def test_unrelated_root_and_same_session_do_not_hide_ready_work(tmp_path: Path) -> None:
    _graph_path, digest = _write_graph(tmp_path, [_unit("B", "ready")])
    unrelated = _claim(session_id=OTHER_SESSION_ID, digest=digest, scope="another-plan#1")
    same_session = _claim(session_id=SESSION_ID, digest=digest)
    for claim in (unrelated, same_session):
        result = evaluate_ready_queue(
            repository_root=tmp_path,
            work_graph_ref_path=GRAPH_REF,
            expected_sha256=digest,
            session_id=SESSION_ID,
            goal_or_graph_scope=GRAPH_SCOPE,
            claim_snapshots=(claim,),
            evaluated_at=NOW,
        )
        assert result.eligible_unit_ids == ("B",)
        assert result.active_conflict_unit_ids == ()


def test_other_session_exact_claim_is_an_integration_wait(tmp_path: Path) -> None:
    _graph_path, digest = _write_graph(tmp_path, [_unit("B", "ready")])
    exact = _claim(session_id=OTHER_SESSION_ID, digest=digest)
    case = _queue(tmp_path, [_unit("B", "ready")], claims=(exact,))
    assert case.queue.eligible_unit_ids == ()
    assert case.queue.active_conflict_unit_ids == ("B",)
    result = _decision(case, _request(blocked_items=("B",)))
    assert result.decision == "integration_wait"


@pytest.mark.parametrize(
    ("claimed_path", "surface_repository", "expected_conflicts"),
    [
        ("shared/component.py", "enforced-planning", ("B",)),
        ("other.py", "enforced-planning", ()),
        ("shared/component.py", "other-repository", ()),
    ],
)
def test_exact_bound_root_claim_maps_overlapping_write_paths_to_units(
    claimed_path: str,
    surface_repository: str,
    expected_conflicts: tuple[str, ...],
    tmp_path: Path,
) -> None:
    unit = _unit("B", "ready")
    unit["conflict_surfaces"] = [
        {
            "kind": "repository_path",
            "target": "shared/component.py",
            "repository": surface_repository,
            "access": "exclusive",
        }
    ]
    _path, digest = _write_graph(tmp_path, [unit])
    root_claim = ClaimQueueSnapshotV1(
        session_id=OTHER_SESSION_ID,
        status="active",
        goal_or_graph_scope=GRAPH_SCOPE,
        work_unit_id=None,
        work_graph_path=GRAPH_REF,
        work_graph_sha256=digest,
        claimed_paths=(claimed_path,),
    )
    case = _queue(tmp_path, [unit], claims=(root_claim,))
    assert case.queue.active_conflict_unit_ids == expected_conflicts
    assert case.queue.eligible_unit_ids == (() if expected_conflicts else ("B",))


@pytest.mark.parametrize("status", ["accepted", "in_progress"])
def test_completed_or_active_state_cannot_verify_a_block(status: str, tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", status)])
    result = _decision(case, _request(blocked_scope="goal"))
    classified = case.queue.terminal_unit_ids if status == "accepted" else case.queue.active_or_indeterminate_unit_ids
    assert classified == ("A",)
    assert result.decision == "blocker_unverified_return_control"
    expected_reason = (
        "queue_has_no_blocked_units" if status == "accepted" else "queue_contains_active_or_indeterminate_state"
    )
    assert result.reason_codes == (expected_reason,)


def test_terminal_units_do_not_mask_a_genuine_remaining_block(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "accepted"), _unit("B", "blocked")])
    result = _decision(case, _request(blocked_items=("B",)))
    assert case.queue.terminal_unit_ids == ("A",)
    assert result.decision == "goal_blocked_verified"


def test_live_claim_bound_to_terminal_unit_fails_queue_coverage(tmp_path: Path) -> None:
    _path, digest = _write_graph(tmp_path, [_unit("A", "accepted")])
    claim = ClaimQueueSnapshotV1(
        session_id=OTHER_SESSION_ID,
        status="active",
        goal_or_graph_scope=GRAPH_SCOPE,
        work_unit_id="A",
        work_graph_path=GRAPH_REF,
        work_graph_sha256=digest,
    )
    case = _queue(tmp_path, [_unit("A", "accepted")], claims=(claim,))
    assert case.queue.coverage == "unavailable"
    assert case.queue.active_conflict_unit_ids == ()
    assert "terminal_units:A" in case.queue.evidence_refs[0]


def test_terminal_status_wins_over_stale_blocked_readiness(tmp_path: Path) -> None:
    unit = _unit("A", "accepted")
    readiness = unit["readiness"]
    assert isinstance(readiness, dict)
    readiness["status"] = "blocked"
    case = _queue(tmp_path, [unit])
    result = _decision(case, _request(blocked_scope="goal"))
    assert case.queue.terminal_unit_ids == ("A",)
    assert result.decision == "blocker_unverified_return_control"
    assert result.reason_codes == ("queue_has_no_blocked_units",)


def test_unit_request_must_name_the_actual_blocked_unit(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "accepted"), _unit("B", "blocked")])
    result = _decision(case, _request(blocked_items=("A",)))
    assert result.decision == "blocker_unverified_return_control"
    assert result.reason_codes == ("requested_unit_not_blocked_in_queue",)


def test_hard_dependency_cycle_makes_queue_unavailable(tmp_path: Path) -> None:
    case = _queue(
        tmp_path,
        [_unit("A", "blocked", dependencies=(_dependency("A"),))],
    )
    assert case.queue.coverage == "unavailable"
    assert "hard_dependency_cycle:A->A" in case.queue.evidence_refs[0]


@pytest.mark.parametrize("failure", ["restricted", "failed_guard", "missing_approval", "stale_approval"])
def test_invalid_ready_semantics_make_queue_unavailable(failure: str, tmp_path: Path) -> None:
    unit = _unit("A", "ready")
    readiness = unit["readiness"]
    assert isinstance(readiness, dict)
    if failure == "restricted":
        unit["claimability"] = "restricted"
    elif failure == "failed_guard":
        readiness["failed_guards"] = ["guard:not-satisfied"]
    else:
        readiness["required_approval_types"] = ["design"]
        if failure == "stale_approval":
            readiness["approvals"] = [
                {
                    "approval_type": "design",
                    "role": "reviewer",
                    "approver_id": "reviewer-1",
                    "approved_revision": "old-design",
                    "approved_at": "2026-08-20T00:00:00+00:00",
                    "expires_at": None,
                }
            ]
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_graph_semantics" in case.queue.evidence_refs[0]


def test_controlled_unit_must_require_its_declared_control_approval(tmp_path: Path) -> None:
    unit = _unit("A", "ready")
    unit["profile"] = "controlled"
    unit["control_approval_types"] = ["deployment"]
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "controlled_approvals_missing_from_readiness" in case.queue.evidence_refs[0]


@pytest.mark.parametrize("claimability", ["unavailable_active_claim", "pending_approval"])
def test_terminal_unit_with_invalid_claimability_makes_queue_unavailable(
    claimability: str,
    tmp_path: Path,
) -> None:
    terminal = _unit("A", "accepted")
    terminal["claimability"] = claimability
    case = _queue(tmp_path, [terminal, _unit("B", "blocked")])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_graph_semantics" in case.queue.evidence_refs[0]


def test_overlapping_ready_conflict_surfaces_make_queue_unavailable(tmp_path: Path) -> None:
    first = _unit("A", "ready")
    second = _unit("B", "ready")
    surface = {
        "kind": "repository_path",
        "target": "shared/component.py",
        "repository": "fixture",
        "access": "exclusive",
    }
    first["conflict_surfaces"] = [surface]
    second["conflict_surfaces"] = [surface]
    case = _queue(tmp_path, [first, second])
    assert case.queue.coverage == "unavailable"
    assert "unresolved_repository_path_conflict" in case.queue.evidence_refs[0]


def test_path_scope_requires_path_conflict_class() -> None:
    with pytest.raises(ValidationError, match="path blocked_scope"):
        _request(blocked_scope="path", blocker_class="hard_dependency")


@pytest.mark.parametrize("blocked_items", [("",), (".",), ("../outside",), ("a/../b",), ("a\\b",)])
def test_path_scope_requires_canonical_portable_refs(blocked_items: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError, match="blocked_item_refs|blocked path refs"):
        _request(blocked_scope="path", blocker_class="path_conflict", blocked_items=blocked_items)


def test_exact_claim_for_unknown_unit_fails_closed(tmp_path: Path) -> None:
    _path, digest = _write_graph(tmp_path, [_unit("A", "blocked")])
    ghost = ClaimQueueSnapshotV1(
        session_id=OTHER_SESSION_ID,
        status="active",
        goal_or_graph_scope=GRAPH_SCOPE,
        work_unit_id="ghost",
        work_graph_path=GRAPH_REF,
        work_graph_sha256=digest,
    )
    case = _queue(tmp_path, [_unit("A", "blocked")], claims=(ghost,))
    assert case.queue.coverage == "unavailable"
    assert "unknown_units:ghost" in case.queue.evidence_refs[0]


@pytest.mark.parametrize(
    ("work_graph_path", "digest_mode"),
    [
        (None, "missing"),
        (GRAPH_REF, "stale"),
        ("docs/plans/different_graph.json", "current"),
    ],
)
def test_same_scope_live_claim_with_stale_or_unbound_graph_fails_closed(
    work_graph_path: str | None,
    digest_mode: str,
    tmp_path: Path,
) -> None:
    _path, digest = _write_graph(tmp_path, [_unit("B", "ready")])
    claim_digest = {
        "missing": None,
        "stale": "0" * 64,
        "current": digest,
    }[digest_mode]
    claim = ClaimQueueSnapshotV1(
        session_id=OTHER_SESSION_ID,
        status="active",
        goal_or_graph_scope=GRAPH_SCOPE,
        work_unit_id="B",
        work_graph_path=work_graph_path,
        work_graph_sha256=claim_digest,
    )
    case = _queue(tmp_path, [_unit("B", "ready")], claims=(claim,))
    assert case.queue.coverage == "unavailable"
    assert case.queue.eligible_unit_ids == ()
    assert "stale_or_unbound_units" in case.queue.evidence_refs[0]


@pytest.mark.parametrize("work_unit_id", ["ghost", None])
def test_unbound_same_scope_unknown_or_root_claim_fails_closed(
    work_unit_id: str | None,
    tmp_path: Path,
) -> None:
    claim = ClaimQueueSnapshotV1(
        session_id=OTHER_SESSION_ID,
        status="active",
        goal_or_graph_scope=GRAPH_SCOPE,
        work_unit_id=work_unit_id,
        work_graph_path=None,
        work_graph_sha256=None,
    )
    case = _queue(tmp_path, [_unit("A", "blocked")], claims=(claim,))
    assert case.queue.coverage == "unavailable"
    assert "stale_or_unbound_units" in case.queue.evidence_refs[0]


def test_queue_identity_binds_graph_path_and_claim_snapshot(tmp_path: Path) -> None:
    graph_path, digest = _write_graph(tmp_path, [_unit("B", "ready")])
    base = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=GRAPH_REF,
        expected_sha256=digest,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        evaluated_at=NOW,
    )
    other_ref = "docs/plans/other_graph.json"
    other_source = tmp_path / other_ref
    other_source.parent.mkdir(parents=True, exist_ok=True)
    other_source.write_bytes(graph_path.read_bytes())
    other_path = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=other_ref,
        expected_sha256=digest,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        evaluated_at=NOW,
    )
    with_claim = evaluate_ready_queue(
        repository_root=tmp_path,
        work_graph_ref_path=GRAPH_REF,
        expected_sha256=digest,
        session_id=SESSION_ID,
        goal_or_graph_scope=GRAPH_SCOPE,
        claim_snapshots=(_claim(session_id=SESSION_ID, digest=digest),),
        evaluated_at=NOW,
    )
    assert len({base.evaluation_id, other_path.evaluation_id, with_claim.evaluation_id}) == 3
    assert f"claim-snapshot-sha256:{with_claim.claim_snapshot_sha256}" in with_claim.evidence_refs


def test_unknown_blocked_unit_cannot_produce_verified_goal_block(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    result = _decision(case, _request(blocked_items=("fabricated",)))
    assert result.decision == "blocker_unverified_return_control"
    assert result.reason_codes == ("blocked_item_not_in_queue",)


def test_unknown_contract_fields_fail_loud(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    payload = {
        "schema_version": "1.0",
        "request_ref": "fixture",
        "request": _request().model_dump(mode="json"),
        "work_graph_ref_path": GRAPH_REF,
        "expected_work_graph_sha256": case.digest,
        "claim_snapshots": [],
        "mailbox_evidence": [],
        "surprise": True,
    }
    with pytest.raises(ValidationError, match="surprise"):
        BlockerDecisionInputV1.model_validate(payload)


def test_distinct_lifecycle_inputs_have_distinct_disposition_ids(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    first = _decision(case, _request(requested_claim_action="session_end", resume_event="event one"))
    second = _decision(case, _request(requested_claim_action="handoff", resume_event="event two"))
    assert first.disposition_id != second.disposition_id
    assert first.claim_action != second.claim_action


def test_semantically_identical_replays_keep_stable_ids(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("A", "blocked")])
    envelope = BlockerDecisionInputV1(
        request_ref="stable-replay",
        request=_request(),
        work_graph_ref_path=GRAPH_REF,
        expected_work_graph_sha256=case.digest,
    )
    first = decide_blocker_disposition(envelope, repository_root=tmp_path, recorded_at=NOW)
    second = decide_blocker_disposition(
        envelope,
        repository_root=tmp_path,
        recorded_at=NOW + timedelta(minutes=1),
    )
    assert first.ready_queue_evaluation_ref == second.ready_queue_evaluation_ref
    assert first.disposition_id == second.disposition_id
    assert first.recorded_at != second.recorded_at


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (("outputs", [""]), "outputs"),
        (("scope.included", [""]), "included"),
        (("acceptance.evidence_required", [""]), "evidence_required"),
        (("control_approval_types", []), "control_approval_types"),
        (("control_approval_types", ["readiness", "readiness"]), "control_approval_types"),
    ],
)
def test_empty_or_duplicate_schema_array_values_fail_closed(
    mutation: tuple[str, list[str]],
    expected: str,
    tmp_path: Path,
) -> None:
    unit = _unit("A", "ready")
    path, value = mutation
    if path == "scope.included":
        assert isinstance(unit["scope"], dict)
        unit["scope"]["included"] = value
    elif path == "acceptance.evidence_required":
        assert isinstance(unit["acceptance"], list)
        assert isinstance(unit["acceptance"][0], dict)
        unit["acceptance"][0]["evidence_required"] = value
    else:
        unit[path] = value
        if path == "control_approval_types":
            unit["profile"] = "controlled"
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_unit" in case.queue.evidence_refs[0]
    assert expected


@pytest.mark.parametrize(("field", "value"), [("created_at", "not-a-date"), ("updated_at", "2026-08-21")])
def test_malformed_or_naive_work_unit_timestamps_fail_closed(
    field: str,
    value: str,
    tmp_path: Path,
) -> None:
    unit = _unit("A", "ready")
    unit[field] = value
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_unit" in case.queue.evidence_refs[0]


@pytest.mark.parametrize(
    "field",
    [
        "control_approval_types",
        "claim_policy",
        "authorization_mode",
        "integration_owner_id",
        "deployment_contract",
        "deployment_environment",
        "created_at",
        "updated_at",
    ],
)
def test_optional_work_unit_fields_may_be_omitted_but_not_null(field: str, tmp_path: Path) -> None:
    unit = _unit("A", "ready")
    unit[field] = None
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_unit" in case.queue.evidence_refs[0]


@pytest.mark.parametrize("field", ["repository", "coordination_key"])
def test_optional_conflict_surface_fields_may_be_omitted_but_not_null(field: str, tmp_path: Path) -> None:
    unit = _unit("A", "ready")
    surface = {
        "kind": "contract",
        "target": "contract:fixture",
        "access": "read",
        field: None,
    }
    unit["conflict_surfaces"] = [surface]
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_unit" in case.queue.evidence_refs[0]


def test_optional_acceptance_negative_control_may_be_omitted_but_not_null(tmp_path: Path) -> None:
    unit = _unit("A", "ready")
    assert isinstance(unit["acceptance"], list)
    assert isinstance(unit["acceptance"][0], dict)
    unit["acceptance"][0]["negative_control"] = None
    case = _queue(tmp_path, [unit])
    assert case.queue.coverage == "unavailable"
    assert "invalid_work_unit" in case.queue.evidence_refs[0]


def test_decision_recomputes_queue_instead_of_accepting_derived_input(tmp_path: Path) -> None:
    case = _queue(tmp_path, [_unit("B", "ready")])
    payload = {
        "schema_version": "1.0",
        "request_ref": "fixture",
        "request": _request(blocked_items=("B",)).model_dump(mode="json"),
        "ready_queue": case.queue.model_dump(mode="json"),
        "mailbox_evidence": [],
    }
    with pytest.raises(ValidationError, match="ready_queue"):
        BlockerDecisionInputV1.model_validate(payload)


def _public_cli_claim(
    *,
    graph_ref: str,
    digest: str,
    scope: str = GRAPH_SCOPE,
    session_id: str = SESSION_ID,
    work_unit_id: str | None = "npw-02-provider-free-blocker-decision",
) -> ClaimQueueSnapshotV1:
    return ClaimQueueSnapshotV1(
        session_id=session_id,
        status="active",
        goal_or_graph_scope=scope,
        work_unit_id=work_unit_id,
        work_graph_path=graph_ref,
        work_graph_sha256=digest,
        claimed_paths=("enforced_planning/blocker_policy.py",),
    )


def _run_public_cli(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    *,
    claims: tuple[ClaimQueueSnapshotV1, ...],
    native_thread_id: str = SESSION_ID.split(":", 1)[1],
) -> tuple[int, str, str]:
    monkeypatch.setenv("CODEX_THREAD_ID", native_thread_id)
    monkeypatch.setattr(blocker_cli, "_canonical_claim_snapshots", lambda _scope: claims)
    return_code = blocker_cli.main(argv)
    captured = capsys.readouterr()
    return return_code, captured.out, captured.err


def test_cli_queue_round_trip_and_unavailable_exit(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/110_no_passive_waiting_work_graph.json"
    graph_path = repo_root / graph_ref
    digest = hashlib.sha256(graph_path.read_bytes()).hexdigest()
    command = [
        "queue",
        "--work-graph-ref",
        graph_ref,
        "--expected-sha256",
        digest,
        "--session-id",
        SESSION_ID,
        "--goal-scope",
        GRAPH_SCOPE,
    ]
    passing_code, passing_stdout, passing_stderr = _run_public_cli(
        monkeypatch,
        capsys,
        command,
        claims=(_public_cli_claim(graph_ref=graph_ref, digest=digest),),
    )
    stale_command = command.copy()
    stale_command[stale_command.index(digest)] = "0" * 64
    stale_code, stale_stdout, _stale_stderr = _run_public_cli(
        monkeypatch,
        capsys,
        stale_command,
        claims=(_public_cli_claim(graph_ref=graph_ref, digest="0" * 64),),
    )
    assert passing_code == 0, passing_stderr
    passing_payload = json.loads(passing_stdout)
    assert "npw-01-progress-lease-current-main" in passing_payload["eligible_unit_ids"]
    assert "npw-02-provider-free-blocker-decision" in passing_payload["eligible_unit_ids"]
    assert stale_code == 3
    assert json.loads(stale_stdout)["coverage"] == "unavailable"


def test_cli_decide_uses_source_graph(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/110_no_passive_waiting_work_graph.json"
    digest = hashlib.sha256((repo_root / graph_ref).read_bytes()).hexdigest()
    input_path = tmp_path / "decision.json"
    decision_input = BlockerDecisionInputV1(
        request_ref="fixture",
        request=_request(blocked_items=("npw-03-safe-lifecycle-integration",)),
        work_graph_ref_path=graph_ref,
        expected_work_graph_sha256=digest,
    )
    input_path.write_text(decision_input.model_dump_json(), encoding="utf-8")
    return_code, stdout, stderr = _run_public_cli(
        monkeypatch,
        capsys,
        ["decide", "--input-json", str(input_path)],
        claims=(_public_cli_claim(graph_ref=graph_ref, digest=digest),),
    )
    assert return_code == 0, stderr
    payload = json.loads(stdout)
    assert payload["disposition"]["decision"] == "continue_ready_work"
    assert payload["ready_queue"]["evaluation_id"] == payload["disposition"]["ready_queue_evaluation_ref"]


def test_public_cli_rejects_caller_claim_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/110_no_passive_waiting_work_graph.json"
    digest = hashlib.sha256((repo_root / graph_ref).read_bytes()).hexdigest()
    input_path = tmp_path / "caller-claims.json"
    decision_input = BlockerDecisionInputV1(
        request_ref="fixture",
        request=_request(blocked_items=("npw-03-safe-lifecycle-integration",)),
        work_graph_ref_path=graph_ref,
        expected_work_graph_sha256=digest,
        claim_snapshots=(_claim(session_id=OTHER_SESSION_ID, digest=digest),),
    )
    input_path.write_text(decision_input.model_dump_json(), encoding="utf-8")
    return_code, _stdout, stderr = _run_public_cli(
        monkeypatch,
        capsys,
        ["decide", "--input-json", str(input_path)],
        claims=(),
    )
    assert return_code == 2
    assert "rejects caller-supplied claim snapshots" in stderr


def test_public_cli_rejects_fabricated_session_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/110_no_passive_waiting_work_graph.json"
    digest = hashlib.sha256((repo_root / graph_ref).read_bytes()).hexdigest()
    return_code, _stdout, stderr = _run_public_cli(
        monkeypatch,
        capsys,
        [
            "queue",
            "--work-graph-ref",
            graph_ref,
            "--expected-sha256",
            digest,
            "--session-id",
            SESSION_ID,
            "--goal-scope",
            GRAPH_SCOPE,
        ],
        claims=(),
        native_thread_id="different-native-session",
    )
    assert return_code == 2
    assert "does not match" in stderr


def test_public_cli_fails_closed_for_graph_from_different_plan(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/106_cross_client_mailbox_fleet_delivery_work_graph.json"
    digest = hashlib.sha256((repo_root / graph_ref).read_bytes()).hexdigest()
    return_code, stdout, _stderr = _run_public_cli(
        monkeypatch,
        capsys,
        [
            "queue",
            "--work-graph-ref",
            graph_ref,
            "--expected-sha256",
            digest,
            "--session-id",
            SESSION_ID,
            "--goal-scope",
            GRAPH_SCOPE,
        ],
        claims=(_public_cli_claim(graph_ref=graph_ref, digest=digest, work_unit_id=None),),
    )
    assert return_code == 3
    assert json.loads(stdout)["evidence_refs"][0] == "work_graph_goal_scope_mismatch"


def test_public_cli_rejects_foreign_project_scope_with_same_plan_number(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/110_no_passive_waiting_work_graph.json"
    digest = hashlib.sha256((repo_root / graph_ref).read_bytes()).hexdigest()
    return_code, _stdout, stderr = _run_public_cli(
        monkeypatch,
        capsys,
        [
            "queue",
            "--work-graph-ref",
            graph_ref,
            "--expected-sha256",
            digest,
            "--session-id",
            SESSION_ID,
            "--goal-scope",
            "bogus-project#110",
        ],
        claims=(),
    )
    assert return_code == 2
    assert "exactly one healthy invoking-session claim" in stderr


def test_public_cli_decide_rejects_foreign_project_scope_with_same_plan_number(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    repo_root = Path(__file__).parents[1]
    graph_ref = "docs/plans/110_no_passive_waiting_work_graph.json"
    digest = hashlib.sha256((repo_root / graph_ref).read_bytes()).hexdigest()
    payload = BlockerDecisionInputV1(
        request_ref="foreign-project",
        request=_request(blocked_scope="goal").model_copy(update={"claim_scope": "bogus-project#110"}),
        work_graph_ref_path=graph_ref,
        expected_work_graph_sha256=digest,
    )
    input_path = tmp_path / "foreign-project.json"
    input_path.write_text(payload.model_dump_json(), encoding="utf-8")
    return_code, _stdout, stderr = _run_public_cli(
        monkeypatch,
        capsys,
        ["decide", "--input-json", str(input_path)],
        claims=(),
    )
    assert return_code == 2
    assert "exactly one healthy invoking-session claim" in stderr
