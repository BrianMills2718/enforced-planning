"""Tests for scripts/pr_auto.py."""

from __future__ import annotations

import importlib.util
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
