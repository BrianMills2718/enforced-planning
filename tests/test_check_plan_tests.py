"""Tests for check_plan_tests.py — plan test requirement parsing.

Covers parse_plan_file(), find_plan_files(), find_test_class(), and
check_test_exists() without running pytest or requiring real plan dirs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from check_plan_tests import (
    TestRequirement as RequiredTestSpec,
    check_test_exists,
    find_plan_files,
    find_test_class,
    parse_plan_file,
    run_tests,
)


# ---------------------------------------------------------------------------
# parse_plan_file
# ---------------------------------------------------------------------------

class TestParsePlanFile:

    def _write_plan(self, tmp_path: Path, name: str, content: str) -> Path:
        f = tmp_path / name
        f.write_text(content)
        return f

    def test_extracts_plan_number(self, tmp_path: Path):
        f = self._write_plan(tmp_path, "07_my-feature.md", "**Status:** Complete\n")
        result = parse_plan_file(f)
        assert result is not None
        assert result.plan_number == 7

    def test_extracts_status(self, tmp_path: Path):
        f = self._write_plan(tmp_path, "01_thing.md", "**Status:** In Progress\n")
        result = parse_plan_file(f)
        assert result.status == "In Progress"

    def test_missing_status_defaults_unknown(self, tmp_path: Path):
        f = self._write_plan(tmp_path, "02_no-status.md", "# Plan\nNo status here.\n")
        result = parse_plan_file(f)
        assert result.status == "Unknown"

    def test_no_tests_section_returns_empty(self, tmp_path: Path):
        f = self._write_plan(tmp_path, "03_no-tests.md", "**Status:** Complete\n## Gap\nText.\n")
        result = parse_plan_file(f)
        assert result.new_tests == []
        assert result.existing_tests == []

    def test_bullet_format_test_parsed(self, tmp_path: Path):
        content = (
            "**Status:** In Progress\n"
            "## Required Tests\n"
            "- `tests/test_foo.py::test_basic`\n"
        )
        f = self._write_plan(tmp_path, "04_bullet.md", content)
        result = parse_plan_file(f)
        assert len(result.new_tests) == 1
        assert result.new_tests[0].file == "tests/test_foo.py"
        assert result.new_tests[0].function == "test_basic"

    def test_bullet_file_only_no_function(self, tmp_path: Path):
        content = (
            "**Status:** In Progress\n"
            "## Required Tests\n"
            "- `tests/test_whole.py`\n"
        )
        f = self._write_plan(tmp_path, "05_file-only.md", content)
        result = parse_plan_file(f)
        assert result.new_tests[0].file == "tests/test_whole.py"
        assert result.new_tests[0].function is None

    def test_non_matching_filename_returns_none(self, tmp_path: Path):
        f = self._write_plan(tmp_path, "CLAUDE.md", "**Status:** Complete\n")
        result = parse_plan_file(f)
        assert result is None

    def test_class_scoped_test_parsed(self, tmp_path: Path):
        content = (
            "**Status:** In Progress\n"
            "## Required Tests\n"
            "- `tests/test_bar.py::TestBar::test_method`\n"
        )
        f = self._write_plan(tmp_path, "06_class.md", content)
        result = parse_plan_file(f)
        assert result.new_tests[0].function == "TestBar::test_method"


# ---------------------------------------------------------------------------
# find_plan_files
# ---------------------------------------------------------------------------

class TestFindPlanFiles:

    def test_finds_numbered_plans(self, tmp_path: Path):
        (tmp_path / "01_first.md").touch()
        (tmp_path / "02_second.md").touch()
        (tmp_path / "CLAUDE.md").touch()
        result = find_plan_files(tmp_path)
        assert len(result) == 2
        assert all(f.name.startswith(("01", "02")) for f in result)

    def test_sorted_by_number(self, tmp_path: Path):
        (tmp_path / "10_tenth.md").touch()
        (tmp_path / "02_second.md").touch()
        (tmp_path / "01_first.md").touch()
        result = find_plan_files(tmp_path)
        numbers = [int(f.name.split("_")[0]) for f in result]
        assert numbers == sorted(numbers)

    def test_empty_dir_returns_empty(self, tmp_path: Path):
        assert find_plan_files(tmp_path) == []

    def test_ignores_non_plan_mds(self, tmp_path: Path):
        (tmp_path / "README.md").touch()
        (tmp_path / "TEMPLATE.md").touch()
        assert find_plan_files(tmp_path) == []


# ---------------------------------------------------------------------------
# find_test_class
# ---------------------------------------------------------------------------

class TestFindTestClass:

    def test_function_inside_class(self):
        content = "class TestFoo:\n    def test_bar(self):\n        pass\n"
        result = find_test_class(content, "test_bar")
        assert result == "TestFoo"

    def test_top_level_function_returns_none(self):
        content = "def test_standalone():\n    pass\n"
        result = find_test_class(content, "test_standalone")
        assert result is None

    def test_missing_function_returns_none(self):
        content = "class TestFoo:\n    def test_other(self):\n        pass\n"
        result = find_test_class(content, "test_nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# check_test_exists
# ---------------------------------------------------------------------------

class TestCheckTestExists:

    def test_file_exists_no_function(self, tmp_path: Path):
        test_file = tmp_path / "tests" / "test_something.py"
        test_file.parent.mkdir()
        test_file.write_text("def test_basic(): pass\n")
        req = RequiredTestSpec(file="tests/test_something.py")
        assert check_test_exists(req, tmp_path) is True

    def test_file_missing_returns_false(self, tmp_path: Path):
        req = RequiredTestSpec(file="tests/test_missing.py")
        assert check_test_exists(req, tmp_path) is False

    def test_function_exists_in_file(self, tmp_path: Path):
        test_file = tmp_path / "tests" / "test_foo.py"
        test_file.parent.mkdir()
        test_file.write_text("def test_my_func(): pass\n")
        req = RequiredTestSpec(file="tests/test_foo.py", function="test_my_func")
        assert check_test_exists(req, tmp_path) is True

    def test_function_missing_from_file_returns_false(self, tmp_path: Path):
        test_file = tmp_path / "tests" / "test_foo.py"
        test_file.parent.mkdir()
        test_file.write_text("def test_other(): pass\n")
        req = RequiredTestSpec(file="tests/test_foo.py", function="test_missing")
        assert check_test_exists(req, tmp_path) is False


def test_run_tests_uses_current_python_interpreter(tmp_path: Path) -> None:
    """Required plan tests must run in the completion process environment."""
    test_file = tmp_path / "tests" / "test_example.py"
    test_file.parent.mkdir()
    test_file.write_text("def test_example(): assert True\n", encoding="utf-8")
    requirement = RequiredTestSpec(file="tests/test_example.py", function="test_example")
    completed = MagicMock(returncode=0, stdout="passed", stderr="")

    # mock-ok: exact subprocess argv is the contract under test.
    with patch("check_plan_tests.subprocess.run", return_value=completed) as run:
        exit_code, _output = run_tests([requirement], tmp_path)

    assert exit_code == 0
    assert run.call_args.args[0][:3] == [sys.executable, "-m", "pytest"]
