"""Focused performance-contract tests for turn-end repository safety."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from enforced_planning import prewrite_claim_fast, prewrite_claim_projection
from enforced_planning.coordination_messages import (
    CoordinationMessageStore,
    ExactSessionSelector,
    MessageStatusRequest,
    SendMessageRequest,
    SessionInboxNotice,
)
from scripts import coordination_hook
from scripts.hook_receipts import load_completed_receipts


def test_meta_wrapper_bootstraps_script_imports_outside_repository(tmp_path: Path) -> None:
    """The project-local native wrapper must not depend on its launch cwd."""

    wrapper = Path(__file__).resolve().parents[1] / "scripts" / "meta" / "coordination_hook.py"

    completed = subprocess.run(
        [sys.executable, str(wrapper), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "Expose canonical mailbox requests" in completed.stdout
    assert "ModuleNotFoundError" not in completed.stderr


def test_stop_refire_returns_before_receipts_or_projection(monkeypatch, tmp_path: Path) -> None:
    payload = {
        "hook_event_name": "Stop",
        "session_id": "repeat-stop",
        "cwd": str(tmp_path),
        "stop_hook_active": True,
    }
    monkeypatch.setattr(
        coordination_hook,
        "_read_hook_input",
        lambda **_kwargs: payload,
    )

    def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("repeat Stop reached fallible hook state")

    monkeypatch.setattr(coordination_hook, "start_hook_invocation", unexpected)
    monkeypatch.setattr(coordination_hook, "_active_claims", unexpected)

    assert coordination_hook.main(["--hook-receipt-dir", str(tmp_path / "receipts")]) == 0


@pytest.mark.parametrize("agent", ("codex", "claude-code"))
@pytest.mark.parametrize("event_name", sorted(coordination_hook.SUPPORTED_EVENTS))
@pytest.mark.parametrize("secondary", (False, True))
def test_mailbox_only_isolates_every_native_boundary(
    monkeypatch, tmp_path: Path, capsys, agent: str, event_name: str, secondary: bool
) -> None:
    """Corrupt claims and dirty, incomplete work cannot affect mailbox delivery."""

    repository = tmp_path / "repository"
    subprocess.run(["git", "init", "-q", str(repository)], check=True)
    (repository / "dirty.txt").write_text("unsaved work\n", encoding="utf-8")
    (repository / "meta-process.yaml").write_text(
        "meta_process:\n  claims:\n    outcome_completion_mode: enforce_selected\n",
        encoding="utf-8",
    )
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    (claims_dir / "corrupt.yaml").write_text("invalid: [", encoding="utf-8")
    prewrite_claim_fast.projection_path_for(claims_dir).write_text("{", encoding="utf-8")
    ledger_dir = tmp_path / "ledgers"
    ledger_dir.mkdir()
    (ledger_dir / "corrupt.json").write_text("{", encoding="utf-8")
    payload = {
        "session_id": "mailbox-only-root", "cwd": str(repository),
        "hook_event_name": event_name, "event_id": "native-boundary",
        "tool_name": "Bash", "tool_input": {"command": "git commit -am work"},
        "completion_attempt": True, "last_assistant_message": "complete",
    }
    if secondary:
        payload["agent_id"] = "child-agent"
    monkeypatch.setattr(coordination_hook, "_read_hook_input", lambda **_kwargs: payload)

    def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("mailbox-only invoked an ancillary gate")

    for name in (
        "_is_completion_shaped_stop", "_outcome_stop_decisions", "_active_claims",
        "_startup_claims", "_startup_claim_summary", "_claimed_projects",
        "_write_closeout_baseline", "_record_touched_repositories",
        "_repository_closeout_failure", "_repository_closeout_gate_disabled",
        "_closeout_ledger_path",
    ):
        monkeypatch.setattr(coordination_hook, name, unexpected)
    monkeypatch.setattr(coordination_hook.coordination_claims, "heartbeat_claims", unexpected)
    monkeypatch.setattr(coordination_hook.coordination_claims, "list_claims", unexpected)
    monkeypatch.setattr(
        coordination_hook.outcome_completion, "evaluate_stop_for_session", unexpected
    )
    calls = []
    real_poll = coordination_hook.coordination_messages.poll_session_inbox

    def poll(**kwargs: object) -> SessionInboxNotice:
        assert not secondary, "secondary execution inspected the primary inbox"
        calls.append(kwargs)
        return real_poll(**kwargs)

    monkeypatch.setattr(coordination_hook.coordination_messages, "poll_session_inbox", poll)
    receipts = tmp_path / "receipts"
    assert coordination_hook.main([
        "--agent", agent, "--mailbox-only", "--claims-dir", str(claims_dir),
        "--root", str(tmp_path / "messages"), "--closeout-ledger-dir", str(ledger_dir),
        "--hook-receipt-dir", str(receipts),
    ]) == 0
    assert capsys.readouterr().out == ""
    assert len(calls) == (0 if secondary else 1)
    if calls:
        assert calls[0]["session_id"] == f"{agent}:mailbox-only-root"
        assert calls[0]["require_live_claim"] is False
        assert calls[0]["observe"] is (event_name != "PostToolUse")
        assert (calls[0]["delivery_event_id"] is None) is (event_name in {"PreToolUse", "Stop"})
    completed = list(load_completed_receipts(receipts))
    assert [receipt["decision"] for receipt in completed] == ["allow"]
    assert completed[0]["reason_code"] == (
        "secondary_execution_callback" if secondary else "no_active_boundary"
    )
    assert sorted(path.name for path in ledger_dir.iterdir()) == ["corrupt.json"]


@pytest.mark.parametrize("agent", ("codex", "claude-code"))
@pytest.mark.parametrize("completion", (
    {"completion_attempt": True},
    {"last_assistant_message": "complete"},
    {"last_assistant_message": "**Recommended next** — complete"},
))
def test_mailbox_only_repeat_stop_returns_before_all_fallible_state(
    monkeypatch, tmp_path: Path, capsys, agent: str, completion: dict[str, object]
) -> None:
    payload = {
        "hook_event_name": "Stop", "session_id": "repeat-stop",
        "cwd": str(tmp_path), "stop_hook_active": True, **completion,
    }
    monkeypatch.setattr(coordination_hook, "_read_hook_input", lambda **_kwargs: payload)

    def unexpected(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("repeat Stop accessed fallible state")

    for name in ("_is_completion_shaped_stop", "start_hook_invocation", "_active_claims"):
        monkeypatch.setattr(coordination_hook, name, unexpected)
    monkeypatch.setattr(coordination_hook.coordination_messages, "poll_session_inbox", unexpected)
    assert coordination_hook.main([
        "--agent", agent, "--mailbox-only", "--hook-receipt-dir", str(tmp_path / "receipts")
    ]) == 0
    assert capsys.readouterr().out == "{}\n"
    assert not (tmp_path / "receipts").exists()


def test_posttool_is_advisory_and_secondary_agent_cannot_poll_root_inbox(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Only the root polls, and PostTool never creates observation evidence."""

    payload: dict[str, object] = {}
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _self: json.dumps(payload)})(),
    )
    monkeypatch.setattr(coordination_hook, "_active_claims", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "heartbeat_claims",
        lambda **_kwargs: (),
    )

    def poll(**kwargs: object) -> SessionInboxNotice:
        calls.append(kwargs)
        return SessionInboxNotice(
            session_id=str(kwargs["session_id"]),
            project="demo",
            active_count=0,
            message_ids=(),
            summary="",
        )

    monkeypatch.setattr(coordination_hook.coordination_messages, "poll_session_inbox", poll)
    arguments = [
        "--claims-dir",
        str(tmp_path / "claims"),
        "--root",
        str(tmp_path / "messages"),
        "--hook-receipt-dir",
        str(tmp_path / "receipts"),
    ]

    payload.update(
        session_id="shared-session",
        cwd="/tmp",
        hook_event_name="UserPromptSubmit",
        hook_run_id="user_prompt_submit:1:/config.toml",
        event_id="prompt-one",
    )
    assert coordination_hook.main(arguments) == 0
    capsys.readouterr()
    payload.update(
        hook_event_name="PostToolUse",
        hook_run_id="post_tool_use:2:/config.toml",
        event_id="root-posttool",
    )
    assert coordination_hook.main(arguments) == 0
    capsys.readouterr()
    payload.update(
        agent_id="child-agent",
        hook_run_id="post_tool_use:3:/config.toml",
        event_id="secondary-posttool",
    )
    assert coordination_hook.main(arguments) == 0
    capsys.readouterr()

    assert [call["observe"] for call in calls] == [True, False]


