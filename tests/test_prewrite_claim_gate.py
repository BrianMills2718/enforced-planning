"""Both-sign tests for native pre-write claim enforcement."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning.prewrite_claim_gate import (
    HookPayloadError,
    PreWriteRequestV1,
    adapt_hook_payload,
    evaluate_prewrite,
    load_prewrite_mode,
)


SESSION = "codex:thread-123"


def _git(repo: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repo_and_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "sample-project"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "seed")
    worktree = repo / "worktrees" / "claimed-lane"
    _git(repo, "worktree", "add", "-b", "claimed-lane", str(worktree))
    (worktree / "src").mkdir()
    (worktree / "src" / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(worktree, "add", "src/allowed.py")
    _git(worktree, "commit", "-m", "lane seed")
    return repo, worktree


def _write_claim(
    claims_dir: Path,
    *,
    repo: Path,
    worktree: Path,
    session_id: str = SESSION,
    write_paths: list[str] | None = None,
    status: str = "active",
) -> Path:
    claims_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    path = claims_dir / "codex_sample-project_claimed-lane.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["sample-project"],
                "scope": "claimed-lane",
                "intent": "test exact pre-write ownership",
                "claim_type": "write",
                "write_paths": write_paths or ["src/allowed.py"],
                "read_paths": [],
                "worktree_path": str(worktree),
                "repo_root": str(repo),
                "branch": "claimed-lane",
                "session_name": "test-prewrite-enforcement",
                "session_id": session_id,
                "heartbeat_at": now.isoformat(),
                "status": status,
                "updated_at": now.isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _request(worktree: Path, *paths: str, session_id: str = SESSION) -> PreWriteRequestV1:
    return PreWriteRequestV1(
        client="codex",
        hook_event_name="PreToolUse",
        tool_name="apply_patch",
        session_id=session_id,
        cwd=str(worktree),
        target_paths=paths,
    )


def _evaluate(
    request: PreWriteRequestV1,
    *,
    mode: str,
    claims_dir: Path,
    tmp_path: Path,
):
    return evaluate_prewrite(
        request,
        mode=mode,
        claims_dir=claims_dir,
        receipt_path=tmp_path / "receipts.jsonl",
        cache_dir=tmp_path / "cache",
    )


def test_exact_live_claim_allows_write(tmp_path: Path) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    claims_dir = tmp_path / "claims"
    _write_claim(claims_dir, repo=repo, worktree=worktree)

    decision = _evaluate(
        _request(worktree, "src/allowed.py"),
        mode="enforce",
        claims_dir=claims_dir,
        tmp_path=tmp_path,
    )

    assert decision.decision == "allow"
    assert decision.reason_code == "exact_live_claim"
    assert decision.claim_scope == "claimed-lane"
    assert decision.normalized_target_paths == ("src/allowed.py",)


@pytest.mark.parametrize(
    ("claim_session", "target", "expected_reason"),
    [
        (None, "src/allowed.py", "no_exact_claim"),
        ("codex:other-thread", "src/allowed.py", "no_exact_claim"),
        (SESSION, "src/not-claimed.py", "path_outside_claim"),
    ],
)
def test_missing_wrong_or_out_of_scope_claim_denied(
    tmp_path: Path,
    claim_session: str | None,
    target: str,
    expected_reason: str,
) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    claims_dir = tmp_path / "claims"
    if claim_session is not None:
        _write_claim(claims_dir, repo=repo, worktree=worktree, session_id=claim_session)

    decision = _evaluate(
        _request(worktree, target),
        mode="enforce",
        claims_dir=claims_dir,
        tmp_path=tmp_path,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == expected_reason


def test_unhealthy_claim_is_denied(tmp_path: Path) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    claims_dir = tmp_path / "claims"
    claim_path = _write_claim(claims_dir, repo=repo, worktree=worktree)
    payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    payload["heartbeat_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
    claim_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    decision = _evaluate(
        _request(worktree, "src/allowed.py"),
        mode="enforce",
        claims_dir=claims_dir,
        tmp_path=tmp_path,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "claim_not_healthy"
    assert "stale_session_heartbeat" in decision.details


def test_wrong_canonical_repo_root_does_not_authorize(tmp_path: Path) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    claims_dir = tmp_path / "claims"
    claim_path = _write_claim(claims_dir, repo=repo, worktree=worktree)
    payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    payload["repo_root"] = str(tmp_path / "different-repository")
    claim_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    decision = _evaluate(
        _request(worktree, "src/allowed.py"),
        mode="enforce",
        claims_dir=claims_dir,
        tmp_path=tmp_path,
    )

    assert decision.decision == "deny"
    assert decision.reason_code == "no_exact_claim"


def test_observe_mode_records_violation_but_does_not_deny(tmp_path: Path) -> None:
    _repo, worktree = _repo_and_worktree(tmp_path)
    claims_dir = tmp_path / "claims"

    decision = _evaluate(
        _request(worktree, "src/allowed.py"),
        mode="observe",
        claims_dir=claims_dir,
        tmp_path=tmp_path,
    )

    assert decision.decision == "observe_violation"
    assert decision.reason_code == "no_exact_claim"
    receipt = json.loads((tmp_path / "receipts.jsonl").read_text(encoding="utf-8"))
    assert receipt["decision"] == "observe_violation"
    assert "patch" not in receipt
    assert "command" not in receipt


def test_codex_and_claude_payloads_normalize_target_paths() -> None:
    codex = adapt_hook_payload(
        {
            "session_id": "thread-123",
            "cwd": "/repo/worktrees/lane",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: src/a.py\n*** Move to: src/b.py\n*** End Patch"
            },
        },
        client="codex",
    )
    claude = adapt_hook_payload(
        {
            "session_id": "session-456",
            "cwd": "/repo/worktrees/lane",
            "hook_event_name": "PreToolUse",
            "tool_name": "Edit",
            "tool_input": {"file_path": "/repo/worktrees/lane/src/a.py"},
        },
        client="claude-code",
    )

    assert codex.session_id == "codex:thread-123"
    assert codex.target_paths == ("src/a.py", "src/b.py")
    assert claude.session_id == "claude-code:session-456"
    assert claude.target_paths == ("/repo/worktrees/lane/src/a.py",)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {
            "session_id": "thread-123",
            "cwd": "/repo",
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {"command": "*** Begin Patch\n*** End Patch"},
        },
        {
            "session_id": "thread-123",
            "cwd": "/repo",
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "sed -i s/a/b/ file"},
        },
    ],
)
def test_malformed_or_unsupported_payload_fails_loud(payload: dict[str, object]) -> None:
    with pytest.raises(HookPayloadError):
        adapt_hook_payload(payload, client="codex")


def test_cached_allow_is_invalidated_when_claim_changes(tmp_path: Path) -> None:
    repo, worktree = _repo_and_worktree(tmp_path)
    claims_dir = tmp_path / "claims"
    claim_path = _write_claim(claims_dir, repo=repo, worktree=worktree)
    request = _request(worktree, "src/allowed.py")

    first = _evaluate(request, mode="enforce", claims_dir=claims_dir, tmp_path=tmp_path)
    second = _evaluate(request, mode="enforce", claims_dir=claims_dir, tmp_path=tmp_path)
    payload = yaml.safe_load(claim_path.read_text(encoding="utf-8"))
    payload["session_id"] = "codex:different-session"
    claim_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    third = _evaluate(request, mode="enforce", claims_dir=claims_dir, tmp_path=tmp_path)

    assert first.decision == "allow" and first.cache_hit is False
    assert second.decision == "allow" and second.cache_hit is True
    assert third.decision == "deny" and third.cache_hit is False


def test_load_prewrite_mode_reads_real_nested_meta_process_shape(tmp_path: Path) -> None:
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n  claims:\n    prewrite_mode: observe\n",
        encoding="utf-8",
    )

    assert load_prewrite_mode(tmp_path) == "observe"


def test_cli_denies_before_tool_and_observe_mode_never_blocks(tmp_path: Path) -> None:
    _repo, worktree = _repo_and_worktree(tmp_path)
    target = worktree / "src" / "allowed.py"
    before = target.read_bytes()
    payload = json.dumps(
        {
            "session_id": "thread-123",
            "cwd": str(worktree),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": "*** Begin Patch\n*** Update File: src/allowed.py\n*** End Patch"
            },
        }
    )
    command = [
        "python",
        "scripts/prewrite_claim_gate.py",
        "--client",
        "codex",
        "--claims-dir",
        str(tmp_path / "claims"),
        "--receipt-path",
        str(tmp_path / "receipts.jsonl"),
        "--cache-dir",
        str(tmp_path / "cache"),
    ]

    denied = subprocess.run(
        [*command, "--mode", "enforce"],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )
    observed = subprocess.run(
        [*command, "--mode", "observe"],
        input=payload,
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[1],
    )

    assert denied.returncode == 2
    assert "no_exact_claim" in denied.stderr
    assert target.read_bytes() == before
    assert observed.returncode == 0
    assert "OBSERVE ONLY" in observed.stdout
