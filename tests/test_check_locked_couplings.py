"""Tests for check_locked_couplings.py — pre-commit locked coupling validator."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_locked_couplings import (
    _find_relationships_yaml,
    _load_relationships,
    _matches_pattern,
    check_locked_couplings,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

V2_YAML = """\
version: 2
coupling_types:
  locked:
    action: block
    description: Commit blocked until coupled doc also updated
    actor: programmatic
couplings:
- sources:
  - src/core.py
  - src/routing.py
  docs:
  - docs/adr/0001-core.md
  - docs/adr/0002-routing.md
  type: locked
  description: Core call path coupling
- sources:
  - src/observability.py
  docs:
  - docs/adr/0007-observability.md
  type: locked
  description: Observability coupling
- sources:
  - src/generated_thing.py
  docs:
  - docs/generated_doc.md
  type: generated
  description: Generated coupling (not locked)
"""

V1_YAML = """\
required_reading:
  defaults:
  - CLAUDE.md
couplings:
- sources:
  - src/core.py
  docs:
  - docs/adr/0001-core.md
  required_reading: true
"""


def make_repo(tmp_path: Path, yaml_content: str, rel_path: str = "scripts/relationships.yaml") -> Path:
    """Create a minimal repo with a relationships.yaml."""
    rel_file = tmp_path / rel_path
    rel_file.parent.mkdir(parents=True, exist_ok=True)
    rel_file.write_text(yaml_content)
    return tmp_path


def staged(files: list[str], _repo_root: Path = Path(".")):
    """Context manager: patch _staged_files to return given files."""
    return patch("check_locked_couplings._staged_files", return_value=files)


# ---------------------------------------------------------------------------
# _find_relationships_yaml
# ---------------------------------------------------------------------------

class TestFindRelationshipsYaml:
    def test_finds_scripts_path(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "relationships.yaml").write_text("")
        assert _find_relationships_yaml(tmp_path) is not None

    def test_finds_root_path(self, tmp_path):
        (tmp_path / "relationships.yaml").write_text("")
        assert _find_relationships_yaml(tmp_path) is not None

    def test_returns_none_if_missing(self, tmp_path):
        assert _find_relationships_yaml(tmp_path) is None

    def test_prefers_scripts_over_root(self, tmp_path):
        (tmp_path / "scripts").mkdir()
        (tmp_path / "scripts" / "relationships.yaml").write_text("a: 1")
        (tmp_path / "relationships.yaml").write_text("b: 2")
        p = _find_relationships_yaml(tmp_path)
        assert "scripts" in str(p)


# ---------------------------------------------------------------------------
# _load_relationships
# ---------------------------------------------------------------------------

class TestLoadRelationships:
    def test_loads_v2(self, tmp_path):
        f = tmp_path / "r.yaml"
        f.write_text(V2_YAML)
        data = _load_relationships(f)
        assert data is not None
        assert data["version"] == 2

    def test_v1_returns_none(self, tmp_path):
        f = tmp_path / "r.yaml"
        f.write_text(V1_YAML)
        assert _load_relationships(f) is None

    def test_malformed_yaml_returns_none(self, tmp_path):
        f = tmp_path / "r.yaml"
        f.write_text("}: not valid yaml :{")
        assert _load_relationships(f) is None

    def test_missing_file_returns_none(self, tmp_path):
        f = tmp_path / "nonexistent.yaml"
        assert _load_relationships(f) is None


# ---------------------------------------------------------------------------
# _matches_pattern
# ---------------------------------------------------------------------------

class TestMatchesPattern:
    def test_exact_match(self):
        assert _matches_pattern("src/core.py", ["src/core.py"])

    def test_glob_match(self):
        assert _matches_pattern("src/observability/logger.py", ["src/observability/*.py"])

    def test_no_match(self):
        assert not _matches_pattern("src/other.py", ["src/core.py", "src/routing.py"])

    def test_multiple_patterns(self):
        assert _matches_pattern("src/routing.py", ["src/core.py", "src/routing.py"])

    def test_star_star_not_needed_for_single_dir(self):
        assert _matches_pattern("src/core.py", ["src/*.py"])


# ---------------------------------------------------------------------------
# check_locked_couplings
# ---------------------------------------------------------------------------

class TestCheckLockedCouplings:
    def test_no_relationships_yaml(self, tmp_path):
        """No relationships.yaml → no violations."""
        with staged(["src/core.py"], tmp_path):
            assert check_locked_couplings(tmp_path) == []

    def test_v1_yaml_skipped(self, tmp_path):
        """V1 relationships.yaml → no violations."""
        make_repo(tmp_path, V1_YAML)
        with staged(["src/core.py"], tmp_path):
            assert check_locked_couplings(tmp_path) == []

    def test_no_staged_files(self, tmp_path):
        """No staged files → no violations."""
        make_repo(tmp_path, V2_YAML)
        with staged([], tmp_path):
            assert check_locked_couplings(tmp_path) == []

    def test_staged_source_with_doc_staged(self, tmp_path):
        """Staged source + coupled doc staged → no violation."""
        make_repo(tmp_path, V2_YAML)
        with staged(["src/core.py", "docs/adr/0001-core.md"], tmp_path):
            violations = check_locked_couplings(tmp_path)
            assert violations == []

    def test_staged_source_without_doc(self, tmp_path):
        """Staged source without any coupled doc → violation."""
        make_repo(tmp_path, V2_YAML)
        with staged(["src/core.py"], tmp_path):
            violations = check_locked_couplings(tmp_path)
            assert len(violations) == 1
            assert violations[0]["coupling_description"] == "Core call path coupling"

    def test_violation_includes_matched_sources(self, tmp_path):
        make_repo(tmp_path, V2_YAML)
        with staged(["src/core.py"], tmp_path):
            v = check_locked_couplings(tmp_path)[0]
            assert "src/core.py" in v["sources_matched"]

    def test_violation_includes_docs_required(self, tmp_path):
        make_repo(tmp_path, V2_YAML)
        with staged(["src/core.py"], tmp_path):
            v = check_locked_couplings(tmp_path)[0]
            assert "docs/adr/0001-core.md" in v["docs_required"]

    def test_multiple_violations(self, tmp_path):
        """Both locked couplings violated when both sources staged without docs."""
        make_repo(tmp_path, V2_YAML)
        with staged(["src/core.py", "src/observability.py"], tmp_path):
            violations = check_locked_couplings(tmp_path)
            assert len(violations) == 2

    def test_non_locked_coupling_not_checked(self, tmp_path):
        """Generated coupling (type: generated) is not enforced."""
        make_repo(tmp_path, V2_YAML)
        with staged(["src/generated_thing.py"], tmp_path):
            violations = check_locked_couplings(tmp_path)
            assert violations == []

    def test_glob_sources_matched(self, tmp_path):
        yaml_content = """\
version: 2
coupling_types:
  locked:
    action: block
    description: test
    actor: programmatic
couplings:
- sources:
  - src/observability/*.py
  docs:
  - docs/adr/0007-observability.md
  type: locked
  description: Observability glob coupling
"""
        make_repo(tmp_path, yaml_content)
        with staged(["src/observability/logger.py"], tmp_path):
            violations = check_locked_couplings(tmp_path)
            assert len(violations) == 1

    def test_relationships_yaml_at_root(self, tmp_path):
        """Also finds relationships.yaml at repo root (not just scripts/)."""
        (tmp_path / "relationships.yaml").write_text(V2_YAML)
        with staged(["src/core.py"], tmp_path):
            violations = check_locked_couplings(tmp_path)
            assert len(violations) == 1
