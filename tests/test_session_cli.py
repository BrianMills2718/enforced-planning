"""Tests for session lifecycle CLI behavior."""

from __future__ import annotations

import base64
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Event, Thread, current_thread
from types import SimpleNamespace

import pytest
import yaml

from enforced_planning import (
    claim_mutation_receipts,
    coordination_claims,
    coordination_messages,
    outcome_admission,
    prewrite_claim_fast,
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
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH",
        tmp_path / "completed-claim-archive.jsonl",
    )
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)


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


def _archived_claim_payload(archive_id: str) -> dict[str, object]:
    """Return the exact terminal YAML retained outside the live registry."""

    matches = [
        receipt
        for receipt in claim_mutation_receipts.load_completed_claim_archive_receipts()
        if receipt.archive_id == archive_id
    ]
    assert len(matches) == 1
    payload = yaml.safe_load(base64.b64decode(matches[0].source_yaml_bytes))
    assert isinstance(payload, dict)
    return payload


def _claim_owner(*, agent: str, project: str, scope: str) -> str:
    """Resolve the fixture's current actor without weakening the production guard."""

    claim, _path, _status = session_lifecycle._claim_record_any_status(
        agent=agent,
        project=project,
        scope=scope,
    )
    return claim.session_id


@contextmanager
def _native_actor(agent: str, session_id: str):
    """Expose the fixture owner through the same ambient marker as production."""

    env_key = coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS[agent]
    previous = os.environ.get(env_key)
    os.environ[env_key] = session_id.removeprefix(f"{agent}:")
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(env_key, None)
        else:
            os.environ[env_key] = previous


def _owner_bound_call(function, **kwargs: object) -> dict[str, object]:
    owner = _claim_owner(**{key: str(kwargs[key]) for key in ("agent", "project", "scope")})
    with _native_actor(str(kwargs["agent"]), owner):
        return function(actor_session_id=owner, **kwargs)


def _resume_session_as_native(**kwargs: object) -> dict[str, object]:
    session_id = str(kwargs["session_id"])
    with _native_actor(str(kwargs["agent"]), session_id):
        return session_lifecycle.resume_session(**kwargs)


def _heartbeat_session_as_native(**kwargs: object) -> dict[str, object]:
    session_id = str(kwargs["session_id"])
    with _native_actor(str(kwargs["agent"]), session_id):
        return session_lifecycle.heartbeat_session(**kwargs)


def _finish_session_as_owner(**kwargs: object) -> dict[str, object]:
    return _owner_bound_call(session_lifecycle.finish_session, **kwargs)


def _close_session_as_owner(**kwargs: object) -> dict[str, object]:
    return _owner_bound_call(session_lifecycle.close_session, **kwargs)


def _handoff_session_as_owner(**kwargs: object) -> dict[str, object]:
    return _owner_bound_call(session_lifecycle.handoff_session, **kwargs)


def _abandon_session_as_owner(**kwargs: object) -> dict[str, object]:
    return _owner_bound_call(session_lifecycle.abandon_session, **kwargs)


