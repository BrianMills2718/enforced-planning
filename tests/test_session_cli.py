"""Tests for session lifecycle CLI behavior."""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
import yaml

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    coordination_messages,
    prewrite_claim_projection,
    session_contracts,
    session_lifecycle,
)


@pytest.fixture(autouse=True)
def _isolate_claim_mutation_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep lifecycle fixtures out of the shared operator ledger."""

    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )


def _git(cwd: Path, *args: str) -> str:
    """Run one real Git command for lifecycle integration fixtures."""

    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _real_repo_with_worktree(
    tmp_path: Path,
    *,
    branch: str = "plan-59-safe-closeout",
) -> tuple[Path, Path, str]:
    """Create a real canonical repo plus an in-repo linked task worktree."""

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "tests@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / ".gitignore").write_text("worktrees/\n", encoding="utf-8")
    (repo_root / "README.md").write_text(
        "\n".join(f"baseline line {index}" for index in range(1, 21)) + "\n",
        encoding="utf-8",
    )
    _git(repo_root, "add", ".gitignore", "README.md")
    _git(repo_root, "commit", "-m", "initial")

    worktree = repo_root / "worktrees" / branch
    _git(repo_root, "worktree", "add", "-b", branch, str(worktree), "main")
    (worktree / "feature.txt").write_text("unique work\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "feature")
    return repo_root, worktree, branch


def _start_real_closeout_claim(
    *,
    repo_root: Path,
    worktree: Path,
    branch: str,
    claims_dir: Path,
    trackers_dir: Path,
) -> Path:
    """Create one claim/tracker pair for a real-Git closeout fixture."""

    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        intent="prove merge-or-disposition closeout",
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch=branch,
        broader_goal="Safe Worktree Lifecycle",
        current_phase="closeout controls",
        plan_ref="Plan #59",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )
    return claims_dir / coordination_claims._claim_filename(
        "codex",
        "enforced-planning",
        branch,
    )


def _send_active_closeout_message(*, claims_dir: Path, recipient_session_id: str) -> str:
    """Persist one actionable message for the exact closeout recipient."""

    sender_session_id = "claude-code:closeout-sender"
    sender_claim = {
        "schema_version": 2,
        "agent": "claude-code",
        "projects": ["enforced-planning"],
        "scope": "closeout-sender",
        "intent": "send closeout coordination",
        "claim_type": "program",
        "write_paths": [],
        "read_paths": [],
        "session_id": sender_session_id,
        "heartbeat_at": "2026-07-28T00:00:00+00:00",
        "status": "active",
        "claimed_at": "2026-07-28T00:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    (claims_dir / "claude-code_enforced-planning_closeout-sender.yaml").write_text(
        yaml.safe_dump(sender_claim, sort_keys=False), encoding="utf-8"
    )
    store = coordination_messages.CoordinationMessageStore(
        root=coordination_messages.default_message_root(claims_dir),
        claims_dir=claims_dir,
    )
    message = store.send(
        coordination_messages.SendMessageRequest(
            caller_session_id=sender_session_id,
            sender_session_id=sender_session_id,
            recipient=coordination_messages.ExactSessionSelector(
                kind="session", session_id=recipient_session_id
            ),
            project="enforced-planning",
            kind="coordination_request",
            subject="Closeout review request",
            body="Please reconcile the outstanding closeout decision.",
        )
    )
    return message.message.message_id


def test_worktree_lifecycle_policy_rejects_overlapping_dispositions(tmp_path: Path) -> None:
    """Policy configuration must fail loud when one outcome has two meanings."""

    config_path = tmp_path / "worktree_lifecycle.yaml"
    config_path.write_text(
        """\
schema_version: 1
dispositions:
  merged: merged
  non_closeable: [active]
  recovery_required: [archived]
  discard_requires_authorization: [archived]
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="groups overlap"):
        session_lifecycle._load_worktree_lifecycle_policy(config_path)


def test_start_session_creates_tracker_and_updates_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Session start should materialize both tracker and compact claim metadata."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    payload = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        intent="implement session lifecycle CLI and governed repo enforcement",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/plan-31-session-cli-enforcement",
        branch="plan-31-session-cli-enforcement",
        broader_goal="Cross-Project Session Lifecycle Enforcement",
        current_phase="wire lifecycle wrappers and sanctioned entrypoints",
        plan_ref="Plan #31",
        session_id="codex:test-session",
        intended_next_phases=["install governed repo wrappers"],
        depends_on_repos=["project-meta"],
        requires_shared_infra_changes=True,
        stop_conditions=["irreversible shared-state action"],
        notes="plan 31 in progress",
        tracker_dir=trackers_dir,
    )

    claim_file = claims_dir / "codex_enforced-planning_plan-31-session-cli-enforcement.yaml"
    assert claim_file.exists()
    loaded_claim = coordination_claims.normalize_claim(
        yaml.safe_load(claim_file.read_text(encoding="utf-8")),
        source_file=str(claim_file),
    )
    assert loaded_claim is not None
    assert coordination_claims.claim_health_status(loaded_claim) == "healthy"
    assert loaded_claim.session_name == "cross-project-session-lifecycle-enforcement"
    assert loaded_claim.broader_goal == "Cross-Project Session Lifecycle Enforcement"
    assert loaded_claim.tracker_path == payload["tracker_path"]
    assert Path(payload["tracker_path"]).exists()
    assert payload["plan_ref"] == "Plan #31"


def test_existing_session_upsert_refreshes_projection_and_emits_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Refreshing a live session claim must remain attributable to the fast gate."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    common = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "plan-108-upsert-receipt",
        "intent": "prove existing-session claim provenance",
        "repo_root": str(tmp_path / "repo"),
        "worktree_path": str(tmp_path / "repo" / "worktrees" / "plan-108-upsert-receipt"),
        "branch": "plan-108-upsert-receipt",
        "broader_goal": "Pre-Write Claim Enforcement",
        "plan_ref": "Plan #108",
        "session_id": "codex:test-session",
        "tracker_dir": trackers_dir,
    }

    session_lifecycle.start_session(current_phase="initial", **common)
    refreshed = session_lifecycle.start_session(current_phase="refreshed", **common)

    records = claim_mutation_receipts.load_receipts()
    upserts = [record for record in records if record.operation == "session_upsert"]
    assert len(upserts) == 1
    receipt = upserts[0]
    assert receipt.target_project == "enforced-planning"
    assert receipt.target_scope == "plan-108-upsert-receipt"
    assert receipt.registry_digest_after == receipt.projection_digest_after
    assert receipt.projection_current_after is True
    assert refreshed["action"] == "updated"


