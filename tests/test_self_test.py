"""Regression tests for the framework self-test entrypoint."""

from pathlib import Path

from scripts.self_test import check_markdown_links


def test_markdown_links_ignore_managed_worktrees(tmp_path: Path) -> None:
    """Branch-local worktree documents must not affect the canonical checkout."""
    retained_doc = tmp_path / "worktrees" / "plan-x" / "docs" / "retained.md"
    retained_doc.parent.mkdir(parents=True)
    retained_doc.write_text("[Missing](missing.md)\n", encoding="utf-8")

    assert check_markdown_links(tmp_path) == []


def test_markdown_links_still_report_broken_canonical_docs(tmp_path: Path) -> None:
    """The exclusion must not weaken validation of ordinary repository docs."""
    canonical_doc = tmp_path / "docs" / "current.md"
    canonical_doc.parent.mkdir(parents=True)
    canonical_doc.write_text("[Missing](missing.md)\n", encoding="utf-8")

    assert check_markdown_links(tmp_path) == [
        "docs/current.md:1: broken link [Missing](missing.md)"
    ]
