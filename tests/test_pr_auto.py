"""Tests for scripts/pr_auto.py."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


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
