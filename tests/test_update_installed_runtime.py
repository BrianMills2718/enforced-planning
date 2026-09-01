from __future__ import annotations

import json
import os
import pwd
import subprocess
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts import update_installed_runtime as runtime_update
from scripts.update_installed_runtime import RuntimeUpdateError, rollback_runtime, update_runtime


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


def _git_path_bytes(repo: Path, name: str) -> bytes | None:
    path = Path(_git(repo, "rev-parse", "--git-path", name))
    if not path.is_absolute():
        path = repo / path
    return path.read_bytes() if path.exists() else None


def test_normalize_origin_accepts_only_explicit_canonical_transports() -> None:
    expected = "github.com/BrianMills2718/enforced-planning"
    assert runtime_update._normalize_origin(
        "https://github.com/BrianMills2718/enforced-planning.git"
    ) == expected
    for origin in (
        "git@github-personal:BrianMills2718/enforced-planning.git",
        "ssh://git@github.com/BrianMills2718/enforced-planning.git",
        "git@untrusted-alias:BrianMills2718/enforced-planning.git",
    ):
        with pytest.raises(RuntimeUpdateError, match="unsupported origin transport"):
            runtime_update._normalize_origin(origin)


def test_default_runtime_path_ignores_caller_codex_home(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CODEX_HOME", "/tmp/attacker-codex-home")

    account_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
    assert runtime_update._default_runtime_repo() == (
        account_home / ".codex" / "runtime" / "enforced-planning"
    )


def test_git_global_url_rewrite_environment_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    injected_config = tmp_path / "attacker.gitconfig"
    injected_config.write_text(
        f'[url "file:///definitely-not-the-canonical-remote/"]\n'
        f'\tinsteadOf = {_git(source, "config", "--local", "--get", "remote.origin.url")}\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(injected_config))

    result = update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert result["action"] == "would_update"
    assert result["remote_main_revision"] == after


def test_source_local_url_rewrite_cannot_spoof_remote_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    _git(
        source,
        "config",
        "url.file:///definitely-not-the-canonical-remote/.insteadOf",
        runtime_update.CANONICAL_ORIGIN,
    )

    result = update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert result["action"] == "would_update"
    assert result["remote_main_revision"] == after


def test_caller_path_cannot_intercept_git_or_receive_auth_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    attacker_bin = tmp_path / "attacker-bin"
    attacker_bin.mkdir()
    marker = tmp_path / "fake-git-ran"
    fake_git = attacker_bin / "git"
    fake_git.write_text(f"#!/bin/sh\ntouch {marker}\nexit 99\n", encoding="utf-8")
    fake_git.chmod(0o755)
    monkeypatch.setenv("PATH", f"{attacker_bin}:{os.environ['PATH']}")

    result = update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert result["remote_main_revision"] == after
    assert not marker.exists()


def test_caller_injected_git_config_and_tls_environment_is_stripped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.file:///tmp/attacker.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com/")
    monkeypatch.setenv("GIT_SSL_NO_VERIFY", "1")
    monkeypatch.setenv("SSL_CERT_FILE", "/tmp/attacker-ca.pem")
    monkeypatch.setenv("LD_PRELOAD", "/tmp/attacker.so")
    monkeypatch.setenv("HTTPS_PROXY", "http://attacker.invalid:8080")

    env = runtime_update._sanitized_git_env()

    assert "GIT_CONFIG_COUNT" not in env
    assert "GIT_CONFIG_KEY_0" not in env
    assert "GIT_CONFIG_VALUE_0" not in env
    assert "GIT_SSL_NO_VERIFY" not in env
    assert "SSL_CERT_FILE" not in env
    assert "LD_PRELOAD" not in env
    assert "HTTPS_PROXY" not in env
    assert env["GIT_CONFIG_GLOBAL"] == os.devnull
    assert env["PATH"] == "/usr/bin:/bin"


def test_local_url_rewrite_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    _git(
        runtime,
        "config",
        "url.file:///tmp/attacker.git.insteadOf",
        _git(runtime, "config", "--local", "--get", "remote.origin.url"),
    )

    with pytest.raises(RuntimeUpdateError, match="unsupported local Git configuration"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)


def test_local_tls_override_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "config", "http.sslVerify", "false")

    with pytest.raises(RuntimeUpdateError, match="unsupported local Git configuration"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)


def test_symlinked_runtime_git_directory_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    external_git_dir = tmp_path / "external-runtime.git-dir"
    (runtime / ".git").rename(external_git_dir)
    (runtime / ".git").symlink_to(external_git_dir, target_is_directory=True)

    with pytest.raises(RuntimeUpdateError, match="standalone clone"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)


def test_symlinked_exact_runtime_path_is_denied_before_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    external = tmp_path / "external-runtime"
    runtime.rename(external)
    runtime.symlink_to(external, target_is_directory=True)
    monkeypatch.setattr(runtime_update, "_canonical_runtime_repo", lambda: runtime.absolute())

    with pytest.raises(RuntimeUpdateError, match="must not contain symlinks") as caught:
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert caught.value.receipt["runtime_repo"] is None
    assert _git(external, "rev-parse", "HEAD") == _before


def test_symlink_loop_runtime_path_emits_structured_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    external = tmp_path / "preserved-runtime"
    runtime.rename(external)
    runtime.symlink_to(runtime, target_is_directory=True)
    monkeypatch.setattr(runtime_update, "_canonical_runtime_repo", lambda: runtime.absolute())

    with pytest.raises(RuntimeUpdateError, match="must not contain symlinks") as caught:
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    receipt = caught.value.receipt
    assert receipt["action"] == "denied"
    assert receipt["state"] == "failed"
    assert receipt["stage"] == "preflight"
    assert receipt["runtime_repo"] is None
    assert _git(external, "rev-parse", "HEAD") == _before


def test_source_symlink_loop_emits_structured_denial(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    source.rename(tmp_path / "preserved-source")
    source.symlink_to(source, target_is_directory=True)

    with pytest.raises(RuntimeUpdateError, match="source repository path cannot be resolved") as caught:
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert caught.value.receipt["action"] == "denied"
    assert caught.value.receipt["stage"] == "preflight"
    assert caught.value.receipt["source_repo"] is None


def test_unsupported_origin_credentials_never_enter_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    credentialed_origin = "https://token:super-secret@evil.example/repo.git"
    _git(runtime, "remote", "set-url", "origin", credentialed_origin)

    with pytest.raises(RuntimeUpdateError, match="not the canonical") as caught:
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    serialized = json.dumps(caught.value.receipt, sort_keys=True)
    assert "token" not in serialized
    assert "super-secret" not in serialized
    assert credentialed_origin not in serialized


def test_main_emits_structured_receipt_for_argument_denial(capsys: pytest.CaptureFixture[str]) -> None:
    assert runtime_update.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "denied"
    assert payload["state"] == "failed"
    assert payload["stage"] == "arguments"
    assert payload["host"]
    assert payload["observed_at"].endswith("Z")
    assert payload["error"]["type"] == "RuntimeUpdateError"


def test_main_emits_complete_json_when_hostname_lookup_fails(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fail_hostname() -> str:
        raise OSError("injected hostname failure")

    monkeypatch.setattr(runtime_update.socket, "gethostname", fail_hostname)

    assert runtime_update.main([]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["action"] == "denied"
    assert payload["state"] == "failed"
    assert payload["stage"] == "arguments"
    assert payload["host"] == "unavailable"
    assert payload["error"]["type"] == "RuntimeUpdateError"


@pytest.mark.parametrize(
    "argv",
    [
        ["--revision", "https://USERMARK:SECRETMARK@TRANSPORTMARK.invalid/repo.git"],
        ["--rollback-ref", "https://USERMARK:SECRETMARK@TRANSPORTMARK.invalid/ref"],
        [
            "--source-repo",
            "/tmp/USERMARK:SECRETMARK@TRANSPORTMARK.invalid/repo",
            "--revision",
            "0" * 40,
        ],
    ],
)
def test_cli_never_serializes_unvalidated_identifier_markers(
    argv: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    assert runtime_update.main(argv) == 1

    stdout = capsys.readouterr().out
    json.loads(stdout)
    assert "USERMARK" not in stdout
    assert "SECRETMARK" not in stdout
    assert "TRANSPORTMARK" not in stdout


@pytest.mark.parametrize(
    "raw_error",
    [
        "https://token:super secret@evil.example/repo.git",
        "https://token:super\rsecret@evil.example/repo.git",
        "https://token:super\nsecret@evil.example/repo.git",
        "https://token:super\r\nsecret@evil.example/repo.git",
        "https://token:super\tsecret@evil.example/repo.git",
        "https://token:super\fsecret@evil.example/repo.git",
        "https://token:super\vsecret@evil.example/repo.git",
        "https://token:super@secret@evil.example/repo.git",
        "https:/token:super-secret@evil.example/repo.git",
        "https//token:super-secret@evil.example/repo.git",
        r"https:\\token:super-secret@evil.example/repo.git",
        "https::token:super-secret@evil.example/repo.git",
        "mailto:ops@example.com",
        "urn:contact:ops@example.com",
        "label ops@example.com",
    ],
)
def test_denial_receipt_uses_fixed_safe_error_boundary(raw_error: str) -> None:
    receipt = runtime_update._base_receipt(
        source_repo=Path("/source"),
        runtime_repo=Path("/runtime"),
        revision="0" * 40,
        write=False,
        now=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
    )
    denial = runtime_update._deny(
        receipt,
        RuntimeUpdateError(f"failed {raw_error}"),
    )

    serialized = json.dumps(denial.receipt, sort_keys=True)
    assert raw_error not in serialized
    assert denial.receipt["error"] == {
        "type": "RuntimeUpdateError",
        "code": "runtime_update_failed",
        "message": "Runtime update failed at the recorded stage; raw error details are omitted.",
    }


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


def test_write_migrates_exact_legacy_runtime_alias_without_dereferencing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "remote", "set-url", "origin", runtime_update.LEGACY_RUNTIME_ORIGIN)

    result = update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=True)

    assert result["action"] == "updated"
    assert result["stored_origin_before"] == "legacy_github_personal_alias"
    assert result["stored_origin_after"] == "canonical_https"
    assert result["origin_migration_required"] is True
    assert _git(runtime, "config", "--local", "--get", "remote.origin.url") == runtime_update.CANONICAL_ORIGIN
    assert _git(runtime, "rev-parse", "HEAD") == after
    assert _git(runtime, "rev-parse", result["recovery_ref"]) == before


def test_check_reports_update_without_mutating_refs_or_fetch_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    refs_before = _all_refs(runtime)
    fetch_head_before = _fetch_head(runtime)
    index_before = _git_path_bytes(runtime, "index")
    (runtime / "one.txt").touch()

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
    assert _git_path_bytes(runtime, "index") == index_before


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


def test_source_origin_metadata_is_not_a_trust_anchor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    other = tmp_path / "other.git"
    subprocess.run(["git", "init", "--bare", str(other)], check=True, capture_output=True)
    _git(source, "remote", "set-url", "origin", str(other))

    result = update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert result["action"] == "would_update"
    assert result["remote_main_revision"] == after
    assert _git(runtime, "rev-parse", "HEAD") == before


def test_noncanonical_runtime_path_is_denied_before_repository_inspection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _runtime, _before, after = _repos(tmp_path, monkeypatch)
    impostor = tmp_path / "impostor"
    subprocess.run(["git", "clone", str(tmp_path / "remote.git"), str(impostor)], check=True, capture_output=True)

    with pytest.raises(RuntimeUpdateError, match="installed runtime path must be exactly") as caught:
        update_runtime(source_repo=source, runtime_repo=impostor, revision=after, write=False)

    assert caught.value.receipt["runtime_repo"] is None
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


def test_forward_update_then_exact_rollback_restores_revision_and_origin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    _git(runtime, "remote", "set-url", "origin", runtime_update.LEGACY_RUNTIME_ORIGIN)

    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 0, tzinfo=UTC),
    )
    recovery_ref = updated["recovery_ref"]
    assert _git(runtime, "rev-parse", "HEAD") == after
    assert _git(runtime, "remote", "get-url", "origin") == runtime_update.CANONICAL_ORIGIN

    checked = rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=False)
    assert checked["action"] == "would_rollback"
    assert checked["mutation_started"] is False
    assert _git(runtime, "rev-parse", "HEAD") == after

    rolled_back = rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)
    assert rolled_back["action"] == "rolled_back"
    assert rolled_back["recovery_ref_consumed"] is True
    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "remote", "get-url", "origin") == runtime_update.LEGACY_RUNTIME_ORIGIN
    assert subprocess.run(
        ["git", "-C", str(runtime), "rev-parse", "--verify", recovery_ref],
        check=False,
        capture_output=True,
        text=True,
    ).returncode != 0
    assert runtime_update._load_recovery_metadata(runtime, recovery_ref)["state"] == "consumed"