def test_existing_session_upsert_reports_audit_failure_after_persisting_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed session-upsert receipt must not conceal the applied claim update."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    common = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "plan-108-upsert-audit-failure",
        "intent": "initial claim intent",
        "repo_root": str(tmp_path / "repo"),
        "worktree_path": str(tmp_path / "repo" / "worktrees" / "plan-108-upsert-audit-failure"),
        "branch": "plan-108-upsert-audit-failure",
        "broader_goal": "Pre-Write Claim Enforcement",
        "plan_ref": "Plan #108",
        "session_id": "codex:test-session",
        "tracker_dir": trackers_dir,
    }
    session_lifecycle.start_session(current_phase="initial", **common)

    def fail_append(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated receipt ledger outage")

    monkeypatch.setattr(claim_mutation_receipts, "append_receipt", fail_append)
    with pytest.raises(claim_mutation_receipts.MutationAuditError, match="session_upsert"):
        session_lifecycle.start_session(
            current_phase="refreshed",
            **{**common, "intent": "persisted update despite receipt failure"},
        )

    claim_file = claims_dir / "codex_enforced-planning_plan-108-upsert-audit-failure.yaml"
    assert yaml.safe_load(claim_file.read_text(encoding="utf-8"))["intent"] == (
        "persisted update despite receipt failure"
    )
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir) is True


def test_session_end_retires_live_ownership_and_preserves_resume_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A real runtime end must release ownership without deleting recoverable work."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "repo" / "worktrees" / "plan-105-root"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-105-root",
        intent="enforce session-bound lanes",
        repo_root=str(tmp_path / "repo"),
        worktree_path=str(worktree),
        branch="plan-105-root",
        broader_goal="Prevent Abandoned Workspace Lanes",
        current_phase="implementation",
        plan_ref="Plan #105",
        session_id="codex:ending-runtime",
        tracker_dir=trackers_dir,
    )

    ended = session_lifecycle.end_runtime_session(
        agent="codex",
        session_id="codex:ending-runtime",
        reason="user exited client",
        claims_dir=claims_dir,
    )
    assert ended["ended_count"] == 1
    assert ended["claims"] == ["enforced-planning:plan-105-root"]
    assert worktree.exists()
    assert coordination_claims.check_claims(claims_dir=claims_dir) == []

    status = session_lifecycle.status_sessions(
        project="enforced-planning",
        include_ended=True,
    )
    assert status["session_count"] == 1
    assert status["sessions"][0]["claim_status"] == "session_ended"
    assert status["sessions"][0]["recovery_action"] == "resume_take_over_or_close_preserved_lane"
    claim_path = claims_dir / "codex_enforced-planning_plan-105-root.yaml"
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert claim_payload["previous_status"] == "active"
    assert claim_payload["session_end_reason"] == "user exited client"

    with pytest.raises(ValueError, match="Preserved session-ended lane"):
        coordination_claims.create_claim(
            agent="claude-code",
            project="enforced-planning",
            scope="plan-105-replacement",
            intent="silently replace ended work",
            plan_ref="Plan #105",
            claim_type="program",
            repo_root=str(tmp_path / "repo"),
            worktree_path=str(tmp_path / "repo" / "worktrees" / "replacement"),
            branch="plan-105-replacement",
            session_id="claude-code:replacement",
            session_name="prevent-abandoned-workspace-lanes",
            broader_goal="Prevent Abandoned Workspace Lanes",
            tracker_path=str(trackers_dir / "replacement.yaml"),
        )

    resumed = session_lifecycle.resume_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-105-root",
        worktree_path=str(worktree),
        branch="plan-105-root",
        current_phase="resumed disposition",
        session_id="codex:new-runtime",
    )
    assert resumed["action"] == "resumed"
    assert resumed["session_id"] == "codex:new-runtime"
    assert coordination_claims.check_claims("enforced-planning")[0].status == "active"


