from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import update_installed_runtime as runtime_update
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


def _repos(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path, str, str]:
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
    monkeypatch.setattr(runtime_update, "CANONICAL_ORIGIN", _git(source, "remote", "get-url", "origin"))
    monkeypatch.setattr(runtime_update, "_canonical_runtime_repo", lambda: runtime.resolve())
    return source, runtime, before, after


def _fetch_head(repo: Path) -> bytes | None:
    path = Path(_git(repo, "rev-parse", "--git-path", "FETCH_HEAD"))
    if not path.is_absolute():
        path = repo / path
    return path.read_bytes() if path.exists() else None


def _all_refs(repo: Path) -> str:
    return _git(repo, "for-each-ref", "--format=%(refname) %(objectname)")


def test_normalize_origin_accepts_only_explicit_canonical_transports() -> None:
    expected = "github.com/BrianMills2718/enforced-planning"
    assert runtime_update._normalize_origin(
        "git@github-personal:BrianMills2718/enforced-planning.git"
    ) == expected
    assert runtime_update._normalize_origin(
        "ssh://git@github.com/BrianMills2718/enforced-planning.git"
    ) == expected
    with pytest.raises(RuntimeUpdateError, match="unsupported origin transport"):
        runtime_update._normalize_origin(
            "git@untrusted-alias:BrianMills2718/enforced-planning.git"
        )


def test_main_emits_structured_receipt_for_argument_denial(capsys: pytest.CaptureFixture[str]) -> None:
    assert runtime_update.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "denied"
    assert payload["state"] == "failed"
    assert payload["stage"] == "arguments"
    assert payload["host"]
    assert payload["observed_at"].endswith("Z")
    assert payload["error"]["type"] == "RuntimeUpdateError"


def test_write_fast_forwards_and_retains_exact_recovery_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)

    result = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 16, 0, tzinfo=UTC),
    )

    assert result["action"] == "updated"
    assert result["state"] == "succeeded"
    assert result["stage"] == "complete"
    assert result["host"]
    assert result["observed_at"].endswith("Z")
    assert result["before_revision"] == before
    assert result["after_revision"] == after
    assert result["recovery_ref"] == f"refs/codex-runtime-recovery/20260901T160000000000Z-{before[:12]}"
    assert _git(runtime, "rev-parse", "HEAD") == after
    assert _git(runtime, "rev-parse", result["recovery_ref"]) == before
    assert _git(runtime, "status", "--porcelain", "--untracked-files=all") == ""


def test_check_reports_update_without_mutating_refs_or_fetch_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    refs_before = _all_refs(runtime)
    fetch_head_before = _fetch_head(runtime)

    result = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=False,
    )

    assert result["action"] == "would_update"
    assert result["state"] == "succeeded"
    assert result["changed"] is True
    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "for-each-ref", "--format=%(refname)", "refs/codex-runtime-recovery") == ""
    assert _all_refs(runtime) == refs_before
    assert _fetch_head(runtime) == fetch_head_before


def test_dirty_runtime_is_denied_before_fetch_or_ref_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    (runtime / "dirty.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(RuntimeUpdateError, match="installed runtime is dirty") as caught:
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert caught.value.receipt["state"] == "failed"
    assert caught.value.receipt["stage"] == "preflight"
    assert caught.value.receipt["before_revision"] is None
    assert caught.value.receipt["target_revision"] == after
    assert caught.value.receipt["recovery_ref"] is None
    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "for-each-ref", "--format=%(refname)", "refs/codex-runtime-recovery") == ""


def test_wrong_origin_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    other = tmp_path / "other.git"
    subprocess.run(["git", "init", "--bare", str(other)], check=True, capture_output=True)
    _git(runtime, "remote", "set-url", "origin", str(other))

    with pytest.raises(RuntimeUpdateError, match="not the canonical") as caught:
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert caught.value.receipt["state"] == "failed"
    assert _git(runtime, "rev-parse", "HEAD") == before


