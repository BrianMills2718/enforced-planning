from __future__ import annotations

import json
import os
import pwd
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

    assert caught.value.receipt["runtime_repo"] == str(runtime.absolute())
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
    assert receipt["runtime_repo"] == str(runtime.absolute())
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
    assert caught.value.receipt["source_repo"] == str(source.absolute())


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


@pytest.mark.parametrize("separator", [" ", "\r", "\n"])
def test_malformed_whitespace_url_credentials_are_redacted_from_denial(
    separator: str,
) -> None:
    receipt = runtime_update._base_receipt(
        source_repo=Path("/source"),
        runtime_repo=Path("/runtime"),
        revision="0" * 40,
        write=False,
        now=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
    )
    denial = runtime_update._deny(
        receipt,
        RuntimeUpdateError(
            f"failed https://token:super{separator}secret@evil.example/repo.git"
        ),
    )

    serialized = json.dumps(denial.receipt, sort_keys=True)
    assert "token" not in serialized
    assert "super" not in serialized
    assert "secret" not in serialized
    assert "https://<redacted>@evil.example/repo.git" in serialized


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
        "message": "injected merge failure",
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
        "type": "OSError",
        "message": "injected operating-system failure",
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
    assert caught.value.receipt["recovery_ref"] == recovery_ref
    assert caught.value.receipt["recovery_ref_retained"] is True
    assert _git(runtime, "rev-parse", recovery_ref) == before
    assert _git(runtime, "rev-parse", "HEAD") == before