def test_secondary_callback_leaves_obligation_for_root_next_pretool(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """Maintenance-mode settings cannot let a secondary callback consume the root gate."""

    payload: dict[str, object] = {}
    poll_count = 0
    monkeypatch.setenv("ENFORCED_PLANNING_HOOK_MODE", "off")
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _self: json.dumps(payload)})(),
    )
    monkeypatch.setattr(coordination_hook, "_active_claims", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_record_touched_repositories", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "heartbeat_claims",
        lambda **_kwargs: (),
    )

    def poll(**kwargs: object) -> SessionInboxNotice:
        nonlocal poll_count
        poll_count += 1
        active = poll_count > 2
        return SessionInboxNotice(
            session_id=str(kwargs["session_id"]),
            project="demo",
            active_count=1 if active else 0,
            message_ids=("msg_" + "1" * 32,) if active else (),
            summary="ACKNOWLEDGEMENT REQUIRED" if active else "",
        )

    class FakeStore:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def record_boundary_block(self, **_kwargs: object) -> None:
            pass

    monkeypatch.setattr(coordination_hook.coordination_messages, "poll_session_inbox", poll)
    monkeypatch.setattr(coordination_hook.coordination_messages, "CoordinationMessageStore", FakeStore)
    arguments = [
        "--claims-dir",
        str(tmp_path / "claims"),
        "--root",
        str(tmp_path / "messages"),
        "--hook-receipt-dir",
        str(tmp_path / "receipts"),
    ]

    payload.update(
        session_id="shared-session",
        cwd="/tmp",
        hook_event_name="SessionStart",
        event_id="session-start",
    )
    assert coordination_hook.main(arguments) == 0
    capsys.readouterr()
    payload.update(
        session_id="shared-session",
        cwd="/tmp",
        hook_event_name="UserPromptSubmit",
        hook_run_id="user_prompt_submit:1:/config.toml",
        event_id="prompt-one",
    )
    assert coordination_hook.main(arguments) == 0
    capsys.readouterr()
    payload.update(
        hook_event_name="PostToolUse",
        agent_id="child-agent",
        hook_run_id="post_tool_use:2:/config.toml",
        event_id="secondary-posttool",
    )
    assert coordination_hook.main(arguments) == 0
    assert capsys.readouterr().out == ""
    payload.pop("agent_id")
    payload.update(
        hook_event_name="PreToolUse",
        hook_run_id="pre_tool_use:3:/config.toml",
        tool_use_id="root-next-tool",
        tool_name="Bash",
        tool_input={"command": "git status --short"},
    )
    assert coordination_hook.main(arguments) == 0
    denial = json.loads(capsys.readouterr().out)

    assert poll_count == 3
    assert denial["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "ACKNOWLEDGEMENT REQUIRED" in denial["hookSpecificOutput"][
        "permissionDecisionReason"
    ]


