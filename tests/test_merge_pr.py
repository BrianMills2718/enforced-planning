"""Tests for scripts/merge_pr.py."""

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


def test_cleanup_worktree_prefers_safe_remove_script(tmp_path: Path, monkeypatch) -> None:
    """cleanup_worktree should prefer a discovered safe-remove script over make."""
    module = _load()
    worktree_path = tmp_path / "wt"
    worktree_path.mkdir()
    safe_remove = tmp_path / "safe_worktree_remove.py"
    safe_remove.write_text("#!/usr/bin/env python3\n", encoding="utf-8")

    # mock-ok: command orchestration around git/gh is external-process glue; this
    # unit test isolates the path-selection behavior instead of invoking real CLIs.
    monkeypatch.setattr(module, "find_worktree_for_branch", lambda _branch: worktree_path)
    monkeypatch.setattr(module, "release_claim_for_branch", lambda _branch: True)
    monkeypatch.setattr(module, "find_existing_script", lambda _paths: safe_remove)

    seen: list[list[str]] = []

    def _fake_run_cmd(cmd: list[str], check: bool = True, capture: bool = True) -> subprocess.CompletedProcess[str]:
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_cmd", _fake_run_cmd)

    result = module.cleanup_worktree("plan-83-example")  # type: ignore[attr-defined]

    assert result is True
    assert seen == [["python", str(safe_remove), str(worktree_path)]]