def test_rollback_denies_mismatched_recovery_ref_without_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 5, tzinfo=UTC),
    )
    recovery_ref = updated["recovery_ref"]
    _git(runtime, "update-ref", recovery_ref, after, before)

    with pytest.raises(RuntimeUpdateError, match="no longer matches") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)

    assert caught.value.receipt["mutation_started"] is False
    assert _git(runtime, "rev-parse", "HEAD") == after


def test_rollback_recovers_partial_update_before_origin_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    _git(runtime, "remote", "set-url", "origin", runtime_update.LEGACY_RUNTIME_ORIGIN)
    real_run = runtime_update._run

    def fail_origin_migration(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args[:3] == ("remote", "set-url", "origin"):
            raise RuntimeUpdateError("injected origin migration failure")
        return real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)

    monkeypatch.setattr(runtime_update, "_run", fail_origin_migration)
    with pytest.raises(RuntimeUpdateError, match="injected origin migration failure") as caught:
        update_runtime(
            source_repo=source,
            runtime_repo=runtime,
            revision=after,
            write=True,
            now=datetime(2026, 9, 1, 18, 10, tzinfo=UTC),
        )

    recovery_ref = caught.value.receipt["recovery_ref"]
    assert _git(runtime, "rev-parse", "HEAD") == after
    monkeypatch.setattr(runtime_update, "_run", real_run)

    rolled_back = rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)

    assert rolled_back["action"] == "rolled_back"
    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "remote", "get-url", "origin") == runtime_update.LEGACY_RUNTIME_ORIGIN