def test_real_subprocess_secondary_posttool_preserves_root_pretool_obligation(
    tmp_path: Path,
) -> None:
    """Exercise the native JSON process boundary with one session and two runs."""

    claims_dir = tmp_path / "coordination" / "claims"
    message_root = tmp_path / "coordination" / "messages-v1"
    claims_dir.mkdir(parents=True)
    for agent, session_id, scope in (
        ("codex", "codex:shared-session", "recipient"),
        ("claude-code", "claude-code:sender", "sender"),
    ):
        (claims_dir / f"{agent}_{scope}.yaml").write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "agent": agent,
                    "projects": ["enforced-planning"],
                    "scope": scope,
                    "intent": scope,
                    "claim_type": "program",
                    "write_paths": [],
                    "read_paths": [],
                    "session_id": session_id,
                    "status": "active",
                    "claimed_at": "2026-09-01T19:00:00+00:00",
                    "expires_at": "2099-09-01T19:00:00+00:00",
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    store = CoordinationMessageStore(root=message_root, claims_dir=claims_dir)
    command = [
        sys.executable,
        "scripts/coordination_hook.py",
        "--claims-dir",
        str(claims_dir),
        "--root",
        str(message_root),
        "--hook-receipt-dir",
        str(tmp_path / "hook-receipts"),
    ]
    cwd = Path(__file__).resolve().parents[1]
    initial_boundary = {
        "session_id": "shared-session",
        "cwd": str(cwd),
        "hook_event_name": "PreToolUse",
        "hook_run_id": "pre_tool_use:1:/config.toml",
        "tool_use_id": "initial-root-tool",
        "tool_name": "Bash",
        "tool_input": {"command": "git status --short"},
    }
    initial = subprocess.run(
        command,
        input=json.dumps(initial_boundary),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert initial.returncode == 0, initial.stderr or initial.stdout
    assert initial.stdout == ""
    persisted = store.send(
        SendMessageRequest(
            caller_session_id="claude-code:sender",
            sender_session_id="claude-code:sender",
            recipient=ExactSessionSelector(
                kind="session", session_id="codex:shared-session"
            ),
            project="enforced-planning",
            kind="coordination_request",
            subject="Root must see this",
            body="Do not let a secondary callback consume this obligation.",
        )
    )
    secondary = subprocess.run(
        command,
        input=json.dumps(
            {
                "session_id": "shared-session",
                "agent_id": "child-agent",
                "cwd": str(cwd),
                "hook_event_name": "PostToolUse",
                "hook_run_id": "post_tool_use:2:/config.toml",
                "tool_use_id": "secondary-tool",
                "tool_name": "Bash",
            }
        ),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert secondary.returncode == 0, secondary.stderr or secondary.stdout
    assert secondary.stdout == ""
    assert store.status(
        MessageStatusRequest(message_id=persisted.message.message_id)
    ).state == "persisted"

    root_next = subprocess.run(
        command,
        input=json.dumps(
            {
                **initial_boundary,
                "hook_run_id": "pre_tool_use:3:/config.toml",
                "tool_use_id": "root-next-tool",
            }
        ),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )
    assert root_next.returncode == 0, root_next.stderr or root_next.stdout
    denial = json.loads(root_next.stdout)["hookSpecificOutput"]
    assert denial["permissionDecision"] == "deny"
    assert persisted.message.message_id in denial["permissionDecisionReason"]
    assert store.status(
        MessageStatusRequest(message_id=persisted.message.message_id)
    ).state == "observed"


def test_repository_statuses_are_collected_concurrently(monkeypatch, tmp_path: Path) -> None:
    repositories = tuple(tmp_path / f"repo-{index}" for index in range(8))
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_status(_repository: Path) -> dict[str, object]:
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"fingerprint": "same", "dirty": False, "entry_count": 0}

    monkeypatch.setattr(coordination_hook, "_repository_status", fake_status)

    snapshot = coordination_hook._repository_statuses(repositories)

    assert len(snapshot) == len(repositories)
    assert max_active > 1


def test_active_claims_use_digest_bound_projection_without_yaml_parse(
    monkeypatch, tmp_path: Path
) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = claims_dir / "claim.yaml"
    claim_path.write_text("status: active\n", encoding="utf-8")
    projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1(
        generated_at=datetime.now(UTC),
        claims_dir=str(claims_dir.resolve()),
        registry_digest=prewrite_claim_fast.registry_digest(claims_dir),
        claims=(
            prewrite_claim_projection.PreWriteAuthorityClaimV1(
                agent="codex",
                projects=("demo",),
                scope="fast-stop",
                claim_type="write",
                session_id="codex:session",
                repo_root=str(tmp_path / "demo"),
                worktree_path=str(tmp_path / "demo" / "worktrees" / "fast-stop"),
                branch="fast-stop",
                write_paths=("src",),
                expires_at=None,
                heartbeat_at=None,
                status="active",
                source_file=str(claim_path),
                source_sha256="a" * 64,
                static_issues=(),
            ),
        ),
    )
    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    projection_path.write_text(projection.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "check_claims",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("parsed YAML registry")),
    )

    claims = coordination_hook._active_claims(claims_dir)

    assert [claim.scope for claim in claims] == ["fast-stop"]


