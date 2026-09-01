from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.update_installed_runtime import RuntimeUpdateError, update_runtime


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _commit(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-m", f"test {name}")
    return _git(repo, "rev-parse", "HEAD")


def _repos(tmp_path: Path) -> tuple[Path, Path, str, str]:
    remote = tmp_path / "remote.git"
    source = tmp_path / "source"
    runtime = tmp_path / "runtime"
    subprocess.run(["git", "init", "--bare", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(source)], check=True, capture_output=True)
    _git(source, "config", "user.email", "test@example.com")
    _git(source, "config", "user.name", "Test User")
    _git(source, "checkout", "-b", "main")
    before = _commit(source, "one.txt", "one\n")
    _git(source, "push", "-u", "origin", "main")
    subprocess.run(["git", "clone", "--branch", "main", str(remote), str(runtime)], check=True, capture_output=True)
    after = _commit(source, "two.txt", "two\n")
    _git(source, "push", "origin", "main")
    return source, runtime, before, after


def test_write_fast_forwards_and_retains_exact_recovery_ref(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)

    result = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )

    assert result["action"] == "updated"
    assert result["before_revision"] == before
    assert result["after_revision"] == after
    assert result["recovery_ref"] == f"refs/codex-runtime-recovery/20260901T160000000000Z-{before[:12]}"
    assert _git(runtime, "rev-parse", "HEAD") == after
    assert _git(runtime, "rev-parse", result["recovery_ref"]) == before
    assert _git(runtime, "status", "--porcelain", "--untracked-files=all") == ""


def test_check_reports_update_without_mutating(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)

    result = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=False,
    )

    assert result["action"] == "would_update"
    assert result["changed"] is True
    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "for-each-ref", "--format=%(refname)", "refs/codex-runtime-recovery") == ""


def test_dirty_runtime_is_denied_before_fetch_or_ref_creation(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)
    (runtime / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeUpdateError, match="installed runtime is dirty"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "for-each-ref", "--format=%(refname)", "refs/codex-runtime-recovery") == ""


def test_wrong_origin_is_denied(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)
    other = tmp_path / "other.git"
    subprocess.run(["git", "init", "--bare", str(other)], check=True, capture_output=True)
    _git(runtime, "remote", "set-url", "origin", str(other))

    with pytest.raises(RuntimeUpdateError, match="origin does not match"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == before


def test_non_tip_revision_is_denied_after_fetch(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)

    with pytest.raises(RuntimeUpdateError, match="not the fetched canonical origin/main"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=before, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == before
    assert after != before


def test_divergent_runtime_is_denied(tmp_path: Path) -> None:
    source, runtime, _before, after = _repos(tmp_path)
    _git(runtime, "config", "user.email", "test@example.com")
    _git(runtime, "config", "user.name", "Test User")
    divergent = _commit(runtime, "local.txt", "local\n")

    with pytest.raises(RuntimeUpdateError, match="cannot fast-forward"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == divergent
    assert _git(runtime, "for-each-ref", "--format=%(refname)", "refs/codex-runtime-recovery") == ""


def test_detached_runtime_fast_forwards_with_checkout_mode_receipt(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)
    _git(runtime, "checkout", "--detach", before)

    result = update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert result["checkout_mode"] == "detached"
    assert result["after_revision"] == after
    symbolic_ref = subprocess.run(
        ["git", "-C", str(runtime), "symbolic-ref", "--quiet", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert symbolic_ref.returncode == 1
    assert symbolic_ref.stdout == ""


def test_non_main_named_branch_is_denied(tmp_path: Path) -> None:
    source, runtime, before, after = _repos(tmp_path)
    _git(runtime, "checkout", "-b", "feature")

    with pytest.raises(RuntimeUpdateError, match="must be on main"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == before
