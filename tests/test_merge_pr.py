"""Tests for rename-safe merge helper cleanup behavior."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path


def load_merge_pr_module():
    """Import the standalone merge_pr script as a test module."""
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "merge_pr.py"
    spec = importlib.util.spec_from_file_location("merge_pr_under_test", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def completed_process(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
):
    """Build a CompletedProcess[str] matching the helper contract."""
    return subprocess.CompletedProcess(args=args, returncode=returncode, stdout=stdout, stderr=stderr)


def test_cleanup_worktree_uses_safe_remove_script_with_discovered_path(
    monkeypatch, tmp_path
):
    """Cleanup should follow the discovered worktree path, not branch-derived layout."""
    module = load_merge_pr_module()
    monkeypatch.chdir(tmp_path)
    safe_remove = tmp_path / "scripts" / "meta" / "worktree-coordination" / "safe_worktree_remove.py"
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n")

    discovered_path = tmp_path / "worktrees" / "tmp-plan-69-llm-client-resync"
    observed_calls: list[list[str]] = []

    monkeypatch.setattr(module, "find_worktree_for_branch", lambda branch: discovered_path)
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)

    def fake_run_cmd(cmd, check=True, capture=True):
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert module.cleanup_worktree("codex/llm-client-worktree-block-resync") is True
    assert observed_calls == [
        ["python", "scripts/meta/worktree-coordination/safe_worktree_remove.py", str(discovered_path)]
    ]


def test_cleanup_worktree_falls_back_to_make_when_safe_remove_missing(
    monkeypatch, tmp_path
):
    """Fallback should preserve the old make-based path only when no safe remover exists."""
    module = load_merge_pr_module()
    monkeypatch.chdir(tmp_path)

    discovered_path = tmp_path / "worktrees" / "branch-dir"
    observed_calls: list[list[str]] = []

    monkeypatch.setattr(module, "find_worktree_for_branch", lambda branch: discovered_path)
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)

    def fake_run_cmd(cmd, check=True, capture=True):
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert module.cleanup_worktree("codex/example") is True
    assert observed_calls == [["make", "worktree-remove", "BRANCH=codex/example"]]


def test_cleanup_worktree_reports_manual_safe_remove_command_on_failure(
    monkeypatch, tmp_path, capsys
):
    """Failure output should guide operators to the path-based cleanup command."""
    module = load_merge_pr_module()
    monkeypatch.chdir(tmp_path)
    safe_remove = tmp_path / "scripts" / "meta" / "worktree-coordination" / "safe_worktree_remove.py"
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n")

    discovered_path = tmp_path / "worktrees" / "tmp-plan-69-llm-client-resync"

    monkeypatch.setattr(module, "find_worktree_for_branch", lambda branch: discovered_path)
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(
            cmd, returncode=1, stderr="cleanup failed"
        ),
    )

    assert module.cleanup_worktree("codex/llm-client-worktree-block-resync") is False
    captured = capsys.readouterr()
    assert "cleanup failed" in captured.out
    assert (
        f"Run manually: python scripts/meta/worktree-coordination/safe_worktree_remove.py {discovered_path}"
        in captured.out
    )
