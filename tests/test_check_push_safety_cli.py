"""Tests for check_push_safety.py's plain-text CLI output.

The real pre-push hook (hooks/git/pre-push) invokes this script without
--json, so the plain-text branch is the entrypoint a person actually reads --
not the JSON payload, which is only inspected directly or by tooling. Found
via /audit 2026-09-14: a real notification could succeed under the hood while
the plain-text output gave zero indication of it.
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]

from enforced_planning import claim_mutation_receipts, coordination_claims, push_safety

_SCRIPTS_DIR = str(Path(__file__).resolve().parents[1] / "scripts")
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

import check_push_safety  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_claim_mutation_ledger(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep this fixture out of the shared operator ledger, same as test_push_safety.py."""

    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_EVENTS_PATH",
        tmp_path / "claim-mutation-events.jsonl",
    )


def _init_git_repo(repo_root: Path) -> None:
    subprocess.run(["git", "init", "-b", "main", str(repo_root)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.name", "Test User"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "config", "user.email", "test@example.com"], check=True, capture_output=True, text=True)
    (repo_root / "README.md").write_text("seed\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "README.md"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "seed"], check=True, capture_output=True, text=True)


def _write_claim(claims_dir: Path, name: str, payload: dict) -> None:
    claims_dir.mkdir(parents=True, exist_ok=True)
    (claims_dir / name).write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_plain_text_output_surfaces_notification_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The real (no --json) entrypoint must show whether the other lane's
    owner was notified, not just the --json payload -- a person only ever
    sees this branch when `git push` actually hits a real conflict."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    other_worktree = tmp_path / "other"
    other_worktree.mkdir()
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-99-other"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('other lane version')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "other lane"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('pusher lane version')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "pusher lane"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    now = datetime.now(timezone.utc).isoformat()
    _write_claim(
        claims_dir,
        "pusher.yaml",
        {
            "agent": "claude-code", "claimed_at": now, "expires_at": "2099-01-01T00:00:00+00:00",
            "projects": ["demo"], "scope": "plan-42-demo", "intent": "Own current branch",
            "claim_type": "program", "plan_ref": "UNPLANNED", "branch": "plan-42-demo",
            "worktree_path": str(repo_root), "session_id": "claude-code:session-pusher",
            "session_name": "pusher", "heartbeat_at": now, "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other.yaml",
        {
            "agent": "claude-code", "claimed_at": now, "expires_at": "2099-01-01T00:00:00+00:00",
            "projects": ["demo"], "scope": "reviewed-scope", "intent": "Touch feature file",
            "claim_type": "write", "write_paths": ["feature.py"], "branch": "plan-99-other",
            "worktree_path": str(other_worktree), "session_id": "claude-code:session-other",
            "status": "active",
        },
    )

    sent_calls: list[dict] = []

    def _fake_route_concern(**kwargs: object) -> dict:
        sent_calls.append(kwargs)
        return {"ok": True, "route": "coordination_mailbox", "destination": "fake/path.json"}

    import enforced_planning.concern_routing as concern_routing

    monkeypatch.setattr(concern_routing, "route_concern", _fake_route_concern)

    exit_code = check_push_safety.main(["--repo-root", str(repo_root), "--branch", "plan-42-demo"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "ERROR overlapping_write_claim" in out
    assert "notified the other lane's owner via coordination_mailbox" in out
    assert len(sent_calls) == 1


def test_plain_text_output_reports_notify_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed delivery attempt must also be visible in the plain-text output,
    distinct from a successful one -- and must not change the exit code."""

    repo_root = tmp_path / "demo"
    _init_git_repo(repo_root)
    other_worktree = tmp_path / "other"
    other_worktree.mkdir()
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-99-other"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('other lane version')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "other lane"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "main"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "checkout", "-b", "plan-42-demo"], check=True, capture_output=True, text=True)
    (repo_root / "feature.py").write_text("print('pusher lane version')\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo_root), "add", "feature.py"], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(repo_root), "commit", "-m", "pusher lane"], check=True, capture_output=True, text=True)

    claims_dir = tmp_path / "claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(push_safety, "load_active_decisions", lambda project, limit=5: [])
    now = datetime.now(timezone.utc).isoformat()
    _write_claim(
        claims_dir,
        "pusher.yaml",
        {
            "agent": "claude-code", "claimed_at": now, "expires_at": "2099-01-01T00:00:00+00:00",
            "projects": ["demo"], "scope": "plan-42-demo", "intent": "Own current branch",
            "claim_type": "program", "plan_ref": "UNPLANNED", "branch": "plan-42-demo",
            "worktree_path": str(repo_root), "session_id": "claude-code:session-pusher",
            "session_name": "pusher", "heartbeat_at": now, "status": "active",
        },
    )
    _write_claim(
        claims_dir,
        "other.yaml",
        {
            "agent": "claude-code", "claimed_at": now, "expires_at": "2099-01-01T00:00:00+00:00",
            "projects": ["demo"], "scope": "reviewed-scope", "intent": "Touch feature file",
            "claim_type": "write", "write_paths": ["feature.py"], "branch": "plan-99-other",
            "worktree_path": str(other_worktree), "session_id": "claude-code:session-other",
            "status": "active",
        },
    )

    import enforced_planning.concern_routing as concern_routing

    def _raise(**_kwargs: object) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(concern_routing, "route_concern", _raise)

    exit_code = check_push_safety.main(["--repo-root", str(repo_root), "--branch", "plan-42-demo"])
    out = capsys.readouterr().out

    assert exit_code == 1
    assert "could not notify the other lane's owner: RuntimeError: boom" in out