def _write_live_claim(claims_dir: Path, *, scope: str = "repair-stop") -> Path:
    claim = claims_dir / f"{scope}.yaml"
    claim.write_text(
        yaml.safe_dump(
            {
                "agent": "codex",
                "projects": ["demo"],
                "scope": scope,
                "intent": "test",
                "claim_type": "write",
                "write_paths": ["src"],
                "session_id": "codex:session",
                "repo_root": str(claims_dir.parent / "demo"),
                "worktree_path": str(claims_dir.parent / "demo" / "worktrees" / scope),
                "branch": scope,
                "status": "active",
            }
        ),
        encoding="utf-8",
    )
    return claim


def test_stop_repairs_stale_projection_before_turn_end_check(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    time.sleep(0.002)
    _write_live_claim(claims_dir)

    claims = coordination_hook._active_claims(claims_dir, turn_end=True)

    assert [claim.scope for claim in claims] == ["repair-stop"]


def test_stop_repairs_malformed_projection_before_turn_end_check(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _write_live_claim(claims_dir, scope="malformed-stop")
    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    projection_path.write_text("not-json\n", encoding="utf-8")
    # Keep the malformed projection newer than the claim so validation, not
    # the mtime crash-window hint, triggers the bounded repair.
    projection_path.touch()

    claims = coordination_hook._active_claims(claims_dir, turn_end=True)

    assert [claim.scope for claim in claims] == ["malformed-stop"]


def test_stop_repairs_projection_after_claim_deletion(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    claim_path = _write_live_claim(claims_dir, scope="deleted-stop")
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    time.sleep(0.002)
    claim_path.unlink()

    claims = coordination_hook._active_claims(claims_dir, turn_end=True)

    assert claims == ()


def test_projection_repair_rechecks_under_lock_before_rebuilding(
    monkeypatch, tmp_path: Path
) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _write_live_claim(claims_dir, scope="writer-completed")
    real_refresh = coordination_hook.coordination_claims.refresh_prewrite_authority_projection

    @contextmanager
    def writer_finishes_before_lock_acquisition(_claims_dir: Path):
        real_refresh(claims_dir)
        yield

    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "claim_registry_lock",
        writer_finishes_before_lock_acquisition,
    )
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "refresh_prewrite_authority_projection",
        lambda _claims_dir: (_ for _ in ()).throw(
            AssertionError("repair redundantly rebuilt a current projection")
        ),
    )

    result = coordination_hook._repair_projection_under_lock(claims_dir)

    assert result["action"] == "already_current"
    assert result["last_phase"] == "complete"
    assert result["lock_wait_ms"] >= 0
    assert result["total_ms"] >= result["lock_wait_ms"]


def test_stop_repair_waits_for_real_writer_then_uses_its_projection(tmp_path: Path) -> None:
    """Exercise the real process/lock race that produced the native Stop warning."""

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    time.sleep(0.002)
    _write_live_claim(claims_dir, scope="contended-stop")
    ready_path = tmp_path / "writer-holds-lock"
    writer = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys,time; from pathlib import Path; "
                "from enforced_planning import coordination_claims; "
                "claims=Path(sys.argv[1]); ready=Path(sys.argv[2]); "
                "lock=coordination_claims.claim_registry_lock(claims); lock.__enter__(); "
                "ready.write_text('locked', encoding='utf-8'); time.sleep(0.35); "
                "coordination_claims.refresh_prewrite_authority_projection(claims); "
                "lock.__exit__(None, None, None)"
            ),
            str(claims_dir),
            str(ready_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 2
    while not ready_path.is_file() and writer.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready_path.is_file(), writer.communicate(timeout=1)[1]

    started = time.monotonic()
    claims = coordination_hook._active_claims(claims_dir, turn_end=True)
    elapsed = time.monotonic() - started
    stdout, stderr = writer.communicate(timeout=2)

    assert writer.returncode == 0, (stdout, stderr)
    assert [claim.scope for claim in claims] == ["contended-stop"]
    assert 0.2 <= elapsed < coordination_hook.TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS


def test_projection_repair_timeout_names_last_observed_phase(monkeypatch, tmp_path: Path) -> None:
    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(
            cmd=["repair"],
            timeout=coordination_hook.TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS,
            stderr="projection_repair_phase=lock_wait\n",
        )

    monkeypatch.setattr(coordination_hook.subprocess, "run", timeout)

    try:
        coordination_hook._repair_turn_end_projection(tmp_path / "claims")
    except coordination_hook.TurnEndProjectionError as exc:
        assert "last_phase=lock_wait" in str(exc)
    else:
        raise AssertionError("timed-out projection repair must remain visible")


def test_stop_warns_when_projection_repair_remains_unavailable(monkeypatch, tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _write_live_claim(claims_dir)
    monkeypatch.setattr(
        coordination_hook,
        "_repair_turn_end_projection",
        lambda _claims_dir: (_ for _ in ()).throw(coordination_hook.TurnEndProjectionError("timed out")),
    )

    try:
        coordination_hook._active_claims(claims_dir, turn_end=True)
    except coordination_hook.TurnEndProjectionError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("turn-end repair failure must remain visible")


def test_stop_projection_only_failure_warns_without_blocking(monkeypatch, tmp_path: Path, capsys) -> None:
    monkeypatch.setattr(
        coordination_hook,
        "_active_claims",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(coordination_hook.TurnEndProjectionError("timed out")),
    )
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(coordination_hook, "_repository_closeout_failure", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type("Notice", (), {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()})(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "Input",
            (),
            {
                "read": lambda _self: json.dumps(
                    {
                        "session_id": "stop-warning",
                        "cwd": "/tmp",
                        "hook_event_name": "Stop",
                        "last_assistant_message": "terminal",
                    }
                )
            },
        )(),
    )

    assert coordination_hook.main(["--claims-dir", str(tmp_path / "claims"), "--hook-receipt-dir", str(tmp_path / "receipts")]) == 0
    output = json.loads(capsys.readouterr().out)
    assert "decision" not in output
    assert "turn-end claim projection unavailable" in output["systemMessage"]


def test_session_start_does_not_load_claim_projection(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        coordination_hook,
        "_active_claims",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("startup scanned claims")),
    )
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type("Notice", (), {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()})(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _self: '{"session_id":"fresh","cwd":"/tmp","hook_event_name":"SessionStart"}'})(),
    )

    assert coordination_hook.main(["--claims-dir", str(tmp_path / "claims"), "--hook-receipt-dir", str(tmp_path / "receipts")]) == 0