def test_native_session_end_hook_requires_real_end_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A turn-level event must never be mistaken for runtime termination."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "repo" / "worktrees" / "hook-root"
    worktree.mkdir(parents=True)
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="hook-root",
        intent="test native end hook",
        repo_root=str(tmp_path / "repo"),
        worktree_path=str(worktree),
        branch="hook-root",
        broader_goal="Test Native Session End",
        current_phase="hook fixture",
        plan_ref="Plan #105",
        session_id="codex:hook-session",
        tracker_dir=trackers_dir,
    )
    command = [
        "python",
        "scripts/session_end.py",
        "--agent",
        "codex",
        "--hook",
        "--claims-dir",
        str(claims_dir),
    ]
    stop = subprocess.run(
        command,
        input=json.dumps(
            {"session_id": "hook-session", "hook_event_name": "Stop"}
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert stop.returncode == 0
    assert "requires hook_event_name=SessionEnd" in stop.stdout
    assert coordination_claims.check_claims(claims_dir=claims_dir)

    ended = subprocess.run(
        command,
        input=json.dumps(
            {
                "session_id": "hook-session",
                "hook_event_name": "SessionEnd",
                "reason": "logout",
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    assert ended.returncode == 0, ended.stderr or ended.stdout
    assert json.loads(ended.stdout)["ended_count"] == 1
    assert coordination_claims.check_claims(claims_dir=claims_dir) == []


def test_start_session_creates_parented_child_and_rejects_second_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session activation should enforce the existing program/parent hierarchy."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        coordination_claims,
        "resolve_canonical_work_unit_binding",
        lambda **_kwargs: ("a" * 64, ()),
    )
    common = {
        "project": "onto-canon6",
        "repo_root": str(tmp_path / "onto-canon6"),
        "broader_goal": "Complete Plan 0141",
        "current_phase": "parallel execution",
        "plan_ref": "Plan #0141",
        "tracker_dir": trackers_dir,
    }
    root_worktree = tmp_path / "onto-canon6" / "worktrees" / "plan0141-root"
    child_worktree = tmp_path / "onto-canon6" / "worktrees" / "plan0141-review"
    root_worktree.mkdir(parents=True)
    child_worktree.mkdir(parents=True)
    session_lifecycle.start_session(
        agent="codex",
        scope="plan0141-root",
        intent="coordinate Plan 0141",
        worktree_path=str(root_worktree),
        branch="plan0141-root",
        session_id="codex:root",
        claim_type="program",
        **common,
    )
    session_lifecycle.start_session(
        agent="claude-code",
        scope="plan0141-review",
        intent="review Plan 0141 output",
        worktree_path=str(child_worktree),
        branch="plan0141-review",
        session_id="claude-code:review",
        claim_type="write",
        write_paths=["src/onto_canon6/review.py"],
        parent_scope="plan0141-root",
        work_graph_path="docs/plans/141_fixture_work_graph.json",
        work_unit_id="plan0141-review",
        **common,
    )

    child_path = claims_dir / "claude-code_onto-canon6_plan0141-review.yaml"
    child = coordination_claims.normalize_claim(
        yaml.safe_load(child_path.read_text(encoding="utf-8")),
        source_file=str(child_path),
    )
    assert child is not None
    assert child.claim_type == "write"
    assert child.write_paths == ["src/onto_canon6/review.py"]
    assert child.parent_scope == "plan0141-root"
    child_status = session_lifecycle.status_sessions(
        project="onto-canon6",
        scope="plan0141-review",
    )
    assert child_status["sessions"][0]["health_status"] == "healthy"
    assert child_status["sessions"][0]["health_issues"] == []
    assert child_status["sessions"][0]["plan_identity"] == "Plan #141"
    assert child_status["sessions"][0]["hierarchy_role"] == "child"
    assert child_status["sessions"][0]["parent_scope"] == "plan0141-root"

    with pytest.raises(ValueError, match="multiple_program_roots"):
        session_lifecycle.start_session(
            agent="openclaw",
            scope="plan0141-second-root",
            intent="duplicate Plan 0141 coordinator",
            worktree_path=str(
                tmp_path / "onto-canon6" / "worktrees" / "plan0141-second-root"
            ),
            branch="plan0141-second-root",
            session_id="openclaw:second-root",
            claim_type="program",
            **common,
        )
    assert not (claims_dir / "openclaw_onto-canon6_plan0141-second-root.yaml").exists()
    assert not list((trackers_dir / "onto-canon6").glob("*second-root*.yaml"))


def test_concurrent_legacy_claim_activation_serializes_hierarchy_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy reservations must not concurrently refresh into duplicate roots."""

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    original_validate = coordination_claims.validate_claim_hierarchy_for_creation

    def delayed_validate(*args, **kwargs):
        original_validate(*args, **kwargs)
        time.sleep(0.05)

    monkeypatch.setattr(
        coordination_claims,
        "validate_claim_hierarchy_for_creation",
        delayed_validate,
    )
    for index, agent in enumerate(("codex", "claude-code"), start=1):
        scope = f"plan141-legacy-{index}"
        payload = {
            "agent": agent,
            "projects": ["onto-canon6"],
            "scope": scope,
            "intent": "legacy Plan 0141 reservation",
            "claim_type": "program",
            "plan_ref": "Plan #0141",
            "branch": scope,
            "worktree_path": str(tmp_path / "onto-canon6" / "worktrees" / scope),
            "status": "active",
        }
        path = claims_dir / coordination_claims._claim_filename(
            agent,
            "onto-canon6",
            scope,
        )
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    def activate(index: int) -> tuple[bool, str]:
        agent = ("codex", "claude-code")[index - 1]
        scope = f"plan141-legacy-{index}"
        try:
            result = session_lifecycle._upsert_session_claim(
                agent=agent,
                project="onto-canon6",
                scope=scope,
                intent="activate legacy Plan 0141 reservation",
                plan_ref="Plan #0141",
                repo_root=str(tmp_path / "onto-canon6"),
                worktree_path=str(tmp_path / "onto-canon6" / "worktrees" / scope),
                branch=scope,
                session_id=f"{agent}:session",
                broader_goal="Complete Plan 0141",
                session_name=f"plan141-legacy-{index}",
                tracker_path=str(tmp_path / "sessions" / f"{scope}.yaml"),
                claim_type="program",
            )
        except ValueError as error:
            return False, str(error)
        return True, result

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(activate, (1, 2)))

    assert sum(1 for ok, _message in results if ok) == 1
    assert sum("multiple_program_roots" in message for _ok, message in results) == 1
    claims = coordination_claims.check_claims("onto-canon6")
    assert sum(claim.session_id is not None for claim in claims) == 1


def test_status_sessions_routes_incomplete_plan_claim_to_contract_repair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session status must expose missing contract fields instead of healthy None values."""

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_lifecycle.coordination_claims, "CLAIMS_DIR", claims_dir)
    worktree = tmp_path / "repo" / "worktrees" / "plan0141-canonical-record-evidence"
    worktree.mkdir(parents=True)
    claim_path = claims_dir / "codex_onto-canon6_plan0141-canonical-record-evidence.yaml"
    claim_path.write_text(
        yaml.safe_dump(
            {
                "agent": "codex",
                "projects": ["onto-canon6"],
                "scope": "plan0141-canonical-record-evidence",
                "intent": "Add canonical-record evidence",
                "claim_type": "write",
                "write_paths": ["src/onto_canon6/document_map/complete_document_semantic_v2.py"],
                "plan_ref": "Plan #0141 Greer row 10302 vertical slice",
                "branch": "plan0141-canonical-record-evidence",
                "worktree_path": str(worktree),
                "session_id": "codex:plan0141",
                "status": "active",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    payload = session_lifecycle.status_sessions(project="onto-canon6")

    assert payload["session_count"] == 1
    session = payload["sessions"][0]
    assert session["health_status"] == "weak"
    assert session["health_issues"] == [
        "missing_session_name",
        "missing_repo_root",
        "missing_broader_goal",
        "missing_tracker_path",
    ]
    assert session["recovery_action"] == "repair_session_contract"


def test_start_session_requires_plan_ref_without_unplanned_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live sessions must declare a plan unless explicitly marked unplanned."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    with pytest.raises(ValueError, match="plan_ref is required"):
        session_lifecycle.start_session(
            agent="codex",
            project="enforced-planning",
            scope="plan-37-session-recovery",
            intent="implement plan-bound session lifecycle",
            repo_root="~/projects/enforced-planning",
            worktree_path="~/projects/enforced-planning_worktrees/plan-37-session-recovery",
            branch="plan-37-session-recovery",
            broader_goal="Plan Bound Session Recovery",
            current_phase="bootstrap",
            session_id="codex:test-session",
            tracker_dir=trackers_dir,
        )


def test_start_session_marks_explicit_unplanned_work(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unplanned work must still be explicit instead of silently plan-less."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    payload = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="emergency-hotfix",
        intent="urgent sanctioned emergency work",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/emergency-hotfix",
        branch="emergency-hotfix",
        broader_goal="Emergency Coordination Hotfix",
        current_phase="containment",
        allow_unplanned=True,
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    assert payload["plan_ref"] == "UNPLANNED"


def test_heartbeat_session_updates_tracker_phase(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Heartbeat should refresh both claim liveness and tracker timestamp."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        intent="implement session lifecycle CLI and governed repo enforcement",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/plan-31-session-cli-enforcement",
        branch="plan-31-session-cli-enforcement",
        broader_goal="Cross-Project Session Lifecycle Enforcement",
        current_phase="initial bootstrap",
        plan_ref="Plan #31",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    payload = session_lifecycle.heartbeat_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        branch="plan-31-session-cli-enforcement",
        session_id="codex:test-session",
        current_phase="template and installer enforcement",
    )

    tracker_payload = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))
    assert payload["updated_count"] == 1
    assert payload["tracker_paths_updated"] == [started["tracker_path"]]
    assert tracker_payload["tracker"]["current_phase"] == "template and installer enforcement"
    assert tracker_payload["timestamps"]["updated_at"] == payload["heartbeat_at"]


def test_heartbeat_session_rejects_zero_matching_claims(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A wrong project selector must fail instead of reporting heartbeat success."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-73-coordination-status-integrity",
        intent="repair coordination status",
        repo_root=str(tmp_path / "enforced-planning"),
        worktree_path=str(tmp_path / "enforced-planning" / "worktrees" / "plan-73"),
        branch="plan-73-coordination-status-integrity",
        broader_goal="Coordination Status Integrity",
        current_phase="negative control",
        plan_ref="Plan #73",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    with pytest.raises(ValueError, match="Heartbeat matched no live claim"):
        session_lifecycle.heartbeat_session(
            agent="codex",
            project="plan-73-coordination-status-integrity",
            scope="plan-73-coordination-status-integrity",
            branch="plan-73-coordination-status-integrity",
            session_id="codex:test-session",
        )


def test_finish_session_blocks_dirty_cleanup_without_handoff(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session finish should fail loud when the worktree is dirty and no handoff is declared."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        intent="implement session lifecycle CLI and governed repo enforcement",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="plan-31-session-cli-enforcement",
        broader_goal="Cross-Project Session Lifecycle Enforcement",
        current_phase="dirty state proof",
        plan_ref="Plan #31",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )
    (worktree / "dirty.txt").write_text("still editing\n", encoding="utf-8")

    def _fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = " M dirty.txt\n"
            stderr = ""
        return Result()

    monkeypatch.setattr(session_lifecycle.subprocess, "run", _fake_run)

    with pytest.raises(ValueError, match="Worktree is dirty"):
        session_lifecycle.finish_session(
            agent="codex",
            project="enforced-planning",
            scope="plan-31-session-cli-enforcement",
            worktree_path=str(worktree),
            release_claim=True,
        )


def test_finish_session_releases_clean_claim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Session finish should release the live claim once the worktree is clean."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        intent="implement session lifecycle CLI and governed repo enforcement",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="plan-31-session-cli-enforcement",
        broader_goal="Cross-Project Session Lifecycle Enforcement",
        current_phase="clean closeout",
        plan_ref="Plan #31",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    def _fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""
        return Result()

    monkeypatch.setattr(session_lifecycle.subprocess, "run", _fake_run)

    payload = session_lifecycle.finish_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        worktree_path=str(worktree),
        release_claim=True,
    )

    assert payload["action"] == "released"
    assert not (claims_dir / "codex_enforced-planning_plan-31-session-cli-enforcement.yaml").exists()


def test_close_session_rejects_clean_unmerged_branch_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: clean committed work must not be silently deleted."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )

    with pytest.raises(ValueError, match="not integrated"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
        )

    assert worktree.exists()
    assert _git(repo_root, "show-ref", "--verify", f"refs/heads/{branch}")
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "active"


def test_close_session_closes_branch_merged_to_default(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control: a merged lane closes and keeps disposition history."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    events_path = tmp_path / "claim-mutation-events.jsonl"
    monkeypatch.setattr(claim_mutation_receipts, "DEFAULT_EVENTS_PATH", events_path)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["disposition"] == "merged"
    assert not worktree.exists()
    branch_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert branch_check.returncode != 0
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "completed"
    assert claim_payload["disposition"] == "merged"
    closeout_records = [
        record
        for record in claim_mutation_receipts.load_receipts(events_path=events_path)
        if record.operation == "closeout"
    ]
    assert len(closeout_records) == 1
    assert closeout_records[0].target_claim_path == str(claim_file)
    assert closeout_records[0].projection_current_after is True


def test_close_session_rejects_active_mailbox_message_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lane cannot strand an actionable exact-recipient message at closeout."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    message_id = _send_active_closeout_message(
        claims_dir=claims_dir, recipient_session_id="codex:test-session"
    )

    with pytest.raises(ValueError, match="active mailbox message"):
        session_lifecycle.close_session(agent="codex", project="enforced-planning", scope=branch)

    assert worktree.exists()
    assert _git(repo_root, "show-ref", "--verify", f"refs/heads/{branch}")
    assert yaml.safe_load(claim_file.read_text(encoding="utf-8"))["status"] == "active"
    store = coordination_messages.CoordinationMessageStore(
        root=coordination_messages.default_message_root(claims_dir), claims_dir=claims_dir
    )
    assert store.status(coordination_messages.MessageStatusRequest(message_id=message_id)).acknowledged is False


def test_close_session_records_explicit_mailbox_deferral(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit closeout deferral is durable and remains bound to the recipient session."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    message_id = _send_active_closeout_message(
        claims_dir=claims_dir, recipient_session_id="codex:test-session"
    )

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        mailbox_disposition="deferred",
        mailbox_note="Deferred at closeout; successor must reconcile the review request.",
    )

    assert payload["action"] == "closed"
    assert payload["mailbox_disposition"] == "deferred"
    assert payload["mailbox_message_ids"] == [message_id]
    store = coordination_messages.CoordinationMessageStore(
        root=coordination_messages.default_message_root(claims_dir), claims_dir=claims_dir
    )
    status = store.status(coordination_messages.MessageStatusRequest(message_id=message_id))
    assert status.acknowledged is True
    acknowledgement = next(receipt for receipt in status.receipts if receipt.event == "acknowledged")
    assert acknowledgement.recipient_session_id == "codex:test-session"
    assert acknowledgement.disposition == "deferred"


def test_close_session_rejects_live_sibling_claim_on_same_worktree_before_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One lane must not remove a worktree still referenced by another live claim."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    sibling = coordination_claims.build_candidate_claim(
        agent="claude-code",
        project="enforced-planning",
        scope="sibling-review",
        intent="review the same lane",
        claim_type="review",
        read_paths=["feature.txt"],
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch=branch,
        session_id="claude-code:test-session",
        session_name="sibling-review",
        broader_goal="Safe Worktree Lifecycle",
        tracker_path=str(trackers_dir / "sibling.yaml"),
        claimed_at="2026-07-28T00:00:00+00:00",
        expires_at="2099-07-28T00:00:00+00:00",
    )
    sibling_payload = sibling.to_dict()
    sibling_payload.pop("project")
    sibling_payload.pop("source_file")
    claims_dir.joinpath("claude-code_enforced-planning_sibling-review.yaml").write_text(
        yaml.safe_dump(sibling_payload, sort_keys=False),
        encoding="utf-8",
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")

    with pytest.raises(ValueError, match="sibling-review"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
        )

    assert worktree.exists()
    assert _git(repo_root, "show-ref", "--verify", f"refs/heads/{branch}")
    assert yaml.safe_load(claim_file.read_text(encoding="utf-8"))["status"] == "active"


def test_close_session_accepts_exact_squash_merge_patch_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A one-parent main commit with the exact task patch licenses squash closeout."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "cherry-pick", "--no-commit", branch)
    _git(repo_root, "commit", "-m", "squash merge feature")
    merge_commit = _git(repo_root, "rev-parse", "HEAD")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        merge_commit=merge_commit,
    )

    assert payload["action"] == "closed"
    assert payload["merged_to_default"] is True
    assert payload["merge_commit"] == merge_commit
    assert payload["merge_evidence"] == "squash_patch_equivalent"
    assert not worktree.exists()
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["merge_commit"] == merge_commit
    assert claim_payload["merge_evidence"] == "squash_patch_equivalent"


def test_patch_normalization_ignores_only_full_index_blob_identity() -> None:
    """Squash comparison must retain modes, binary payloads, and content lines."""

    patch_body = (
        b"diff --git a/example.bin b/example.bin\n"
        b"old mode 100644\n"
        b"new mode 100755\n"
        b"GIT binary patch\n"
        b"literal 3\n"
        b"KcmZQz\n"
        b"+index remains ordinary file content here\n"
    )
    first = b"index " + b"a" * 40 + b".." + b"b" * 40 + b" 100644\n" + patch_body
    second = b"index " + b"c" * 40 + b".." + b"d" * 40 + b" 100644\n" + patch_body

    assert session_lifecycle._patch_without_blob_identity(
        first
    ) == session_lifecycle._patch_without_blob_identity(second)
    assert session_lifecycle._patch_without_blob_identity(
        first
    ) != session_lifecycle._patch_without_blob_identity(
        second.replace(b"new mode 100755", b"new mode 100644")
    )
    assert session_lifecycle._patch_without_blob_identity(
        first
    ) != session_lifecycle._patch_without_blob_identity(
        second.replace(b"KcmZQz", b"KcmZRz")
    )
    assert session_lifecycle._patch_without_blob_identity(
        first
    ) != session_lifecycle._patch_without_blob_identity(
        second.replace(b"+index remains", b"+index changed")
    )


def test_close_session_accepts_squash_patch_after_independent_same_file_change(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unrelated base blob identity must not strand an otherwise exact squash patch."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    branch_lines = (worktree / "README.md").read_text(encoding="utf-8").splitlines()
    branch_lines[1] = "task branch change"
    (worktree / "README.md").write_text("\n".join(branch_lines) + "\n", encoding="utf-8")
    _git(worktree, "add", "README.md")
    _git(worktree, "commit", "-m", "update task setting")

    main_lines = (repo_root / "README.md").read_text(encoding="utf-8").splitlines()
    main_lines[17] = "independent main change"
    (repo_root / "README.md").write_text("\n".join(main_lines) + "\n", encoding="utf-8")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "update unrelated main setting")
    merge_parent = _git(repo_root, "rev-parse", "HEAD")
    merge_base = _git(repo_root, "merge-base", branch, merge_parent)
    _git(repo_root, "cherry-pick", "--no-commit", f"{merge_base}..{branch}")
    _git(repo_root, "commit", "-m", "squash merge feature after main advanced")
    merge_commit = _git(repo_root, "rev-parse", "HEAD")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        merge_commit=merge_commit,
    )

    assert payload["action"] == "closed"
    assert payload["merge_evidence"] == "squash_patch_equivalent"
    assert not worktree.exists()
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["merge_commit"] == merge_commit


def test_close_session_rejects_unrelated_commit_as_squash_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any main commit whose patch differs from the task branch must fail closed."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    (repo_root / "unrelated.txt").write_text("different patch\n", encoding="utf-8")
    _git(repo_root, "add", "unrelated.txt")
    _git(repo_root, "commit", "-m", "unrelated main change")
    unrelated_commit = _git(repo_root, "rev-parse", "HEAD")

    with pytest.raises(ValueError, match="not integrated"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
            merge_commit=unrelated_commit,
        )

    assert worktree.exists()
    assert yaml.safe_load(claim_file.read_text(encoding="utf-8"))["status"] == "active"


def test_close_session_accepts_branch_merged_to_remote_default_when_local_default_is_behind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale primary checkout must not block proven remote-default integration."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(
        repo_root,
        "update-ref",
        "refs/remotes/origin/main",
        f"refs/heads/{branch}",
    )

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["merged_to_default"] is True
    assert payload["default_remote_ref"] == "refs/remotes/origin/main"
    assert payload["default_branch_pushed"] is True
    assert not worktree.exists()


def test_close_session_deletes_merged_branch_with_stale_feature_upstream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit default-merge proof must outrank a stale feature upstream."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    stale_base = _git(repo_root, "rev-parse", "main~1")
    stale_upstream_tip = _git(
        repo_root,
        "commit-tree",
        f"{stale_base}^{{tree}}",
        "-p",
        stale_base,
        "-m",
        "divergent feature upstream",
    )
    _git(repo_root, "remote", "add", "origin", str(repo_root))
    _git(repo_root, "update-ref", f"refs/remotes/origin/{branch}", stale_upstream_tip)
    _git(repo_root, "config", f"branch.{branch}.remote", "origin")
    _git(repo_root, "config", f"branch.{branch}.merge", f"refs/heads/{branch}")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["merged_to_default"] is True
    assert payload["force_delete_branch"] is True
    assert payload["branch_action"] == "deleted"
    assert not worktree.exists()
    branch_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert branch_check.returncode != 0


def test_close_session_rejects_unpushed_default_branch_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: merged work remains live until canonical main is pushed."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    remote_default_ref = "refs/remotes/origin/main"
    _git(repo_root, "update-ref", remote_default_ref, "refs/heads/main")
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")

    with pytest.raises(ValueError, match="Push the default branch before closeout"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
        )
    assert worktree.exists()

    _git(repo_root, "update-ref", remote_default_ref, "refs/heads/main")
    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )
    assert payload["default_branch_pushed"] is True


