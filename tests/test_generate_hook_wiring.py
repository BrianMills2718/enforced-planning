"""Tests for deterministic Claude read-gating hook wiring generation."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml  # type: ignore[import-untyped]


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_META_ROOT / "scripts" / "generate_hook_wiring.py"


def _scaffold_target_repo(repo_root: Path) -> None:
    """Create the minimum repo surface needed for hook-wiring generation."""

    (repo_root / "scripts" / "meta").mkdir(parents=True, exist_ok=True)
    (repo_root / "scripts" / "relationships.yaml").write_text("governance: []\n", encoding="utf-8")
    (repo_root / "scripts" / "meta" / "file_context.py").write_text(
        '"""Stub file context resolver for generator tests."""\n',
        encoding="utf-8",
    )


def _write_python_without_yaml(repo_root: Path) -> None:
    """Install a target-runtime probe that deterministically rejects PyYAML imports."""

    interpreter = repo_root / ".venv" / "bin" / "python"
    interpreter.parent.mkdir(parents=True, exist_ok=True)
    interpreter.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    interpreter.chmod(0o755)


def test_generate_hook_wiring_dry_run_reports_expected_changes(tmp_path: Path) -> None:
    """Dry-run output should describe the files the generator would install."""

    _scaffold_target_repo(tmp_path)

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["write_mode"] is False
    assert "sync:.claude/hooks/gate-edit.sh" in payload["actions"]
    assert "sync:.claude/hooks/track-reads.sh" in payload["actions"]
    assert "sync:.claude/hooks/notify-coordination-messages.sh" in payload["actions"]
    assert "sync:.codex/hooks/notify-coordination-messages.sh" in payload["actions"]
    assert "sync:.codex/hooks.json" in payload["actions"]
    assert "sync:scripts/check_required_reading.py" in payload["actions"]
    assert "sync:scripts/meta/hook_log.py" in payload["actions"]
    assert "sync:scripts/meta/context_packet.py" in payload["actions"]
    assert "sync:enforced_planning/context_packet.py" in payload["actions"]
    assert "sync:enforced_planning/relationship_context.py" in payload["actions"]
    assert "sync:.claude/settings.json" in payload["actions"]


def test_generate_hook_wiring_writes_files_and_merges_settings(tmp_path: Path) -> None:
    """Write mode should install support files and preserve existing hook entries."""

    _scaffold_target_repo(tmp_path)
    (tmp_path / ".claude").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": "bash .claude/hooks/protect-main.sh",
                                    "timeout": 5000,
                                }
                            ],
                        }
                    ]
                }
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--write",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["write_mode"] is True

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    pretool = next(item for item in settings["hooks"]["PreToolUse"] if item["matcher"] == "Edit|Write")
    posttool = next(item for item in settings["hooks"]["PostToolUse"] if item["matcher"] == "Read")

    commands = [hook["command"] for hook in pretool["hooks"]]
    assert commands == [
        "bash .claude/hooks/protect-main.sh",
        "bash .claude/hooks/gate-edit.sh",
    ]
    assert [hook["command"] for hook in posttool["hooks"]] == [
        "bash .claude/hooks/track-reads.sh",
        "bash .claude/hooks/notify-coordination-messages.sh",
    ]

    assert (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert (tmp_path / ".claude" / "hooks" / "track-reads.sh").exists()
    codex_hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert set(codex_hooks["hooks"]) == {"SessionStart", "UserPromptSubmit", "PostToolUse"}
    assert (tmp_path / ".codex" / "hooks" / "notify-coordination-messages.sh").exists()
    assert (tmp_path / "scripts" / "check_required_reading.py").exists()
    assert (tmp_path / "scripts" / "meta" / "hook_log.py").exists()
    assert (tmp_path / "scripts" / "meta" / "context_packet.py").exists()
    assert (tmp_path / "enforced_planning" / "context_packet.py").exists()
    assert (tmp_path / "enforced_planning" / "relationship_context.py").exists()
    assert (tmp_path / "enforced_planning" / "prewrite_claim_fast.py").exists()
    assert (tmp_path / "enforced_planning" / "prewrite_claim_projection.py").exists()
    assert (tmp_path / "scripts" / "refresh_prewrite_claim_projection.py").exists()


def test_generate_hook_wiring_is_idempotent(tmp_path: Path) -> None:
    """A second write after sync should report no further changes."""

    _scaffold_target_repo(tmp_path)

    first = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--write",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert first.returncode == 0

    second = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert second.returncode == 0
    payload = json.loads(second.stdout)
    assert payload["actions"] == []
    assert payload["changed_files"] == []


def test_generate_hook_wiring_installs_prewrite_gate_only_when_opted_in(tmp_path: Path) -> None:
    """Observe/enforce modes install both native adapters without changing off defaults."""

    _scaffold_target_repo(tmp_path)
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n  claims:\n    prewrite_mode: observe\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--write", "--json"],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert (tmp_path / ".claude" / "hooks" / "prewrite-claim-gate.sh").is_file()
    assert (tmp_path / ".codex" / "hooks" / "prewrite-claim-gate.sh").is_file()
    assert (tmp_path / "enforced_planning" / "prewrite_claim_fast.py").is_file()
    assert (tmp_path / "enforced_planning" / "prewrite_claim_projection.py").is_file()
    assert (tmp_path / "scripts" / "refresh_prewrite_claim_projection.py").is_file()
    claude = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    codex = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    claude_pre = next(item for item in claude["hooks"]["PreToolUse"] if item["matcher"] == "Edit|Write")
    codex_pre = next(item for item in codex["hooks"]["PreToolUse"] if item["matcher"] == "Edit|Write")
    assert "bash .claude/hooks/prewrite-claim-gate.sh" in [item["command"] for item in claude_pre["hooks"]]
    assert (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/prewrite-claim-gate.sh"'
        in [item["command"] for item in codex_pre["hooks"]]
    )

    second = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--write", "--json"],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout)
    assert second_payload["actions"] == []
    assert second_payload["changed_files"] == []


def test_installed_prewrite_runtime_projects_and_classifies_native_payloads(
    tmp_path: Path,
) -> None:
    """The installed copy must run independently at the target-repo boundary."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold_target_repo(repo)
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n  claims:\n    prewrite_mode: observe\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (repo / "src").mkdir()
    (repo / "src" / "allowed.py").write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    install = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--write", "--json"],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert install.returncode == 0, install.stderr

    claims_dir = tmp_path / "claims"
    claims_dir.mkdir()
    projection_path = tmp_path / "projection.json"
    receipt_path = tmp_path / "receipts.jsonl"
    now = datetime.now(timezone.utc)
    (claims_dir / "codex_installed-test_main.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 3,
                "agent": "codex",
                "claimed_at": now.isoformat(),
                "expires_at": (now + timedelta(hours=1)).isoformat(),
                "projects": ["installed-test"],
                "scope": "main",
                "intent": "exercise installed pre-write runtime",
                "claim_type": "write",
                "write_paths": ["src/allowed.py"],
                "read_paths": [],
                "worktree_path": str(repo),
                "repo_root": str(repo),
                "branch": "main",
                "session_name": "installed-test",
                "session_id": "codex:installed-test",
                "heartbeat_at": now.isoformat(),
                "status": "active",
                "updated_at": now.isoformat(),
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    refresh = subprocess.run(
        [
            sys.executable,
            str(repo / "scripts" / "refresh_prewrite_claim_projection.py"),
            "--claims-dir",
            str(claims_dir),
            "--projection-path",
            str(projection_path),
            "--json",
        ],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert refresh.returncode == 0, refresh.stderr

    def invoke(target: str) -> dict[str, object]:
        payload = {
            "session_id": "installed-test",
            "cwd": str(repo),
            "hook_event_name": "PreToolUse",
            "tool_name": "apply_patch",
            "tool_input": {
                "command": f"*** Begin Patch\n*** Update File: {target}\n*** End Patch"
            },
        }
        completed = subprocess.run(
            [
                sys.executable,
                str(repo / "scripts" / "prewrite_claim_gate.py"),
                "--client",
                "codex",
                "--mode",
                "observe",
                "--claims-dir",
                str(claims_dir),
                "--projection-path",
                str(projection_path),
                "--receipt-path",
                str(receipt_path),
                "--json",
            ],
            cwd=repo,
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr
        return json.loads(completed.stdout)

    allowed = invoke("src/allowed.py")
    violation = invoke("src/outside.py")

    assert (allowed["decision"], allowed["reason_code"]) == (
        "allow",
        "exact_live_claim",
    )
    assert (violation["decision"], violation["reason_code"]) == (
        "observe_violation",
        "path_outside_claim",
    )
    receipts = [json.loads(line) for line in receipt_path.read_text(encoding="utf-8").splitlines()]
    assert [item["reason_code"] for item in receipts] == [
        "exact_live_claim",
        "path_outside_claim",
    ]


def test_generate_hook_wiring_fails_without_file_context(tmp_path: Path) -> None:
    """The generator should fail loudly when the repo lacks file_context.py."""

    (tmp_path / "scripts").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "relationships.yaml").write_text("governance: []\n", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(tmp_path),
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "Missing file-context resolver required for read-gating" in result.stderr


def test_generate_hook_wiring_fails_when_target_python_lacks_yaml(tmp_path: Path) -> None:
    """Host dependencies cannot stand in for the interpreter the installed hook uses."""

    _scaffold_target_repo(tmp_path)
    _write_python_without_yaml(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path)],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "cannot import PyYAML" in result.stderr