def test_root_override_derives_fixture_local_hook_receipts(monkeypatch, tmp_path: Path) -> None:
    root = tmp_path / "coordination" / "messages-v1"
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type("Notice", (), {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()})(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _self: '{"session_id":"local","cwd":"/tmp","hook_event_name":"SessionStart"}'})(),
    )

    assert coordination_hook.main(["--claims-dir", str(tmp_path / "claims"), "--root", str(root)]) == 0
    assert len(load_completed_receipts(root.parent / "hook-invocations-v1")) == 1


def test_session_start_skips_heartbeat_with_large_completed_registry(monkeypatch, tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    for index in range(1_500):
        (claims_dir / f"completed-{index:04d}.yaml").write_text("status: completed\n", encoding="utf-8")
    monkeypatch.setattr(
        coordination_hook,
        "_active_claims",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("startup scanned claims")),
    )
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "heartbeat_claims",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("startup heartbeated claims")),
    )
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type("Notice", (), {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()})(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type("Input", (), {"read": lambda _self: '{"session_id":"large","cwd":"/tmp","hook_event_name":"SessionStart"}'})(),
    )

    started = time.monotonic()
    assert coordination_hook.main(["--claims-dir", str(claims_dir), "--hook-receipt-dir", str(tmp_path / "receipts")]) == 0
    assert time.monotonic() - started < 1.0


