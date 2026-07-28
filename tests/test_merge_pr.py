"""Tests for rename-safe merge helper cleanup behavior."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPTS_DIR / "merge_pr.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("merge_pr_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def completed_process(
    args: list[str], returncode: int = 0, stdout: str = "", stderr: str = ""
) -> subprocess.CompletedProcess[str]:
    """Build a CompletedProcess[str] matching the helper contract."""
    return subprocess.CompletedProcess(
        args=args, returncode=returncode, stdout=stdout, stderr=stderr
    )


def test_find_existing_script_returns_first_existing(tmp_path: Path) -> None:
    """Helper should prefer the first existing script in priority order."""
    module = _load()
    second = tmp_path / "second.py"
    first = tmp_path / "first.py"
    second.write_text("# second\n", encoding="utf-8")
    first.write_text("# first\n", encoding="utf-8")

    found = module.find_existing_script(  # type: ignore[attr-defined]
        [str(first), str(second)]
    )

    assert found == first


def test_find_existing_script_returns_none_when_missing(tmp_path: Path) -> None:
    """Helper should return None when no candidate path exists."""
    module = _load()

    found = module.find_existing_script(  # type: ignore[attr-defined]
        [str(tmp_path / "missing-a.py"), str(tmp_path / "missing-b.py")]
    )

    assert found is None


def test_cleanup_worktree_uses_safe_remove_script_with_discovered_path(
    monkeypatch, tmp_path
) -> None:
    """Cleanup should follow the discovered worktree path, not branch-derived layout."""
    module = _load()
    monkeypatch.chdir(tmp_path)
    safe_remove = (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "safe_worktree_remove.py"
    )
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    discovered_path = tmp_path / "worktrees" / "tmp-plan-69-llm-client-resync"
    observed_calls: list[list[str]] = []

    monkeypatch.setattr(
        module, "find_worktree_for_branch", lambda branch: discovered_path
    )
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)

    def fake_run_cmd(
        cmd, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert (
        module.cleanup_worktree("codex/llm-client-worktree-block-resync") is True
    )
    assert observed_calls == [
        [
            "python",
            "scripts/meta/worktree-coordination/safe_worktree_remove.py",
            str(discovered_path),
        ]
    ]


def test_cleanup_worktree_falls_back_to_make_when_safe_remove_missing(
    monkeypatch, tmp_path
) -> None:
    """Fallback should preserve the old make-based path only when no safe remover exists."""
    module = _load()
    monkeypatch.chdir(tmp_path)

    discovered_path = tmp_path / "worktrees" / "branch-dir"
    observed_calls: list[list[str]] = []

    monkeypatch.setattr(
        module, "find_worktree_for_branch", lambda branch: discovered_path
    )
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)

    def fake_run_cmd(
        cmd, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert module.cleanup_worktree("codex/example") is True
    assert observed_calls == [["make", "worktree-remove", "BRANCH=codex/example"]]


def test_cleanup_worktree_reports_manual_safe_remove_command_on_failure(
    monkeypatch, tmp_path, capsys
) -> None:
    """Failure output should guide operators to the path-based cleanup command."""
    module = _load()
    monkeypatch.chdir(tmp_path)
    safe_remove = (
        tmp_path
        / "scripts"
        / "meta"
        / "worktree-coordination"
        / "safe_worktree_remove.py"
    )
    safe_remove.parent.mkdir(parents=True)
    safe_remove.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    discovered_path = tmp_path / "worktrees" / "tmp-plan-69-llm-client-resync"

    monkeypatch.setattr(
        module, "find_worktree_for_branch", lambda branch: discovered_path
    )
    monkeypatch.setattr(module, "release_claim_for_branch", lambda branch: True)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(
            cmd, returncode=1, stderr="cleanup failed"
        ),
    )

    assert (
        module.cleanup_worktree("codex/llm-client-worktree-block-resync") is False
    )
    captured = capsys.readouterr()
    assert "cleanup failed" in captured.out
    assert (
        "Run manually: python scripts/meta/worktree-coordination/safe_worktree_remove.py "
        f"{discovered_path}"
    ) in captured.out


def test_cleanup_without_worktree_still_records_session_close(
    monkeypatch, tmp_path
) -> None:
    """A missing local worktree must not silently leave merged ownership active."""

    module = _load()
    monkeypatch.chdir(tmp_path)
    session_close = tmp_path / "scripts" / "session_close.py"
    session_close.parent.mkdir(parents=True)
    session_close.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
    monkeypatch.setenv("CODEX_THREAD_ID", "test-thread")
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: None)
    observed_calls: list[list[str]] = []

    def fake_run_cmd(
        cmd, check: bool = True, capture: bool = True
    ) -> subprocess.CompletedProcess[str]:
        observed_calls.append(cmd)
        return completed_process(cmd)

    monkeypatch.setattr(module, "run_cmd", fake_run_cmd)

    assert module.cleanup_worktree("plan-107-landed") is True
    assert observed_calls == [
        [
            "python",
            "scripts/session_close.py",
            "--agent",
            "codex",
            "--project",
            tmp_path.name,
            "--scope",
            "plan-107-landed",
            "--branch",
            "plan-107-landed",
        ]
    ]


def test_merge_reports_high_failure_when_post_merge_closeout_fails(
    monkeypatch, capsys
) -> None:
    """A successful GitHub merge is not a successful command until closeout succeeds."""

    module = _load()
    monkeypatch.setattr(module, "get_pr_branch", lambda _pr: "plan-107-landed")
    monkeypatch.setattr(module, "check_pr_mergeable", lambda _pr: (True, "OK"))
    monkeypatch.setattr(module, "cleanup_worktree", lambda _branch: False)
    monkeypatch.setattr(
        module,
        "run_cmd",
        lambda cmd, check=True, capture=True: completed_process(cmd),
    )

    assert module.merge_pr(107) is False
    assert "HIGH: PR merged, but claim/worktree closeout failed" in capsys.readouterr().out
