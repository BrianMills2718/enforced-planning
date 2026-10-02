"""Tests for doc-code coupling enforcement."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "check_doc_coupling.py"


def _load_module():
    """Load the doc-coupling checker as an isolated module."""

    spec = importlib.util.spec_from_file_location("check_doc_coupling_module", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_check_couplings_matches_globbed_doc_targets() -> None:
    """Changed source files should satisfy globbed doc targets when they update."""

    module = _load_module()
    changed_files = {
        "scripts/meta/generate_agent_docs.py",
        "generated/agent_docs/README.md",
        "generated/agent_docs/subtrees/docs.md",
    }
    couplings = [
        {
            "sources": ["scripts/meta/generate_agent_docs.py"],
            "docs": ["generated/agent_docs/**/*.md"],
            "description": "Generated docs must stay aligned.",
        }
    ]

    strict_violations, soft_warnings = module.check_couplings(changed_files, couplings)

    assert strict_violations == []
    assert soft_warnings == []


def test_verify_sync_suppresses_violation_when_docs_current() -> None:
    """Couplings with verify_sync should not violate when sync command passes."""

    module = _load_module()
    changed_files = {"CLAUDE.md"}
    couplings = [
        {
            "sources": ["CLAUDE.md"],
            "docs": ["generated/agent_docs/README.md"],
            "description": "Generated docs must stay aligned.",
            "verify_sync": "true",  # always exits 0
        }
    ]

    strict_violations, soft_warnings = module.check_couplings(changed_files, couplings)
    assert strict_violations == []
    assert soft_warnings == []


def test_verify_sync_does_not_suppress_when_sync_fails() -> None:
    """Couplings with verify_sync should still violate when sync command fails."""

    module = _load_module()
    changed_files = {"CLAUDE.md"}
    couplings = [
        {
            "sources": ["CLAUDE.md"],
            "docs": ["generated/agent_docs/README.md"],
            "description": "Generated docs must stay aligned.",
            "verify_sync": "false",  # always exits 1
        }
    ]

    strict_violations, soft_warnings = module.check_couplings(changed_files, couplings)
    assert len(strict_violations) == 1
    assert strict_violations[0]["description"] == "Generated docs must stay aligned."


def test_validate_config_accepts_matching_doc_glob(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Globbed doc targets should validate against real matching files."""

    module = _load_module()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "scripts" / "meta").mkdir(parents=True, exist_ok=True)
    (repo_root / "scripts" / "meta" / "generate_agent_docs.py").write_text(
        "# generator\n", encoding="utf-8"
    )
    (repo_root / "generated" / "agent_docs" / "subtrees").mkdir(parents=True, exist_ok=True)
    (repo_root / "generated" / "agent_docs" / "README.md").write_text("# Index\n", encoding="utf-8")
    (repo_root / "generated" / "agent_docs" / "subtrees" / "docs.md").write_text("# Docs\n", encoding="utf-8")
    monkeypatch.chdir(repo_root)

    warnings = module.validate_config(
        [
            {
                "sources": ["scripts/meta/generate_agent_docs.py"],
                "docs": ["generated/agent_docs/**/*.md"],
            }
        ]
    )

    assert warnings == []


def test_validate_config_reports_missing_source_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A nonexistent source cannot silently remain a coupling authority."""

    module = _load_module()
    monkeypatch.chdir(tmp_path)
    (tmp_path / "CLAUDE.md").write_text("# Rules\n", encoding="utf-8")

    warnings = module.validate_config(
        [{"sources": ["docs/missing-policy.md"], "docs": ["CLAUDE.md"]}]
    )

    assert warnings == ["Coupled source doesn't exist: docs/missing-policy.md"]


# --- default .doc-coupling-acks discovery (project-meta#2314) ---------------

import subprocess
import sys

import yaml

_SCRIPT = REPO_ROOT / "scripts" / "meta" / "check_doc_coupling.py"


def _make_repo(tmp_path: Path, acks=None) -> Path:
    repo = tmp_path / "repo"
    (repo / "scripts").mkdir(parents=True)
    (repo / "src.py").write_text("x = 1\n")
    (repo / "A.md").write_text("a\n")
    (repo / "B.md").write_text("b\n")
    (repo / "scripts" / "relationships.yaml").write_text(
        yaml.safe_dump(
            {
                "couplings": [
                    {
                        "sources": ["src.py"],
                        "docs": ["A.md", "B.md"],
                        "description": "src needs docs",
                        "strict": True,
                    }
                ]
            }
        )
    )
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@example.com"],
        ["git", "config", "user.name", "t"],
        ["git", "add", "-A"],
        ["git", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(cmd, cwd=repo, check=True)
    (repo / "src.py").write_text("x = 2\n")
    subprocess.run(["git", "add", "src.py"], cwd=repo, check=True)
    if acks is not None:
        (repo / ".doc-coupling-acks").write_text(yaml.safe_dump(acks))
    return repo


def _run(repo: Path, *extra: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_SCRIPT), "--staged", "--strict", *extra],
        cwd=cwd or repo,
        capture_output=True,
        text=True,
    )


def test_no_ack_file_violation_still_fails(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path)
    result = _run(repo)
    assert result.returncode == 1, result.stdout + result.stderr


def test_default_ack_file_covering_all_docs_passes_without_flag(tmp_path: Path) -> None:
    acks = [{"path": "A.md", "reason": "ok"}, {"path": "B.md", "reason": "ok"}]
    repo = _make_repo(tmp_path, acks)
    result = _run(repo)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ACKNOWLEDGED GAPS" in result.stdout


def test_default_ack_file_found_from_subdirectory_via_git_root(tmp_path: Path) -> None:
    acks = [{"path": "A.md", "reason": "ok"}, {"path": "B.md", "reason": "ok"}]
    repo = _make_repo(tmp_path, acks)
    # config path is cwd-relative, so pass it explicitly from a subdirectory.
    result = _run(
        repo, "--config", str(repo / "scripts" / "relationships.yaml"), cwd=repo / "scripts"
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_default_ack_empty_reason_still_fails(tmp_path: Path) -> None:
    acks = [{"path": "A.md", "reason": "ok"}, {"path": "B.md", "reason": "  "}]
    repo = _make_repo(tmp_path, acks)
    assert _run(repo).returncode == 1


def test_default_ack_covering_only_some_docs_still_fails(tmp_path: Path) -> None:
    repo = _make_repo(tmp_path, [{"path": "A.md", "reason": "ok"}])
    assert _run(repo).returncode == 1


def test_explicit_ack_file_overrides_default(tmp_path: Path) -> None:
    good = [{"path": "A.md", "reason": "ok"}, {"path": "B.md", "reason": "ok"}]
    repo = _make_repo(tmp_path, good)
    other = tmp_path / "other-acks"
    other.write_text(yaml.safe_dump([{"path": "A.md", "reason": "only one"}]))
    assert _run(repo, "--ack-file", str(other)).returncode == 1
    # and the reverse: explicit full ack passes even when default is partial
    repo2 = _make_repo(tmp_path / "second", [{"path": "A.md", "reason": "ok"}])
    full = tmp_path / "full-acks"
    full.write_text(yaml.safe_dump(good))
    assert _run(repo2, "--ack-file", str(full)).returncode == 0
