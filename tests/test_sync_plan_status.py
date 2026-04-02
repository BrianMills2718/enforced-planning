"""Tests for sync_plan_status.py — plan status sync utilities.

Covers parse_plan_status (file → structured dict) and parse_index_table
(CLAUDE.md table → structured dict).  Both are pure file readers with no
git or network dependencies.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "sync_plan_status_module", SCRIPTS_DIR / "sync_plan_status.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_plan(tmp_path: Path, filename: str, content: str) -> Path:
    path = tmp_path / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_plan_status
# ---------------------------------------------------------------------------


def test_parse_plan_status_complete(tmp_path: Path) -> None:
    """Complete status is parsed correctly."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "07_example.md",
        """
        # Example Plan
        **Status:** ✅ Complete
        **Priority:** High

        ## Problem
        Something needs fixing.

        ## Plan
        1. Fix it.

        ## Verification
        Run tests.
        """,
    )
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is not None
    assert result["number"] == 7
    assert "✅" in result["status_emoji"]
    assert result["has_plan_section"] is True
    assert result["has_problem_section"] is True
    assert result["has_verification_section"] is True


def test_parse_plan_status_planned(tmp_path: Path) -> None:
    """Planned status is parsed correctly."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "12_planned.md",
        """
        # Planned Work
        **Status:** 📋 Planned

        ## Problem
        We need this.
        """,
    )
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is not None
    assert result["number"] == 12
    assert "📋" in result["status_emoji"]
    assert result["has_plan_section"] is False


def test_parse_plan_status_in_progress(tmp_path: Path) -> None:
    """In Progress emoji is recognized."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "03_wip.md",
        """
        # WIP
        **Status:** 🚧 In Progress
        """,
    )
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is not None
    assert "🚧" in result["status_emoji"]


def test_parse_plan_status_blocked(tmp_path: Path) -> None:
    """Blocked emoji is recognized."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "05_blocked.md",
        """
        # Blocked
        **Status:** ⏸️ Blocked
        """,
    )
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is not None
    assert "⏸️" in result["status_emoji"]


def test_parse_plan_status_no_number_returns_none(tmp_path: Path) -> None:
    """File without NN_ prefix returns None."""
    m = _load()
    path = tmp_path / "README.md"
    path.write_text("# README\n", encoding="utf-8")
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is None


def test_parse_plan_status_missing_status_line_returns_none(tmp_path: Path) -> None:
    """Plan file without **Status:** line returns None."""
    m = _load()
    path = _write_plan(tmp_path, "08_no_status.md", "# No Status\nSome content.\n")
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is None


def test_parse_plan_status_extracts_title(tmp_path: Path) -> None:
    """Title is extracted from the first heading."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "15_titled.md",
        """
        # My Special Plan Title
        **Status:** ✅ Complete
        """,
    )
    result = m.parse_plan_status(path)  # type: ignore[attr-defined]
    assert result is not None
    assert "My Special Plan Title" in result["title"]


def test_parse_plan_status_nonexistent_returns_none(tmp_path: Path) -> None:
    """Non-existent file returns None."""
    m = _load()
    result = m.parse_plan_status(tmp_path / "99_ghost.md")  # type: ignore[attr-defined]
    assert result is None


# ---------------------------------------------------------------------------
# parse_index_table
# ---------------------------------------------------------------------------

_INDEX_CONTENT = textwrap.dedent("""\
    # Plans Index

    ## Gap Summary

    | # | Name | Priority | Status | Blocks |
    |---|------|----------|--------|--------|
    | 1 | [Plan One](01_plan_one.md) | High | ✅ Complete | - |
    | 2 | [Plan Two](02_plan_two.md) | Medium | 📋 Planned | - |
    | 3 | [Plan Three](03_plan_three.md) | High | 🚧 In Progress | - |

""")


def test_parse_index_table_basic(tmp_path: Path) -> None:
    """Three rows in the index table are all parsed."""
    m = _load()
    index_path = tmp_path / "CLAUDE.md"
    index_path.write_text(_INDEX_CONTENT, encoding="utf-8")
    result = m.parse_index_table(index_path)  # type: ignore[attr-defined]
    assert len(result) == 3
    assert 1 in result
    assert 2 in result
    assert 3 in result


def test_parse_index_table_status_emojis(tmp_path: Path) -> None:
    """Status emojis are parsed from each row."""
    m = _load()
    index_path = tmp_path / "CLAUDE.md"
    index_path.write_text(_INDEX_CONTENT, encoding="utf-8")
    result = m.parse_index_table(index_path)  # type: ignore[attr-defined]
    assert "✅" in result[1]["status_emoji"]
    assert "📋" in result[2]["status_emoji"]
    assert "🚧" in result[3]["status_emoji"]


def test_parse_index_table_nonexistent_returns_empty(tmp_path: Path) -> None:
    """Non-existent index file returns empty dict."""
    m = _load()
    result = m.parse_index_table(tmp_path / "CLAUDE.md")  # type: ignore[attr-defined]
    assert result == {}


def test_parse_index_table_no_gap_summary_section(tmp_path: Path) -> None:
    """File without Gap Summary section returns empty dict."""
    m = _load()
    index_path = tmp_path / "CLAUDE.md"
    index_path.write_text("# Just a heading\nSome text.\n", encoding="utf-8")
    result = m.parse_index_table(index_path)  # type: ignore[attr-defined]
    assert result == {}


def test_parse_index_table_plan_numbers_are_integers(tmp_path: Path) -> None:
    """Dict keys are int plan numbers, not strings."""
    m = _load()
    index_path = tmp_path / "CLAUDE.md"
    index_path.write_text(_INDEX_CONTENT, encoding="utf-8")
    result = m.parse_index_table(index_path)  # type: ignore[attr-defined]
    for key in result:
        assert isinstance(key, int)