def test_startup_claims_filter_canonical_live_statuses_without_yaml_parse(
    monkeypatch, tmp_path: Path
) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    source = claims_dir / "claim.yaml"
    source.write_text("status: active\n", encoding="utf-8")
    claims = tuple(
        prewrite_claim_projection.PreWriteAuthorityClaimV1(
            agent="codex",
            projects=("demo",),
            scope=status,
            claim_type="write",
            session_id=f"codex:{status}",
            repo_root=str(tmp_path / "demo"),
            worktree_path=str(tmp_path / "demo" / "worktrees" / status),
            branch=status,
            write_paths=("src",),
            expires_at=None,
            heartbeat_at=None,
            status=status,
            source_file=str(source),
            source_sha256="a" * 64,
            static_issues=(),
        )
        for status in ("active", "blocked", "handoff", "completed")
    )
    projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1(
        generated_at=datetime.now(UTC),
        claims_dir=str(claims_dir.resolve()),
        registry_digest=prewrite_claim_fast.registry_digest(claims_dir),
        claims=claims,
    )
    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    projection_path.write_text(projection.model_dump_json(), encoding="utf-8")
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "check_claims",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("startup parsed YAML registry")),
    )

    live, warning = coordination_hook._startup_claims(claims_dir)

    assert warning is None
    assert [claim.status for claim in live] == ["active", "blocked", "handoff"]


def test_startup_claims_reject_stale_projection_without_adopting_claim(tmp_path: Path) -> None:
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    time.sleep(0.002)
    _write_live_claim(claims_dir, scope="stale-startup")

    claims, warning = coordination_hook._startup_claims(claims_dir)

    assert claims == ()
    assert warning is not None
    assert "projection is stale" in warning
    assert "no assignment was adopted" in warning


def test_startup_claims_wait_for_real_writer_then_use_completed_projection(tmp_path: Path) -> None:
    """Startup must not observe the sanctioned claim/projection transaction mid-write."""

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    ready_path = tmp_path / "writer-mutated-claim"
    writer = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import sys,time; from pathlib import Path; "
                "from enforced_planning import coordination_claims; "
                "claims=Path(sys.argv[1]); ready=Path(sys.argv[2]); "
                "lock=coordination_claims.claim_registry_lock(claims); lock.__enter__(); "
                "claim=claims/'startup-race.yaml'; "
                "claim.write_text('agent: codex\\nprojects: [demo]\\nscope: startup-race\\nintent: test\\n' "
                "+ 'claim_type: write\\nwrite_paths: [src]\\nsession_id: codex:session\\n' "
                "+ f'repo_root: {claims.parent / \"demo\"}\\n' "
                "+ f'worktree_path: {claims.parent / \"demo\" / \"worktrees\" / \"startup-race\"}\\n' "
                "+ 'branch: startup-race\\nstatus: active\\n', encoding='utf-8'); "
                "ready.write_text('mutated', encoding='utf-8'); time.sleep(0.35); "
                "coordination_claims.refresh_prewrite_authority_projection(claims); "
                "lock.__exit__(None, None, None)"
            ),
            str(claims_dir),
            str(ready_path),
        ],
        cwd=Path(__file__).resolve().parents[1],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + 2
    while not ready_path.is_file() and writer.poll() is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert ready_path.is_file(), writer.communicate(timeout=1)[1]

    started = time.monotonic()
    claims, warning = coordination_hook._startup_claims(claims_dir)
    elapsed = time.monotonic() - started
    stdout, stderr = writer.communicate(timeout=2)

    assert writer.returncode == 0, (stdout, stderr)
    assert warning is None
    assert [claim.scope for claim in claims] == ["startup-race"]
    assert 0.2 <= elapsed < coordination_hook.STARTUP_PROJECTION_READ_LOCK_TIMEOUT_SECONDS


def test_shared_startup_labels_exact_owner_and_other_session_as_global_context() -> None:
    def claim(agent: str, session_id: str, scope: str) -> object:
        return type(
            "ProjectedClaim",
            (),
            {
                "agent": agent,
                "session_id": session_id,
                "scope": scope,
                "status": "active",
                "projects": ("demo",),
            },
        )()

    claims = (
        claim("codex", "codex:current", "owned-lane"),
        claim("claude-code", "claude-code:other", "other-lane"),
    )

    codex = coordination_hook._startup_claim_summary(
        agent="codex", session_id="codex:current", project="demo", claims=claims
    )
    claude = coordination_hook._startup_claim_summary(
        agent="claude-code", session_id="claude-code:other", project="demo", claims=claims
    )

    assert codex is not None and "Current session ownership: project=demo; scope=owned-lane" in codex
    assert codex is not None and "Global context (not your current work): project=demo; scope=other-lane" in codex
    assert claude is not None and "Current session ownership: project=demo; scope=other-lane" in claude
    assert claude is not None and "Global context (not your current work): project=demo; scope=owned-lane" in claude