def test_main_checkout_update_then_rollback_restores_main_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 15, tzinfo=UTC),
    )

    rolled_back = rollback_runtime(
        runtime_repo=runtime,
        recovery_ref=updated["recovery_ref"],
        write=True,
    )

    assert rolled_back["action"] == "rolled_back"
    assert rolled_back["checkout_mode"] == "main"
    assert _git(runtime, "symbolic-ref", "--short", "HEAD") == "main"
    assert _git(runtime, "rev-parse", "HEAD") == before


def test_rollback_origin_failure_is_retryable_with_current_receipt_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    _git(runtime, "remote", "set-url", "origin", runtime_update.LEGACY_RUNTIME_ORIGIN)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 16, tzinfo=UTC),
    )
    recovery_ref = updated["recovery_ref"]
    real_run = runtime_update._run
    failed = False

    def fail_origin_once(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        if not failed and args[:3] == ("remote", "set-url", "origin"):
            failed = True
            raise RuntimeUpdateError("injected rollback origin failure")
        return real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)

    monkeypatch.setattr(runtime_update, "_run", fail_origin_once)
    with pytest.raises(RuntimeUpdateError, match="injected rollback origin failure") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)

    assert caught.value.receipt["after_revision"] == before
    assert caught.value.receipt["recovery_ref_consumed"] is False
    assert _git(runtime, "rev-parse", recovery_ref) == before
    monkeypatch.setattr(runtime_update, "_run", real_run)

    retried = rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)
    assert retried["action"] == "rolled_back"
    assert _git(runtime, "rev-parse", "HEAD") == before
    assert _git(runtime, "remote", "get-url", "origin") == runtime_update.LEGACY_RUNTIME_ORIGIN