def test_close_session_accepts_branch_merged_to_pushed_remote_default_when_local_is_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A stale local main must not prevent safe closeout of a remotely merged lane."""
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(repo_root=repo_root, worktree=worktree, branch=branch, claims_dir=claims_dir, trackers_dir=trackers_dir)
    stale_main = _git(repo_root, "rev-parse", "refs/heads/main").strip()
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    _git(repo_root, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    _git(repo_root, "reset", "--hard", stale_main)

    payload = session_lifecycle.close_session(agent="codex", project="enforced-planning", scope=branch)

    assert payload["merged_to_default"] is True
    assert payload["default_branch_pushed"] is True
    assert not worktree.exists()


def test_close_session_accepts_remote_merged_branch_when_local_default_diverges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A divergent local default ref must not block remote-proven lane closure."""
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(repo_root=repo_root, worktree=worktree, branch=branch, claims_dir=claims_dir, trackers_dir=trackers_dir)
    local_main = _git(repo_root, "rev-parse", "refs/heads/main").strip()
    divergent_main = _git(repo_root, "commit-tree", f"{local_main}^{{tree}}", "-p", local_main, "-m", "preserved local divergence").strip()
    _git(repo_root, "update-ref", "refs/remotes/origin/main", f"refs/heads/{branch}")
    _git(repo_root, "update-ref", "refs/heads/main", divergent_main)

    payload = session_lifecycle.close_session(agent="codex", project="enforced-planning", scope=branch)

    assert payload["merged_to_default"] is True
    assert payload["default_branch_pushed"] is False
    assert not worktree.exists()


