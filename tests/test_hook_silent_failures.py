"""Hooks must report their own failure instead of silently switching a control off.

Observed 2026-09-14 against origin/main with a helper script that raises:

- ``check-hook-enabled.sh`` returned 1 (disabled) with no output, so an optional
  safety hook turned itself off whenever its config reader crashed;
- ``gate-edit.sh`` blocked the edit with ``"reason": "\\n"``, leaving the agent no
  way to see what failed;
- ``gate-edit.sh`` with no ``jq`` on PATH exited 0 with no output, so the
  required-reading gate let every edit through unseen;
- ``post-edit-quiz.sh`` exited 0 with no output when the quiz generator crashed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / "hooks" / "claude"
CRASH = 'raise RuntimeError("demo-crash-marker")\n'


def _repo(tmp_path: Path, hook: str) -> Path:
    """Create a real Git repo with one hook copied to .claude/hooks."""
    repo = tmp_path / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "meta").mkdir(parents=True)
    shutil.copy2(HOOKS / hook, repo / ".claude" / "hooks" / hook)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    return repo


def _run(repo: Path, hook: str, payload: dict, env: dict | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke one hook through bash with a JSON payload on stdin."""
    return subprocess.run(
        ["bash", str(repo / ".claude" / "hooks" / hook)],
        input=json.dumps(payload),
        cwd=repo,
        env=env or {**os.environ, "PYTHON": sys.executable},
        capture_output=True,
        text=True,
        check=False,
    )


def test_hook_enabled_helper_keeps_hook_on_and_reports_when_config_reader_crashes(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "check-hook-enabled.sh")
    (repo / "scripts" / "meta_config.py").write_text(CRASH, encoding="utf-8")
    result = subprocess.run(
        ["bash", str(repo / ".claude" / "hooks" / "check-hook-enabled.sh"), "enforce_workflow"],
        cwd=repo,
        env={**os.environ, "PYTHON": sys.executable},
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, "a crashed config reader must not disable the hook"
    assert "demo-crash-marker" in result.stderr


def test_gate_edit_block_reason_names_the_crash(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gate-edit.sh")
    (repo / "scripts" / "check_required_reading.py").write_text(CRASH, encoding="utf-8")
    target = repo / "target.py"
    target.write_text("", encoding="utf-8")
    result = _run(repo, "gate-edit.sh", {"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
    assert result.returncode == 2
    body = json.loads(result.stdout)
    assert "demo-crash-marker" in body["reason"]


def test_gate_edit_says_it_is_not_running_when_jq_is_missing(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "gate-edit.sh")
    (repo / "scripts" / "check_required_reading.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    target = repo / "target.py"
    target.write_text("", encoding="utf-8")
    bin_dir = tmp_path / "bin-without-jq"
    bin_dir.mkdir()
    for tool in ("bash", "cat", "git", "python", "python3", "dirname", "basename", "pwd", "sed", "awk",
                 "grep", "tr", "wc", "date", "mkdir", "head", "cut", "env", "realpath", "readlink"):
        found = shutil.which(tool)
        if found:
            (bin_dir / tool).symlink_to(found)
    result = _run(
        repo,
        "gate-edit.sh",
        {"tool_name": "Edit", "tool_input": {"file_path": str(target)}},
        env={"PATH": str(bin_dir), "HOME": str(tmp_path)},
    )
    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert "jq" in body["hookSpecificOutput"]["additionalContext"]


def test_post_edit_quiz_reports_a_crashed_generator(tmp_path: Path) -> None:
    repo = _repo(tmp_path, "post-edit-quiz.sh")
    (repo / "scripts" / "generate_quiz.py").write_text(CRASH, encoding="utf-8")
    (repo / "src").mkdir()
    target = repo / "src" / "module.py"
    target.write_text("", encoding="utf-8")
    result = _run(repo, "post-edit-quiz.sh", {"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert "demo-crash-marker" in body["hookSpecificOutput"]["additionalContext"]


def test_post_edit_quiz_stays_quiet_on_deliberate_not_configured_exit(tmp_path: Path) -> None:
    """Negative control: exit 2 means no relationships.yaml, not a failure worth a message."""
    repo = _repo(tmp_path, "post-edit-quiz.sh")
    (repo / "scripts" / "generate_quiz.py").write_text(
        'import sys\nprint("No relationships.yaml found", file=sys.stderr)\nsys.exit(2)\n', encoding="utf-8"
    )
    (repo / "src").mkdir()
    target = repo / "src" / "module.py"
    target.write_text("", encoding="utf-8")
    result = _run(repo, "post-edit-quiz.sh", {"tool_name": "Edit", "tool_input": {"file_path": str(target)}})
    assert result.returncode == 0
    assert result.stdout == ""


def test_canonical_lock_hook_reports_a_script_that_cannot_start(tmp_path: Path) -> None:
    """canonical_lock.py reports its own runtime errors, but an import-time crash was hidden by 2>/dev/null || true."""
    repo = tmp_path / "repo"
    (repo / ".claude" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "worktree-coordination").mkdir(parents=True)
    shutil.copy2(
        HOOKS / "worktree-coordination" / "reconcile-canonical-locks.sh",
        repo / ".claude" / "hooks" / "reconcile-canonical-locks.sh",
    )
    (repo / "scripts" / "worktree-coordination" / "canonical_lock.py").write_text(CRASH, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    result = _run(repo, "reconcile-canonical-locks.sh", {"hook_event_name": "SessionStart"})
    assert result.returncode == 0
    body = json.loads(result.stdout)
    assert "demo-crash-marker" in body["systemMessage"]


def test_hook_enabled_helper_still_reports_disabled_without_a_crash(tmp_path: Path) -> None:
    """Negative control: a deliberate exit 1 from the config reader still means disabled."""
    repo = _repo(tmp_path, "check-hook-enabled.sh")
    (repo / "scripts" / "meta_config.py").write_text("import sys\nsys.exit(1)\n", encoding="utf-8")
    result = subprocess.run(
        ["bash", str(repo / ".claude" / "hooks" / "check-hook-enabled.sh"), "enforce_workflow"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