def test_rollback_ref_delete_failure_is_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 17, tzinfo=UTC),
    )
    recovery_ref = updated["recovery_ref"]
    real_run = runtime_update._run
    failed = False

    def fail_ref_delete_once(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        if not failed and args[:3] == ("update-ref", "--no-deref", "-d"):
            failed = True
            raise RuntimeUpdateError("injected recovery ref deletion failure")
        return real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)

    monkeypatch.setattr(runtime_update, "_run", fail_ref_delete_once)
    with pytest.raises(RuntimeUpdateError, match="injected recovery ref deletion failure") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)

    assert caught.value.receipt["after_revision"] == before
    assert caught.value.receipt["recovery_ref_consumed"] is False
    assert _git(runtime, "rev-parse", recovery_ref) == before
    monkeypatch.setattr(runtime_update, "_run", real_run)

    retried = rollback_runtime(runtime_repo=runtime, recovery_ref=recovery_ref, write=True)
    assert retried["action"] == "finalized_rollback"
    assert retried["recovery_ref_consumed"] is True
    assert retried["recovery_record_state"] == "consumed"


def test_rollback_rejects_forged_suffix_even_with_matching_ref_and_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 18, tzinfo=UTC),
    )
    forged_ref = f"{runtime_update.RECOVERY_NAMESPACE}/20260901T181800000000Z-{after[:12]}"
    _git(runtime, "update-ref", "--no-deref", forged_ref, before)
    runtime_update._record_recovery_metadata(
        runtime,
        recovery_ref=forged_ref,
        before=before,
        target=after,
        prior_origin=runtime_update.CANONICAL_ORIGIN,
        checkout_mode="detached",
        checkout_ref=None,
    )

    with pytest.raises(RuntimeUpdateError, match="not bound") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=forged_ref, write=True)

    assert caught.value.receipt["mutation_started"] is False
    assert _git(runtime, "rev-parse", "HEAD") == after


