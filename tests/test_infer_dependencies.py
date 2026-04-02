"""Tests for infer_dependencies.py — dependency inference engine."""

from pathlib import Path

import pytest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from infer_dependencies import scan_file, scan_repo, _is_suppressed, _resolve_path


class TestSuppression:
    """Test inline suppression markers."""

    def test_html_comment_suppression(self):
        assert _is_suppressed("<!-- governance: no-dep -->")

    def test_python_comment_suppression(self):
        assert _is_suppressed("# governance: no-dep")

    def test_no_suppression(self):
        assert not _is_suppressed("regular line of code")

    def test_suppression_with_surrounding_text(self):
        assert _is_suppressed("some text <!-- governance: no-dep --> more text")


class TestResolvePath:
    """Test path resolution for file references."""

    def test_relative_path(self, tmp_path):
        (tmp_path / "target.md").write_text("target")
        source = tmp_path / "source.md"
        result = _resolve_path(source, "target.md", tmp_path)
        assert result == tmp_path / "target.md"

    def test_parent_relative(self, tmp_path):
        subdir = tmp_path / "sub"
        subdir.mkdir()
        (tmp_path / "target.md").write_text("target")
        source = subdir / "source.md"
        result = _resolve_path(source, "../target.md", tmp_path)
        assert result == tmp_path / "target.md"

    def test_nonexistent_path(self, tmp_path):
        source = tmp_path / "source.md"
        result = _resolve_path(source, "nonexistent.md", tmp_path)
        assert result is None

    def test_url_ignored(self, tmp_path):
        source = tmp_path / "source.md"
        assert _resolve_path(source, "https://example.com", tmp_path) is None

    def test_anchor_ignored(self, tmp_path):
        source = tmp_path / "source.md"
        assert _resolve_path(source, "#section", tmp_path) is None


class TestScanFile:
    """Test single-file scanning."""

    def test_markdown_links(self, tmp_path):
        (tmp_path / "target.md").write_text("target doc")
        source = tmp_path / "source.md"
        source.write_text("[link](target.md)\n")
        edges = scan_file(source, tmp_path)
        assert len(edges) == 1
        assert edges[0]["type"] == "markdown_link"
        assert edges[0]["target"] == "target.md"

    def test_python_import(self, tmp_path):
        source = tmp_path / "test.py"
        source.write_text("from llm_client import call_llm\n")
        edges = scan_file(source, tmp_path)
        imports = [e for e in edges if e["type"] == "python_import"]
        assert len(imports) == 1
        assert imports[0]["target"] == "[cross-project:llm_client]"

    def test_plan_reference_in_markdown(self, tmp_path):
        source = tmp_path / "doc.md"
        source.write_text("See Plan #42 for details\n")
        edges = scan_file(source, tmp_path)
        plan_refs = [e for e in edges if e["type"] == "plan_reference"]
        assert len(plan_refs) == 1
        assert plan_refs[0]["target"] == "[plan:#42]"

    def test_adr_reference(self, tmp_path):
        source = tmp_path / "doc.md"
        source.write_text("Per ADR-5, we use Pydantic\n")
        edges = scan_file(source, tmp_path)
        adr_refs = [e for e in edges if e["type"] == "adr_reference"]
        assert len(adr_refs) == 1
        assert adr_refs[0]["target"] == "[adr:5]"

    def test_suppressed_link_ignored(self, tmp_path):
        (tmp_path / "target.md").write_text("target")
        source = tmp_path / "source.md"
        source.write_text("[link](target.md) <!-- governance: no-dep -->\n")
        edges = scan_file(source, tmp_path)
        assert len(edges) == 0

    def test_external_url_ignored(self, tmp_path):
        source = tmp_path / "doc.md"
        source.write_text("[ext](https://example.com)\n")
        edges = scan_file(source, tmp_path)
        md_links = [e for e in edges if e["type"] == "markdown_link"]
        assert len(md_links) == 0


class TestScanRepo:
    """Test full repo scanning."""

    def test_scan_small_repo(self, tmp_path):
        (tmp_path / "README.md").write_text("[link](docs/plan.md)\n")
        docs = tmp_path / "docs"
        docs.mkdir()
        (docs / "plan.md").write_text("Plan content referencing ADR-1\n")
        (tmp_path / "main.py").write_text("from llm_client import call_llm\n")

        edges = scan_repo(tmp_path)
        types = {e["type"] for e in edges}
        assert "markdown_link" in types
        assert "python_import" in types
        assert "adr_reference" in types

    def test_skip_git_dir(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "config").write_text("from llm_client import x\n")
        (tmp_path / "main.py").write_text("clean code\n")

        edges = scan_repo(tmp_path)
        # Should NOT have any edges from .git/
        git_edges = [e for e in edges if ".git" in e["source"]]
        assert len(git_edges) == 0

    def test_deduplication(self, tmp_path):
        source = tmp_path / "doc.md"
        # Same link twice on different lines
        source.write_text("[a](target.md)\n[b](target.md)\n")
        (tmp_path / "target.md").write_text("target")
        edges = scan_repo(tmp_path)
        md_links = [e for e in edges if e["type"] == "markdown_link"]
        assert len(md_links) == 1  # Deduplicated