def test_pretool_gate_never_heartbeats_or_rebuilds_claim_state(monkeypatch, tmp_path: Path) -> None:
    """The latency-sensitive gate must remain a projection read, not a registry write."""

    monkeypatch.setattr(
        coordination_hook,
        "_active_claims",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("PreToolUse scanned the claim registry")
        ),
    )
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_record_touched_repositories", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(
        coordination_hook.coordination_claims,
        "heartbeat_claims",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("PreToolUse heartbeated claims")),
    )
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type(
            "Notice",
            (),
            {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()},
        )(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "Input",
            (),
            {
                "read": lambda _self: json.dumps(
                    {
                        "session_id": "pretool",
                        "cwd": str(tmp_path),
                        "hook_event_name": "PreToolUse",
                        "tool_name": "apply_patch",
                        "tool_use_id": "tool-pretool",
                        "tool_input": {"patch": "*** Begin Patch\n*** End Patch"},
                    }
                )
            },
        )(),
    )

    assert coordination_hook.main(
        [
            "--claims-dir",
            str(tmp_path / "claims"),
            "--hook-receipt-dir",
            str(tmp_path / "receipts"),
        ]
    ) == 0


def test_native_shaped_stop_repairs_interrupted_projection_and_allows_turn(tmp_path: Path) -> None:
    claims_dir = tmp_path / "coordination" / "claims"
    claims_dir.mkdir(parents=True)
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    time.sleep(0.002)
    _write_live_claim(claims_dir, scope="native-stop")

    completed = subprocess.run(
        [
            sys.executable,
            str(Path(coordination_hook.__file__).resolve()),
            "--claims-dir",
            str(claims_dir),
            "--root",
            str(tmp_path / "coordination" / "messages-v1"),
            "--closeout-ledger-dir",
            str(tmp_path / "coordination" / "ledgers"),
            "--hook-receipt-dir",
            str(tmp_path / "coordination" / "receipts"),
        ],
        input=json.dumps(
            {
                "session_id": "session",
                "cwd": str(Path(__file__).resolve().parents[1]),
                "hook_event_name": "Stop",
                "hook_run_id": "stop:native-repair",
                "last_assistant_message": "terminal report",
            }
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    claims = coordination_hook._active_claims(claims_dir)
    assert [claim.scope for claim in claims] == ["native-stop"]


def test_posttool_repairs_stale_projection_instead_of_discarding_the_turn(tmp_path: Path) -> None:
    """The non-Stop path must get the bounded repair the Stop path already has.

    Same fixture as `test_stop_repairs_stale_projection_before_turn_end_check`,
    with `turn_end=False`. Before this, the repair was reachable only from `Stop`,
    so a PostToolUse event that arrived while the projection was momentarily
    behind raised and the handler threw away the claims notice and the mailbox
    summary it had already assembled. The message
    "active-claim projection is stale relative to the canonical claim registry"
    appears 1,972 times in this machine's Claude Code transcripts.

    The staleness is transient by construction: the registry is the authority,
    the projection is derived from it, and the repair takes the registry lock.
    Run by hand against a settled registry the repair returns `already_current`
    and the digests then match, which is why refusing without attempting it was
    never the safe choice -- only the loud one.
    """

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    coordination_hook.coordination_claims.refresh_prewrite_authority_projection(claims_dir)
    time.sleep(0.002)
    _write_live_claim(claims_dir, scope="repair-posttool")

    claims = coordination_hook._active_claims(claims_dir)

    assert [claim.scope for claim in claims] == ["repair-posttool"]


def test_posttool_projection_failure_is_not_recorded_as_a_block(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """A PostToolUse event blocks nothing, so its receipt must not say `block`.

    On `Stop` the handler renders a real boundary denial. On every other event it
    prints a `systemMessage` and returns 0 -- nothing is blocked -- and it still
    completed the receipt with `decision="block"`. 164 of the 171 blocks across
    the three runs read on 2026-09-06 were this, and every one of them was a
    PostToolUse event where nothing was denied.

    A governance record that reports blocks it did not make is worse than no
    record: it is the number someone quotes.
    """

    monkeypatch.setattr(
        coordination_hook,
        "_active_claims",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            coordination_hook.RepositoryCloseoutError("active-claim projection is stale")
        ),
    )
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_repository_closeout_failure", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type(
            "Notice", (), {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()}
        )(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "Input",
            (),
            {
                "read": lambda _self: json.dumps(
                    {"session_id": "posttool-stale", "cwd": "/tmp", "hook_event_name": "PostToolUse"}
                )
            },
        )(),
    )

    receipts = tmp_path / "receipts"
    assert coordination_hook.main(
        ["--claims-dir", str(tmp_path / "claims"), "--hook-receipt-dir", str(receipts)]
    ) == 0

    output = json.loads(capsys.readouterr().out)
    assert "decision" not in output, "PostToolUse must not render a denial"

    completed = list(load_completed_receipts(receipts))
    assert len(completed) == 1
    receipt = completed[0]
    assert receipt["decision"] == "warn", (
        "the handler printed a warning and returned 0; recording that as a block "
        "makes the governance record overstate what AES actually did"
    )
    assert receipt["reason_code"] == "turn_end_repository_safety_unavailable"