@pytest.mark.parametrize("symbolic_target", ["refs/heads/main", "refs/heads/missing-target"])
def test_update_refuses_symbolic_recovery_ref_without_mutating_its_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    symbolic_target: str,
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    observed = datetime(2026, 9, 1, 18, 19, tzinfo=UTC)
    recovery_ref = runtime_update._recovery_ref(before, observed)
    _git(runtime, "symbolic-ref", recovery_ref, symbolic_target)
    target_before = subprocess.run(
        ["git", "-C", str(runtime), "rev-parse", "--verify", symbolic_target],
        check=False,
        capture_output=True,
        text=True,
    )

    with pytest.raises(RuntimeUpdateError):
        update_runtime(
            source_repo=source,
            runtime_repo=runtime,
            revision=after,
            write=True,
            now=observed,
        )

    assert _git(runtime, "symbolic-ref", recovery_ref) == symbolic_target
    target_after = subprocess.run(
        ["git", "-C", str(runtime), "rev-parse", "--verify", symbolic_target],
        check=False,
        capture_output=True,
        text=True,
    )
    assert (target_after.returncode, target_after.stdout) == (
        target_before.returncode,
        target_before.stdout,
    )


def test_check_rejects_fsmonitor_before_it_can_execute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    marker = tmp_path / "fsmonitor-executed"
    fsmonitor = tmp_path / "fsmonitor.sh"
    fsmonitor.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    fsmonitor.chmod(0o755)
    _git(runtime, "config", "core.fsmonitor", str(fsmonitor))

    with pytest.raises(RuntimeUpdateError, match="unsupported local Git configuration"):
        update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)

    assert not marker.exists()


