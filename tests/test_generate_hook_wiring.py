"""Tests for deterministic Claude read-gating hook wiring generation."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


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
    assert "sync:scripts/check_required_reading.py" in payload["actions"]
    assert "sync:scripts/meta/hook_log.py" in payload["actions"]
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

    assert (tmp_path / ".claude" / "hooks" / "gate-edit.sh").exists()
    assert (tmp_path / ".claude" / "hooks" / "track-reads.sh").exists()
    assert (tmp_path / "scripts" / "check_required_reading.py").exists()
    assert (tmp_path / "scripts" / "meta" / "hook_log.py").exists()


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
