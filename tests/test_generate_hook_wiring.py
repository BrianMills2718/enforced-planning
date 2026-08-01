"""Tests for deterministic Claude read-gating hook wiring generation."""

from __future__ import annotations

import json
import os
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
    ]
    mailbox_posttool = next(
        item for item in settings["hooks"]["PostToolUse"] if item["matcher"] == "*"
    )
    assert [hook["command"] for hook in mailbox_posttool["hooks"]] == [
        "bash .claude/hooks/notify-coordination-messages.sh",
    ]

    assert (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert (tmp_path / ".claude" / "hooks" / "track-reads.sh").exists()
    codex_hooks = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    assert set(codex_hooks["hooks"]) == {
        "SessionStart",
        "UserPromptSubmit",
        "PostToolUse",
        "PreToolUse",
        "Stop",
    }
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
    codex_pre = next(item for item in codex["hooks"]["PreToolUse"] if item["matcher"] == "apply_patch")
    assert "bash .claude/hooks/prewrite-claim-gate.sh" in [item["command"] for item in claude_pre["hooks"]]
    assert (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/prewrite-claim-gate.sh"'
        in [item["command"] for item in codex_pre["hooks"]]
    )


def test_generate_hook_wiring_migrates_only_its_stale_codex_prewrite_command(
    tmp_path: Path,
) -> None:
    """Codex migration must preserve unrelated commands in the old matcher block."""

    _scaffold_target_repo(tmp_path)
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n  claims:\n    prewrite_mode: observe\n",
        encoding="utf-8",
    )
    stale_command = (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/'
        'prewrite-claim-gate.sh"'
    )
    custom_hook = {
        "type": "command",
        "command": "python scripts/custom_edit_guard.py",
        "timeout": 7,
    }
    (tmp_path / ".codex").mkdir(parents=True)
    (tmp_path / ".codex" / "hooks.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "matcher": "Edit|Write",
                            "hooks": [
                                custom_hook,
                                {
                                    "type": "command",
                                    "command": stale_command,
                                    "timeout": 1,
                                    "statusMessage": "Checking write ownership",
                                },
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
        [sys.executable, str(SCRIPT), "--repo-root", str(tmp_path), "--write", "--json"],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    codex = json.loads((tmp_path / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    stale = next(
        item for item in codex["hooks"]["PreToolUse"] if item["matcher"] == "Edit|Write"
    )
    active = next(
        item for item in codex["hooks"]["PreToolUse"] if item["matcher"] == "apply_patch"
    )
    assert stale["hooks"] == [custom_hook]
    assert [item["command"] for item in active["hooks"]] == [stale_command]


def test_generate_hook_wiring_installs_artifact_creation_gate_only_when_opted_in(
    tmp_path: Path,
) -> None:
    """Artifact creation mode should independently install both native adapters."""

    repo = tmp_path / "repo"
    repo.mkdir()
    _scaffold_target_repo(repo)
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n  artifact_creation:\n    mode: observe\n",
        encoding="utf-8",
    )
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--write"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert (repo / ".claude" / "hooks" / "artifact-creation-gate.sh").is_file()
    assert (repo / ".codex" / "hooks" / "artifact-creation-gate.sh").is_file()
    assert (repo / "scripts" / "artifact_creation.py").is_file()
    assert (repo / "enforced_planning" / "artifact_creation.py").is_file()

    claude = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    codex = json.loads((repo / ".codex" / "hooks.json").read_text(encoding="utf-8"))
    claude_pre = next(item for item in claude["hooks"]["PreToolUse"] if item["matcher"] == "Edit|Write")
    codex_pre = next(item for item in codex["hooks"]["PreToolUse"] if item["matcher"] == "Edit|Write")
    assert "bash .claude/hooks/artifact-creation-gate.sh" in [item["command"] for item in claude_pre["hooks"]]
    assert (
        'bash "$(git rev-parse --show-toplevel)/.codex/hooks/artifact-creation-gate.sh"'
        in [item["command"] for item in codex_pre["hooks"]]
    )

    second = subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--write", "--json"],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    assert second.returncode == 0, second.stderr
    second_payload = json.loads(second.stdout)
    assert second_payload["actions"] == []
    assert second_payload["changed_files"] == []


def test_artifact_creation_profile_has_no_read_gate_dependency_or_side_effect(
    tmp_path: Path,
) -> None:
    """A bounded rollout must not require or install the unrelated read-gating stack."""

    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "scripts" / "relationships.yaml").write_text(
        "schema_version: 2\nartifacts: []\n",
        encoding="utf-8",
    )
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  artifact_creation:\n    mode: observe\n",
        encoding="utf-8",
    )
    (repo / ".claude").mkdir()
    (repo / ".claude" / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    "PostToolUse": [
                        {
                            "matcher": "Read",
                            "hooks": [{"type": "command", "command": "keep-me"}],
                        }
                    ]
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repo-root",
            str(repo),
            "--profile",
            "artifact-creation",
            "--write",
            "--json",
        ],
        cwd=str(PROJECT_META_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["profile"] == "artifact-creation"
    assert payload["required_inputs"] == ["scripts/relationships.yaml"]
    assert not (repo / "scripts" / "meta" / "file_context.py").exists()
    assert not (repo / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert not (repo / ".claude" / "hooks" / "track-reads.sh").exists()
    settings = json.loads((repo / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert settings["hooks"]["PostToolUse"][0]["hooks"] == [
        {"type": "command", "command": "keep-me"}
    ]
    pretool = next(
        item
        for item in settings["hooks"]["PreToolUse"]
        if item["matcher"] == "Edit|Write"
    )
    assert [item["command"] for item in pretool["hooks"]] == [
        "bash .claude/hooks/artifact-creation-gate.sh"
    ]


def test_installed_artifact_creation_hooks_allow_registered_and_deny_missing_intent(
    tmp_path: Path,
) -> None:
    """Both installed client adapters must enforce the same repository decision."""

    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "meta-process.yaml").write_text(
        "meta_process:\n  artifact_creation:\n    mode: enforce\n",
        encoding="utf-8",
    )
    _write_yaml = lambda path, payload: path.write_text(  # noqa: E731
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
    _write_yaml(
        repo / "scripts" / "artifact_directory_policy.yaml",
        {
            "schema_version": 1,
            "controlled_globs": ["**/*.md"],
            "directory_rules": [
                {
                    "id": "docs",
                    "path_globs": ["docs/**/*.md"],
                    "allowed_kinds": ["documentation"],
                    "allowed_authorities": ["canonical"],
                }
            ],
        },
    )
    _write_yaml(
        repo / "scripts" / "relationships.yaml",
        {
            "schema_version": 2,
            "artifacts": [
                {
                    "artifact_id": "fixture:allowed",
                    "path": "docs/allowed.md",
                    "kind": "documentation",
                    "owner": "fixture",
                    "concern_id": "fixture-status",
                    "authority": "canonical",
                    "creation_justification": "Provide the one registered positive control.",
                    "separate_file_reason": "Exercise installed client hook behavior.",
                    "review_triggers": ["Fixture contract changes."],
                    "lifecycle": {
                        "status": "active",
                        "retirement_condition": "Retire with this fixture.",
                    },
                    "alignment": {"authority_refs": ["README.md"]},
                }
            ],
        },
    )
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        [sys.executable, str(SCRIPT), "--repo-root", str(repo), "--profile", "artifact-creation", "--write"],
        cwd=str(PROJECT_META_ROOT),
        check=True,
        capture_output=True,
        text=True,
    )

    codex_payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "apply_patch",
        "session_id": "installed-artifact-gate",
        "cwd": str(repo),
        "tool_input": {
            "command": "*** Begin Patch\n*** Add File: docs/missing.md\n+x\n*** End Patch"
        },
    }
    denied = subprocess.run(
        ["bash", ".codex/hooks/artifact-creation-gate.sh"],
        cwd=repo,
        input=json.dumps(codex_payload),
        env={
            **os.environ,
            "ARTIFACT_CREATION_RECEIPT_PATH": str(tmp_path / "receipts.jsonl"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert denied.returncode == 2
    assert "intent_missing" in denied.stderr

    claude_payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Write",
        "session_id": "installed-artifact-gate",
        "cwd": str(repo),
        "tool_input": {"file_path": str(repo / "docs" / "allowed.md")},
    }
    allowed = subprocess.run(
        ["bash", ".claude/hooks/artifact-creation-gate.sh"],
        cwd=repo,
        input=json.dumps(claude_payload),
        env={
            **os.environ,
            "ARTIFACT_CREATION_RECEIPT_PATH": str(tmp_path / "receipts.jsonl"),
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert allowed.returncode == 0, allowed.stderr
    assert not (repo / "docs" / "allowed.md").exists()


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