def test_mutating_update_and_rollback_suppress_checkout_hooks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    marker = tmp_path / "post-checkout-executed"
    hook = runtime / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\ntouch {marker}\n", encoding="utf-8")
    hook.chmod(0o755)

    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 20, tzinfo=UTC),
    )
    rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert not marker.exists()


def test_rollback_origin_after_effect_failure_is_observed_and_retryable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    _git(runtime, "remote", "set-url", "origin", runtime_update.LEGACY_RUNTIME_ORIGIN)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 21, tzinfo=UTC),
    )
    real_run = runtime_update._run
    failed = False

    def fail_after_origin_change(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        result = real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)
        if not failed and args[:3] == ("remote", "set-url", "origin"):
            failed = True
            raise RuntimeUpdateError("injected after-effect origin failure")
        return result

    monkeypatch.setattr(runtime_update, "_run", fail_after_origin_change)
    with pytest.raises(RuntimeUpdateError, match="injected after-effect origin failure") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert caught.value.receipt["after_revision"] == before
    assert caught.value.receipt["stored_origin_after"] == "legacy_github_personal_alias"
    assert caught.value.receipt["receipt_refresh_failed"] is False
    monkeypatch.setattr(runtime_update, "_run", real_run)
    retried = rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)
    assert retried["action"] == "rolled_back"


def test_rollback_ref_delete_after_effect_failure_retries_from_tombstone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 22, tzinfo=UTC),
    )
    real_run = runtime_update._run
    failed = False

    def fail_after_ref_delete(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal failed
        result = real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)
        if not failed and args[:3] == ("update-ref", "--no-deref", "-d"):
            failed = True
            raise RuntimeUpdateError("injected after-effect ref deletion failure")
        return result

    monkeypatch.setattr(runtime_update, "_run", fail_after_ref_delete)
    with pytest.raises(RuntimeUpdateError, match="injected after-effect ref deletion failure") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert caught.value.receipt["recovery_ref_consumed"] is True
    assert caught.value.receipt["recovery_record_state"] == "consumed"
    monkeypatch.setattr(runtime_update, "_run", real_run)
    retried = rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)
    assert retried["action"] == "already_rolled_back"


def test_rollback_failure_receipt_marks_refresh_probe_failure_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    _git(runtime, "remote", "set-url", "origin", runtime_update.LEGACY_RUNTIME_ORIGIN)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 23, tzinfo=UTC),
    )
    real_run = runtime_update._run
    mutation_failed = False

    def fail_mutation_then_refresh(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal mutation_failed
        if not mutation_failed and args[:3] == ("remote", "set-url", "origin"):
            mutation_failed = True
            raise RuntimeUpdateError("injected rollback failure")
        if mutation_failed and args == ("rev-parse", "HEAD") and not check:
            raise RuntimeUpdateError("injected refresh failure with secret text")
        return real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)

    monkeypatch.setattr(runtime_update, "_run", fail_mutation_then_refresh)
    with pytest.raises(RuntimeUpdateError, match="injected rollback failure") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert caught.value.receipt["receipt_refresh_failed"] is True
    assert caught.value.receipt["after_revision"] is None
    assert "secret text" not in json.dumps(caught.value.receipt)


def test_rollback_rejects_annotated_tag_recovery_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 24, tzinfo=UTC),
    )
    _git(runtime, "config", "user.email", "test@example.com")
    _git(runtime, "config", "user.name", "Test User")
    _git(runtime, "tag", "-a", "annotated-recovery", before, "-m", "test")
    tag_object = _git(runtime, "rev-parse", "annotated-recovery")
    _git(runtime, "update-ref", "--no-deref", updated["recovery_ref"], tag_object)

    with pytest.raises(RuntimeUpdateError, match="directly to a commit") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert caught.value.receipt["mutation_started"] is False
    assert _git(runtime, "rev-parse", "HEAD") == after


def test_rollback_rejects_duplicate_recovery_metadata_values(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    _git(runtime, "checkout", "--detach", before)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 25, tzinfo=UTC),
    )
    key = runtime_update._recovery_config_key(updated["recovery_ref"], "record")
    record = _git(runtime, "config", "--local", "--get", key)
    _git(runtime, "config", "--local", "--add", key, record)

    with pytest.raises(RuntimeUpdateError, match="exactly one recovery record") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert caught.value.receipt["mutation_started"] is False
    assert _git(runtime, "rev-parse", "HEAD") == after


