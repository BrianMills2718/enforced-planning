"""Integration-style tests for Claude read-gating hooks in project-meta.

These tests execute the real shell hooks via subprocess so the repo validates
the same path Claude Code uses at runtime. They focus on the first activation
slice: non-`src/` gating, hook logging, and project-meta hook wiring.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


PROJECT_META_ROOT = Path(__file__).resolve().parents[1]
LOCAL_GATE_HOOK = PROJECT_META_ROOT / ".claude" / "hooks" / "gate-edit.sh"
LOCAL_TRACK_HOOK = PROJECT_META_ROOT / ".claude" / "hooks" / "track-reads.sh"
TEMPLATE_GATE_HOOK = PROJECT_META_ROOT / "meta-process" / "hooks" / "claude" / "gate-edit.sh"
TEMPLATE_TRACK_HOOK = PROJECT_META_ROOT / "meta-process" / "hooks" / "claude" / "track-reads.sh"
SETTINGS_FILE = PROJECT_META_ROOT / ".claude" / "settings.json"
NON_SRC_TARGET = "meta-process/hooks/claude/gate-edit.sh"
REQUIRED_DOCS = [
    "docs/ops/CONTEXT_INJECTION_AND_REQUIRED_READING_MATRIX.md",
    "docs/ops/STRATEGIC_REVIEW_ACTIVE_STACK_2026-03-18.md",
    "docs/plans/08_read-gating-activation-and-context-enforcement.md",
    "scripts/CLAUDE.md",
]


def _run_hook(
    script: Path,
    payload: dict[str, object],
    tmp_path: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Execute a hook script with isolated reads/log files."""

    env = os.environ.copy()
    env["CLAUDE_SESSION_READS_FILE"] = str(tmp_path / "session_reads.txt")
    env["CLAUDE_HOOK_LOG_FILE"] = str(tmp_path / "hook_log.jsonl")
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(script)],
        cwd=str(PROJECT_META_ROOT),
        env=env,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def _write_temp_relationships(
    tmp_path: Path,
    managed_mode: str,
    unmanaged_mode: str = "ignore",
    *,
    managed_exclude: list[str] | None = None,
) -> Path:
    exclude_patterns = managed_exclude or []
    config = "\n".join(
        [
            "required_reading:",
            "  defaults: []",
            "governance: []",
            "couplings: []",
            "architecture: []",
            "adrs: {}",
            "file_scope:",
            "  managed:",
            "    include: [\"**\"]",
            f"    mode: {managed_mode}",
            f"    exclude: {exclude_patterns}",
            "  unmanaged:",
            f"    mode: {unmanaged_mode}",
        ]
        + [""]
    )
    path = tmp_path / "relationships_scope.yaml"
    path.write_text(config, encoding="utf-8")
    return path


def _read_log_entries(tmp_path: Path) -> list[dict[str, object]]:
    """Load JSONL hook log entries emitted during a test."""

    log_file = tmp_path / "hook_log.jsonl"
    if not log_file.exists():
        return []
    return [
        json.loads(line)
        for line in log_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_gate_edit_blocks_non_src_file_without_required_reads(tmp_path: Path) -> None:
    """The gate should block non-source files when relationships require docs."""

    result = _run_hook(
        LOCAL_GATE_HOOK,
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": NON_SRC_TARGET},
        },
        tmp_path,
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "REQUIRED READS MISSING" in payload["reason"]
    assert "hookSpecificOutput" in payload
    assert "additionalContext" in payload["hookSpecificOutput"]
    assert payload["hookSpecificOutput"]["additionalContext"] != ""

    entries = _read_log_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["hook"] == "gate-edit"
    assert entries[0]["decision"] == "block"
    assert entries[0]["file_path"] == NON_SRC_TARGET
    assert entries[0]["required_reads"] == REQUIRED_DOCS
    assert entries[0]["reads_completed"] == []
    assert entries[0]["reads_file"] == str((tmp_path / "session_reads.txt").resolve())
    assert entries[0]["context_emitted"] is True
    assert entries[0]["context_bytes"] > 0


def test_gate_edit_block_context_falls_back_when_limit_small(tmp_path: Path) -> None:
    """Gate should emit path-only fallback context when configured size limits are too low."""

    result = _run_hook(
        LOCAL_GATE_HOOK,
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": NON_SRC_TARGET},
        },
        tmp_path,
        extra_env={"CLAUDE_GATE_CONTEXT_MAX_BYTES": "120"},
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert "Read the listed documents and retry:" in context
    assert "docs/ops/CONTEXT_INJECTION_AND_REQUIRED_READING_MATRIX.md" in context

    entries = _read_log_entries(tmp_path)
    assert entries[0]["context_emitted"] is True
    assert entries[0]["context_bytes"] > 0


def test_gate_edit_allows_after_required_reads_and_logs_completion(tmp_path: Path) -> None:
    """The gate should allow once all required docs were read in the session file."""

    reads_file = tmp_path / "session_reads.txt"
    reads_file.write_text("\n".join(REQUIRED_DOCS) + "\n", encoding="utf-8")

    result = _run_hook(
        LOCAL_GATE_HOOK,
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": NON_SRC_TARGET},
        },
        tmp_path,
    )

    assert result.returncode == 0
    assert result.stdout == ""

    entries = _read_log_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["decision"] == "allow"
    assert entries[0]["required_reads"] == REQUIRED_DOCS
    assert entries[0]["reads_completed"] == REQUIRED_DOCS
    assert entries[0]["missing_reads"] == []
    assert entries[0]["reads_file"] == str((tmp_path / "session_reads.txt").resolve())
    assert entries[0]["context_emitted"] is False
    assert entries[0]["context_bytes"] == 0


