"""Safety tests for governed-repository fleet upgrades."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "upgrade_governed_repos.py"


def _load():
    spec = importlib.util.spec_from_file_location("upgrade_governed_repos_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_write_mode_requires_explicit_repo(capsys) -> None:
    """--write must never fan out to the whole fleet in one shot.

    Regression for the design doc's "Minimal First Slice": batch write-mode
    is a later slice, not this command's default. Checked before the
    registry is even read, so a missing --repo can never license mutation.
    """
    module = _load()

    assert module.main(["--write", "--registry", "/definitely/missing.yaml"]) == 2
    captured = capsys.readouterr()
    assert "--write requires --repo REPO_ID" in captured.err
    assert "one repo at a time" in captured.err


def test_write_repo_refuses_non_brian_owner(tmp_path: Path) -> None:
    """Fleet write-mode must not silently reach a non-Brian-owned repo.

    A company/org repo needs its own explicit authorization distinct from
    blanket personal-fleet write-mode (see CLAUDE.md's repository-routing
    rules); this must be a skip, not an attempted sync.
    """
    module = _load()

    result = module.write_repo("some-org-repo", tmp_path, "governed", "inside-success")
    assert result.skipped is True
    assert "inside-success" in result.skip_reason
    assert "explicit authorization" in result.skip_reason


def test_write_repo_skips_missing_repo_root(tmp_path: Path) -> None:
    module = _load()
    missing = tmp_path / "does-not-exist"
    result = module.write_repo("ghost-repo", missing, "governed", "brian")
    assert result.skipped is True
    assert "does not exist" in result.skip_reason


def test_write_repo_skips_repo_without_makefile(tmp_path: Path) -> None:
    """Cannot use the sanctioned maintenance-worktree entrypoint without one."""
    module = _load()
    result = module.write_repo("no-makefile-repo", tmp_path, "governed", "brian")
    assert result.skipped is True
    assert "Makefile" in result.skip_reason


def test_single_line_collapses_multiline_reason() -> None:
    """A multi-line reason breaks Make's `"$(VAR)"` recipe-line expansion.

    Regression for a live bug: an embedded newline in WORKTREE_DISPOSITION_REASON
    silently made the abandoned-then-merged session-close retry never actually
    run, leaving worktrees/branches behind after every failed write attempt.
    """
    module = _load()
    multiline = "Running pre-commit checks...\nChecking doc-code coupling...\n  Violation: X"
    collapsed = module._single_line(multiline, 200)
    assert "\n" not in collapsed
    assert "Running pre-commit checks..." in collapsed


def test_native_agent_uses_exact_codex_runtime_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    for env_key in module.coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.values():
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "native-codex-thread")

    assert module._native_agent() == "codex"


def test_native_agent_rejects_ambiguous_runtime_markers(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load()
    for env_key in module.coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.values():
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "native-codex-thread")
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "native-claude-thread")

    with pytest.raises(ValueError, match="exactly one native agent runtime marker"):
        module._native_agent()


def test_source_revision_tag_is_stable_git_identity() -> None:
    module = _load()

    revision = module._source_revision_tag()

    assert len(revision) == 12
    assert all(char in "0123456789abcdef" for char in revision)


def test_write_repo_bootstraps_with_whole_repository_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every supported maintenance wrapper understands bootstrap `.` scope."""

    module = _load()
    repo = tmp_path / "consumer"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "worktree:\n\t@true\n\nmaintenance-worktree:\n\t@true\n",
        encoding="utf-8",
    )
    for env_key in module.coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.values():
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "native-codex-thread")
    calls: list[list[str]] = []

    def reject_after_capture(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        del cwd
        calls.append(cmd)
        return subprocess.CompletedProcess(
            cmd,
            1,
            stdout="broad_scope_mode_required; broad_scope_reason_required",
            stderr="fixture stop",
        )

    monkeypatch.setattr(module, "_run", reject_after_capture)

    result = module.write_repo("consumer", repo, "governed", "brian")

    assert result.write_error.startswith("make maintenance-worktree failed")
    assert result.branch.endswith(module._source_revision_tag())
    assert calls[0][3] == "maintenance-worktree"
    assert "WORKTREE_AGENT=codex" in calls[0]
    assert "SESSION_WRITE_PATHS=." in calls[0]
    assert calls[1][3] == "worktree"
    assert "SESSION_BROAD_SCOPE_MODE=bootstrap" in calls[1]
    assert any(item.startswith("SESSION_TARGET_WORKTREE_PATH=") for item in calls[1])


def test_write_repo_cannot_install_when_claim_narrowing_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The temporary broad bootstrap cannot reach installer mutation."""

    module = _load()
    repo = tmp_path / "consumer"
    repo.mkdir()
    (repo / "Makefile").write_text(
        "worktree:\n\t@true\n\nmaintenance-worktree:\n\t@true\n",
        encoding="utf-8",
    )
    for env_key in module.coordination_claims.STRICT_NATIVE_SESSION_ENV_KEYS.values():
        monkeypatch.delenv(env_key, raising=False)
    monkeypatch.setenv("CODEX_THREAD_ID", "native-codex-thread")
    calls: list[list[str]] = []

    def run_until_narrowing_fails(
        cmd: list[str],
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del cwd
        calls.append(cmd)
        if "maintenance-worktree" in cmd:
            (repo / "worktrees" / next(item.split("=", 1)[1] for item in cmd if item.startswith("BRANCH="))).mkdir(
                parents=True
            )
            return subprocess.CompletedProcess(cmd, 0, stdout="created", stderr="")
        if "session-narrow" in cmd:
            return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="narrowing denied")
        if cmd[:3] == ["git", "status", "--porcelain"]:
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        if "worktree-remove" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="closed", stderr="")
        raise AssertionError(f"unexpected command after narrowing failure: {cmd}")

    monkeypatch.setattr(module, "_run", run_until_narrowing_fails)

    result = module.write_repo("consumer", repo, "governed", "brian")

    assert result.write_error == "session-narrow failed before installer mutation: narrowing denied"
    assert any("session-narrow" in cmd for cmd in calls)
    assert all(str(module.INSTALL_SCRIPT) not in cmd for cmd in calls)
