"""Tests for check_plan_blockers.py — stale blocker detection.

Covers parse_plan_file, find_stale_blockers, and suggest_new_status.
All tests use temporary plan files so they are independent of the real
docs/plans directory.
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "check_plan_blockers_module", SCRIPTS_DIR / "check_plan_blockers.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_plan(tmp_path: Path, filename: str, content: str) -> Path:
    """Write a plan file and return its path."""
    path = tmp_path / filename
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# parse_plan_file
# ---------------------------------------------------------------------------


def test_parse_plan_file_extracts_number_from_filename(tmp_path: Path) -> None:
    """Plan number is taken from the NN_ filename prefix."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "07_my-plan.md",
        """
        # My Plan
        **Status:** ✅ Complete
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    assert info.number == 7


def test_parse_plan_file_complete_status(tmp_path: Path) -> None:
    """'Complete' in status text is recognized."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "03_example.md",
        """
        # Example Plan
        **Status:** ✅ Complete
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    assert info.is_complete


def test_parse_plan_file_blocked_status(tmp_path: Path) -> None:
    """'Blocked' in status text is recognized."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "05_blocked.md",
        """
        # Blocked Plan
        **Status:** ⏸️ Blocked
        **Blocked By:** #3
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    assert info.is_blocked
    assert info.blocked_by == [3]


def test_parse_plan_file_multiple_blockers(tmp_path: Path) -> None:
    """Multiple blocker refs in Blocked By are all extracted."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "09_multi.md",
        """
        # Multi Blocked
        **Status:** ⏸️ Blocked
        **Blocked By:** #3, #7
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    assert set(info.blocked_by) == {3, 7}


def test_parse_plan_file_none_blocker_ignored(tmp_path: Path) -> None:
    """'None' as Blocked By value yields empty list."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "04_noblock.md",
        """
        # No Blocker
        **Status:** 📋 Planned
        **Blocked By:** None
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    assert info.blocked_by == []


def test_parse_plan_file_no_number_returns_none(tmp_path: Path) -> None:
    """File without NN_ prefix yields None."""
    m = _load()
    path = _write_plan(tmp_path, "readme.md", "# README\n")
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is None


def test_parse_plan_file_missing_file_returns_none(tmp_path: Path) -> None:
    """Non-existent file yields None."""
    m = _load()
    info = m.parse_plan_file(tmp_path / "99_ghost.md")  # type: ignore[attr-defined]
    assert info is None


# ---------------------------------------------------------------------------
# find_stale_blockers
# ---------------------------------------------------------------------------


def test_find_stale_blockers_detects_blocked_by_complete(tmp_path: Path) -> None:
    """A plan blocked by a Complete plan is stale."""
    m = _load()
    complete_path = _write_plan(
        tmp_path,
        "01_base.md",
        """
        # Base
        **Status:** ✅ Complete
        """,
    )
    blocked_path = _write_plan(
        tmp_path,
        "02_dependent.md",
        """
        # Dependent
        **Status:** ⏸️ Blocked
        **Blocked By:** #1
        """,
    )
    plans = {
        1: m.parse_plan_file(complete_path),  # type: ignore[attr-defined]
        2: m.parse_plan_file(blocked_path),  # type: ignore[attr-defined]
    }
    stale = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
    assert len(stale) == 1
    blocked, blocker_num, blocker = stale[0]
    assert blocked.number == 2
    assert blocker_num == 1
    assert blocker.number == 1


def test_find_stale_blockers_none_when_blocker_still_in_progress(tmp_path: Path) -> None:
    """Blocked-by plan that is In Progress is not stale."""
    m = _load()
    in_progress_path = _write_plan(
        tmp_path,
        "01_wip.md",
        """
        # WIP
        **Status:** 🚧 In Progress
        """,
    )
    blocked_path = _write_plan(
        tmp_path,
        "02_waiting.md",
        """
        # Waiting
        **Status:** ⏸️ Blocked
        **Blocked By:** #1
        """,
    )
    plans = {
        1: m.parse_plan_file(in_progress_path),  # type: ignore[attr-defined]
        2: m.parse_plan_file(blocked_path),  # type: ignore[attr-defined]
    }
    stale = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
    assert stale == []


def test_find_stale_blockers_none_when_not_blocked(tmp_path: Path) -> None:
    """Planned plan not blocked by anything has no stale blockers."""
    m = _load()
    complete_path = _write_plan(
        tmp_path,
        "01_done.md",
        """
        # Done
        **Status:** ✅ Complete
        """,
    )
    planned_path = _write_plan(
        tmp_path,
        "02_planned.md",
        """
        # Planned
        **Status:** 📋 Planned
        """,
    )
    plans = {
        1: m.parse_plan_file(complete_path),  # type: ignore[attr-defined]
        2: m.parse_plan_file(planned_path),  # type: ignore[attr-defined]
    }
    stale = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
    assert stale == []


def test_find_stale_blockers_unknown_blocker_skipped(tmp_path: Path) -> None:
    """If the blocking plan doesn't exist in the dict, it's silently skipped."""
    m = _load()
    blocked_path = _write_plan(
        tmp_path,
        "02_missing_dep.md",
        """
        # Missing Dep
        **Status:** ⏸️ Blocked
        **Blocked By:** #99
        """,
    )
    plans = {2: m.parse_plan_file(blocked_path)}  # type: ignore[attr-defined]
    stale = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
    assert stale == []


# ---------------------------------------------------------------------------
# suggest_new_status
# ---------------------------------------------------------------------------


def test_suggest_new_status_returns_planned_when_steps_present(tmp_path: Path) -> None:
    """Plans with a ## Plan or ## Steps section get 'Planned'."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "03_with_steps.md",
        """
        # With Steps
        **Status:** ⏸️ Blocked
        **Blocked By:** #1

        ## Plan
        1. Do the thing
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    suggestion = m.suggest_new_status(info)  # type: ignore[attr-defined]
    assert suggestion == "Planned"


def test_suggest_new_status_returns_needs_plan_as_default(tmp_path: Path) -> None:
    """Plans without steps get 'Needs Plan'."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "04_empty.md",
        """
        # Empty Plan
        **Status:** ⏸️ Blocked
        **Blocked By:** #1
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None
    suggestion = m.suggest_new_status(info)  # type: ignore[attr-defined]
    assert suggestion == "Needs Plan"


# ---------------------------------------------------------------------------
# update_plan_status
# ---------------------------------------------------------------------------


def test_update_plan_status_leaves_quoted_status_line_in_body_untouched(tmp_path: Path) -> None:
    """Regression: re.sub without count=1 rewrote every Status line in the file.

    Real plan files quote an earlier status line later in the document, e.g.
    inside a Progress-section example or backtick-quoted prose (observed in
    this repo's own docs/plans/102_plan_status_projection.md, and in other
    governed repos' plan files). Only the canonical header-block line -- the
    first occurrence -- may ever be live-updated.
    """
    m = _load()
    path = _write_plan(
        tmp_path,
        "07_example.md",
        """
        # Plan #7: Example

        **Status:** ⏸️ Blocked
        **Blocked By:** #3

        ## Progress

        Phase 1 shipped when the plan read `**Status:** ⏸️ Blocked` before
        Plan #3 landed.
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None

    m.update_plan_status(info, "Complete")  # type: ignore[attr-defined]

    updated = path.read_text()
    status_lines = [line for line in updated.splitlines() if line.startswith("**Status:**")]
    assert status_lines == ["**Status:** ✅ Complete"]
    assert "the plan read `**Status:** ⏸️ Blocked` before" in updated
    assert "**Blocked By:** None" in updated


def test_update_plan_status_leaves_quoted_blocked_by_line_untouched(tmp_path: Path) -> None:
    """Same regression for the Blocked By rewrite."""
    m = _load()
    path = _write_plan(
        tmp_path,
        "08_example.md",
        """
        # Plan #8: Example

        **Status:** ⏸️ Blocked
        **Blocked By:** #3

        ## Progress

        The stale-blocker check exists because a line like
        `**Blocked By:** #3` can go unnoticed once #3 completes.
        """,
    )
    info = m.parse_plan_file(path)  # type: ignore[attr-defined]
    assert info is not None

    m.update_plan_status(info, "Complete")  # type: ignore[attr-defined]

    updated = path.read_text()
    blocked_by_lines = [line for line in updated.splitlines() if line.startswith("**Blocked By:**")]
    assert blocked_by_lines == ["**Blocked By:** None"]
    assert "a line like\n`**Blocked By:** #3` can go unnoticed" in updated
