"""Tests for scripts/pr_auto.py."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
MODULE_PATH = SCRIPTS_DIR / "pr_auto.py"


def _load() -> object:
    spec = importlib.util.spec_from_file_location("pr_auto_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_parse_github_repo_slug_supports_common_remote_forms() -> None:
    """SSH and HTTPS remotes should normalize to owner/repo."""
    module = _load()

    assert module.parse_github_repo_slug("git@github.com:BrianMills2718/project-meta.git") == "BrianMills2718/project-meta"  # type: ignore[attr-defined]
    assert module.parse_github_repo_slug("https://github.com/BrianMills2718/project-meta.git") == "BrianMills2718/project-meta"  # type: ignore[attr-defined]


def test_origin_matches_expected_repo_compares_repo_name_only() -> None:
    """Origin check should compare the repo name after slug parsing."""
    module = _load()

    assert module.origin_matches_expected_repo(  # type: ignore[attr-defined]
        "git@github.com:BrianMills2718/project-meta.git",
        "project-meta",
    )
    assert not module.origin_matches_expected_repo(  # type: ignore[attr-defined]
        "git@github.com:BrianMills2718/project-meta.git",
        "llm_client",
    )


def test_filter_non_ignorable_status_lines_drops_known_transient_metadata() -> None:
    """Status filter should remove active-work/session noise and keep real dirt."""
    module = _load()

    filtered = module.filter_non_ignorable_status_lines(  # type: ignore[attr-defined]
        [
            "?? .claude/active-work.yaml",
            "?? .claude/sessions/2026-04-03/foo.json",
            " M docs/plans/83_scripts-meta-wave10-merge-pr-and-pr-auto-convergence.md",
        ]
    )

    assert filtered == [
        "M docs/plans/83_scripts-meta-wave10-merge-pr-and-pr-auto-convergence.md",
    ]


def test_sanitize_github_env_removes_token_overrides() -> None:
    """GitHub token env vars should be removed so gh uses stored auth."""
    module = _load()

    env = module.sanitize_github_env(  # type: ignore[attr-defined]
        {
            "GITHUB_TOKEN": "x",
            "GH_TOKEN": "y",
            "GITHUB_ENTERPRISE_TOKEN": "z",
            "KEEP_ME": "ok",
        }
    )

    assert "GITHUB_TOKEN" not in env
    assert "GH_TOKEN" not in env
    assert "GITHUB_ENTERPRISE_TOKEN" not in env
    assert env["KEEP_ME"] == "ok"
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


def test_isolated_github_auth_does_not_mutate_shared_config(tmp_path: Path) -> None:
    """Account selection must use a temporary GH config directory."""
    module = _load()
    source = tmp_path / "shared-gh"
    source.mkdir()
    hosts = source / "hosts.yml"
    hosts.write_text("active: original\n", encoding="utf-8")
    observed: list[tuple[Path, str]] = []

    def fake_switch(cwd: Path, env: dict[str, str], account: str) -> None:
        isolated_hosts = Path(env["GH_CONFIG_DIR"]) / "hosts.yml"
        observed.append((isolated_hosts, account))
        isolated_hosts.write_text("active: selected\n", encoding="utf-8")

    module._switch_gh_account = fake_switch  # type: ignore[attr-defined]
    with module.isolated_github_auth(  # type: ignore[attr-defined]
        cwd=tmp_path,
        gh_env={**os.environ, "GH_CONFIG_DIR": str(source)},
        account="expected-owner",
    ) as env:
        isolated_dir = Path(env["GH_CONFIG_DIR"])
        assert isolated_dir != source
        assert (isolated_dir / "hosts.yml").read_text(encoding="utf-8") == "active: selected\n"

    assert observed[0][1] == "expected-owner"
    assert hosts.read_text(encoding="utf-8") == "active: original\n"
    assert not isolated_dir.exists()


def _completed(
    cmd: list[str],
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(cmd, returncode, stdout, stderr)


def _published_ref(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return _completed(cmd, stdout=f"{'a' * 40}\t{cmd[-1]}\n")


def test_unpublished_branch_rebases_before_first_push(tmp_path: Path) -> None:
    """A branch without a remote ref may be rebased before its first publication."""
    module = _load()
    commands: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        commands.append(cmd)
        if cmd[:4] == ["git", "ls-remote", "--exit-code", "--heads"]:
            return _completed(cmd, returncode=2)
        return _completed(cmd)

    module.run_cmd = fake_run  # type: ignore[attr-defined]
    module._prepare_branch_for_push(  # type: ignore[attr-defined]
        tmp_path,
        branch="fix/unpublished",
        base="main",
    )
    module._push_branch(tmp_path)  # type: ignore[attr-defined]

    assert commands == [
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "refs/heads/fix/unpublished"],
        ["git", "fetch", "origin"],
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "refs/heads/fix/unpublished"],
        ["git", "rebase", "origin/main"],
        ["git", "push", "-u", "origin", "HEAD"],
    ]


def test_published_branch_allows_only_normal_fast_forward_push(tmp_path: Path) -> None:
    """A published branch already containing its remote and base may push normally."""
    module = _load()
    commands: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        commands.append(cmd)
        if cmd[:4] == ["git", "ls-remote", "--exit-code", "--heads"]:
            return _published_ref(cmd)
        return _completed(cmd)

    module.run_cmd = fake_run  # type: ignore[attr-defined]
    module._prepare_branch_for_push(  # type: ignore[attr-defined]
        tmp_path,
        branch="fix/published",
        base="main",
    )
    module._push_branch(tmp_path)  # type: ignore[attr-defined]

    assert commands == [
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "refs/heads/fix/published"],
        ["git", "fetch", "origin"],
        ["git", "merge-base", "--is-ancestor", "origin/fix/published", "HEAD"],
        ["git", "merge-base", "--is-ancestor", "origin/main", "HEAD"],
        ["git", "push", "-u", "origin", "HEAD"],
    ]
    assert not any(command[:2] == ["git", "rebase"] for command in commands)


def test_published_branch_divergence_refuses_without_rebase_or_push(tmp_path: Path) -> None:
    """Divergence from a published feature ref requires explicit recovery."""
    module = _load()
    commands: list[list[str]] = []

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        commands.append(cmd)
        if cmd[:4] == ["git", "ls-remote", "--exit-code", "--heads"]:
            return _published_ref(cmd)
        if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
            return _completed(cmd, returncode=1)
        return _completed(cmd)

    module.run_cmd = fake_run  # type: ignore[attr-defined]

    try:
        module._prepare_branch_for_push(  # type: ignore[attr-defined]
            tmp_path,
            branch="fix/diverged",
            base="main",
        )
    except SystemExit as exc:
        assert "not an ancestor of local HEAD" in str(exc)
        assert "--force-with-lease" in str(exc)
    else:
        raise AssertionError("published divergence should be refused")

    assert not any(command[:2] in (["git", "rebase"], ["git", "push"]) for command in commands)


def test_published_branch_base_advance_refuses_without_branch_mutation(tmp_path: Path) -> None:
    """A newer base must not trigger an automatic rewrite of published history."""
    module = _load()
    commands: list[list[str]] = []
    ancestry_checks = 0

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal ancestry_checks
        del cwd, env, check
        commands.append(cmd)
        if cmd[:4] == ["git", "ls-remote", "--exit-code", "--heads"]:
            return _published_ref(cmd)
        if cmd[:3] == ["git", "merge-base", "--is-ancestor"]:
            ancestry_checks += 1
            return _completed(cmd, returncode=0 if ancestry_checks == 1 else 1)
        return _completed(cmd)

    module.run_cmd = fake_run  # type: ignore[attr-defined]

    try:
        module._prepare_branch_for_push(  # type: ignore[attr-defined]
            tmp_path,
            branch="fix/base-advanced",
            base="main",
        )
    except SystemExit as exc:
        assert "origin/main advanced" in str(exc)
        assert "git rebase origin/main" in str(exc)
        assert "--force-with-lease" in str(exc)
    else:
        raise AssertionError("published branch behind base should be refused")

    assert not any(command[:2] in (["git", "rebase"], ["git", "push"]) for command in commands)


def test_unpublished_branch_refuses_if_published_between_lookup_and_fetch(tmp_path: Path) -> None:
    """A concurrent first publication must stop before local history is rewritten."""
    module = _load()
    commands: list[list[str]] = []
    remote_lookups = 0

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        nonlocal remote_lookups
        del cwd, env, check
        commands.append(cmd)
        if cmd[:4] == ["git", "ls-remote", "--exit-code", "--heads"]:
            remote_lookups += 1
            return _completed(cmd, returncode=2) if remote_lookups == 1 else _published_ref(cmd)
        return _completed(cmd)

    module.run_cmd = fake_run  # type: ignore[attr-defined]

    with pytest.raises(SystemExit, match="was published while pr-auto was preparing it") as exc_info:
        module._prepare_branch_for_push(  # type: ignore[attr-defined]
            tmp_path,
            branch="fix/publication-race",
            base="main",
        )

    assert "No rebase or push was attempted" in str(exc_info.value)
    assert commands == [
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "refs/heads/fix/publication-race"],
        ["git", "fetch", "origin"],
        ["git", "ls-remote", "--exit-code", "--heads", "origin", "refs/heads/fix/publication-race"],
    ]


@pytest.mark.parametrize(
    "stdout",
    [
        "",
        f"{'a' * 40}\trefs/heads/fix/exact\n{'b' * 40}\trefs/heads/fix/exact\n",
        "not-a-full-object-id\trefs/heads/fix/exact\n",
        f"{'a' * 40}\trefs/heads/fix/other\n",
    ],
    ids=["empty", "multiple", "malformed-sha", "mismatched-ref"],
)
def test_remote_branch_exists_rejects_non_exact_evidence(tmp_path: Path, stdout: str) -> None:
    """Successful lookup status is insufficient without one exact ref record."""
    module = _load()

    def fake_run(
        cmd: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        del cwd, env, check
        return _completed(cmd, stdout=stdout)

    module.run_cmd = fake_run  # type: ignore[attr-defined]

    with pytest.raises(SystemExit, match="remote branch lookup"):
        module._remote_branch_exists(tmp_path, "fix/exact")  # type: ignore[attr-defined]