def test_close_session_keeps_canonical_root_after_worktree_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """In-repo worktree paths must resolve the canonical root before removal."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    claim_payload.pop("repo_root")
    claim_file.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["worktree_action"] == "removed"
    assert payload["branch_action"] == "deleted"
    assert repo_root.exists()


def test_close_session_fails_before_registry_mutation_when_ignored_directory_is_not_deletable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read-only ignored cache must not leave a half-removed worktree."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    (worktree / ".gitignore").write_text("runtime-cache/\n", encoding="utf-8")
    _git(worktree, "add", ".gitignore")
    _git(worktree, "commit", "-m", "ignore runtime cache")
    cache = worktree / "runtime-cache"
    cache.mkdir()
    (cache / "artifact.bin").write_bytes(b"preserve me")
    cache.chmod(0o555)

    try:
        with pytest.raises(PermissionError, match="before Git registry mutation"):
            session_lifecycle.close_session(
                agent="codex",
                project="enforced-planning",
                scope=branch,
                disposition="archived",
                disposition_reason="historical lane with remote recovery",
                recovery_ref="refs/heads/main",
            )

        assert worktree.exists()
        assert str(worktree) in _git(repo_root, "worktree", "list", "--porcelain")
        claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        assert claim_payload["status"] == "active"
        assert "disposition" not in claim_payload
    finally:
        cache.chmod(0o755)


def test_close_session_resolves_missing_nested_worktree_repo_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A removed slash-nested worktree must still resolve its canonical repo."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(
        tmp_path,
        branch="feat/nested-closeout",
    )
    claim_file = _start_real_closeout_claim(
        repo_root=worktree,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge nested feature")
    _git(repo_root, "worktree", "remove", str(worktree))

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["disposition"] == "merged"
    assert payload["worktree_action"] == "already_missing"
    assert payload["branch_action"] == "deleted"
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "completed"
    assert claim_payload["disposition"] == "merged"


def test_close_session_records_receipt_after_removing_loaded_runtime_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout keeps loaded-writer provenance after its source worktree is gone."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    events_path = tmp_path / "claim-mutation-events.jsonl"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(claim_mutation_receipts, "DEFAULT_EVENTS_PATH", events_path)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    runtime_source = worktree / "enforced_planning" / "coordination_claims.py"
    runtime_source.parent.mkdir()
    runtime_source.write_text("# loaded closeout runtime\n", encoding="utf-8")
    _git(worktree, "add", str(runtime_source.relative_to(worktree)))
    _git(worktree, "commit", "-m", "add closeout runtime fixture")
    loaded_identity = claim_mutation_receipts.writer_identity(runtime_source)
    monkeypatch.setattr(coordination_claims, "__file__", str(runtime_source))
    monkeypatch.setattr(coordination_claims, "_LOADED_WRITER_IDENTITY", loaded_identity)
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert not worktree.exists()
    assert yaml.safe_load(claim_file.read_text(encoding="utf-8"))["status"] == "completed"
    closeout_receipt = [
        receipt
        for receipt in claim_mutation_receipts.load_receipts(events_path=events_path)
        if receipt.operation == "closeout"
    ][-1]
    assert (
        closeout_receipt.writer_source_path,
        closeout_receipt.writer_source_sha256,
        closeout_receipt.writer_repo_root,
    ) == loaded_identity


def test_close_session_reconciles_exact_session_ended_missing_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A preserved exact lane closes without attempting filesystem deletion."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    session_lifecycle.end_runtime_session(
        agent="codex",
        session_id="codex:test-session",
        reason="runtime ended before physical closeout",
        claims_dir=claims_dir,
    )
    _git(repo_root, "worktree", "remove", str(worktree))
    claim_before = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    tracker = Path(claim_before["tracker_path"])
    digest = session_lifecycle._tracker_sha256(tracker)

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        reconcile_missing_worktree=True,
        expected_tracker_sha256=digest,
    )

    assert payload["action"] == "closed"
    assert payload["worktree_action"] == "not_attempted_absent_recorded_worktree"
    receipt = payload["missing_worktree_reconciliation"]
    assert receipt == {
        "schema_version": "1.0",
        "claim_status_before": "session_ended",
        "recorded_worktree_path": str(worktree),
        "tracker_path": str(tracker),
        "tracker_sha256": digest,
        "filesystem_action": "not_attempted_absent_recorded_worktree",
        "merge_evidence": "branch_ancestor",
        "merge_commit": "none",
    }
    claim_after = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_after["status"] == "completed"
    assert claim_after["missing_worktree_reconciliation"] == receipt
    assert session_contracts.read_session_tracker(tracker)["tracker"]["current_phase"] == "closed"


@pytest.mark.parametrize(
    ("end_session", "remove_worktree", "digest"),
    [
        (False, True, "correct"),
        (True, False, "correct"),
        (True, True, "wrong"),
    ],
)
def test_close_session_missing_worktree_reconciliation_rejects_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    end_session: bool,
    remove_worktree: bool,
    digest: str,
) -> None:
    """Live, present, or digest-changed lanes remain preserved for recovery."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    if end_session:
        session_lifecycle.end_runtime_session(
            agent="codex",
            session_id="codex:test-session",
            reason="runtime ended before physical closeout",
            claims_dir=claims_dir,
        )
    if remove_worktree:
        _git(repo_root, "worktree", "remove", str(worktree))
    claim_before = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    tracker = Path(claim_before["tracker_path"])
    expected_digest = session_lifecycle._tracker_sha256(tracker)
    if digest == "wrong":
        expected_digest = "0" * 64

    with pytest.raises(ValueError):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
            reconcile_missing_worktree=True,
            expected_tracker_sha256=expected_digest,
        )

    claim_after = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_after["status"] == claim_before["status"]
    assert not claim_after.get("missing_worktree_reconciliation")
    assert worktree.exists() is (not remove_worktree)