def test_stop_projection_failure_is_still_recorded_as_a_block(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    """The counterpart control: on Stop a denial is rendered, so `block` is true.

    Without this, the fix above could be satisfied by never recording a block at
    all, which would hide the one event where AES does refuse something.
    """

    monkeypatch.setattr(
        coordination_hook,
        "_active_claims",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            coordination_hook.RepositoryCloseoutError("active-claim projection is stale")
        ),
    )
    monkeypatch.setattr(coordination_hook, "_canonical_project", lambda _cwd: "demo")
    monkeypatch.setattr(coordination_hook, "_write_closeout_baseline", lambda **_kwargs: None)
    monkeypatch.setattr(coordination_hook, "_repository_closeout_failure", lambda **_kwargs: None)
    monkeypatch.setattr(
        coordination_hook.coordination_messages,
        "poll_session_inbox",
        lambda **_kwargs: type(
            "Notice", (), {"active_count": 0, "acknowledgement_count": 0, "summary": "", "message_ids": ()}
        )(),
    )
    monkeypatch.setattr(
        "sys.stdin",
        type(
            "Input",
            (),
            {
                "read": lambda _self: json.dumps(
                    {
                        "session_id": "stop-stale",
                        "cwd": "/tmp",
                        "hook_event_name": "Stop",
                        "last_assistant_message": "terminal",
                    }
                )
            },
        )(),
    )

    receipts = tmp_path / "receipts"
    assert coordination_hook.main(
        ["--claims-dir", str(tmp_path / "claims"), "--hook-receipt-dir", str(receipts)]
    ) == 0

    receipt = load_completed_receipts(receipts)[0]
    assert receipt["decision"] == "block"


def test_the_repair_budget_covers_the_actual_worker(tmp_path: Path) -> None:
    """Package import alone cannot establish that the bounded worker works."""
    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    _write_live_claim(claims_dir, scope="budget-worker")

    result = coordination_hook._repair_turn_end_projection(claims_dir)

    assert result["action"] == "rebuilt"
    assert result["last_phase"] == "complete"
    projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1.model_validate_json(
        prewrite_claim_fast.projection_path_for(claims_dir).read_text(encoding="utf-8")
    )
    assert [claim.scope for claim in projection.claims] == ["budget-worker"]


def test_repair_timeout_is_an_explicit_parameter() -> None:
    """The budget is a named argument, so a caller can be read and tested.

    It was a module constant read inside the function, which is why the earlier
    per-event budget experiment could be written at all -- and why its cost was
    invisible until a real-subprocess test went red.
    """

    import inspect

    parameters = inspect.signature(coordination_hook._repair_turn_end_projection).parameters
    assert "timeout" in parameters
    assert parameters["timeout"].default == coordination_hook.TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS


def test_closeout_gate_marker_does_not_disable_message_delivery(monkeypatch, tmp_path: Path) -> None:
    """The split. Turning off the dirty-tree gate must not take delivery with it.

    On 2026-09-03 the dirty-repository half of this hook blocked turn end
    wrongly, and the fix replaced the whole Stop command in
    ~/.claude/settings.json with `true`. That silently disabled cross-session
    message delivery for every claude-code session on the host for six days,
    visible only as one warning line when somebody sent a message. These two
    concerns share a hook and a shape; they must not share a switch.
    """
    marker = tmp_path / "closeout-gate-disabled"
    monkeypatch.setattr(coordination_hook, "CLOSEOUT_GATE_DISABLE_MARKER", marker)

    assert coordination_hook._repository_closeout_gate_disabled() is False
    marker.write_text("disabled for a stated reason\n", encoding="utf-8")
    assert coordination_hook._repository_closeout_gate_disabled() is True

    # Delivery is decided by the inbox notice, never by this marker: nothing in
    # the mailbox path reads it.
    source = Path(coordination_hook.__file__).read_text(encoding="utf-8")
    call_sites = [
        line
        for line in source.splitlines()
        if "_repository_closeout_gate_disabled()" in line
        and not line.lstrip().startswith("def ")
    ]
    assert len(call_sites) == 1, f"the marker must gate one call site, found {call_sites}"
    guarded = source.split(call_sites[0])[1][:400]
    assert "_repository_closeout_failure(" in guarded


def test_closeout_gate_fails_safe_when_the_marker_cannot_be_read(monkeypatch) -> None:
    """An unreadable marker is not consent.

    A silently-skipped closeout check is how uncommitted work gets lost, so any
    error leaves the dirty-repository gate ENABLED.
    """

    class Unreadable:
        def is_file(self) -> bool:
            raise OSError("permission denied")

    monkeypatch.setattr(coordination_hook, "CLOSEOUT_GATE_DISABLE_MARKER", Unreadable())

    assert coordination_hook._repository_closeout_gate_disabled() is False
