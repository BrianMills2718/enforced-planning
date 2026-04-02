"""Tests for parse_plan.py — plan file parsing utilities.

Covers the pure-function layer: parse_files_affected, parse_references_reviewed,
check_file_in_scope, and get_plan_number_from_branch.  Git-dependent helpers
(find_plan_file, get_active_plan_number) are not tested here because they
require a real repository context.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "parse_plan_module", SCRIPTS_DIR / "parse_plan.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# get_plan_number_from_branch
# ---------------------------------------------------------------------------


def test_branch_with_plan_prefix_returns_number() -> None:
    """plan-15-feature-name should yield 15."""
    m = _load()
    assert m.get_plan_number_from_branch("plan-15-feature-name") == 15  # type: ignore[attr-defined]


def test_branch_single_digit_plan_returns_number() -> None:
    """plan-7-foo should yield 7."""
    m = _load()
    assert m.get_plan_number_from_branch("plan-7-foo") == 7  # type: ignore[attr-defined]


def test_branch_without_plan_prefix_returns_none() -> None:
    """main and feature branches have no plan number."""
    m = _load()
    assert m.get_plan_number_from_branch("main") is None  # type: ignore[attr-defined]
    assert m.get_plan_number_from_branch("feature-xyz") is None  # type: ignore[attr-defined]
    assert m.get_plan_number_from_branch("") is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# parse_files_affected
# ---------------------------------------------------------------------------


def test_parse_files_affected_basic_entries() -> None:
    """Standard Files Affected section parses all entries."""
    m = _load()
    content = (
        "## Files Affected\n"
        "- src/foo.py (modify)\n"
        "- src/bar.py (create)\n"
        "- tests/test_foo.py (create)\n"
    )
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 3
    assert result[0] == {"path": "src/foo.py", "action": "modify"}
    assert result[1] == {"path": "src/bar.py", "action": "create"}
    assert result[2] == {"path": "tests/test_foo.py", "action": "create"}


def test_parse_files_affected_default_action_is_modify() -> None:
    """Entry without an action defaults to 'modify'."""
    m = _load()
    content = "## Files Affected\n- src/foo.py\n"
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["action"] == "modify"


def test_parse_files_affected_stops_at_next_heading() -> None:
    """Parser must not bleed into the next ## section."""
    m = _load()
    content = (
        "## Files Affected\n"
        "- src/a.py (modify)\n"
        "\n"
        "## Steps\n"
        "- Do something\n"
    )
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "src/a.py"


def test_parse_files_affected_missing_section_returns_empty() -> None:
    """When no Files Affected section exists, return an empty list."""
    m = _load()
    content = "## Steps\n- Do something\n"
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert result == []


def test_parse_files_affected_ignores_comment_lines() -> None:
    """Lines starting with # inside the section are skipped."""
    m = _load()
    content = (
        "## Files Affected\n"
        "# this is a comment\n"
        "- src/real.py (modify)\n"
    )
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "src/real.py"


def test_parse_files_affected_asterisk_bullet() -> None:
    """Both * and - bullets work."""
    m = _load()
    content = "## Files Affected\n* src/star.py (delete)\n"
    result = m.parse_files_affected(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0] == {"path": "src/star.py", "action": "delete"}


# ---------------------------------------------------------------------------
# parse_references_reviewed
# ---------------------------------------------------------------------------


def test_parse_references_reviewed_with_line_range() -> None:
    """Line ranges are captured as start/end dicts."""
    m = _load()
    content = (
        "## References Reviewed\n"
        "- src/executor.py:45-89 - existing action handling\n"
    )
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert result[0]["path"] == "src/executor.py"
    assert result[0]["lines"] == {"start": 45, "end": 89}
    assert result[0]["description"] == "existing action handling"


def test_parse_references_reviewed_without_lines() -> None:
    """References without line numbers have no 'lines' key."""
    m = _load()
    content = "## References Reviewed\n- docs/architecture.md - overview\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert "lines" not in result[0]
    assert result[0]["path"] == "docs/architecture.md"
    assert result[0]["description"] == "overview"


def test_parse_references_reviewed_without_description() -> None:
    """References without a description have no 'description' key."""
    m = _load()
    content = "## References Reviewed\n- docs/README.md\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 1
    assert "description" not in result[0] or result[0].get("description") == ""


def test_parse_references_reviewed_missing_section_returns_empty() -> None:
    """When no References Reviewed section exists, return an empty list."""
    m = _load()
    content = "## Files Affected\n- src/foo.py\n"
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert result == []


def test_parse_references_reviewed_multiple_entries() -> None:
    """Multiple reference entries are all captured."""
    m = _load()
    content = (
        "## References Reviewed\n"
        "- src/a.py:1-10 - first file\n"
        "- docs/b.md - second file\n"
        "- src/c.py\n"
    )
    result = m.parse_references_reviewed(content)  # type: ignore[attr-defined]
    assert len(result) == 3


# ---------------------------------------------------------------------------
# check_file_in_scope
# ---------------------------------------------------------------------------


def test_file_in_scope_exact_match() -> None:
    """Exact path match is in scope."""
    m = _load()
    files = [{"path": "src/foo.py", "action": "modify"}]
    in_scope, reason = m.check_file_in_scope("src/foo.py", files)  # type: ignore[attr-defined]
    assert in_scope
    assert "modify" in reason


def test_file_in_scope_directory_prefix() -> None:
    """File under a declared directory is in scope."""
    m = _load()
    files = [{"path": "src", "action": "modify"}]
    in_scope, _ = m.check_file_in_scope("src/nested/file.py", files)  # type: ignore[attr-defined]
    assert in_scope


def test_file_not_in_scope() -> None:
    """File that is not declared and not under a declared directory is out of scope."""
    m = _load()
    files = [{"path": "src/foo.py", "action": "modify"}]
    in_scope, reason = m.check_file_in_scope("tests/test_other.py", files)  # type: ignore[attr-defined]
    assert not in_scope
    assert "Not in Files Affected" in reason


def test_file_scope_empty_files_list() -> None:
    """Empty files list means nothing is in scope."""
    m = _load()
    in_scope, _ = m.check_file_in_scope("src/anything.py", [])  # type: ignore[attr-defined]
    assert not in_scope


def test_file_scope_does_not_match_partial_name() -> None:
    """src/foo_extra.py should not match declared path src/foo.py (exact only)."""
    m = _load()
    files = [{"path": "src/foo.py", "action": "modify"}]
    in_scope, _ = m.check_file_in_scope("src/foo_extra.py", files)  # type: ignore[attr-defined]
    assert not in_scope
