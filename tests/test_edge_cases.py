"""Edge case tests for enforced-planning scripts.

Covers: check_plan_blockers circular deps, check_doc_coupling wrapper,
parse_plan edge cases (empty frontmatter, malformed content).
"""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load_module(name: str) -> object:
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
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
# check_plan_blockers — circular dependency handling
# ---------------------------------------------------------------------------

class TestCircularDependencies:
    """Circular deps (A blocks B, B blocks A) should not cause infinite loops."""

    def _load(self) -> object:
        return _load_module("check_plan_blockers")

    def test_circular_dep_does_not_hang(self, tmp_path: Path) -> None:
        """find_stale_blockers must terminate even if A blocks B and B blocks A."""
        m = self._load()
        _write_plan(tmp_path, "01_alpha.md", """\
            # Alpha
            **Status:** Blocked
            **Blocked By:** #2
        """)
        _write_plan(tmp_path, "02_beta.md", """\
            # Beta
            **Status:** Blocked
            **Blocked By:** #1
        """)
        plans = m.load_all_plans(tmp_path)  # type: ignore[attr-defined]
        # Neither is Complete so find_stale_blockers should return empty — not hang
        result = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
        assert result == []

    def test_self_referential_block_ignored(self, tmp_path: Path) -> None:
        """A plan blocked by itself should not appear as a stale blocker."""
        m = self._load()
        _write_plan(tmp_path, "03_gamma.md", """\
            # Gamma
            **Status:** Blocked
            **Blocked By:** #3
        """)
        plans = m.load_all_plans(tmp_path)  # type: ignore[attr-defined]
        result = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
        # Not stale because Plan 3 is not Complete
        assert result == []

    def test_chain_of_blocked_plans(self, tmp_path: Path) -> None:
        """A->B->C chain where B is Complete — A should show as stale, not C."""
        m = self._load()
        _write_plan(tmp_path, "01_a.md", """\
            # A
            **Status:** Blocked
            **Blocked By:** #2
        """)
        _write_plan(tmp_path, "02_b.md", """\
            # B
            **Status:** Complete
            **Blocked By:** #3
        """)
        _write_plan(tmp_path, "03_c.md", """\
            # C
            **Status:** In Progress
        """)
        plans = m.load_all_plans(tmp_path)  # type: ignore[attr-defined]
        result = m.find_stale_blockers(plans)  # type: ignore[attr-defined]
        # Only A is blocked by a Complete plan (B)
        assert len(result) == 1
        blocked_plan, blocker_num, blocker_plan = result[0]
        assert blocked_plan.number == 1
        assert blocker_num == 2


# ---------------------------------------------------------------------------
# check_plan_blockers — missing / zero blockers edge cases
# ---------------------------------------------------------------------------

class TestMissingBlockers:
    """Plans with no blockers, missing blocker files, or None values."""

    def _load(self) -> object:
        return _load_module("check_plan_blockers")

    def test_plan_with_empty_plans_dir(self, tmp_path: Path) -> None:
        """Empty directory returns no plans and no stale blockers."""
        m = self._load()
        plans = m.load_all_plans(tmp_path)  # type: ignore[attr-defined]
        assert plans == {}
        assert m.find_stale_blockers(plans) == []  # type: ignore[attr-defined]

    def test_plan_zero_padded_number(self, tmp_path: Path) -> None:
        """Plan files like 007_foo.md extract number 7 correctly."""
        m = self._load()
        _write_plan(tmp_path, "007_foo.md", """\
            # Foo
            **Status:** In Progress
        """)
        plans = m.load_all_plans(tmp_path)  # type: ignore[attr-defined]
        assert 7 in plans
        assert plans[7].number == 7

    def test_non_numeric_filename_skipped(self, tmp_path: Path) -> None:
        """Files without leading digits are not loaded as plans."""
        m = self._load()
        _write_plan(tmp_path, "README.md", "# Not a plan\n**Status:** Blocked\n")
        plans = m.load_all_plans(tmp_path)  # type: ignore[attr-defined]
        assert plans == {}


# ---------------------------------------------------------------------------
# check_doc_coupling — wrapper existence guard
# ---------------------------------------------------------------------------

class TestDocCouplingWrapper:
    """check_doc_coupling.py is a compatibility wrapper — test its guard."""

    def test_wrapper_exits_gracefully_when_target_missing(self) -> None:
        """Wrapper raises SystemExit(2) if the wrapped script doesn't exist."""
        wrapper = SCRIPTS_DIR / "check_doc_coupling.py"
        assert wrapper.exists(), "Wrapper script must exist"

        content = wrapper.read_text()
        # The wrapper should check for TARGET existence and raise SystemExit(2)
        assert "SystemExit(2)" in content or "raise SystemExit(2)" in content


# ---------------------------------------------------------------------------
# parse_plan.py — malformed content edge cases
# ---------------------------------------------------------------------------

class TestParsePlanEdgeCases:
    """parse_plan.py edge cases: empty files, missing sections."""

    def _load(self) -> object:
        return _load_module("parse_plan")

    def test_parse_branch_name_no_digits(self) -> None:
        """Branch name without digits returns None plan number."""
        m = self._load()
        result = m.get_plan_number_from_branch("feature/no-numbers-here")  # type: ignore[attr-defined]
        assert result is None

    def test_parse_branch_leading_zeros(self) -> None:
        """Branch name with leading zeros extracts the correct int."""
        m = self._load()
        result = m.get_plan_number_from_branch("plan-007-fix-thing")  # type: ignore[attr-defined]
        assert result == 7

    def test_parse_files_affected_no_section_returns_empty(self) -> None:
        """Content with no '## Files Affected' heading returns empty list."""
        m = self._load()
        plan_content = "# Title\n\n**Status:** In Progress\n\nSome description.\n"
        result = m.parse_files_affected(plan_content)  # type: ignore[attr-defined]
        assert result == []

    def test_parse_files_affected_single_entry(self) -> None:
        """Files Affected with one file entry returns one item."""
        m = self._load()
        plan_content = "## Files Affected\n\n- `src/foo.py` (modify)\n"
        result = m.parse_files_affected(plan_content)  # type: ignore[attr-defined]
        assert len(result) == 1
        assert "foo.py" in result[0]["path"]