def test_session_narrow_json_deny_narrow_admit_journey(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The public CLI performs one native-session-bound exact narrowing."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "docs").mkdir()
    (repo / "docs" / "plan.md").write_text("plan\n", encoding="utf-8")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "owner")
    monkeypatch.setattr(
        session_lifecycle,
        "_poll_mailbox",
        lambda **_kwargs: {"summary": "coordination mailbox: no active messages", "messages": []},
    )
    now = datetime.now(timezone.utc)
    claim_path = claims_dir / coordination_claims._claim_filename("codex", "demo", "broad")
    claim_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 6,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["demo"],
                "scope": "broad",
                "intent": "narrow docs ownership",
                "claim_type": "write",
                "write_paths": ["docs"],
                "read_paths": [],
                "worktree_path": str(repo),
                "repo_root": str(repo),
                "branch": "main",
                "session_name": "broad",
                "broader_goal": "remove false serialization",
                "tracker_path": str(tmp_path / "tracker.yaml"),
                "session_id": "codex:owner",
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
                "plan_ref": "UNPLANNED",
                "broad_scope_mode": "bounded",
                "broad_scope_reason": "the fixture owns the full docs tree",
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    prewrite_claim_projection.write_projection(claims_dir=claims_dir)
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "session_narrow.py"
    spec = importlib.util.spec_from_file_location("session_narrow_cli_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    exit_code = module.main(
        [
            "--agent",
            "codex",
            "--project",
            "demo",
            "--scope",
            "broad",
            "--write-path",
            "docs/plan.md",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["action"] == "narrowed"
    assert payload["old_write_paths"] == ["docs"]
    assert payload["new_write_paths"] == ["docs/plan.md"]
    assert yaml.safe_load(claim_path.read_text(encoding="utf-8"))["write_paths"] == ["docs/plan.md"]


@pytest.mark.parametrize(
    ("binding_arguments", "expected_error"),
    [
        (["--start-revision", "a" * 40], "does not support revision custody"),
        (
            ["--plan-repo-root", "/tmp/project-meta", "--plan-start-point", "b" * 40],
            "does not support external plan-authority custody",
        ),
        (["--plan-start-point", "b" * 40], "does not support external plan-authority custody"),
    ],
)
def test_session_start_wrapper_rejects_stale_lifecycle_revision_contract(
    monkeypatch: pytest.MonkeyPatch,
    binding_arguments: list[str],
    expected_error: str,
) -> None:
    """A new wrapper must not silently discard custody when installed support is stale."""

    module_path = Path(__file__).resolve().parents[1] / "scripts" / "session_start.py"
    spec = importlib.util.spec_from_file_location("session_start_revision_contract_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    args = module.parse_args(
        [
            "--agent",
            "codex",
            "--project",
            "demo",
            "--scope",
            "lane",
            "--intent",
            "test stale support",
            "--repo-root",
            "/tmp/demo",
            "--worktree-path",
            "/tmp/demo/worktrees/lane",
            "--branch",
            "lane",
            "--broader-goal",
            "Test stale support",
            "--current-phase",
            "fixture",
            *binding_arguments,
        ]
    )
    monkeypatch.setattr(module.inspect, "signature", lambda _callable: SimpleNamespace(parameters={}))

    with pytest.raises(RuntimeError, match=expected_error):
        module._supported_start_kwargs(args)


def test_cross_repository_session_retains_plan_custody_and_rejects_rebinding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Activation and refresh preserve the external plan independently of the target."""

    from enforced_planning import plan_validation

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    target_root = tmp_path / "aes"
    plan_root = tmp_path / "project-meta"
    target_root.mkdir()
    plan_root.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    for root in (target_root, plan_root):
        _git(root, "init", "-b", "main")
        _git(root, "config", "user.email", "tests@example.com")
        _git(root, "config", "user.name", "Test User")
        (root / "README.md").write_text("seed\n", encoding="utf-8")
        _git(root, "add", ".")
        _git(root, "commit", "-m", "seed")
    plan_revision = _git(plan_root, "rev-parse", "HEAD")
    plan_sha256 = "d" * 64
    graph_path = "docs/plans/249_cross_repository_work_graph.json"
    (target_root / graph_path).parent.mkdir(parents=True)
    (target_root / graph_path).write_text(
        json.dumps(
            {
                "units": [
                    {
                        "id": "P249-AES01",
                        "design_revision": f"sha256:{plan_sha256}",
                        "status": "ready",
                        "readiness": {"status": "ready", "required_approval_types": [], "approvals": []},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _git(target_root, "add", ".")
    _git(target_root, "commit", "-m", "target graph")
    target_revision = _git(target_root, "rev-parse", "HEAD")
    worktree = target_root / "worktrees" / "plan249-aes01"
    _git(target_root, "worktree", "add", "-b", "plan249-aes01", str(worktree), target_revision)

    def _validate(**kwargs):
        assert kwargs["repo_root"] == plan_root.resolve()
        return SimpleNamespace(
            mode="enforce",
            disposition="pass",
            findings=[],
            source_revision=kwargs["start_point"],
            plan_sha256=plan_sha256,
        )

    monkeypatch.setattr(plan_validation, "validate_plan_integrity_at_revision", _validate)
    claim_kwargs = {
        "agent": "codex",
        "project": "aes",
        "scope": "plan249-aes01",
        "intent": "implement the external plan vertical",
        "repo_root": str(target_root),
        "worktree_path": str(worktree),
        "branch": "plan249-aes01",
        "broader_goal": "Implement External Plan Vertical",
        "plan_ref": "project-meta#249",
        "session_id": "codex:cross-repo-owner",
        "claim_type": "write",
        "write_paths": ["src/aes"],
        "work_graph_path": graph_path,
        "work_unit_id": "P249-AES01",
    }
    created, _message = coordination_claims.create_claim(
        **claim_kwargs,
        session_name="implement-external-plan-vertical",
        start_point=target_revision,
        plan_repo_root=str(plan_root),
        plan_start_point=plan_revision,
    )
    assert created
    claim_path = claims_dir / "codex_aes_plan249-aes01.yaml"
    reservation = coordination_claims.normalize_claim(
        yaml.safe_load(claim_path.read_text(encoding="utf-8")),
        source_file=str(claim_path),
    )
    assert reservation is not None
    pending = outcome_admission.evaluate_selection_pending_session_activation(reservation)
    assert pending.disposition == "defer"
    assert pending.reason_code == "selection_pending"
    started = session_lifecycle.start_session(
        **claim_kwargs,
        current_phase="activate exact external authority",
        start_revision=target_revision,
        plan_repo_root=str(plan_root),
        plan_start_point=plan_revision,
        tracker_dir=trackers_dir,
    )
    tracker_path = Path(started["tracker_path"])
    tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert tracker["schema_version"] == 3
    assert tracker["claim"]["start_revision"] == target_revision
    assert tracker["claim"]["plan_repo_root"] == str(plan_root.resolve())
    assert tracker["claim"]["plan_revision"] == plan_revision
    assert tracker["claim"]["plan_sha256"] == plan_sha256

    session_lifecycle.start_session(
        **claim_kwargs,
        current_phase="refresh without repeating retained authority",
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_aes_plan249-aes01.yaml"
    before_claim = claim_path.read_bytes()
    before_tracker = tracker_path.read_bytes()
    (plan_root / "README.md").write_text("later plan repository revision\n", encoding="utf-8")
    _git(plan_root, "commit", "-am", "later authority revision")
    with pytest.raises(ValueError, match="different plan revision"):
        session_lifecycle.start_session(
            **claim_kwargs,
            current_phase="attempt authority rebinding",
            plan_repo_root=str(plan_root),
            plan_start_point=_git(plan_root, "rev-parse", "HEAD"),
            tracker_dir=trackers_dir,
        )
    assert claim_path.read_bytes() == before_claim
    assert tracker_path.read_bytes() == before_tracker


def test_session_start_preserves_existing_revision_custody_and_rolls_back_mismatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The claim-to-tracker handoff retains A and cannot be refreshed to caller-supplied B."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "revision-lane"
    repo_root.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "tests@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "docs/plans").mkdir(parents=True)
    (repo_root / "meta-process.yaml").write_text(
        'meta_process:\n  plans:\n    integrity:\n      mode: "off"\n',
        encoding="utf-8",
    )
    graph_path = repo_root / "docs/plans/1_revision_work_graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "id": "revision-lane",
                        "status": "ready",
                        "readiness": {
                            "status": "ready",
                            "required_approval_types": [],
                            "approvals": [],
                            "failed_guards": [],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "revision-bound plan")
    revision_a = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "worktree", "add", "-b", "revision-lane", str(worktree), revision_a)

    created, _message = coordination_claims.create_claim(
        agent="codex",
        project="demo",
        scope="revision-lane",
        intent="retain one exact lane revision",
        plan_ref="demo#1",
        claim_type="write",
        write_paths=["src/feature.py"],
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="revision-lane",
        session_id="codex:revision-owner",
        session_name="retain-one-revision",
        broader_goal="Retain One Revision",
        work_graph_path="docs/plans/1_revision_work_graph.json",
        work_unit_id="revision-lane",
        start_point=revision_a,
    )
    assert created

    started = session_lifecycle.start_session(
        agent="codex",
        project="demo",
        scope="revision-lane",
        intent="retain one exact lane revision",
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="revision-lane",
        broader_goal="Retain One Revision",
        current_phase="bind tracker",
        plan_ref="demo#1",
        session_id="codex:revision-owner",
        claim_type="write",
        write_paths=["src/feature.py"],
        work_graph_path="docs/plans/1_revision_work_graph.json",
        work_unit_id="revision-lane",
        start_revision=revision_a,
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_demo_revision-lane.yaml"
    tracker_path = Path(started["tracker_path"])
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    tracker_payload = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert claim_payload["schema_version"] == 6
    assert "broad_scope_mode" not in claim_payload
    assert claim_payload["start_revision"] == revision_a
    assert tracker_payload["schema_version"] == 2
    assert tracker_payload["claim"]["start_revision"] == revision_a
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()

    with pytest.raises(ValueError, match="retains start revision"):
        session_lifecycle.start_session(
            agent="codex",
            project="demo",
            scope="revision-lane",
            intent="attempt revision drift",
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="revision-lane",
            broader_goal="Retain One Revision",
            current_phase="attempt drift",
            plan_ref="demo#1",
            session_id="codex:revision-owner",
            claim_type="write",
            write_paths=["src/feature.py"],
            work_graph_path="docs/plans/1_revision_work_graph.json",
            work_unit_id="revision-lane",
            start_revision="b" * 40,
            tracker_dir=trackers_dir,
        )

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before


def _prepare_selection_pending_reservation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Path, Path, Path, Path, str]:
    """Create one exact v4 claim whose only health gap is its first tracker."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "staged-lane"
    repo_root.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(
        coordination_claims,
        "validate_native_session_binding",
        lambda _agent, _session_id, **_kwargs: None,
    )
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "tests@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "docs/plans").mkdir(parents=True)
    (repo_root / "meta-process.yaml").write_text(
        """meta_process:
  plans:
    integrity:
      mode: "off"
  claims:
    outcome_admission_mode: enforce_selected
""",
        encoding="utf-8",
    )
    graph_path = repo_root / "docs/plans/1_staged_work_graph.json"
    graph_path.write_text(
        json.dumps(
            {
                "units": [
                    {
                        "id": "staged-lane",
                        "status": "ready",
                        "readiness": {
                            "status": "ready",
                            "required_approval_types": [],
                            "approvals": [],
                            "failed_guards": [],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "staged reservation")
    revision = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "worktree", "add", "-b", "staged-lane", str(worktree), revision)

    created, _message = coordination_claims.create_claim(
        agent="codex",
        project="demo",
        scope="staged-lane",
        intent="activate one exact staged reservation",
        plan_ref="demo#1",
        claim_type="write",
        write_paths=["src/feature.py"],
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="staged-lane",
        session_id="codex:staged-owner",
        # The claim CLI receives the human-readable goal from the canonical
        # Make path; session start omits --session-name and derives the slug.
        session_name="Prove Staged Activation",
        broader_goal="Prove Staged Activation",
        work_graph_path="docs/plans/1_staged_work_graph.json",
        work_unit_id="staged-lane",
        start_point=revision,
    )
    assert created
    claim_path = claims_dir / "codex_demo_staged-lane.yaml"
    return repo_root, worktree, claim_path, trackers_dir, revision


def test_configured_session_start_defers_only_tracker_creation_until_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid v4 reservation gets a tracker, but no selected-outcome allow."""

    repo_root, worktree, claim_path, trackers_dir, revision = _prepare_selection_pending_reservation(
        tmp_path,
        monkeypatch,
    )
    receipt_path = tmp_path / "outcome-admission.jsonl"
    started = session_lifecycle.start_session(
        agent="codex",
        project="demo",
        scope="staged-lane",
        intent="activate one exact staged reservation",
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="staged-lane",
        broader_goal="Prove Staged Activation",
        current_phase="selection pending",
        plan_ref="demo#1",
        session_id="codex:staged-owner",
        claim_type="write",
        write_paths=["src/feature.py"],
        work_graph_path="docs/plans/1_staged_work_graph.json",
        work_unit_id="staged-lane",
        start_revision=revision,
        tracker_dir=trackers_dir,
        outcome_admission_receipt_path=receipt_path,
    )

    pending_receipt_path = outcome_admission.selection_pending_activation_receipt_path(receipt_path)
    [activation_receipt] = outcome_admission.load_selection_pending_activation_receipts(pending_receipt_path)
    assert activation_receipt.result.disposition == "defer"
    assert activation_receipt.result.reason_code == "selection_pending"
    assert activation_receipt.result.evidence is not None
    assert not receipt_path.exists()
    tracker_path = Path(started["tracker_path"])
    assert tracker_path.is_file()
    assert yaml.safe_load(claim_path.read_text(encoding="utf-8"))["session_name"] == ("prove-staged-activation")
    claim_after_start = claim_path.read_bytes()
    tracker_after_start = tracker_path.read_bytes()

    selected_prewrite = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parents[1] / "scripts" / "outcome_admission.py"),
            "selected",
            "--agent",
            "codex",
            "--project",
            "demo",
            "--scope",
            "staged-lane",
            "--session-id",
            "codex:staged-owner",
            "--boundary",
            "prewrite",
            "--target-path",
            "src/feature.py",
            "--claims-dir",
            str(claim_path.parent),
            "--receipt-path",
            str(receipt_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=False,
        capture_output=True,
        text=True,
    )
    assert selected_prewrite.returncode == 2
    prewrite_payload = json.loads(selected_prewrite.stdout)
    assert prewrite_payload["decision"]["reason_code"] == "outcome_selection_required"
    assert prewrite_payload["resolution_error_code"] == "selection_missing"

    with pytest.raises(PermissionError, match="outcome_selection_required"):
        _heartbeat_session_as_native(
            agent="codex",
            project="demo",
            scope="staged-lane",
            branch="staged-lane",
            session_id="codex:staged-owner",
            tracker_dir=trackers_dir,
            outcome_selected=True,
            outcome_admission_receipt_path=receipt_path,
        )

    assert claim_path.read_bytes() == claim_after_start
    assert tracker_path.read_bytes() == tracker_after_start
    receipts = outcome_admission.load_outcome_admission_receipts(receipt_path)
    assert receipts[-1].result.resolution_error_code == "selection_missing"


@pytest.mark.parametrize(
    ("corruption", "expected_error"),
    [
        ("self_attested_graph_digest", "selection_pending_binding_mismatch"),
        ("sha256_shaped_git_revision", "selection_pending_start_revision_invalid"),
        ("trackerless_schema_v3", "selection_pending_claim_version_invalid"),
    ],
)
def test_selection_pending_corruption_leaves_zero_tracker_or_claim_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    expected_error: str,
) -> None:
    """Staged activation must prove its injected defect reached the real gate."""

    repo_root, worktree, claim_path, trackers_dir, revision = _prepare_selection_pending_reservation(
        tmp_path,
        monkeypatch,
    )
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    if corruption == "self_attested_graph_digest":
        claim_payload["work_graph_sha256"] = "f" * 64
    elif corruption == "sha256_shaped_git_revision":
        claim_payload["start_revision"] = "e" * 64
    else:
        claim_payload["schema_version"] = 3
    claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")
    claim_before = claim_path.read_bytes()
    receipt_path = tmp_path / "outcome-admission.jsonl"

    with pytest.raises(PermissionError, match="outcome_admission_state_invalid"):
        session_lifecycle.start_session(
            agent="codex",
            project="demo",
            scope="staged-lane",
            intent="activate one exact staged reservation",
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="staged-lane",
            broader_goal="Prove Staged Activation",
            current_phase="selection pending",
            plan_ref="demo#1",
            session_id="codex:staged-owner",
            claim_type="write",
            write_paths=["src/feature.py"],
            work_graph_path="docs/plans/1_staged_work_graph.json",
            work_unit_id="staged-lane",
            start_revision=revision,
            tracker_dir=trackers_dir,
            outcome_admission_receipt_path=receipt_path,
        )

    assert claim_path.read_bytes() == claim_before
    assert not trackers_dir.exists()
    pending_receipt_path = outcome_admission.selection_pending_activation_receipt_path(receipt_path)
    [receipt] = outcome_admission.load_selection_pending_activation_receipts(pending_receipt_path)
    assert receipt.result.resolution_error_code == expected_error


def test_selection_pending_rejects_caller_scope_smuggling_before_tracker_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tracker handoff cannot replace claim scope and acquire bootstrap authority."""

    repo_root, worktree, claim_path, trackers_dir, revision = _prepare_selection_pending_reservation(
        tmp_path,
        monkeypatch,
    )
    claim_before = claim_path.read_bytes()
    receipt_path = tmp_path / "outcome-admission.jsonl"

    with pytest.raises(ValueError, match="caller changed: write_paths"):
        session_lifecycle.start_session(
            agent="codex",
            project="demo",
            scope="staged-lane",
            intent="activate one exact staged reservation",
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="staged-lane",
            broader_goal="Prove Staged Activation",
            current_phase="selection pending",
            plan_ref="demo#1",
            session_id="codex:staged-owner",
            claim_type="write",
            write_paths=["docs/plans/999_unrelated.md"],
            work_graph_path="docs/plans/1_staged_work_graph.json",
            work_unit_id="staged-lane",
            start_revision=revision,
            tracker_dir=trackers_dir,
            outcome_admission_receipt_path=receipt_path,
        )

    assert claim_path.read_bytes() == claim_before
    assert not trackers_dir.exists()
    assert not receipt_path.exists()
    assert not outcome_admission.selection_pending_activation_receipt_path(receipt_path).exists()
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim = coordination_claims.normalize_claim(claim_payload, source_file=str(claim_path))
    assert claim is not None
    assert (
        outcome_admission.evaluate_claim_bootstrap_admission(
            claim,
            target_path="docs/plans/999_unrelated.md",
        )
        is None
    )


def test_selection_pending_compare_and_swap_rejects_claim_change_before_link(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A claim change after evaluation cannot inherit the staged receipt."""

    repo_root, worktree, claim_path, trackers_dir, revision = _prepare_selection_pending_reservation(
        tmp_path,
        monkeypatch,
    )
    original_write_tracker = session_lifecycle.session_contracts.write_session_tracker

    def write_tracker_then_change_claim(*args: object, **kwargs: object) -> Path:
        tracker_path = original_write_tracker(*args, **kwargs)
        claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        claim_payload["intent"] = "injected concurrent claim change"
        claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")
        assert yaml.safe_load(claim_path.read_text(encoding="utf-8"))["intent"] == ("injected concurrent claim change")
        return tracker_path

    monkeypatch.setattr(
        session_lifecycle.session_contracts,
        "write_session_tracker",
        write_tracker_then_change_claim,
    )
    receipt_path = tmp_path / "outcome-admission.jsonl"

    with pytest.raises(ValueError, match="changed after selection-pending validation"):
        session_lifecycle.start_session(
            agent="codex",
            project="demo",
            scope="staged-lane",
            intent="activate one exact staged reservation",
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="staged-lane",
            broader_goal="Prove Staged Activation",
            current_phase="selection pending",
            plan_ref="demo#1",
            session_id="codex:staged-owner",
            claim_type="write",
            write_paths=["src/feature.py"],
            work_graph_path="docs/plans/1_staged_work_graph.json",
            work_unit_id="staged-lane",
            start_revision=revision,
            tracker_dir=trackers_dir,
            outcome_admission_receipt_path=receipt_path,
        )

    assert not list(trackers_dir.glob("*.yaml"))
    changed_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert changed_claim["intent"] == "injected concurrent claim change"


def test_session_start_does_not_invent_revision_custody_for_running_legacy_claim(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A v3 claim with a tracker is historical evidence, not an upgradeable reservation."""

    claims_dir = tmp_path / "claims"
    repo_root = tmp_path / "repo"
    worktree = repo_root / "worktrees" / "legacy-running-lane"
    repo_root.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "tests@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "docs/plans").mkdir(parents=True)
    (repo_root / "meta-process.yaml").write_text(
        'meta_process:\n  plans:\n    integrity:\n      mode: "off"\n',
        encoding="utf-8",
    )
    (repo_root / "docs/plans/1_revision_work_graph.json").write_text(
        json.dumps(
            {
                "units": [
                    {
                        "id": "legacy-running-lane",
                        "status": "ready",
                        "readiness": {
                            "status": "ready",
                            "required_approval_types": [],
                            "approvals": [],
                            "failed_guards": [],
                        },
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    _git(repo_root, "add", ".")
    _git(repo_root, "commit", "-m", "legacy revision-bound plan")
    revision = _git(repo_root, "rev-parse", "HEAD")
    _git(repo_root, "worktree", "add", "-b", "legacy-running-lane", str(worktree), revision)

    created, _message = coordination_claims.create_claim(
        agent="codex",
        project="demo",
        scope="legacy-running-lane",
        intent="represent an already-running legacy lane",
        plan_ref="demo#1",
        claim_type="write",
        write_paths=["src/feature.py"],
        repo_root=str(repo_root),
        worktree_path=str(worktree),
        branch="legacy-running-lane",
        session_id="codex:legacy-owner",
        session_name="legacy-running-lane",
        broader_goal="Preserve Historical Claim Truth",
        tracker_path=str(tmp_path / "sessions" / "legacy.yaml"),
        work_graph_path="docs/plans/1_revision_work_graph.json",
        work_unit_id="legacy-running-lane",
        start_point=revision,
    )
    assert created
    claim_path = claims_dir / "codex_demo_legacy-running-lane.yaml"
    legacy_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    legacy_payload["schema_version"] = 3
    legacy_payload.pop("start_revision")
    claim_path.write_text(yaml.safe_dump(legacy_payload, sort_keys=False), encoding="utf-8")
    claim_before = claim_path.read_bytes()

    with pytest.raises(ValueError, match="refusing to invent historical revision custody"):
        session_lifecycle._upsert_session_claim(
            agent="codex",
            project="demo",
            scope="legacy-running-lane",
            intent="attempt an unsupported historical upgrade",
            plan_ref="demo#1",
            repo_root=str(repo_root),
            worktree_path=str(worktree),
            branch="legacy-running-lane",
            session_id="codex:legacy-owner",
            broader_goal="Preserve Historical Claim Truth",
            session_name="legacy-running-lane",
            tracker_path=str(tmp_path / "sessions" / "legacy.yaml"),
            claim_type="write",
            write_paths=["src/feature.py"],
            work_graph_path="docs/plans/1_revision_work_graph.json",
            work_unit_id="legacy-running-lane",
            start_revision=revision,
        )

    assert claim_path.read_bytes() == claim_before


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
            recipient=coordination_messages.ExactSessionSelector(kind="session", session_id=recipient_session_id),
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
    assert loaded_claim.progress_kind == "claim_started"
    assert loaded_claim.evidence_ref == "Plan #31"
    assert loaded_claim.next_action == "implement session lifecycle CLI and governed repo enforcement"
    assert Path(payload["tracker_path"]).exists()
    assert payload["plan_ref"] == "Plan #31"


def test_status_sessions_exposes_stalled_progress_with_one_frozen_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session JSON reports exact stalled evidence and the bounded recovery action."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="plan-110-progress-status",
        intent="Expose stalled progress",
        repo_root=str(tmp_path / "repo"),
        worktree_path=str(worktree),
        branch="plan-110-progress-status",
        broader_goal="Progress Lease",
        current_phase="status evidence",
        plan_ref="Plan #110",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_enforced-planning_plan-110-progress-status.yaml"
    claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim.update(
        {
            "heartbeat_at": "2026-08-21T09:59:00+00:00",
            "progress_at": "2026-08-21T08:00:00+00:00",
            "progress_kind": "integration_result",
            "evidence_ref": "receipt:integration-7",
            "next_action": "record progress or hand off the lane",
        }
    )
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    observed_at = datetime.fromisoformat("2026-08-21T10:00:00+00:00")

    payload = session_lifecycle.status_sessions(
        project="enforced-planning",
        scope="plan-110-progress-status",
        now=observed_at,
    )
    session = payload["sessions"][0]

    assert payload["observed_at"] == observed_at.isoformat()
    assert session["health_status"] == "stalled"
    assert session["progress_issues"] == ["stalled_progress_lease"]
    assert session["progress_kind"] == "integration_result"
    assert session["evidence_ref"] == "receipt:integration-7"
    assert session["next_action"] == "record progress or hand off the lane"
    assert session["recovery_action"] == "record_progress_or_handoff"


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
    claim_path = claims_dir / "codex_enforced-planning_plan-108-upsert-receipt.yaml"
    progress_before = {
        field: yaml.safe_load(claim_path.read_text(encoding="utf-8")).get(field)
        for field in coordination_claims.PROGRESS_FIELD_NAMES
    }
    refreshed = session_lifecycle.start_session(current_phase="refreshed", **common)
    refreshed_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))

    records = claim_mutation_receipts.load_receipts()
    upserts = [record for record in records if record.operation == "session_upsert"]
    assert len(upserts) == 1
    receipt = upserts[0]
    assert receipt.target_project == "enforced-planning"
    assert receipt.target_scope == "plan-108-upsert-receipt"
    assert receipt.registry_digest_after == receipt.projection_digest_after
    assert receipt.projection_current_after is True
    assert refreshed["action"] == "updated"
    assert {field: refreshed_claim.get(field) for field in coordination_claims.PROGRESS_FIELD_NAMES} == progress_before


def _maintenance_refresh_args(tmp_path: Path, trackers_dir: Path) -> dict[str, object]:
    branch = "fix/maintenance-provenance-refresh"
    goal = "Unplanned maintenance: fix maintenance provenance refresh"
    worktree = tmp_path / "repo" / "worktrees" / branch
    worktree.mkdir(parents=True)
    return {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": branch,
        "intent": goal,
        "repo_root": str(tmp_path / "repo"),
        "worktree_path": str(worktree),
        "branch": branch,
        "broader_goal": goal,
        "current_phase": "maintenance-bootstrap",
        "plan_ref": None,
        "session_id": "codex:maintenance-owner",
        "session_name": session_contracts.derive_session_name(goal),
        "claim_type": "program",
        "write_paths": ["enforced_planning/session_lifecycle.py", "tests/test_session_cli.py"],
        "read_paths": [],
        "tracker_dir": trackers_dir,
        "allow_unplanned": True,
    }


def _delegated_session_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, object], Path, Path]:
    """Create one healthy parent and pristine child Git lane."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "seed")
    _git(repo, "switch", "-c", "weekly-parent")
    (repo / "parent.txt").write_text("parent\n", encoding="utf-8")
    _git(repo, "add", "parent.txt")
    _git(repo, "commit", "-m", "parent lane")
    child_worktree = tmp_path / "child-worktree"
    _git(repo, "worktree", "add", "-b", "fix/delegated-child", str(child_worktree), "HEAD")
    (child_worktree / "enforced_planning").mkdir()
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "trackers"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setenv("CODEX_THREAD_ID", "parent-native")
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="weekly-parent",
        intent="Coordinate the weekly implementation",
        repo_root=str(repo),
        worktree_path=str(repo),
        branch="weekly-parent",
        broader_goal="Coordinate the weekly implementation",
        current_phase="delegating one bounded child",
        session_id="codex:parent-native",
        claim_type="program",
        tracker_dir=trackers_dir,
        allow_unplanned=True,
    )
    goal = "Delegated maintenance: fix delegated child"
    start_revision = _git(child_worktree, "rev-parse", "HEAD")
    args: dict[str, object] = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "fix/delegated-child",
        "intent": goal,
        "repo_root": str(repo),
        "worktree_path": str(child_worktree),
        "branch": "fix/delegated-child",
        "broader_goal": goal,
        "current_phase": "implement delegated lifecycle test",
        "parent_scope": "weekly-parent",
        "parent_session_id": "codex:parent-native",
        "child_session_id": "codex:child-native",
        "start_revision": start_revision,
        "write_paths": ["enforced_planning/delegated.py"],
        "tracker_dir": trackers_dir,
    }
    return args, claims_dir, child_worktree


def test_parent_can_create_and_revoke_one_pristine_delegated_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The parent acts as itself while the child receives and loses custody."""

    args, claims_dir, child_worktree = _delegated_session_fixture(tmp_path, monkeypatch)
    started = session_lifecycle.start_delegated_session(**args)
    assert started["action"] == "delegated_created"
    child_claim = session_lifecycle._single_matching_live_claim(
        agent="codex",
        project="enforced-planning",
        scope="fix/delegated-child",
    )
    assert child_claim.session_id == "codex:child-native"
    assert child_claim.parent_scope == "weekly-parent"
    assert outcome_admission.is_sanctioned_delegated_maintenance_claim(child_claim)

    revoked = session_lifecycle.revoke_delegated_session(
        agent="codex",
        project="enforced-planning",
        scope="fix/delegated-child",
        repo_root=str(args["repo_root"]),
        worktree_path=str(args["worktree_path"]),
        branch=str(args["branch"]),
        parent_scope="weekly-parent",
        parent_session_id="codex:parent-native",
        child_session_id="codex:child-native",
        expected_start_revision=str(args["start_revision"]),
        tracker_path=str(started["tracker_path"]),
    )
    assert revoked["action"] == "delegated_revoked"
    assert revoked["canonical_lock_reconciliation_required"] is True
    assert not child_worktree.exists()
    assert not (claims_dir / coordination_claims._claim_filename("codex", "enforced-planning", "fix/delegated-child")).exists()
    parent = session_lifecycle._single_matching_live_claim(
        agent="codex",
        project="enforced-planning",
        scope="weekly-parent",
    )
    assert parent.session_id == "codex:parent-native"
    archived = _archived_claim_payload(str(revoked["claim_archive_id"]))
    assert archived["disposition"] == "superseded"
    assert archived["disposition_reason"] == "unused delegated child cancelled"


def test_delegated_start_rejects_a_non_native_parent_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, claims_dir, _child_worktree = _delegated_session_fixture(tmp_path, monkeypatch)
    args["parent_session_id"] = "codex:someone-else"
    with pytest.raises(ValueError, match="does not match the current codex runtime"):
        session_lifecycle.start_delegated_session(**args)
    assert not (claims_dir / coordination_claims._claim_filename("codex", "enforced-planning", "fix/delegated-child")).exists()


def test_delegated_start_rolls_back_claim_projection_and_tracker_on_audit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, claims_dir, _child_worktree = _delegated_session_fixture(tmp_path, monkeypatch)
    from enforced_planning.prewrite_claim_fast import projection_path_for

    projection_path = projection_path_for(claims_dir)
    projection_before = projection_path.read_bytes()
    child_claim_path = claims_dir / coordination_claims._claim_filename(
        "codex", "enforced-planning", "fix/delegated-child"
    )
    contract = session_contracts.SessionContract.build(
        agent="codex",
        project="enforced-planning",
        scope="fix/delegated-child",
        intent=str(args["intent"]),
        plan_ref=session_contracts.UNPLANNED_PLAN_REF,
        repo_root=str(args["repo_root"]),
        worktree_path=str(args["worktree_path"]),
        branch=str(args["branch"]),
        session_id="codex:child-native",
        broader_goal=str(args["broader_goal"]),
        start_revision=str(args["start_revision"]),
        allow_unplanned=True,
    )
    tracker_path = session_contracts.session_tracker_path(
        contract,
        tracker_dir=args["tracker_dir"],
    ).expanduser().resolve()

    def fail_audit(**_kwargs: object) -> object:
        raise OSError("injected delegated audit failure")

    monkeypatch.setattr(coordination_claims, "record_claim_mutation", fail_audit)
    with pytest.raises(OSError, match="injected delegated audit failure"):
        session_lifecycle.start_delegated_session(**args)
    assert not child_claim_path.exists()
    assert not tracker_path.exists()
    assert projection_path.read_bytes() == projection_before


def test_delegated_revoke_rejects_dirty_child_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, claims_dir, child_worktree = _delegated_session_fixture(tmp_path, monkeypatch)
    started = session_lifecycle.start_delegated_session(**args)
    (child_worktree / "dirty.txt").write_text("dirty\n", encoding="utf-8")
    child_claim_path = claims_dir / coordination_claims._claim_filename(
        "codex", "enforced-planning", "fix/delegated-child"
    )
    claim_before = child_claim_path.read_bytes()
    with pytest.raises(ValueError, match="worktree is dirty"):
        session_lifecycle.revoke_delegated_session(
            agent="codex",
            project="enforced-planning",
            scope="fix/delegated-child",
            repo_root=str(args["repo_root"]),
            worktree_path=str(args["worktree_path"]),
            branch=str(args["branch"]),
            parent_scope="weekly-parent",
            parent_session_id="codex:parent-native",
            child_session_id="codex:child-native",
            expected_start_revision=str(args["start_revision"]),
            tracker_path=str(started["tracker_path"]),
        )
    assert child_claim_path.read_bytes() == claim_before


def test_delegated_revoke_retries_exact_completed_child_after_archive_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    args, claims_dir, child_worktree = _delegated_session_fixture(tmp_path, monkeypatch)
    started = session_lifecycle.start_delegated_session(**args)
    real_archive = coordination_claims._archive_completed_claim_locked
    attempts = 0

    def fail_first_archive(*archive_args: object, **archive_kwargs: object):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise OSError("injected delegated archive failure")
        return real_archive(*archive_args, **archive_kwargs)

    monkeypatch.setattr(
        coordination_claims,
        "_archive_completed_claim_locked",
        fail_first_archive,
    )
    revoke_args = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "fix/delegated-child",
        "repo_root": str(args["repo_root"]),
        "worktree_path": str(args["worktree_path"]),
        "branch": str(args["branch"]),
        "parent_scope": "weekly-parent",
        "parent_session_id": "codex:parent-native",
        "child_session_id": "codex:child-native",
        "expected_start_revision": str(args["start_revision"]),
        "tracker_path": str(started["tracker_path"]),
    }
    with pytest.raises(OSError, match="injected delegated archive failure"):
        session_lifecycle.revoke_delegated_session(**revoke_args)
    child_claim_path = claims_dir / coordination_claims._claim_filename(
        "codex", "enforced-planning", "fix/delegated-child"
    )
    stranded = yaml.safe_load(child_claim_path.read_text(encoding="utf-8"))
    assert stranded["status"] == "completed"
    assert not child_worktree.exists()

    retried = session_lifecycle.revoke_delegated_session(**revoke_args)
    assert retried["action"] == "delegated_revoked"
    assert attempts == 2
    assert not child_claim_path.exists()


def test_sanctioned_maintenance_start_refresh_preserves_bootstrap_provenance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An exact owner refresh may move liveness and phase, never maintenance identity."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    claim_before = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    tracker_before = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))

    refreshed = session_lifecycle.start_session(**{**common, "current_phase": "focused regression tests"})
    claim_after = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    tracker_after = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))

    assert refreshed["action"] == "updated"
    assert outcome_admission.is_sanctioned_maintenance_claim(
        session_lifecycle._single_matching_live_claim(
            agent="codex", project="enforced-planning", scope=str(common["scope"])
        )
    )
    assert tracker_after["claim"] == tracker_before["claim"]
    assert tracker_after["tracker"]["current_phase"] == "focused regression tests"
    immutable_claim_fields = set(tracker_before["claim"]) | {
        "claim_type",
        "write_paths",
        "read_paths",
        "parent_scope",
        "work_graph_path",
        "work_unit_id",
        "start_revision",
        "plan_repo_root",
        "plan_revision",
        "plan_sha256",
    }
    assert {field: claim_after.get(field) for field in immutable_claim_fields} == {
        field: claim_before.get(field) for field in immutable_claim_fields
    }


def test_broad_maintenance_refresh_preserves_omitted_bootstrap_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ordinary refresh omission retains the broad bootstrap's typed custody."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    target_worktree = str(common["worktree_path"])
    bootstrap_reason = "construct this maintenance lane, then narrow before its first repository write"
    bootstrap = {
        **common,
        "write_paths": ["."],
        "broad_scope_mode": "bootstrap",
        "broad_scope_reason": bootstrap_reason,
        "target_worktree_path": target_worktree,
    }
    started = session_lifecycle.start_session(**bootstrap)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    tracker_claim_before = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))["claim"]
    assert outcome_admission.is_sanctioned_maintenance_claim(
        session_lifecycle._single_matching_live_claim(
            agent="codex", project="enforced-planning", scope=str(common["scope"])
        )
    )

    ordinary_refresh = {
        key: value
        for key, value in common.items()
        if key not in {"claim_type", "write_paths", "read_paths"}
    }
    refreshed = session_lifecycle.start_session(
        **{**ordinary_refresh, "current_phase": "narrowing maintenance custody"}
    )
    claim_after = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    tracker_after = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))

    assert refreshed["action"] == "updated"
    assert claim_after["write_paths"] == ["."]
    assert claim_after["broad_scope_mode"] == "bootstrap"
    assert claim_after["broad_scope_reason"] == bootstrap_reason
    assert claim_after["target_worktree_path"] == target_worktree
    assert tracker_after["claim"] == tracker_claim_before
    assert tracker_after["tracker"]["current_phase"] == "narrowing maintenance custody"
    assert outcome_admission.is_sanctioned_maintenance_claim(
        session_lifecycle._single_matching_live_claim(
            agent="codex", project="enforced-planning", scope=str(common["scope"])
        )
    )


def test_maintenance_cli_omission_preserves_tracker_contract_and_explicit_api_drift_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI omission is distinct from an explicit API request to replace tracker state."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    tracker_contract = {
        "intended_next_phases": ["integration", "closeout"],
        "depends_on_repos": ["project-meta"],
        "requires_shared_infra_changes": True,
        "stop_conditions": ["authority changes"],
        "notes": "retain exact maintenance context",
    }
    started = session_lifecycle.start_session(**{**common, **tracker_contract})
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])

    module_path = Path(__file__).resolve().parents[1] / "scripts" / "session_start.py"
    spec = importlib.util.spec_from_file_location("session_start_omission_contract_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    args = module.parse_args(
        [
            "--agent",
            "codex",
            "--project",
            "enforced-planning",
            "--scope",
            str(common["scope"]),
            "--intent",
            str(common["intent"]),
            "--repo-root",
            str(common["repo_root"]),
            "--worktree-path",
            str(common["worktree_path"]),
            "--branch",
            str(common["branch"]),
            "--broader-goal",
            str(common["broader_goal"]),
            "--current-phase",
            "CLI omission refresh",
            "--allow-unplanned",
            "--session-id",
            str(common["session_id"]),
            "--session-name",
            str(common["session_name"]),
        ]
    )
    kwargs = module._supported_start_kwargs(args)
    assert {
        field: kwargs[field]
        for field in (
            "intended_next_phases",
            "depends_on_repos",
            "requires_shared_infra_changes",
            "stop_conditions",
            "notes",
        )
    } == {
        "intended_next_phases": None,
        "depends_on_repos": None,
        "requires_shared_infra_changes": None,
        "stop_conditions": None,
        "notes": None,
    }

    refreshed = session_lifecycle.start_session(**kwargs, tracker_dir=trackers_dir)
    tracker_after = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert refreshed["action"] == "updated"
    assert tracker_after["tracker"] == {"current_phase": "CLI omission refresh", **tracker_contract}

    for explicit_drift in (
        {"intended_next_phases": []},
        {"depends_on_repos": []},
        {"requires_shared_infra_changes": False},
        {"stop_conditions": []},
        {"notes": ""},
    ):
        claim_before = claim_path.read_bytes()
        tracker_before = tracker_path.read_bytes()
        with pytest.raises(
            ValueError,
            match="sanctioned maintenance refresh cannot change immutable provenance",
        ):
            session_lifecycle.start_session(
                **{
                    **kwargs,
                    "current_phase": "explicit drift attempt",
                    "tracker_dir": trackers_dir,
                    **explicit_drift,
                }
            )
        assert claim_path.read_bytes() == claim_before
        assert tracker_path.read_bytes() == tracker_before