def test_close_session_rejects_unknown_disposition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown disposition values must fail before any cleanup mutation."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )

    with pytest.raises(ValueError, match="Unsupported worktree disposition"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
            disposition="forgotten",
        )
    assert worktree.exists()


def test_close_session_archives_unique_branch_with_durable_recovery_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-merge closeout may delete locally only after durable ref proof."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    recovery_ref = f"refs/remotes/origin/{branch}"
    _git(repo_root, "update-ref", recovery_ref, f"refs/heads/{branch}")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        disposition="archived",
        disposition_reason="preserve the reviewed experiment without merging it",
        recovery_ref=recovery_ref,
    )

    assert payload["disposition"] == "archived"
    assert _git(repo_root, "show-ref", "--verify", recovery_ref)
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "completed"
    assert claim_payload["recovery_ref"] == recovery_ref


def test_close_session_requires_durable_ref_for_retained_unique_commits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: retained unique work needs an independent recovery ref."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )

    with pytest.raises(ValueError, match="requires --recovery-ref"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
            disposition="archived",
            disposition_reason="preserve for possible later review",
        )
    assert worktree.exists()


def test_close_session_requires_explicit_unique_discard_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: abandonment never silently authorizes unique deletion."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )

    with pytest.raises(ValueError, match="requires --allow-discard-unique"):
        session_lifecycle.close_session(
            agent="codex",
            project="enforced-planning",
            scope=branch,
            disposition="abandoned",
            disposition_reason="experiment rejected after review",
        )
    assert worktree.exists()


