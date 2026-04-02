"""Tests for check_mock_usage.py — suspicious mock pattern detection.

Covers find_mock_usage (file scanning) and check_suspicious (pattern analysis).
All tests write temporary test files so they are hermetic.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "check_mock_usage_module", SCRIPTS_DIR / "check_mock_usage.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def _write_test_file(tests_dir: Path, name: str, content: str) -> Path:
    path = tests_dir / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# find_mock_usage
# ---------------------------------------------------------------------------


def test_find_mock_usage_detects_patch_decorator(tmp_path: Path) -> None:
    """@patch decorators in test files are detected."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write_test_file(
        tests_dir,
        "test_example.py",
        "from unittest.mock import patch\n\n@patch('src.module.func')\ndef test_foo(): pass\n",
    )
    result = m.find_mock_usage(tests_dir)  # type: ignore[attr-defined]
    assert len(result) == 1
    lines = list(result.values())[0]
    # Should have found the import + the @patch line
    assert any("@patch" in line for _, line in lines)


def test_find_mock_usage_detects_magic_mock(tmp_path: Path) -> None:
    """MagicMock usage (non-import) is flagged."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write_test_file(
        tests_dir,
        "test_magic.py",
        "from unittest.mock import MagicMock\n\ndef test_x():\n    m = MagicMock()\n",
    )
    result = m.find_mock_usage(tests_dir)  # type: ignore[attr-defined]
    assert len(result) == 1
    lines = list(result.values())[0]
    assert any("MagicMock()" in line for _, line in lines)


def test_find_mock_usage_ignores_non_test_files(tmp_path: Path) -> None:
    """Only test_*.py files are scanned."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    # This file does NOT start with test_
    _write_test_file(
        tests_dir,
        "helper.py",
        "from unittest.mock import patch\n",
    )
    result = m.find_mock_usage(tests_dir)  # type: ignore[attr-defined]
    assert result == {}


def test_find_mock_usage_empty_directory(tmp_path: Path) -> None:
    """Empty tests directory returns empty dict."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    result = m.find_mock_usage(tests_dir)  # type: ignore[attr-defined]
    assert result == {}


def test_find_mock_usage_clean_test_file(tmp_path: Path) -> None:
    """Test files with no mocks return empty entries."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    _write_test_file(
        tests_dir,
        "test_clean.py",
        "def test_add():\n    assert 1 + 1 == 2\n",
    )
    result = m.find_mock_usage(tests_dir)  # type: ignore[attr-defined]
    assert result == {}


# ---------------------------------------------------------------------------
# check_suspicious
# ---------------------------------------------------------------------------


def test_check_suspicious_flags_src_patch(tmp_path: Path) -> None:
    """@patch('src.module') without mock-ok comment is suspicious."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    path = _write_test_file(
        tests_dir,
        "test_suspicious.py",
        "@patch('src.module.func')\ndef test_foo(): pass\n",
    )
    mock_usage = {str(path): [(1, "@patch('src.module.func')")]}
    warnings = m.check_suspicious(mock_usage)  # type: ignore[attr-defined]
    assert len(warnings) >= 1
    assert any("src." in w for w in warnings)


def test_check_suspicious_skips_ok_patterns(tmp_path: Path) -> None:
    """@patch on time.sleep is an approved pattern and not flagged."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    path = _write_test_file(
        tests_dir,
        "test_ok.py",
        "@patch('time.sleep')\ndef test_foo(): pass\n",
    )
    mock_usage = {str(path): [(1, "@patch('time.sleep')")]}
    warnings = m.check_suspicious(mock_usage)  # type: ignore[attr-defined]
    assert warnings == []


def test_check_suspicious_respects_inline_mock_ok(tmp_path: Path) -> None:
    """A '# mock-ok: reason' comment on the same line suppresses the warning."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    path = _write_test_file(
        tests_dir,
        "test_inline_ok.py",
        "@patch('src.thing')  # mock-ok: external dep pinned\ndef test_foo(): pass\n",
    )
    mock_usage = {str(path): [(1, "@patch('src.thing')  # mock-ok: external dep pinned")]}
    warnings = m.check_suspicious(mock_usage)  # type: ignore[attr-defined]
    assert warnings == []


def test_check_suspicious_respects_file_level_mock_ok(tmp_path: Path) -> None:
    """A file-level '# mock-ok:' in the first 20 lines suppresses all warnings."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    path = _write_test_file(
        tests_dir,
        "test_file_ok.py",
        "# mock-ok: entire file uses mocks for legacy integration reasons\n"
        "@patch('src.thing')\ndef test_foo(): pass\n",
    )
    mock_usage = {str(path): [(2, "@patch('src.thing')")]}
    warnings = m.check_suspicious(mock_usage)  # type: ignore[attr-defined]
    assert warnings == []


def test_check_suspicious_no_warnings_for_clean_usage(tmp_path: Path) -> None:
    """Test with no suspicious patterns returns empty list."""
    m = _load()
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    path = _write_test_file(
        tests_dir,
        "test_requests.py",
        "from unittest.mock import patch\n@patch('requests.get')\ndef test_foo(mock_get): pass\n",
    )
    # @patch('requests.get') doesn't match SUSPICIOUS_PATTERNS (which look for src. prefix)
    mock_usage = {str(path): [(2, "@patch('requests.get')")]}
    warnings = m.check_suspicious(mock_usage)  # type: ignore[attr-defined]
    assert warnings == []
