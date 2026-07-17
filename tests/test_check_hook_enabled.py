"""Tests for stage-aware Claude hook enablement."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "hooks"
    / "claude"
    / "check-hook-enabled.sh"
)


def _run(repo: Path, hook_name: str) -> subprocess.CompletedProcess[str]:
    """Resolve one hook setting using the tracked shell entrypoint."""

    return subprocess.run(
        ["bash", str(SCRIPT), hook_name],
        cwd=repo,
        env={**os.environ, "PYTHON": sys.executable},
        capture_output=True,
        text=True,
        check=False,
    )


def _repo(tmp_path: Path, config: str | None) -> Path:
    """Create a real Git root with an optional policy configuration."""

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    if config is not None:
        (tmp_path / "meta-process.yaml").write_text(config, encoding="utf-8")
    return tmp_path


def test_hooks_are_disabled_when_configuration_is_absent(tmp_path: Path) -> None:
    """Installing helper code alone must not enable coordinated-work hooks."""

    repo = _repo(tmp_path, None)
    assert _run(repo, "enforce_workflow").returncode == 1
    assert _run(repo, "warn_worktree_cwd").returncode == 1
    assert _run(repo, "protect_main").returncode == 1


def test_development_defaults_disable_worktree_hooks(tmp_path: Path) -> None:
    """The starter's false values must control actual hook behavior."""

    repo = _repo(
        tmp_path,
        """\
meta_process:
  worktrees:
    enabled: false
    protect_main: false
""",
    )
    assert _run(repo, "enforce_workflow").returncode == 1
    assert _run(repo, "protect_main").returncode == 1


def test_coordinated_config_enables_worktree_hooks(tmp_path: Path) -> None:
    """A repository can explicitly opt into collision and main-path controls."""

    repo = _repo(
        tmp_path,
        """\
meta_process:
  worktrees:
    enabled: true
    protect_main: true
""",
    )
    assert _run(repo, "enforce_workflow").returncode == 0
    assert _run(repo, "warn_worktree_cwd").returncode == 0
    assert _run(repo, "protect_main").returncode == 0


def test_malformed_config_fails_loud(tmp_path: Path) -> None:
    """Invalid policy configuration must not silently choose enabled or disabled."""

    repo = _repo(tmp_path, "meta_process: []\n")
    result = _run(repo, "enforce_workflow")
    assert result.returncode == 2
    assert "cannot resolve hook mode" in result.stderr