def test_close_session_abandons_unique_branch_only_with_explicit_authorization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control: explicit abandonment records and performs unique deletion."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        disposition="abandoned",
        disposition_reason="experiment rejected after explicit review",
        allow_discard_unique=True,
    )

    assert payload["disposition"] == "abandoned"
    assert not worktree.exists()
    branch_check = subprocess.run(
        ["git", "show-ref", "--verify", f"refs/heads/{branch}"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    assert branch_check.returncode != 0
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "completed"
    assert claim_payload["disposition"] == "abandoned"


def test_close_session_completes_claim_even_when_worktree_already_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout reruns should retain completed history after partial cleanup."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-42-atomic-closeout",
        intent="implement atomic closeout lifecycle",
        repo_root=str(repo_root),
        worktree_path=str(tmp_path / "missing-worktree"),
        branch="plan-42-atomic-closeout",
        broader_goal="Coordination Runtime Completion",
        current_phase="rerun proof",
        plan_ref="Plan #42",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    def _fake_run(cmd, cwd=None, capture_output=True, text=True, check=False):  # type: ignore[no-untyped-def]
        class Result:
            returncode = 1
            stdout = ""
            stderr = ""

        if cmd[:2] == ["git", "show-ref"]:
            return Result()
        raise AssertionError(f"Unexpected command: {cmd}")

    monkeypatch.setattr(session_lifecycle.subprocess, "run", _fake_run)

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-42-atomic-closeout",
        worktree_path=str(tmp_path / "missing-worktree"),
        branch="plan-42-atomic-closeout",
    )

    assert payload["worktree_action"] == "already_missing"
    assert payload["branch_action"] == "already_missing"
    claim_file = claims_dir / "codex_enforced-planning_plan-42-atomic-closeout.yaml"
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "completed"
    assert claim_payload["disposition"] == "merged"


def test_close_session_recovers_exact_tracker_after_claim_refresh_lost_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout must not strand the original tracker after a claim refresh."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", trackers_dir)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    original_claim = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    tracker_path = Path(original_claim["tracker_path"])
    refreshed_claim = dict(original_claim)
    refreshed_claim["tracker_path"] = None
    refreshed_claim["broader_goal"] = None
    claim_file.write_text(yaml.safe_dump(refreshed_claim, sort_keys=False), encoding="utf-8")
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")

    payload = session_lifecycle.close_session(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["tracker_path"] == str(tracker_path)
    tracker_payload = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert tracker_payload["tracker"]["current_phase"] == "closed"


def test_tracker_recovery_rejects_ambiguous_exact_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lost tracker path must fail loud when exact identity matches twice."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", trackers_dir)
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "ambiguous-tracker"
    worktree.mkdir(parents=True)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="ambiguous-tracker",
        intent="exercise tracker ambiguity guard",
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="ambiguous-tracker",
        broader_goal="Tracker Ambiguity Guard",
        current_phase="fixture setup",
        plan_ref="Plan #59",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )
    tracker_path = Path(started["tracker_path"])
    duplicate = tracker_path.with_name("codex__enforced-planning__codex-test-session__duplicate.yaml")
    duplicate.write_text(tracker_path.read_text(encoding="utf-8"), encoding="utf-8")

    with pytest.raises(ValueError, match="Ambiguous exact session trackers"):
        session_contracts.find_session_tracker_path(
            agent="codex",
            project="enforced-planning",
            scope="ambiguous-tracker",
            session_id="codex:test-session",
        )


