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

import yaml

from enforced_planning import prewrite_claim_fast, prewrite_claim_projection
from scripts import coordination_hook


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
    assert len(list((root.parent / "hook-invocations-v1").rglob("completed.json"))) == 1


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
