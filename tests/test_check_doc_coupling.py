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