def test_handoff_session_marks_lane_for_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit handoff should keep the lane live but mark the recovery action."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        intent="implement plan-bound session lifecycle",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="plan-37-session-recovery",
        broader_goal="Plan Bound Session Recovery",
        current_phase="mid-implementation",
        plan_ref="Plan #37",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    payload = session_lifecycle.handoff_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        note="resume tomorrow from a fresh runtime",
    )
    status_payload = session_lifecycle.status_sessions(project="enforced-planning", scope="plan-37-session-recovery")
    tracker_payload = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))

    assert payload["action"] == "handoff"
    assert status_payload["sessions"][0]["claim_status"] == "handoff"
    assert status_payload["sessions"][0]["recovery_action"] == "resume_or_finish_handoff"
    assert tracker_payload["tracker"]["current_phase"] == "handoff required"


def test_resume_session_rebinds_stale_or_handoff_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resume should attach a fresh runtime session to the same plan-bound lane."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        intent="implement plan-bound session lifecycle",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="plan-37-session-recovery",
        broader_goal="Plan Bound Session Recovery",
        current_phase="mid-implementation",
        plan_ref="Plan #37",
        session_id="codex:old-session",
        tracker_dir=trackers_dir,
    )
    session_lifecycle.handoff_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        note="resume later",
    )

    payload = session_lifecycle.resume_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        worktree_path=str(worktree),
        branch="plan-37-session-recovery",
        current_phase="fresh runtime resumed",
        session_id="codex:new-session",
        note="resumed after overnight stop",
    )
    tracker_payload = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))
    status_payload = session_lifecycle.status_sessions(project="enforced-planning", scope="plan-37-session-recovery")

    assert payload["action"] == "resumed"
    assert payload["session_id"] == "codex:new-session"
    assert status_payload["sessions"][0]["claim_status"] == "active"
    assert status_payload["sessions"][0]["recovery_action"] == "continue"
    assert tracker_payload["tracker"]["current_phase"] == "fresh runtime resumed"


def test_abandon_session_removes_lane_from_live_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Abandoned lanes should stop participating in live session status."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        intent="implement plan-bound session lifecycle",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="plan-37-session-recovery",
        broader_goal="Plan Bound Session Recovery",
        current_phase="mid-implementation",
        plan_ref="Plan #37",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    payload = session_lifecycle.abandon_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        note="machine crashed and work will not be resumed",
    )
    tracker_payload = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))
    status_payload = session_lifecycle.status_sessions(project="enforced-planning", scope="plan-37-session-recovery")

    assert payload["action"] == "abandoned"
    assert status_payload["session_count"] == 0
    assert tracker_payload["tracker"]["current_phase"] == "abandoned"


def test_start_session_auto_resolves_codex_runtime_session_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Codex should use the same session lifecycle contract without explicit session_id."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "codex-thread-123")

    payload = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-32-cross-tool-session-rollout",
        intent="document and verify cross-tool session adapters and rollout",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/plan-32-cross-tool-session-rollout",
        branch="plan-32-cross-tool-session-rollout",
        broader_goal="Cross-Tool Session Adapter Rollout",
        current_phase="codex adapter proof",
        plan_ref="Plan #32",
        tracker_dir=trackers_dir,
    )

    assert payload["session_id"] == "codex:codex-thread-123"


def test_start_session_rejects_explicit_id_that_mismatches_codex_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session start must bind ownership to the actual interactive runtime."""

    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", tmp_path / "claims")
    monkeypatch.setenv("CODEX_THREAD_ID", "019f9b0a-5a78-7a91-a6c6-940aa5393e6b")

    with pytest.raises(ValueError, match="do not substitute a lane name"):
        session_lifecycle.start_session(
            agent="codex",
            project="inside-success",
            scope="second-slack-vertical-20260730",
            intent="run one retained Slack vertical",
            repo_root="~/projects/inside-success",
            worktree_path="~/projects/inside-success/worktrees/second-slack-vertical-20260730",
            branch="feat/second-slack-vertical-20260730",
            broader_goal="Improve retained Slack knowledge",
            current_phase="vertical execution",
            session_id="codex:second-slack-vertical-20260730",
            tracker_dir=tmp_path / "sessions",
            allow_unplanned=True,
        )


def test_start_session_auto_resolves_claude_code_runtime_session_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claude Code should produce the same claim/tracker contract shape."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "7777")

    payload = session_lifecycle.start_session(
        agent="claude-code",
        project="enforced-planning",
        scope="plan-32-cross-tool-session-rollout",
        intent="document and verify cross-tool session adapters and rollout",
        repo_root="~/projects/enforced-planning",
        worktree_path="~/projects/enforced-planning_worktrees/plan-32-cross-tool-session-rollout",
        branch="plan-32-cross-tool-session-rollout",
        broader_goal="Cross-Tool Session Adapter Rollout",
        current_phase="claude code adapter proof",
        plan_ref="Plan #32",
        tracker_dir=trackers_dir,
    )

    claim_file = claims_dir / "claude-code_enforced-planning_plan-32-cross-tool-session-rollout.yaml"
    loaded_claim = coordination_claims.normalize_claim(
        yaml.safe_load(claim_file.read_text(encoding="utf-8")),
        source_file=str(claim_file),
    )
    assert payload["session_id"] == "claude-code:sse:7777"
    assert loaded_claim is not None
    assert loaded_claim.session_name == "cross-tool-session-adapter-rollout"
    assert loaded_claim.broader_goal == "Cross-Tool Session Adapter Rollout"