def test_rollback_rejects_changed_checkout_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    updated = update_runtime(
        source_repo=source,
        runtime_repo=runtime,
        revision=after,
        write=True,
        now=datetime(2026, 9, 1, 18, 26, tzinfo=UTC),
    )
    _git(runtime, "checkout", "--detach", after)

    with pytest.raises(RuntimeUpdateError, match="checkout identity") as caught:
        rollback_runtime(runtime_repo=runtime, recovery_ref=updated["recovery_ref"], write=True)

    assert caught.value.receipt["mutation_started"] is False
    assert _git(runtime, "rev-parse", "HEAD") == after


def test_update_operations_share_one_exclusive_runtime_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, _before, after = _repos(tmp_path, monkeypatch)
    entered = threading.Event()
    finished = threading.Event()
    result: list[dict[str, object]] = []

    def run_check() -> None:
        entered.set()
        result.append(
            update_runtime(source_repo=source, runtime_repo=runtime, revision=after, write=False)
        )
        finished.set()

    with runtime_update._exclusive_runtime_lock(runtime):
        worker = threading.Thread(target=run_check)
        worker.start()
        assert entered.wait(timeout=1)
        assert not finished.wait(timeout=0.1)
    worker.join(timeout=5)

    assert finished.is_set()
    assert result[0]["action"] == "would_update"


def test_partial_failure_receipt_retains_recovery_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    real_run = runtime_update._run

    def fail_merge(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "merge":
            raise RuntimeUpdateError("injected merge failure")
        return real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)

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
        "code": "runtime_update_failed",
        "message": "Runtime update failed at the recorded stage; raw error details are omitted.",
    }
    assert real_run(runtime, "rev-parse", receipt["recovery_ref"]).stdout.strip() == before


def test_oserror_after_recovery_ref_emits_structured_partial_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    real_run = runtime_update._run

    def fail_merge(
        repo: Path,
        *args: str,
        check: bool = True,
        mutating: bool = False,
        network_auth: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        if args and args[0] == "merge":
            raise OSError("injected operating-system failure")
        return real_run(repo, *args, check=check, mutating=mutating, network_auth=network_auth)

    monkeypatch.setattr(runtime_update, "_run", fail_merge)
    with pytest.raises(RuntimeUpdateError, match="injected operating-system failure") as caught:
        update_runtime(
            source_repo=source,
            runtime_repo=runtime,
            revision=after,
            write=True,
            now=datetime(2026, 9, 1, 16, 35, tzinfo=UTC),
        )

    receipt = caught.value.receipt
    assert receipt["action"] == "partial_failure"
    assert receipt["state"] == "failed"
    assert receipt["stage"] == "apply_update"
    assert receipt["after_revision"] == before
    assert receipt["recovery_ref_retained"] is True
    assert receipt["error"] == {
        "type": "RuntimeUpdateError",
        "code": "runtime_update_failed",
        "message": "Runtime update failed at the recorded stage; raw error details are omitted.",
    }
    assert real_run(runtime, "rev-parse", receipt["recovery_ref"]).stdout.strip() == before


def test_recovery_ref_collision_is_denied_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, runtime, before, after = _repos(tmp_path, monkeypatch)
    observed = datetime(2026, 9, 1, 16, 45, tzinfo=UTC)
    recovery_ref = runtime_update._recovery_ref(before, observed)
    _git(runtime, "update-ref", recovery_ref, before)

    with pytest.raises(RuntimeUpdateError, match="already exists") as caught:
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
    assert caught.value.receipt["recovery_ref"] == recovery_ref
    assert caught.value.receipt["recovery_ref_retained"] is True
    assert _git(runtime, "rev-parse", recovery_ref) == before
    assert _git(runtime, "rev-parse", "HEAD") == before
