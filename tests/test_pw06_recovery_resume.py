"""Plan 108 PW-06 recovery-and-resume composition checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import coordination_claims, session_lifecycle
from enforced_planning.prewrite_claim_projection import write_projection
from scripts import prewrite_claim_gate

SESSION_ID = "claude-code:pw06-recovery"
INSTALLED_GATE = Path.home() / ".codex/runtime/enforced-planning/scripts/prewrite_claim_gate.py"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _claimed_repo(workspace: Path, claims_dir: Path, name: str) -> Path:
    repo = workspace / name
    repo.mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "PW-06 Test")
    _git(repo, "config", "user.email", "pw06@example.com")
    (repo / "README.md").write_text(f"{name}\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = repo / "worktrees" / f"{name}-lane"
    worktree.parent.mkdir()
    _git(repo, "worktree", "add", "-b", f"{name}-lane", str(worktree))

    now = datetime.now(UTC)
    claim = {
        "schema_version": 3,
        "agent": "claude-code",
        "claimed_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "projects": [name],
        "scope": f"{name}-lane",
        "intent": "exercise exact recovery from an ambiguous native session",
        "claim_type": "write",
        "plan_ref": "UNPLANNED",
        "write_paths": ["README.md"],
        "read_paths": [],
        "worktree_path": str(worktree),
        "repo_root": str(repo),
        "branch": f"{name}-lane",
        "session_name": "pw06-recovery",
        "broader_goal": "complete recovery and resume through combined hooks",
        "tracker_path": str(workspace / f"{name}-tracker.yaml"),
        "session_id": SESSION_ID,
        "heartbeat_at": now.isoformat(),
        "status": "active",
        "updated_at": now.isoformat(),
    }
    claim_path = claims_dir / f"claude-code_{name}_{name}-lane.yaml"
    claim_path.write_text(yaml.safe_dump(claim, sort_keys=False), encoding="utf-8")
    return worktree


def _run_gate(
    *,
    payload: dict[str, object],
    claims_dir: Path,
    projection_path: Path,
    receipt_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, dict[str, object]]:
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(payload)))
    code = prewrite_claim_gate.main(
        [
            "--client",
            "claude-code",
            "--mode",
            "enforce",
            "--claims-dir",
            str(claims_dir),
            "--projection-path",
            str(projection_path),
            "--receipt-path",
            str(receipt_dir / "receipts.jsonl"),
            "--outcome-receipt-path",
            str(receipt_dir / "outcome-receipts.jsonl"),
            "--json",
        ]
    )
    captured = capsys.readouterr()
    assert not captured.err
    return code, json.loads(captured.out)


def test_ambiguous_session_denial_supplies_executable_exact_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The first denial must expose a self-owned command the same gate admits."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _claimed_repo(workspace, claims_dir, "first")
    _claimed_repo(workspace, claims_dir, "second")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)

    payload = {
        "session_id": "pw06-recovery",
        "cwd": str(workspace),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "touch ambiguous-write"},
    }
    code, decision = _run_gate(
        payload=payload,
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_dir=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert code == 2
    assert decision["reason_code"] == "ambiguous_exact_session_target", decision
    recovery = decision["recovery"]
    assert "Command: " in recovery
    command = recovery.split("Command: ", 1)[1]
    assert (
        prewrite_claim_gate._special_unclaimed_command(
            command,
            client="claude-code",
            claims_dir=claims_dir,
            projection_path=projection_path,
            subagent_event=False,
            native_session=SESSION_ID,
        )
        == "native_closeout"
    )


def test_installed_combined_gate_supplies_the_same_exact_recovery(tmp_path: Path) -> None:
    """The deployed adapter must expose the repaired transition, not only source."""

    if not INSTALLED_GATE.is_file():
        pytest.skip("installed combined gate is unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _claimed_repo(workspace, claims_dir, "first")
    _claimed_repo(workspace, claims_dir, "second")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    payload = {
        "session_id": "pw06-recovery",
        "cwd": str(workspace),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "touch ambiguous-write"},
    }

    completed = subprocess.run(
        [
            "/usr/bin/python3",
            str(INSTALLED_GATE),
            "--client",
            "claude-code",
            "--mode",
            "enforce",
            "--claims-dir",
            str(claims_dir),
            "--projection-path",
            str(projection_path),
            "--receipt-path",
            str(tmp_path / "receipts.jsonl"),
            "--outcome-receipt-path",
            str(tmp_path / "outcome-receipts.jsonl"),
            "--json",
        ],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 2, completed.stderr
    assert not completed.stderr
    decision = json.loads(completed.stdout)
    assert decision["reason_code"] == "ambiguous_exact_session_target"
    assert "Command: /usr/bin/python3" in decision["recovery"]
    assert "/scripts/session_end.py" in decision["recovery"]
    assert not (workspace / "ambiguous-write").exists()


def test_installed_gate_keeps_deterministic_authority_when_model_service_is_absent(
    tmp_path: Path,
) -> None:
    """Advisory model availability cannot add a block or grant authority."""
    if not INSTALLED_GATE.is_file():
        pytest.skip("installed combined gate is unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _claimed_repo(workspace, claims_dir, "first")
    _claimed_repo(workspace, claims_dir, "second")
    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    payload = {
        "session_id": "pw06-recovery",
        "cwd": str(workspace),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": "touch ambiguous-write"},
    }
    env = os.environ.copy()
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY"):
        env.pop(key, None)

    started = time.monotonic()
    completed = subprocess.run(
        [
            "/usr/bin/python3",
            str(INSTALLED_GATE),
            "--client",
            "claude-code",
            "--mode",
            "enforce",
            "--claims-dir",
            str(claims_dir),
            "--projection-path",
            str(projection_path),
            "--receipt-path",
            str(tmp_path / "receipts.jsonl"),
            "--outcome-receipt-path",
            str(tmp_path / "outcome-receipts.jsonl"),
            "--json",
        ],
        input=json.dumps(payload),
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )
    elapsed = time.monotonic() - started

    assert completed.returncode == 2, completed.stderr
    decision = json.loads(completed.stdout)
    assert decision["reason_code"] == "ambiguous_exact_session_target"
    assert "Command: /usr/bin/python3" in decision["recovery"]
    assert elapsed < 2.0, "the synchronous gate appears to wait on an external service"
    assert not (workspace / "ambiguous-write").exists()

def test_ended_claim_resumes_one_lane_and_preserves_edit_boundaries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A retained lane can resume, edit only its scope, and end without residue."""

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    claims_dir = tmp_path / "claims"
    trackers_dir = tmp_path / "trackers"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)

    lanes: dict[str, Path] = {}
    for name in ("first", "second"):
        repo = workspace / name
        repo.mkdir()
        _git(repo, "init", "-b", "main")
        _git(repo, "config", "user.name", "PW-06 Test")
        _git(repo, "config", "user.email", "pw06@example.com")
        (repo / "README.md").write_text(f"{name}\n", encoding="utf-8")
        _git(repo, "add", "README.md")
        _git(repo, "commit", "-m", "seed")
        worktree = repo / "worktrees" / f"{name}-lane"
        worktree.parent.mkdir()
        _git(repo, "worktree", "add", "-b", f"{name}-lane", str(worktree))
        lanes[name] = worktree
        session_lifecycle.start_session(
            agent="claude-code",
            project=name,
            scope=f"{name}-lane",
            intent="exercise retained-lane recovery",
            repo_root=str(repo),
            worktree_path=str(worktree),
            branch=f"{name}-lane",
            broader_goal="complete recovery and resume through combined hooks",
            current_phase="before runtime end",
            plan_ref="UNPLANNED",
            session_id=SESSION_ID,
            claim_type="write",
            write_paths=["README.md"],
            allow_unplanned=True,
            allow_parallel=True,
            tracker_dir=trackers_dir,
        )

    ended = session_lifecycle.end_runtime_session(
        agent="claude-code",
        session_id=SESSION_ID,
        reason="simulate a real client restart",
        claims_dir=claims_dir,
    )
    assert ended["ended_count"] == 2
    assert coordination_claims.check_claims(claims_dir=claims_dir) == []

    successor = "claude-code:pw06-successor"
    monkeypatch.setenv(
        coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS["claude-code"],
        "pw06-successor",
    )
    resumed = session_lifecycle.resume_session(
        agent="claude-code",
        project="first",
        scope="first-lane",
        worktree_path=str(lanes["first"]),
        branch="first-lane",
        current_phase="resume exact retained lane",
        session_id=successor,
    )
    assert resumed["action"] == "resumed"
    active = coordination_claims.check_claims(claims_dir=claims_dir)
    assert [(claim.primary_project(), claim.scope, claim.session_id) for claim in active] == [
        ("first", "first-lane", successor)
    ]

    projection_path = tmp_path / "projection.json"
    write_projection(claims_dir=claims_dir, projection_path=projection_path)
    base_payload: dict[str, object] = {
        "session_id": "pw06-successor",
        "cwd": str(lanes["first"]),
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
    }
    allowed_code, allowed = _run_gate(
        payload={**base_payload, "tool_input": {"command": "printf recovered >> README.md"}},
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_dir=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert allowed_code == 0, allowed
    assert allowed["decision"] == "allow"
    with (lanes["first"] / "README.md").open("a", encoding="utf-8") as handle:
        handle.write("recovered\n")
    assert _git(lanes["first"], "diff", "--name-only") == "README.md"
    assert _git(lanes["first"], "diff", "--", "README.md").endswith(
        "@@ -1 +1,2 @@\n first\n+recovered"
    )

    denied_code, denied = _run_gate(
        payload={**base_payload, "tool_input": {"command": "touch outside.txt"}},
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_dir=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert denied_code == 2, denied
    assert not (lanes["first"] / "outside.txt").exists()

    foreign_code, foreign = _run_gate(
        payload={
            **base_payload,
            "session_id": "pw06-foreign",
            "tool_input": {"command": "printf foreign >> README.md"},
        },
        claims_dir=claims_dir,
        projection_path=projection_path,
        receipt_dir=tmp_path,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    assert foreign_code == 2, foreign
    assert (lanes["first"] / "README.md").read_text(encoding="utf-8") == "first\nrecovered\n"

    reended = session_lifecycle.end_runtime_session(
        agent="claude-code",
        session_id=successor,
        reason="retain verified edit for disposition",
        claims_dir=claims_dir,
    )
    assert reended["ended_count"] == 1
    assert coordination_claims.check_claims(claims_dir=claims_dir) == []
    status = session_lifecycle.status_sessions(project="first", include_ended=True)
    assert status["sessions"][0]["claim_status"] == "session_ended"
    assert status["sessions"][0]["recovery_action"] == "resume_take_over_or_close_preserved_lane"