def test_maintenance_refresh_serializes_tracker_write_through_claim_upsert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A competing tracker writer cannot enter between phase and claim persistence."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(**common)
    tracker_path = Path(started["tracker_path"])
    waiting_for_tracker_lock = Event()
    tracker_lock_acquired = Event()
    completed = Event()
    failures: list[BaseException] = []
    competitor: list[Thread] = []
    real_write = session_lifecycle._write_claim_and_refresh_projection
    real_tracker_lock = session_contracts.session_tracker_lock

    @contextmanager
    def observed_tracker_lock(path: Path):
        is_competitor = current_thread().name == "competing-tracker-writer"
        if is_competitor:
            waiting_for_tracker_lock.set()
        with real_tracker_lock(path):
            if is_competitor:
                tracker_lock_acquired.set()
            yield

    def competing_tracker_write() -> None:
        try:
            session_contracts.update_session_tracker(
                tracker_path,
                current_phase="concurrent tracker refresh",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            completed.set()

    def observe_claim_write(*args: object, **kwargs: object) -> tuple[Path, str]:
        thread = Thread(target=competing_tracker_write, name="competing-tracker-writer")
        competitor.append(thread)
        thread.start()
        assert waiting_for_tracker_lock.wait(timeout=2)
        assert tracker_lock_acquired.is_set() is False
        tracker_payload = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
        assert tracker_payload["tracker"]["current_phase"] == "serialized maintenance refresh"
        return real_write(*args, **kwargs)

    monkeypatch.setattr(session_contracts, "session_tracker_lock", observed_tracker_lock)
    monkeypatch.setattr(session_lifecycle, "_write_claim_and_refresh_projection", observe_claim_write)
    refreshed = session_lifecycle.start_session(
        **{**common, "current_phase": "serialized maintenance refresh"}
    )

    assert refreshed["action"] == "updated"
    assert len(competitor) == 1
    competitor[0].join(timeout=2)
    assert tracker_lock_acquired.is_set()
    assert completed.is_set()
    assert failures == []


def test_maintenance_refresh_classifies_one_locked_tracker_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Immutable tracker state cannot change between classification and snapshot custody."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(
        **{**common, "notes": "original immutable notes"}
    )
    tracker_path = Path(started["tracker_path"])
    waiting_for_tracker_lock = Event()
    tracker_lock_acquired = Event()
    completed = Event()
    failures: list[BaseException] = []
    competitor: list[Thread] = []
    classifier_observed = Event()
    real_classifier = outcome_admission.is_sanctioned_maintenance_claim_payload
    real_tracker_lock = session_contracts.session_tracker_lock

    @contextmanager
    def observed_tracker_lock(path: Path):
        is_competitor = current_thread().name == "pre-snapshot-tracker-writer"
        if is_competitor:
            waiting_for_tracker_lock.set()
        with real_tracker_lock(path):
            if is_competitor:
                tracker_lock_acquired.set()
            yield

    def competing_tracker_write() -> None:
        try:
            session_contracts.update_session_tracker(
                tracker_path,
                notes="concurrent notes after coherent refresh",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            completed.set()

    def classify_locked_payload(*args: object, **kwargs: object) -> bool:
        thread = Thread(target=competing_tracker_write, name="pre-snapshot-tracker-writer")
        competitor.append(thread)
        thread.start()
        assert waiting_for_tracker_lock.wait(timeout=2)
        assert tracker_lock_acquired.is_set() is False
        classifier_observed.set()
        return real_classifier(*args, **kwargs)

    monkeypatch.setattr(session_contracts, "session_tracker_lock", observed_tracker_lock)
    monkeypatch.setattr(
        outcome_admission,
        "is_sanctioned_maintenance_claim_payload",
        classify_locked_payload,
    )
    refreshed = session_lifecycle.start_session(
        **{
            **common,
            "current_phase": "coherent locked refresh",
            "notes": "original immutable notes",
        }
    )

    assert refreshed["action"] == "updated"
    assert classifier_observed.is_set()
    assert len(competitor) == 1
    competitor[0].join(timeout=2)
    assert tracker_lock_acquired.is_set()
    assert completed.is_set()
    assert failures == []
    tracker_after = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert tracker_after["tracker"]["current_phase"] == "coherent locked refresh"
    assert tracker_after["tracker"]["notes"] == "concurrent notes after coherent refresh"


def test_maintenance_refresh_cannot_reactivate_claim_ended_before_locked_reload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A canonical session end wins when it completes before refresh takes custody."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()
    real_registry_lock = coordination_claims.claim_registry_lock
    refresh_thread = current_thread()
    end_completed = Event()
    end_results: list[tuple[int, list[str], str, str]] = []
    end_failures: list[BaseException] = []
    end_threads: list[Thread] = []
    end_started = False

    def end_claim() -> None:
        try:
            end_results.append(
                coordination_claims.end_session_claims(
                    agent="codex",
                    session_id=str(common["session_id"]),
                    reason="runtime terminated during refresh",
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            end_failures.append(exc)
        finally:
            end_completed.set()

    @contextmanager
    def end_before_refresh_lock(path: Path | None = None):
        nonlocal end_started
        if current_thread() is refresh_thread and not end_started:
            end_started = True
            thread = Thread(target=end_claim, name="ending-maintenance-owner")
            end_threads.append(thread)
            thread.start()
            assert end_completed.wait(timeout=2)
        with real_registry_lock(path):
            yield

    monkeypatch.setattr(coordination_claims, "claim_registry_lock", end_before_refresh_lock)
    with pytest.raises(ValueError, match="initially live claim ended.*refusing reactivation"):
        session_lifecycle.start_session(
            **{**common, "current_phase": "must not reactivate ended claim"}
        )

    assert len(end_threads) == 1
    end_threads[0].join(timeout=2)
    assert end_failures == []
    assert len(end_results) == 1
    assert end_results[0][0] == 1
    claim_after = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert claim_path.read_bytes() != claim_before
    assert claim_after["status"] == coordination_claims.SESSION_ENDED_STATUS
    assert claim_after["session_end_reason"] == "runtime terminated during refresh"
    assert tracker_path.read_bytes() == tracker_before


def test_malformed_maintenance_refresh_fails_before_concurrent_session_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Malformed explicit maintenance never escapes locked custody into generic refresh."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    malformed_tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    malformed_tracker["claim"]["broader_goal"] = "corrupted maintenance provenance"
    session_contracts._atomic_write_session_tracker(tracker_path, malformed_tracker)
    tracker_before = tracker_path.read_bytes()
    waiting_for_registry = Event()
    registry_acquired = Event()
    completed = Event()
    failures: list[BaseException] = []
    end_threads: list[Thread] = []
    real_classifier = outcome_admission.is_sanctioned_maintenance_claim_payload
    real_registry_lock = coordination_claims.claim_registry_lock

    @contextmanager
    def observed_registry_lock(path: Path | None = None):
        is_ender = current_thread().name == "ending-malformed-maintenance"
        if is_ender:
            waiting_for_registry.set()
        with real_registry_lock(path):
            if is_ender:
                registry_acquired.set()
            yield

    def end_claim() -> None:
        try:
            coordination_claims.end_session_claims(
                agent="codex",
                session_id=str(common["session_id"]),
                reason="end malformed maintenance owner",
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            failures.append(exc)
        finally:
            completed.set()

    def classify_then_end(*args: object, **kwargs: object) -> bool:
        result = real_classifier(*args, **kwargs)
        assert result is False
        thread = Thread(target=end_claim, name="ending-malformed-maintenance")
        end_threads.append(thread)
        thread.start()
        assert waiting_for_registry.wait(timeout=2)
        assert registry_acquired.is_set() is False
        return result

    monkeypatch.setattr(coordination_claims, "claim_registry_lock", observed_registry_lock)
    monkeypatch.setattr(
        outcome_admission,
        "is_sanctioned_maintenance_claim_payload",
        classify_then_end,
    )
    with pytest.raises(ValueError, match="malformed locked tracker provenance"):
        session_lifecycle.start_session(
            **{**common, "current_phase": "must not repair malformed provenance"}
        )

    assert len(end_threads) == 1
    end_threads[0].join(timeout=2)
    assert registry_acquired.is_set()
    assert completed.is_set()
    assert failures == []
    claim_after = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    assert claim_after["status"] == coordination_claims.SESSION_ENDED_STATUS
    assert tracker_path.read_bytes() == tracker_before


def test_explicit_unplanned_marker_malformed_maintenance_refresh_fails_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Canonical claim identity fails closed independent of caller flag syntax."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = {
        **_maintenance_refresh_args(tmp_path, trackers_dir),
        "plan_ref": session_contracts.UNPLANNED_PLAN_REF,
        "allow_unplanned": False,
    }
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    malformed_tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    malformed_tracker["claim"]["broader_goal"] = "corrupted maintenance provenance"
    session_contracts._atomic_write_session_tracker(tracker_path, malformed_tracker)
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()

    with pytest.raises(ValueError, match="malformed locked tracker provenance"):
        session_lifecycle.start_session(
            **{**common, "current_phase": "must not rewrite malformed explicit marker"}
        )

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before


def test_malformed_maintenance_refresh_cannot_overwrite_cross_session_successor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A blocked successor transfer wins without any old-owner tracker mutation."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    malformed_tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    malformed_tracker["claim"]["broader_goal"] = "corrupted maintenance provenance"
    session_contracts._atomic_write_session_tracker(tracker_path, malformed_tracker)
    tracker_before = tracker_path.read_bytes()
    transfer_waiting = Event()
    transfer_acquired = Event()
    release_transfer = Event()
    transfer_completed = Event()
    transfer_results: list[dict[str, object]] = []
    transfer_failures: list[BaseException] = []
    transfer_threads: list[Thread] = []
    real_classifier = outcome_admission.is_sanctioned_maintenance_claim_payload
    real_registry_lock = coordination_claims.claim_registry_lock
    paused_transfer_lock = False

    @contextmanager
    def pause_transfer_after_registry_acquisition(path: Path | None = None):
        nonlocal paused_transfer_lock
        is_transfer = current_thread().name == "cross-session-maintenance-transfer"
        if is_transfer and not paused_transfer_lock:
            transfer_waiting.set()
        with real_registry_lock(path):
            if is_transfer and not paused_transfer_lock:
                paused_transfer_lock = True
                transfer_acquired.set()
                assert release_transfer.wait(timeout=2)
            yield

    def transfer_claim() -> None:
        try:
            session_lifecycle.end_runtime_session(
                agent="codex",
                session_id=str(common["session_id"]),
                reason="transfer malformed maintenance lane",
            )
            transfer_results.append(
                _resume_session_as_native(
                    agent="codex",
                    project="enforced-planning",
                    scope=str(common["scope"]),
                    worktree_path=str(common["worktree_path"]),
                    branch=str(common["branch"]),
                    current_phase="successor owns malformed lane disposition",
                    session_id="codex:successor-runtime",
                    note="successor accepted custody",
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            transfer_failures.append(exc)
        finally:
            transfer_completed.set()

    def classify_then_transfer(*args: object, **kwargs: object) -> bool:
        result = real_classifier(*args, **kwargs)
        assert result is False
        thread = Thread(target=transfer_claim, name="cross-session-maintenance-transfer")
        transfer_threads.append(thread)
        thread.start()
        assert transfer_waiting.wait(timeout=2)
        assert transfer_acquired.is_set() is False
        return result

    monkeypatch.setattr(
        coordination_claims,
        "claim_registry_lock",
        pause_transfer_after_registry_acquisition,
    )
    monkeypatch.setattr(
        outcome_admission,
        "is_sanctioned_maintenance_claim_payload",
        classify_then_transfer,
    )
    with pytest.raises(ValueError, match="malformed locked tracker provenance"):
        session_lifecycle.start_session(
            **{**common, "current_phase": "old owner must not overwrite successor"}
        )

    assert transfer_acquired.wait(timeout=2)
    assert tracker_path.read_bytes() == tracker_before
    release_transfer.set()
    assert len(transfer_threads) == 1
    transfer_threads[0].join(timeout=5)
    assert transfer_completed.is_set()
    assert transfer_failures == []
    assert len(transfer_results) == 1
    assert transfer_results[0]["action"] == "resumed"
    successor_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    successor_tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert successor_claim["status"] == "active"
    assert successor_claim["session_id"] == "codex:successor-runtime"
    assert successor_tracker["claim"]["session_id"] == "codex:successor-runtime"
    assert successor_tracker["tracker"]["current_phase"] == "successor owns malformed lane disposition"


def test_generic_existing_refresh_serializes_cross_session_transfer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generic tracker and claim refresh retains registry custody until both commit."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    goal = "ordinary unplanned lifecycle coverage"
    common = {
        **_maintenance_refresh_args(tmp_path, trackers_dir),
        "intent": goal,
        "broader_goal": goal,
        "session_name": session_contracts.derive_session_name(goal),
        "plan_ref": session_contracts.UNPLANNED_PLAN_REF,
        "allow_unplanned": False,
    }
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    transfer_waiting = Event()
    transfer_acquired = Event()
    transfer_completed = Event()
    transfer_results: list[dict[str, object]] = []
    transfer_failures: list[BaseException] = []
    transfer_threads: list[Thread] = []
    real_registry_lock = coordination_claims.claim_registry_lock
    real_tracker_write = session_contracts.write_session_tracker

    @contextmanager
    def observed_registry_lock(path: Path | None = None):
        is_transfer = current_thread().name == "generic-cross-session-transfer"
        if is_transfer:
            transfer_waiting.set()
        with real_registry_lock(path):
            if is_transfer:
                transfer_acquired.set()
            yield

    def transfer_claim() -> None:
        try:
            session_lifecycle.end_runtime_session(
                agent="codex",
                session_id=str(common["session_id"]),
                reason="generic refresh owner ended",
            )
            transfer_results.append(
                _resume_session_as_native(
                    agent="codex",
                    project="enforced-planning",
                    scope=str(common["scope"]),
                    worktree_path=str(common["worktree_path"]),
                    branch=str(common["branch"]),
                    current_phase="generic successor active",
                    session_id="codex:generic-successor",
                )
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            transfer_failures.append(exc)
        finally:
            transfer_completed.set()

    def write_while_transfer_waits(*args: object, **kwargs: object) -> Path:
        thread = Thread(target=transfer_claim, name="generic-cross-session-transfer")
        transfer_threads.append(thread)
        thread.start()
        assert transfer_waiting.wait(timeout=2)
        assert transfer_acquired.is_set() is False
        result = real_tracker_write(*args, **kwargs)
        assert transfer_acquired.is_set() is False
        return result

    monkeypatch.setattr(coordination_claims, "claim_registry_lock", observed_registry_lock)
    monkeypatch.setattr(session_contracts, "write_session_tracker", write_while_transfer_waits)
    refreshed = session_lifecycle.start_session(
        **{**common, "current_phase": "generic refresh committed first"}
    )

    assert refreshed["action"] == "updated"
    assert len(transfer_threads) == 1
    transfer_threads[0].join(timeout=5)
    assert transfer_acquired.is_set()
    assert transfer_completed.is_set()
    assert transfer_failures == []
    assert transfer_results[0]["action"] == "resumed"
    successor_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    successor_tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert successor_claim["session_id"] == "codex:generic-successor"
    assert successor_tracker["claim"]["session_id"] == "codex:generic-successor"
    assert successor_tracker["tracker"]["current_phase"] == "generic successor active"


def test_generic_existing_refresh_rolls_back_tracker_before_releasing_custody(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed generic claim update restores exact tracker bytes under registry custody."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    goal = "ordinary unplanned rollback coverage"
    common = {
        **_maintenance_refresh_args(tmp_path, trackers_dir),
        "intent": goal,
        "broader_goal": goal,
        "session_name": session_contracts.derive_session_name(goal),
        "plan_ref": session_contracts.UNPLANNED_PLAN_REF,
        "allow_unplanned": False,
    }
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()

    def reject_claim_update(**_kwargs: object) -> str:
        raise ValueError("injected generic claim failure")

    monkeypatch.setattr(session_lifecycle, "_upsert_session_claim", reject_claim_update)
    with pytest.raises(ValueError, match="injected generic claim failure"):
        session_lifecycle.start_session(
            **{**common, "current_phase": "must roll back generic tracker"}
        )

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before


@pytest.mark.parametrize(
    "drift",
    [
        {"intent": "replace immutable maintenance intent"},
        {"repo_root": "/tmp/different-repo"},
        {"worktree_path": "/tmp/different-worktree"},
        {"branch": "fix/different-branch"},
        {"broader_goal": "Unplanned maintenance: different goal", "session_name": None},
        {"claim_type": "write"},
        {"write_paths": ["different.py"]},
        {"intended_next_phases": ["newly invented phase"]},
        {"broad_scope_reason": "replace immutable bootstrap custody"},
    ],
)
def test_sanctioned_maintenance_start_rejects_provenance_drift_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drift: dict[str, object],
) -> None:
    """Identity drift fails before either the claim or tracker bytes change."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    common = _maintenance_refresh_args(tmp_path, trackers_dir)
    started = session_lifecycle.start_session(**common)
    claim_path = claims_dir / "codex_enforced-planning_fix_maintenance-provenance-refresh.yaml"
    tracker_path = Path(started["tracker_path"])
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()

    with pytest.raises(
        ValueError,
        match=(
            "sanctioned maintenance refresh cannot change immutable provenance"
            "|A live lane already exists"
        ),
    ):
        session_lifecycle.start_session(**{**common, "current_phase": "drift attempt", **drift})

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before


def test_existing_session_upsert_rejects_new_write_overlap_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refreshing an existing claim cannot silently acquire another session's path."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    first_worktree = tmp_path / "first-worktree"
    second_worktree = tmp_path / "second-worktree"
    first_worktree.mkdir()
    second_worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)

    first = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "first-lane",
        "intent": "Own the first path",
        "repo_root": str(tmp_path / "repo"),
        "worktree_path": str(first_worktree),
        "branch": "first-lane",
        "broader_goal": "Test claim refresh conflicts",
        "current_phase": "initial ownership",
        "session_id": "codex:first-owner",
        "claim_type": "write",
        "write_paths": ["src/first.py"],
        "tracker_dir": trackers_dir,
        "allow_unplanned": True,
    }
    first_started = session_lifecycle.start_session(**first)
    session_lifecycle.start_session(
        agent="claude-code",
        project="enforced-planning",
        scope="second-lane",
        intent="Own the shared guide",
        repo_root=str(tmp_path / "repo"),
        worktree_path=str(second_worktree),
        branch="second-lane",
        broader_goal="Test claim refresh conflicts",
        current_phase="guide ownership",
        session_id="claude-code:second-owner",
        claim_type="write",
        write_paths=["docs/shared-guide.md"],
        tracker_dir=trackers_dir,
        allow_unplanned=True,
    )
    first_path = claims_dir / "codex_enforced-planning_first-lane.yaml"
    second_path = claims_dir / "claude-code_enforced-planning_second-lane.yaml"
    first_tracker_path = Path(first_started["tracker_path"])
    before = {
        first_path: first_path.read_bytes(),
        second_path: second_path.read_bytes(),
        first_tracker_path: first_tracker_path.read_bytes(),
    }
    receipt_count = len(claim_mutation_receipts.load_receipts())

    with pytest.raises(ValueError, match="existing-session update would overlap active write ownership"):
        session_lifecycle.start_session(
            **{
                **first,
                "current_phase": "attempt overlapping expansion",
                "write_paths": ["src/first.py", "docs/shared-guide.md"],
            }
        )

    assert {path: path.read_bytes() for path in before} == before
    assert len(claim_mutation_receipts.load_receipts()) == receipt_count
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)


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
    started = session_lifecycle.start_session(current_phase="initial", **common)

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
    tracker_payload = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))
    assert tracker_payload["claim"]["intent"] == "persisted update despite receipt failure"
    assert tracker_payload["tracker"]["current_phase"] == "refreshed"
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

    resumed = _resume_session_as_native(
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
    subprocess_ledger = tmp_path / "subprocess-claim-mutation-events.jsonl"
    subprocess_wrapper = "\n".join(
        [
            "import runpy",
            "import sys",
            "from pathlib import Path",
            "from enforced_planning import claim_mutation_receipts",
            "script_path = sys.argv.pop(1)",
            "claim_mutation_receipts.DEFAULT_EVENTS_PATH = Path(sys.argv.pop(1))",
            "sys.argv[0] = script_path",
            "runpy.run_path(script_path, run_name='__main__')",
        ]
    )
    command = [
        sys.executable,
        "-c",
        subprocess_wrapper,
        str(Path(__file__).resolve().parents[1] / "scripts" / "session_end.py"),
        str(subprocess_ledger),
        "--agent",
        "codex",
        "--hook",
        "--claims-dir",
        str(claims_dir),
    ]
    stop = subprocess.run(
        command,
        input=json.dumps({"session_id": "hook-session", "hook_event_name": "Stop"}),
        capture_output=True,
        text=True,
        check=False,
    )
    assert stop.returncode == 0
    assert "requires hook_event_name=SessionEnd" in stop.stdout
    assert coordination_claims.check_claims(claims_dir=claims_dir)
    assert not subprocess_ledger.exists()

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
    assert subprocess_ledger.is_file()


def test_start_session_creates_parented_child_and_rejects_second_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Session activation should enforce the existing program/parent hierarchy."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.setattr(
        coordination_claims,
        "resolve_canonical_work_unit_binding",
        lambda **_kwargs: ("a" * 64, (), "b" * 40),
    )
    monkeypatch.setattr(
        coordination_claims,
        "resolve_default_integration_revision",
        lambda _root: "b" * 40,
    )
    monkeypatch.setattr(
        coordination_claims,
        "validate_start_revision_targets",
        lambda **_kwargs: None,
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
        start_revision="b" * 40,
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
            worktree_path=str(tmp_path / "onto-canon6" / "worktrees" / "plan0141-second-root"),
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
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
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

    payload = _heartbeat_session_as_native(
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


def test_unplanned_program_owner_heartbeat_is_liveness_not_outcome_admission(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact owner can stay live without claiming a selected outcome."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="unplanned-heartbeat",
        intent="repair lifecycle liveness",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="unplanned-heartbeat",
        broader_goal="Lifecycle Liveness",
        current_phase="fixture setup",
        allow_unplanned=True,
        session_id="codex:owner-runtime",
        tracker_dir=trackers_dir,
    )
    (worktree / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_admission_mode: enforce_selected\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="requires the current native codex runtime"):
        session_lifecycle.heartbeat_session(
            agent="codex",
            project="enforced-planning",
            scope="unplanned-heartbeat",
            session_id="codex:owner-runtime",
        )

    payload = _heartbeat_session_as_native(
        agent="codex",
        project="enforced-planning",
        scope="unplanned-heartbeat",
        session_id="codex:owner-runtime",
        current_phase="active repair",
    )
    claim_path = claims_dir / "codex_enforced-planning_unplanned-heartbeat.yaml"
    owner_bytes = claim_path.read_bytes()
    monkeypatch.setenv("CODEX_THREAD_ID", "foreign-runtime")

    with pytest.raises(ValueError, match="does not match the current codex runtime"):
        session_lifecycle.heartbeat_session(
            agent="codex",
            project="enforced-planning",
            scope="unplanned-heartbeat",
            session_id="codex:owner-runtime",
        )

    assert payload["updated_count"] == 1
    assert payload["outcome_admission_receipts"] == []
    assert claim_path.read_bytes() == owner_bytes


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
        _heartbeat_session_as_native(
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
        _finish_session_as_owner(
            agent="codex",
            project="enforced-planning",
            scope="plan-31-session-cli-enforcement",
            worktree_path=str(worktree),
            release_claim=True,
        )


def test_finish_session_dirty_handoff_refreshes_projection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dirty handoff must not leave the pre-write projection stale."""

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
        current_phase="dirty handoff proof",
        plan_ref="Plan #31",
        session_id="codex:test-session",
        tracker_dir=trackers_dir,
    )

    def _fake_run(*_args, **_kwargs):
        class Result:
            returncode = 0
            stdout = " M dirty.txt\n"
            stderr = ""

        return Result()

    monkeypatch.setattr(session_lifecycle.subprocess, "run", _fake_run)

    payload = _finish_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="plan-31-session-cli-enforcement",
        worktree_path=str(worktree),
        allow_dirty_handoff=True,
        note="handoff with preserved dirty state",
    )

    claim = coordination_claims._load_claims(claims_dir)[0]
    assert payload["action"] == "handoff"
    assert claim.status == "handoff"
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir) is True


def test_finish_session_rejects_clean_managed_worktree_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A clean managed lane must close through disposition-aware session-close."""

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

    with pytest.raises(ValueError, match="use session-close"):
        _finish_session_as_owner(
            agent="codex",
            project="enforced-planning",
            scope="plan-31-session-cli-enforcement",
            worktree_path=str(worktree),
            release_claim=True,
        )

    assert (claims_dir / "codex_enforced-planning_plan-31-session-cli-enforcement.yaml").exists()


def test_release_claim_rejects_managed_worktree_bypass(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Generic claim release cannot detach ownership from an existing Git lane."""

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

    with pytest.raises(ValueError, match="managed worktree claim"):
        coordination_claims.release_claim("codex", "enforced-planning", branch)

    assert claim_file.exists()
    assert worktree.exists()
    assert _git(repo_root, "show-ref", "--verify", f"refs/heads/{branch}")


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
        _close_session_as_owner(
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

    payload = _close_session_as_owner(
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
    assert not claim_file.exists()
    archive_records = claim_mutation_receipts.load_completed_claim_archive_receipts()
    assert len(archive_records) == 1
    assert archive_records[0].archive_id == payload["claim_archive_id"]
    archived_payload = yaml.safe_load(base64.b64decode(archive_records[0].source_yaml_bytes))
    assert archived_payload["status"] == "completed"
    assert archived_payload["disposition"] == "merged"
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
    message_id = _send_active_closeout_message(claims_dir=claims_dir, recipient_session_id="codex:test-session")

    with pytest.raises(ValueError, match="active mailbox message"):
        _close_session_as_owner(agent="codex", project="enforced-planning", scope=branch)

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
    message_id = _send_active_closeout_message(claims_dir=claims_dir, recipient_session_id="codex:test-session")

    payload = _close_session_as_owner(
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
        _close_session_as_owner(
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

    payload = _close_session_as_owner(
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
    assert not claim_file.exists()
    claim_payload = _archived_claim_payload(payload["claim_archive_id"])
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

    assert session_lifecycle._patch_without_blob_identity(first) == session_lifecycle._patch_without_blob_identity(
        second
    )
    assert session_lifecycle._patch_without_blob_identity(first) != session_lifecycle._patch_without_blob_identity(
        second.replace(b"new mode 100755", b"new mode 100644")
    )
    assert session_lifecycle._patch_without_blob_identity(first) != session_lifecycle._patch_without_blob_identity(
        second.replace(b"KcmZQz", b"KcmZRz")
    )
    assert session_lifecycle._patch_without_blob_identity(first) != session_lifecycle._patch_without_blob_identity(
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

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        merge_commit=merge_commit,
    )

    assert payload["action"] == "closed"
    assert payload["merge_evidence"] == "squash_patch_equivalent"
    assert not worktree.exists()
    assert not claim_file.exists()
    claim_payload = _archived_claim_payload(payload["claim_archive_id"])
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
        _close_session_as_owner(
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

    payload = _close_session_as_owner(
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

    payload = _close_session_as_owner(
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
        _close_session_as_owner(
            agent="codex",
            project="enforced-planning",
            scope=branch,
        )
    assert worktree.exists()

    _git(repo_root, "update-ref", remote_default_ref, "refs/heads/main")
    payload = _close_session_as_owner(
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
    _start_real_closeout_claim(
        repo_root=repo_root, worktree=worktree, branch=branch, claims_dir=claims_dir, trackers_dir=trackers_dir
    )
    stale_main = _git(repo_root, "rev-parse", "refs/heads/main").strip()
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    _git(repo_root, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    _git(repo_root, "reset", "--hard", stale_main)

    payload = _close_session_as_owner(agent="codex", project="enforced-planning", scope=branch)

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
    _start_real_closeout_claim(
        repo_root=repo_root, worktree=worktree, branch=branch, claims_dir=claims_dir, trackers_dir=trackers_dir
    )
    local_main = _git(repo_root, "rev-parse", "refs/heads/main").strip()
    divergent_main = _git(
        repo_root, "commit-tree", f"{local_main}^{{tree}}", "-p", local_main, "-m", "preserved local divergence"
    ).strip()
    _git(repo_root, "update-ref", "refs/remotes/origin/main", f"refs/heads/{branch}")
    _git(repo_root, "update-ref", "refs/heads/main", divergent_main)

    payload = _close_session_as_owner(agent="codex", project="enforced-planning", scope=branch)

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

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["worktree_action"] == "removed"
    assert payload["branch_action"] == "deleted"
    assert repo_root.exists()


def test_close_session_recovers_from_stale_repo_root_using_recorded_worktree(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retry must use the worktree's Git lineage after stale root metadata."""

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

    stale_repo_root = tmp_path / "unrelated-repo"
    stale_repo_root.mkdir()
    _git(stale_repo_root, "init", "-b", "main")
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    claim_payload["repo_root"] = str(stale_repo_root)
    claim_payload["status"] = "closing"
    claim_file.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["worktree_action"] == "removed"
    assert payload["branch_action"] == "deleted"
    assert not claim_file.exists()
    completed_claim = _archived_claim_payload(payload["claim_archive_id"])
    assert completed_claim["status"] == "completed"
    assert completed_claim["repo_root"] == str(repo_root)


def test_close_session_reanchors_inside_worktree_cwd_before_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Closeout moves the process to the canonical root before removing its cwd."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    repo_root, worktree, branch = _real_repo_with_worktree(tmp_path)
    claim_file = _start_real_closeout_claim(
        repo_root=repo_root,
        worktree=worktree,
        branch=branch,
        claims_dir=claims_dir,
        trackers_dir=trackers_dir,
    )
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge feature")
    original_claim = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    tracker_path = Path(original_claim["tracker_path"])
    monkeypatch.chdir(worktree)

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["worktree_action"] == "removed"
    assert payload["branch_action"] == "deleted"
    assert Path.cwd() == repo_root.resolve()
    assert not claim_file.exists()
    tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert tracker["tracker"]["current_phase"] == "closed"
    assert not worktree.exists()


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
            _close_session_as_owner(
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

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert payload["disposition"] == "merged"
    assert payload["worktree_action"] == "already_missing"
    assert payload["branch_action"] == "deleted"
    assert not claim_file.exists()
    claim_payload = _archived_claim_payload(payload["claim_archive_id"])
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

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
    )

    assert payload["action"] == "closed"
    assert not worktree.exists()
    assert not claim_file.exists()
    assert _archived_claim_payload(payload["claim_archive_id"])["status"] == "completed"
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

    payload = _close_session_as_owner(
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
    assert not claim_file.exists()
    claim_after = _archived_claim_payload(payload["claim_archive_id"])
    assert claim_after["status"] == "completed"
    assert claim_after["missing_worktree_reconciliation"] == receipt
    assert session_contracts.read_session_tracker(tracker)["tracker"]["current_phase"] == "closed"


def test_close_session_archives_session_ended_canonical_root_without_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy canonical-root custody archives metadata while retaining Git state."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "tests@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    branch = "docs/refresh-arrangement"
    _git(repo_root, "switch", "-c", branch)
    (repo_root / "finder.md").write_text("current\n", encoding="utf-8")
    _git(repo_root, "add", "finder.md")
    _git(repo_root, "commit", "-m", "refresh finder")
    _git(repo_root, "switch", "main")
    _git(repo_root, "merge", "--no-ff", branch, "-m", "merge finder")
    _git(repo_root, "update-ref", "refs/remotes/origin/main", "refs/heads/main")
    _git(repo_root, "switch", branch)
    session_lifecycle.start_session(
        agent="codex",
        project="inside-success-mega",
        scope=branch,
        intent="archive legacy canonical-root custody",
        repo_root=str(repo_root),
        worktree_path=str(repo_root),
        branch=branch,
        broader_goal="Retain Finder Repository",
        current_phase="terminal metadata archival",
        plan_ref="UNPLANNED",
        session_id="codex:canonical-root-owner",
        tracker_dir=trackers_dir,
    )
    session_lifecycle.end_runtime_session(
        agent="codex",
        session_id="codex:canonical-root-owner",
        reason="implementation merged before metadata closeout",
        claims_dir=claims_dir,
    )
    claim_file = claims_dir / coordination_claims._claim_filename(
        "codex", "inside-success-mega", branch
    )
    claim_before = claim_file.read_bytes()
    tracker = Path(yaml.safe_load(claim_before)["tracker_path"])
    tracker_digest = session_lifecycle._tracker_sha256(tracker)
    claim_digest = hashlib.sha256(claim_before).hexdigest()
    branch_tip = _git(repo_root, "rev-parse", f"refs/heads/{branch}")
    worktree_list_before = _git(repo_root, "worktree", "list", "--porcelain")

    def fail_remove(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("canonical-root reconciliation must never remove a worktree")

    def fail_delete(*_args: object, **_kwargs: object) -> str:
        raise AssertionError("canonical-root reconciliation must never delete a branch")

    monkeypatch.setattr(session_lifecycle, "_remove_worktree_path", fail_remove)
    monkeypatch.setattr(session_lifecycle, "_delete_branch", fail_delete)

    payload = _close_session_as_owner(
        agent="codex",
        project="inside-success-mega",
        scope=branch,
        reconcile_canonical_root=True,
        expected_claim_sha256=claim_digest,
        expected_tracker_sha256=tracker_digest,
    )

    assert payload["action"] == "closed"
    assert payload["worktree_action"] == "retained_canonical_root"
    assert payload["branch_action"] == "retained_canonical_branch"
    assert repo_root.is_dir()
    assert _git(repo_root, "rev-parse", f"refs/heads/{branch}") == branch_tip
    assert _git(repo_root, "symbolic-ref", "--short", "HEAD") == branch
    assert _git(repo_root, "worktree", "list", "--porcelain") == worktree_list_before
    assert not claim_file.exists()
    archived = _archived_claim_payload(payload["claim_archive_id"])
    receipt = archived["canonical_root_reconciliation"]
    assert archived["status"] == "completed"
    assert receipt["claim_sha256"] == claim_digest
    assert receipt["tracker_sha256"] == tracker_digest
    assert receipt["filesystem_action"] == "retained_canonical_root"
    assert receipt["branch_action"] == "retained_canonical_branch"


@pytest.mark.parametrize(
    ("ended", "claim_digest", "tracker_digest", "dirty", "expected"),
    [
        (False, "correct", "correct", False, "session_ended"),
        (True, "wrong", "correct", False, "claim digest mismatch"),
        (True, "correct", "wrong", False, "tracker digest mismatch"),
        (True, "correct", "correct", True, "clean canonical checkout"),
    ],
)
def test_close_session_canonical_root_reconciliation_rejects_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ended: bool,
    claim_digest: str,
    tracker_digest: str,
    dirty: bool,
    expected: str,
) -> None:
    """Status, exact digests, and clean canonical identity all fail closed."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    _git(repo_root, "init", "-b", "main")
    _git(repo_root, "config", "user.email", "tests@example.com")
    _git(repo_root, "config", "user.name", "Test User")
    (repo_root / "README.md").write_text("baseline\n", encoding="utf-8")
    _git(repo_root, "add", "README.md")
    _git(repo_root, "commit", "-m", "initial")
    branch = "legacy-finder"
    _git(repo_root, "switch", "-c", branch)
    session_lifecycle.start_session(
        agent="codex",
        project="inside-success-mega",
        scope=branch,
        intent="negative canonical-root reconciliation",
        repo_root=str(repo_root),
        worktree_path=str(repo_root),
        branch=branch,
        broader_goal="Retain Finder Repository",
        current_phase="terminal metadata archival",
        plan_ref="UNPLANNED",
        session_id="codex:canonical-root-owner",
        tracker_dir=trackers_dir,
    )
    if ended:
        session_lifecycle.end_runtime_session(
            agent="codex",
            session_id="codex:canonical-root-owner",
            reason="runtime ended",
            claims_dir=claims_dir,
        )
    claim_file = claims_dir / coordination_claims._claim_filename(
        "codex", "inside-success-mega", branch
    )
    claim_before = claim_file.read_bytes()
    tracker = Path(yaml.safe_load(claim_before)["tracker_path"])
    expected_claim_digest = hashlib.sha256(claim_before).hexdigest()
    expected_tracker_digest = session_lifecycle._tracker_sha256(tracker)
    if claim_digest == "wrong":
        expected_claim_digest = "0" * 64
    if tracker_digest == "wrong":
        expected_tracker_digest = "0" * 64
    if dirty:
        (repo_root / "uncommitted.txt").write_text("preserve me\n", encoding="utf-8")

    with pytest.raises(ValueError, match=expected):
        _close_session_as_owner(
            agent="codex",
            project="inside-success-mega",
            scope=branch,
            reconcile_canonical_root=True,
            expected_claim_sha256=expected_claim_digest,
            expected_tracker_sha256=expected_tracker_digest,
        )

    assert claim_file.read_bytes() == claim_before
    assert repo_root.exists()
    assert _git(repo_root, "symbolic-ref", "--short", "HEAD") == branch


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
        _close_session_as_owner(
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
        _close_session_as_owner(
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

    payload = _close_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope=branch,
        disposition="archived",
        disposition_reason="preserve the reviewed experiment without merging it",
        recovery_ref=recovery_ref,
    )

    assert payload["disposition"] == "archived"
    assert _git(repo_root, "show-ref", "--verify", recovery_ref)
    assert not claim_file.exists()
    claim_payload = _archived_claim_payload(payload["claim_archive_id"])
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
        _close_session_as_owner(
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
        _close_session_as_owner(
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

    payload = _close_session_as_owner(
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
    assert not claim_file.exists()
    claim_payload = _archived_claim_payload(payload["claim_archive_id"])
    assert claim_payload["status"] == "completed"
    assert claim_payload["disposition"] == "abandoned"


def test_close_session_refuses_merged_disposition_when_worktree_and_branch_are_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing branch evidence must not create a false merged disposition."""

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

    with pytest.raises(ValueError, match="integration.*cannot be proven"):
        _close_session_as_owner(
            agent="codex",
            project="enforced-planning",
            scope="plan-42-atomic-closeout",
            worktree_path=str(tmp_path / "missing-worktree"),
            branch="plan-42-atomic-closeout",
        )

    claim_file = claims_dir / "codex_enforced-planning_plan-42-atomic-closeout.yaml"
    claim_payload = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
    assert claim_payload["status"] == "active"
    assert "disposition" not in claim_payload


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

    payload = _close_session_as_owner(
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


def test_same_runtime_resume_atomically_reattaches_one_exact_tracker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A refreshed claim can recover only its uniquely matching exact tracker."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", trackers_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="same-runtime-reattach",
        intent="recover exact tracker custody",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="same-runtime-reattach",
        broader_goal="Same Runtime Reattachment",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:same-runtime",
        tracker_dir=trackers_dir,
    )
    tracker_path = Path(started["tracker_path"])
    claim_path = claims_dir / "codex_enforced-planning_same-runtime-reattach.yaml"
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim_payload["tracker_path"] = None
    claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")

    result = _resume_session_as_native(
        agent="codex",
        project="enforced-planning",
        scope="same-runtime-reattach",
        worktree_path=str(worktree),
        branch="same-runtime-reattach",
        current_phase="tracker restored",
        session_id="codex:same-runtime",
    )

    restored_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    restored_tracker = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    assert result["tracker_path"] == str(tracker_path.resolve())
    assert restored_claim["tracker_path"] == str(tracker_path.resolve())
    assert restored_claim["session_id"] == restored_tracker["claim"]["session_id"] == "codex:same-runtime"
    assert restored_tracker["tracker"]["current_phase"] == "tracker restored"


def test_same_runtime_resume_rejects_tracker_with_mismatched_exact_custody(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filename identity cannot override branch/repo/worktree/tracker custody."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(session_contracts, "DEFAULT_SESSION_TRACKERS_DIR", trackers_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="mismatched-reattach",
        intent="reject mismatched tracker custody",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="mismatched-reattach",
        broader_goal="Mismatched Reattachment",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:same-runtime",
        tracker_dir=trackers_dir,
    )
    tracker_path = Path(started["tracker_path"])
    tracker_payload = yaml.safe_load(tracker_path.read_text(encoding="utf-8"))
    tracker_payload["claim"]["branch"] = "foreign-branch"
    tracker_path.write_text(yaml.safe_dump(tracker_payload, sort_keys=False), encoding="utf-8")
    claim_path = claims_dir / "codex_enforced-planning_mismatched-reattach.yaml"
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim_payload["tracker_path"] = None
    claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()

    with pytest.raises(ValueError, match="branch"):
        _resume_session_as_native(
            agent="codex",
            project="enforced-planning",
            scope="mismatched-reattach",
            worktree_path=str(worktree),
            branch="mismatched-reattach",
            current_phase="must not resume",
            session_id="codex:same-runtime",
        )

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before


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
    claim_path = claims_dir / "codex_enforced-planning_plan-37-session-recovery.yaml"
    before_handoff = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    progress_before = {field: before_handoff.get(field) for field in coordination_claims.PROGRESS_FIELD_NAMES}

    payload = _handoff_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        note="resume tomorrow from a fresh runtime",
    )
    status_payload = session_lifecycle.status_sessions(project="enforced-planning", scope="plan-37-session-recovery")
    tracker_payload = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))
    after_handoff = yaml.safe_load(claim_path.read_text(encoding="utf-8"))

    assert payload["action"] == "handoff"
    assert status_payload["sessions"][0]["claim_status"] == "handoff"
    assert status_payload["sessions"][0]["recovery_action"] == "resume_or_finish_handoff"
    assert tracker_payload["tracker"]["current_phase"] == "handoff required"
    assert {field: after_handoff.get(field) for field in coordination_claims.PROGRESS_FIELD_NAMES} == progress_before
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)


def test_foreign_runtime_cannot_handoff_claim_owner_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal lifecycle writer must prove it is the claim's exact actor."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="actor-guard",
        intent="prove foreign lifecycle denial",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="actor-guard",
        broader_goal="Actor Guard",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:owner-runtime",
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_enforced-planning_actor-guard.yaml"
    claim_before = claim_path.read_bytes()
    monkeypatch.setenv("CODEX_THREAD_ID", "foreign-runtime")

    with pytest.raises(ValueError, match="does not match the current codex runtime"):
        session_lifecycle.handoff_session(
            agent="codex",
            project="enforced-planning",
            scope="actor-guard",
            note="foreign mutation attempt",
            actor_session_id="codex:owner-runtime",
        )

    assert claim_path.read_bytes() == claim_before


@pytest.mark.parametrize("native_value", [None, "foreign-runtime"])
@pytest.mark.parametrize("operation", ["finish", "close", "handoff", "abandon"])
def test_terminal_lifecycle_requires_ambient_exact_owner_marker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    native_value: str | None,
) -> None:
    """Known owner text cannot authorize any terminal mutation from a foreign shell."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="marker-guard",
        intent="prove native actor binding",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="marker-guard",
        broader_goal="Actor Guard",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:owner-runtime",
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_enforced-planning_marker-guard.yaml"
    before = claim_path.read_bytes()
    if native_value is None:
        monkeypatch.delenv("CODEX_THREAD_ID", raising=False)
        expected = "requires the current native codex runtime"
    else:
        monkeypatch.setenv("CODEX_THREAD_ID", native_value)
        expected = "does not match the current codex runtime"
    common = {
        "agent": "codex",
        "project": "enforced-planning",
        "scope": "marker-guard",
        "actor_session_id": "codex:owner-runtime",
    }
    calls = {
        "finish": lambda: session_lifecycle.finish_session(worktree_path=str(worktree), **common),
        "close": lambda: session_lifecycle.close_session(**common),
        "handoff": lambda: session_lifecycle.handoff_session(note="attempt", **common),
        "abandon": lambda: session_lifecycle.abandon_session(note="attempt", **common),
    }

    with pytest.raises(ValueError, match=expected):
        calls[operation]()

    assert claim_path.read_bytes() == before


def test_resume_session_rebinds_stale_or_handoff_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit handoff should authorize a fresh runtime on the same plan-bound lane."""

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
    claim_path = claims_dir / "codex_enforced-planning_plan-37-session-recovery.yaml"
    progress_before = {
        field: yaml.safe_load(claim_path.read_text(encoding="utf-8")).get(field)
        for field in coordination_claims.PROGRESS_FIELD_NAMES
    }
    _handoff_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="plan-37-session-recovery",
        note="resume later",
    )

    payload = _resume_session_as_native(
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
    resumed_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))

    assert payload["action"] == "resumed"
    assert payload["session_id"] == "codex:new-session"
    custody = payload["claim_session_transfer"]
    assert custody is not None
    custody_path = Path(custody["receipt_path"])
    assert custody_path.is_file()
    assert custody["receipt_sha256"] == hashlib.sha256(custody_path.read_bytes()).hexdigest()
    custody_payload = json.loads(custody_path.read_text(encoding="utf-8"))
    assert custody_payload["record_type"] == "claim_session_custody_transfer"
    assert custody_payload["action"] == "session_resume"
    assert custody_payload["prior_session_id"] == "codex:old-session"
    assert custody_payload["successor_session_id"] == "codex:new-session"
    assert custody_payload["repo_root"] == str(Path("~/projects/enforced-planning").expanduser().resolve())
    assert custody_payload["worktree_path"] == str(worktree.resolve())
    assert custody_payload["branch"] == "plan-37-session-recovery"
    assert custody_payload["prior_claim_sha256"] != custody_payload["successor_claim_sha256"]
    assert status_payload["sessions"][0]["claim_status"] == "active"
    assert status_payload["sessions"][0]["recovery_action"] == "continue"
    assert tracker_payload["tracker"]["current_phase"] == "fresh runtime resumed"
    assert tracker_payload["claim"]["session_id"] == "codex:new-session"
    assert {field: resumed_claim.get(field) for field in coordination_claims.PROGRESS_FIELD_NAMES} == progress_before
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)


def test_resume_observer_cannot_see_split_claim_tracker_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status observer blocks across the two-authority custody commit."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="atomic-observer",
        intent="prove observer atomicity",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="atomic-observer",
        broader_goal="Atomic Resume",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:old-runtime",
        tracker_dir=trackers_dir,
    )
    _handoff_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="atomic-observer",
        note="ready",
    )
    entered_tracker_write = Event()
    release_tracker_write = Event()
    original_write = session_contracts._atomic_write_session_tracker

    def paused_tracker_write(path: Path, payload: dict[str, object]) -> None:
        entered_tracker_write.set()
        assert release_tracker_write.wait(timeout=5)
        original_write(path, payload)

    monkeypatch.setattr(session_contracts, "_atomic_write_session_tracker", paused_tracker_write)
    with ThreadPoolExecutor(max_workers=2) as executor:
        resume_future = executor.submit(
            _resume_session_as_native,
            agent="codex",
            project="enforced-planning",
            scope="atomic-observer",
            worktree_path=str(worktree),
            branch="atomic-observer",
            current_phase="successor active",
            session_id="codex:new-runtime",
        )
        assert entered_tracker_write.wait(timeout=5)
        status_future = executor.submit(
            session_lifecycle.status_sessions,
            project="enforced-planning",
            scope="atomic-observer",
        )
        time.sleep(0.05)
        assert not status_future.done()
        release_tracker_write.set()
        assert resume_future.result(timeout=5)["session_id"] == "codex:new-runtime"
        observed = status_future.result(timeout=5)

    tracker = yaml.safe_load(Path(started["tracker_path"]).read_text(encoding="utf-8"))
    assert observed["sessions"][0]["session_id"] == "codex:new-runtime"
    assert observed["sessions"][0]["current_phase"] == "successor active"
    assert tracker["claim"]["session_id"] == "codex:new-runtime"


def test_status_observer_does_not_create_chmod_or_prune_coordination_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Claimless status remains read-only when writer lock files are absent."""

    coordination_root = tmp_path / "coordination"
    claims_dir = coordination_root / "claims"
    trackers_dir = coordination_root / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="read-only-status",
        intent="prove read-only observation",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="read-only-status",
        broader_goal="Read Only Status",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:read-only-status",
        tracker_dir=trackers_dir,
    )
    tracker_path = Path(started["tracker_path"])
    claim_lock = claims_dir.parent / f".{claims_dir.name}.lock"
    tracker_lock = tracker_path.parent / f".{tracker_path.name}.lock"
    claim_lock.unlink()
    tracker_lock.unlink()
    legacy_staging = claims_dir / ".owner.yaml.status-observer.tmp"
    legacy_staging.write_text("retain legacy staging", encoding="utf-8")
    shared_staging_dir = claims_dir.parent / f".{claims_dir.name}-write-staging"
    shared_staging_dir.mkdir(exist_ok=True)
    shared_staging = shared_staging_dir / "status-observer.tmp"
    shared_staging.write_text("retain shared staging", encoding="utf-8")
    stale_time = time.time() - coordination_claims.CLAIM_WRITE_STAGING_MAX_AGE_SECONDS - 60
    os.utime(legacy_staging, (stale_time, stale_time))
    os.utime(shared_staging, (stale_time, stale_time))

    def tree_snapshot(root: Path) -> tuple[tuple[str, int, int, str | None], ...]:
        rows: list[tuple[str, int, int, str | None]] = []
        for path in sorted(root.rglob("*")):
            stat_result = path.lstat()
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
            rows.append((str(path.relative_to(root)), stat_result.st_mode, stat_result.st_ino, digest))
        return tuple(rows)

    original_modes = {
        coordination_root: coordination_root.stat().st_mode,
        claims_dir: claims_dir.stat().st_mode,
        tracker_path.parent: tracker_path.parent.stat().st_mode,
        shared_staging_dir: shared_staging_dir.stat().st_mode,
    }
    for directory in original_modes:
        directory.chmod(0o500)
    before = tree_snapshot(coordination_root)
    try:
        payload = session_lifecycle.status_sessions(
            project="enforced-planning",
            scope="read-only-status",
        )
        after = tree_snapshot(coordination_root)
    finally:
        for directory, mode in original_modes.items():
            directory.chmod(mode & 0o777)

    assert payload["session_count"] == 1
    assert payload["sessions"][0]["current_phase"] == "fixture setup"
    assert before == after
    assert not claim_lock.exists()
    assert not tracker_lock.exists()
    assert legacy_staging.exists()
    assert shared_staging.exists()


def test_status_with_persistent_lock_and_missing_tracker_is_read_only_and_weak(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vanished tracker under its retained lock is classified, not crashed or recreated."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="missing-tracker-status",
        intent="classify a missing tracker",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="missing-tracker-status",
        broader_goal="Missing Tracker Status",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:missing-tracker",
        tracker_dir=trackers_dir,
    )
    tracker_path = Path(started["tracker_path"])
    tracker_lock = tracker_path.parent / f".{tracker_path.name}.lock"
    assert tracker_lock.is_file()
    tracker_path.unlink()
    lock_before = tracker_lock.read_bytes()

    result = session_lifecycle.status_sessions(
        project="enforced-planning",
        scope="missing-tracker-status",
    )

    session = result["sessions"][0]
    assert session["health_status"] == "weak"
    assert "missing_tracker_file" in session["health_issues"]
    assert not tracker_path.exists()
    assert tracker_lock.read_bytes() == lock_before

    claim_path = claims_dir / "codex_enforced-planning_missing-tracker-status.yaml"
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim_payload["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")
    stale = session_lifecycle.status_sessions(
        project="enforced-planning",
        scope="missing-tracker-status",
    )["sessions"][0]
    assert stale["health_status"] == "stale"
    assert "missing_tracker_file" in stale["health_issues"]


def test_resume_reports_post_commit_mailbox_failure_without_rolling_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mailbox visibility failure cannot make completed custody look unsuccessful."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="mailbox-after-resume",
        intent="prove committed transfer reporting",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="mailbox-after-resume",
        broader_goal="Truthful Resume",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:old-runtime",
        tracker_dir=trackers_dir,
    )
    _handoff_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="mailbox-after-resume",
        note="ready",
    )
    monkeypatch.setattr(
        session_lifecycle,
        "_poll_mailbox",
        lambda **_kwargs: (_ for _ in ()).throw(OSError("mailbox unavailable")),
    )

    result = _resume_session_as_native(
        agent="codex",
        project="enforced-planning",
        scope="mailbox-after-resume",
        worktree_path=str(worktree),
        branch="mailbox-after-resume",
        current_phase="successor active",
        session_id="codex:new-runtime",
    )

    claim = yaml.safe_load((claims_dir / "codex_enforced-planning_mailbox-after-resume.yaml").read_text())
    tracker = yaml.safe_load(Path(started["tracker_path"]).read_text())
    assert result["action"] == "resumed"
    assert result["coordination_mailbox"]["degraded_reason"] == "post_commit_mailbox_poll_failed"
    assert result["claim_session_transfer"] is not None
    assert claim["session_id"] == tracker["claim"]["session_id"] == "codex:new-runtime"


def test_resume_receipt_failure_rolls_back_before_successor_heartbeat_can_enter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Receipt failure restores predecessor bytes while custody locks remain held."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="receipt-after-resume",
        intent="prove committed receipt reporting",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="receipt-after-resume",
        broader_goal="Truthful Custody Receipt",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:old-runtime",
        tracker_dir=trackers_dir,
    )
    _handoff_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="receipt-after-resume",
        note="ready",
    )
    claim_path = claims_dir / "codex_enforced-planning_receipt-after-resume.yaml"
    tracker_path = Path(started["tracker_path"])
    claim_before = claim_path.read_bytes()
    tracker_before = tracker_path.read_bytes()
    entered_receipt = Event()
    release_receipt = Event()

    def paused_receipt_failure(**_kwargs: object) -> dict[str, object]:
        entered_receipt.set()
        assert release_receipt.wait(timeout=5)
        raise OSError("receipt store unavailable")

    monkeypatch.setattr(session_lifecycle, "_persist_claim_session_transfer_receipt", paused_receipt_failure)
    with ThreadPoolExecutor(max_workers=2) as executor:
        resume_future = executor.submit(
            _resume_session_as_native,
            agent="codex",
            project="enforced-planning",
            scope="receipt-after-resume",
            worktree_path=str(worktree),
            branch="receipt-after-resume",
            current_phase="successor active",
            session_id="codex:new-runtime",
        )
        assert entered_receipt.wait(timeout=5)
        heartbeat_future = executor.submit(
            _heartbeat_session_as_native,
            agent="codex",
            project="enforced-planning",
            scope="receipt-after-resume",
            current_phase="successor heartbeat",
            session_id="codex:new-runtime",
        )
        time.sleep(0.05)
        assert not heartbeat_future.done()
        release_receipt.set()
        with pytest.raises(OSError, match="receipt store unavailable"):
            resume_future.result(timeout=5)
        with pytest.raises((PermissionError, ValueError), match="session|owner|owned"):
            heartbeat_future.result(timeout=5)

    assert claim_path.read_bytes() == claim_before
    assert tracker_path.read_bytes() == tracker_before
    mutation_receipts = claim_mutation_receipts.load_receipts()
    assert mutation_receipts[-2].session_id == "codex:new-runtime"
    assert mutation_receipts[-1].session_id == "codex:old-runtime"
    assert mutation_receipts[-1].registry_digest_after == coordination_claims._registry_digest(claims_dir)
    assert mutation_receipts[-1].projection_current_after is True


def test_resume_rolls_back_claim_and_tracker_when_tracker_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ordinary cross-runtime resume is exact-byte atomic across both authorities."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="resume-rollback",
        intent="exercise resume rollback",
        repo_root=str(tmp_path),
        worktree_path=str(worktree),
        branch="resume-rollback",
        broader_goal="Resume Rollback",
        current_phase="fixture setup",
        plan_ref="UNPLANNED",
        session_id="codex:old-session",
        tracker_dir=trackers_dir,
    )
    _handoff_session_as_owner(
        agent="codex",
        project="enforced-planning",
        scope="resume-rollback",
        note="transfer fixture",
    )
    claim_path = claims_dir / "codex_enforced-planning_resume-rollback.yaml"
    tracker_path = Path(started["tracker_path"])
    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    before = (claim_path.read_bytes(), tracker_path.read_bytes())
    monkeypatch.setattr(
        session_contracts,
        "_atomic_write_session_tracker",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("injected tracker failure")),
    )

    with pytest.raises(OSError, match="injected tracker failure"):
        _resume_session_as_native(
            agent="codex",
            project="enforced-planning",
            scope="resume-rollback",
            worktree_path=str(worktree),
            branch="resume-rollback",
            current_phase="new runtime",
            session_id="codex:new-session",
        )

    assert (claim_path.read_bytes(), tracker_path.read_bytes()) == before
    assert prewrite_claim_projection.projection_is_current(
        claims_dir=claims_dir,
        projection_path=projection_path,
    )


@pytest.mark.parametrize("claim_status", ["active", "blocked"])
def test_resume_session_rejects_different_runtime_for_healthy_live_lane_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    claim_status: str,
) -> None:
    """A healthy owner must remain authoritative until an explicit recovery condition exists."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    started = session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="healthy-live-lane",
        intent="preserve exact runtime ownership",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="healthy-live-lane",
        broader_goal="Reliable Runtime Handoffs",
        current_phase="healthy owner is still working",
        plan_ref="Plan #37",
        session_id="codex:owning-runtime",
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_enforced-planning_healthy-live-lane.yaml"
    if claim_status != "active":
        claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
        claim_payload["status"] = claim_status
        claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")
        prewrite_claim_projection.write_projection(claims_dir=claims_dir)
    projection_path = prewrite_claim_projection.projection_path_for(claims_dir)
    tracker_path = Path(started["tracker_path"])
    claim_before = claim_path.read_bytes()
    projection_before = projection_path.read_bytes()
    tracker_before = tracker_path.read_bytes()

    with pytest.raises(ValueError, match="still owned by runtime session codex:owning-runtime"):
        _resume_session_as_native(
            agent="codex",
            project="enforced-planning",
            scope="healthy-live-lane",
            worktree_path=str(worktree),
            branch="healthy-live-lane",
            current_phase="unauthorized takeover",
            session_id="codex:different-runtime",
        )

    assert claim_path.read_bytes() == claim_before
    assert projection_path.read_bytes() == projection_before
    assert tracker_path.read_bytes() == tracker_before

    resumed = _resume_session_as_native(
        agent="codex",
        project="enforced-planning",
        scope="healthy-live-lane",
        worktree_path=str(worktree),
        branch="healthy-live-lane",
        current_phase="owning runtime refreshed",
        session_id="codex:owning-runtime",
    )
    assert resumed["action"] == "resumed"
    assert resumed["session_id"] == "codex:owning-runtime"


def test_resume_session_rebinds_lane_with_stale_heartbeat(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A genuinely stale heartbeat should remain an explicit crash-recovery path."""

    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "sessions"
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.delenv("CODEX_THREAD_ID", raising=False)

    session_lifecycle.start_session(
        agent="codex",
        project="enforced-planning",
        scope="stale-heartbeat-lane",
        intent="recover a crashed runtime",
        repo_root="~/projects/enforced-planning",
        worktree_path=str(worktree),
        branch="stale-heartbeat-lane",
        broader_goal="Reliable Runtime Handoffs",
        current_phase="runtime stopped heartbeating",
        plan_ref="Plan #37",
        session_id="codex:stale-runtime",
        tracker_dir=trackers_dir,
    )
    claim_path = claims_dir / "codex_enforced-planning_stale-heartbeat-lane.yaml"
    claim_payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    claim_payload["heartbeat_at"] = "2000-01-01T00:00:00+00:00"
    claim_path.write_text(yaml.safe_dump(claim_payload, sort_keys=False), encoding="utf-8")

    payload = _resume_session_as_native(
        agent="codex",
        project="enforced-planning",
        scope="stale-heartbeat-lane",
        worktree_path=str(worktree),
        branch="stale-heartbeat-lane",
        current_phase="crash recovery",
        session_id="codex:recovery-runtime",
    )
    resumed_claim = yaml.safe_load(claim_path.read_text(encoding="utf-8"))

    assert payload["action"] == "resumed"
    assert resumed_claim["session_id"] == "codex:recovery-runtime"
    assert resumed_claim["status"] == "active"
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)


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

    payload = _abandon_session_as_owner(
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
    assert prewrite_claim_projection.projection_is_current(claims_dir=claims_dir)


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
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_SESSION_ID", raising=False)
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