def test_matching_caller_selected_wrong_origins_are_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    other = tmp_path / "other.git"
    subprocess.run(["git", "init", "--bare", str(other)], check=True, capture_output=True)
    _git(source, "remote", "set-url", "origin", str(other))
    _git(runtime, "remote", "set-url", "origin", str(other))

    with pytest.raises(RuntimeUpdateError, match="source repository is not the canonical"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert _git(runtime, "rev-parse", "HEAD") == before


def test_noncanonical_runtime_path_is_denied_before_repository_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    impostor = tmp_path / "impostor"
    subprocess.run(["git", "clone", str(tmp_path / "remote.git"), str(impostor)], check=True, capture_output=True)

    with pytest.raises(RuntimeUpdateError, match="installed runtime path must be exactly") as caught:
        update_runtime(source_repo=source, runtime_repo=impostor, revision=after, write=False)

    assert caught.value.receipt["runtime_repo"] == str(impostor.resolve())
    assert caught.value.receipt["stage"] == "preflight"


def test_runtime_subdirectory_is_denied_as_nonexact_worktree_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    subdirectory = runtime / "nested"
    subdirectory.mkdir()
    monkeypatch.setattr(runtime_update, "_canonical_runtime_repo", lambda: subdirectory.resolve())

    with pytest.raises(RuntimeUpdateError, match="exact Git worktree root"):
        update_runtime(source_repo=source, runtime_repo=subdirectory, revision=after, write=False)


def test_source_and_runtime_must_be_distinct_clones(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _runtime, _before, after = _repos(tmp_path, monkeypatch)
    monkeypatch.setattr(runtime_update, "_canonical_runtime_repo", lambda: source.resolve())

    with pytest.raises(RuntimeUpdateError, match="must be distinct clones"):
        update_runtime(source_repo=source, runtime_repo=source, revision=after, write=False)


def test_non_tip_revision_is_denied_without_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    refs_before = _all_refs(runtime)
    fetch_head_before = _fetch_head(runtime)

    with pytest.raises(RuntimeUpdateError, match="not canonical origin/main"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=before, write=False)

    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _all_refs(runtime) == refs_before
    assert _fetch_head(runtime) == fetch_head_before
    assert after != before


def test_divergent_runtime_is_denied(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "config", "user.email", "test@example.com")
    _git(runtime, "config", "user.name", "Test User")
    divergent = _commit(runtime, "local.txt", "local\n")

    with pytest.raises(RuntimeUpdateError, match="cannot fast-forward"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == divergent
    assert _git(runtime, "for-each-ref", "--format=%(refname)", "refs/codex-runtime-recovery") == ""


def test_detached_runtime_fast_forwards_with_checkout_mode_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
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


def test_non_main_named_branch_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "-b", "feature")

    with pytest.raises(RuntimeUpdateError, match="must be on main"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert _git(runtime, "rev-parse", "HEAD") == before


def test_explicit_detached_replacement_retains_divergent_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    _git(runtime, "config", "user.email", "test@example.com")
    _git(runtime, "config", "user.name", "Test User")
    divergent = _commit(runtime, "divergent.txt", "divergent\n")

    result = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        allow_detached_replacement=True,
    )

    assert result["checkout_mode"] == "detached"
    assert result["update_mode"] == "detached_replacement"
    assert result["before_revision"] == divergent
    assert result["after_revision"] == after
    assert _git(runtime, "rev-parse", result["recovery_ref"]) == divergent


def test_partial_failure_receipt_retains_recovery_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    real_run = runtime_update._run

    def fail_merge(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "merge":
            raise RuntimeUpdateError("injected merge failure")
        return real_run(repo, *args, check=check)

    monkeypatch.setattr(runtime_update, "_run", fail_merge)
    with pytest.raises(RuntimeUpdateError, match="injected merge failure") as caught:
        update_runtime(
            source_repo=source,
            runtime_repo=runtime,
            revision=after,
            write=True,
            now=datetime(2026, 9, 1, 16, 30, tzinfo=UTC),
        )

    receipt = caught.value.receipt
    assert receipt["action"] == "partial_failure"
    assert receipt["state"] == "failed"
    assert receipt["stage"] == "apply_update"
    assert receipt["before_revision"] == before
    assert receipt["target_revision"] == after
    assert receipt["after_revision"] == before
    assert receipt["recovery_ref"]
    assert receipt["recovery_ref_retained"] is True
    assert receipt["error"] == {
        "type": "RuntimeUpdateError",
        "message": "injected merge failure",
    }
    assert real_run(runtime, "rev-parse", receipt["recovery_ref"]).stdout.strip() == before


def test_recovery_ref_collision_is_denied_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    observed = datetime(2026, 9, 1, 16, 45, tzinfo=UTC)
    recovery_ref = runtime_update._recovery_ref(before, observed)
    _git(runtime, "update-ref", recovery_ref, before)

    with pytest.raises(RuntimeUpdateError, match="cannot lock ref") as caught:
        update_runtime(
            source_repo=source,
            runtime_repo=runtime,
            revision=after,
            write=True,
            now=observed,
        )

    assert caught.value.receipt["action"] == "partial_failure"
    assert caught.value.receipt["stage"] == "create_recovery_ref"
    assert caught.value.receipt["mutation_started"] is True
    assert _git(runtime, "rev-parse", recovery_ref) == before
    assert _git(runtime, "rev-parse", "HEAD") == before