def test_track_reads_records_session_entry_and_log(tmp_path: Path) -> None:
    """The read hook should append the read path and emit a log entry."""

    result = _run_hook(
        LOCAL_TRACK_HOOK,
        {
            "tool_name": "Read",
            "tool_input": {"file_path": "docs/ops/GOVERNED_REPO_CONTRACT.md"},
        },
        tmp_path,
        extra_env={
            "CLAUDE_HOOK_EXPERIMENT_ID": "ctx-exp-1",
            "CLAUDE_HOOK_VARIANT_ID": "full-context",
            "CLAUDE_HOOK_DOWNSTREAM_RUN_ID": "run_ctx_eval_1",
        },
    )

    assert result.returncode == 0
    reads_file = tmp_path / "session_reads.txt"
    assert reads_file.read_text(encoding="utf-8").splitlines() == [
        "docs/ops/GOVERNED_REPO_CONTRACT.md",
    ]

    entries = _read_log_entries(tmp_path)
    assert len(entries) == 1
    assert entries[0]["hook"] == "track-reads"
    assert entries[0]["decision"] == "recorded"
    assert entries[0]["file_path"] == "docs/ops/GOVERNED_REPO_CONTRACT.md"
    assert entries[0]["reads_file"] == str((tmp_path / "session_reads.txt").resolve())
    assert entries[0]["experiment_id"] == "ctx-exp-1"
    assert entries[0]["variant_id"] == "full-context"
    assert entries[0]["downstream_run_id"] == "run_ctx_eval_1"


def test_gate_edit_allows_with_scope_warning_when_unregistered_managed_file(tmp_path: Path) -> None:
    """Unregistered managed files can warn without blocking when managed mode is warn."""

    result = _run_hook(
        LOCAL_GATE_HOOK,
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/critical_service.py"},
        },
        tmp_path,
        extra_env={
            "CLAUDE_CHECK_REQUIRED_READING_CONFIG": str(_write_temp_relationships(tmp_path, "warn")),
            "CLAUDE_GATE_CONTEXT_MAX_BYTES": "0",
        },
    )

    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["hookSpecificOutput"]["additionalContext"] != ""

    log = _read_log_entries(tmp_path)
    assert log[0]["decision"] == "allow"
    assert log[0]["scope_warnings"] == ["src/critical_service.py"]
    assert log[0]["scope_violations"] == []


def test_gate_edit_blocks_with_scope_violation_when_unregistered_managed_file(tmp_path: Path) -> None:
    """Unregistered managed files can hard-fail when managed mode is hard-fail."""

    result = _run_hook(
        LOCAL_GATE_HOOK,
        {
            "tool_name": "Edit",
            "tool_input": {"file_path": "src/critical_service.py"},
        },
        tmp_path,
        extra_env={
            "CLAUDE_CHECK_REQUIRED_READING_CONFIG": str(_write_temp_relationships(tmp_path, "hard-fail")),
        },
    )

    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["decision"] == "block"
    assert "scope violations" in payload["reason"]
    assert "SCOPE VIOLATIONS" in payload["reason"].upper()


def test_project_meta_settings_wire_read_gate_hooks() -> None:
    """The active project-meta Claude settings should wire the read-gate hooks."""

    settings = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    pretool = settings["hooks"]["PreToolUse"]
    posttool = settings["hooks"]["PostToolUse"]

    edit_hooks = next(item for item in pretool if item["matcher"] == "Edit|Write")
    read_hooks = next(item for item in posttool if item["matcher"] == "Read")

    commands = [hook["command"] for hook in edit_hooks["hooks"]]
    assert "bash .claude/hooks/protect-main.sh" in commands
    assert "bash .claude/hooks/gate-edit.sh" in commands

    read_commands = [hook["command"] for hook in read_hooks["hooks"]]
    assert read_commands == ["bash .claude/hooks/track-reads.sh"]


def test_template_and_local_hook_copies_stay_in_sync() -> None:
    """Template hooks should match the active local copies used by project-meta."""

    assert LOCAL_GATE_HOOK.read_text(encoding="utf-8") == TEMPLATE_GATE_HOOK.read_text(encoding="utf-8")
    assert LOCAL_TRACK_HOOK.read_text(encoding="utf-8") == TEMPLATE_TRACK_HOOK.read_text(encoding="utf-8")
