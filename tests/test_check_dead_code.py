"""Tests for check_dead_code.py — dead code detection wrapper.

Covers the pure helpers: _parse_vulture_line and _load_config.
The check_dead_code() integration function is tested with a minimal
project root that has the tool disabled so no subprocess is invoked.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "check_dead_code_module", SCRIPTS_DIR / "check_dead_code.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# _parse_vulture_line
# ---------------------------------------------------------------------------


def test_parse_vulture_line_valid_output() -> None:
    """Parses a standard vulture output line into a Finding."""
    m = _load()
    line = "scripts/foo.py:42: unused function 'bar' (90% confidence)"
    result = m._parse_vulture_line(line)  # type: ignore[attr-defined]
    assert result is not None
    assert result.file == "scripts/foo.py"
    assert result.line == 42
    assert result.name == "bar"
    assert result.kind == "unused-function"
    assert result.confidence == 90


def test_parse_vulture_line_variable() -> None:
    """Parses 'unused variable' kind correctly."""
    m = _load()
    line = "src/utils.py:7: unused variable '_tmp' (60% confidence)"
    result = m._parse_vulture_line(line)  # type: ignore[attr-defined]
    assert result is not None
    assert result.kind == "unused-variable"
    assert result.name == "_tmp"
    assert result.confidence == 60


def test_parse_vulture_line_invalid_returns_none() -> None:
    """Garbage input returns None."""
    m = _load()
    assert m._parse_vulture_line("") is None  # type: ignore[attr-defined]
    assert m._parse_vulture_line("not a vulture line") is None  # type: ignore[attr-defined]
    assert m._parse_vulture_line("src/foo.py: no match here") is None  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _load_config
# ---------------------------------------------------------------------------


def test_load_config_returns_defaults_when_no_file(tmp_path: Path) -> None:
    """Returns sensible defaults when meta-process.yaml is absent."""
    m = _load()
    config = m._load_config(tmp_path)  # type: ignore[attr-defined]
    assert config["enabled"] is False
    assert config["strict"] is False
    assert isinstance(config["min_confidence"], int)


def test_load_config_reads_enabled_flag(tmp_path: Path) -> None:
    """Enabled flag from YAML is respected."""
    m = _load()
    yaml_content = (
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n"
        "      strict: true\n"
        "      min_confidence: 70\n"
    )
    (tmp_path / "meta-process.yaml").write_text(yaml_content, encoding="utf-8")
    config = m._load_config(tmp_path)  # type: ignore[attr-defined]
    assert config["enabled"] is True
    assert config["strict"] is True
    assert config["min_confidence"] == 70


def test_load_config_missing_dead_code_section_returns_defaults(tmp_path: Path) -> None:
    """meta-process.yaml without dead_code section uses defaults."""
    m = _load()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n  version: '1.0'\n", encoding="utf-8"
    )
    config = m._load_config(tmp_path)  # type: ignore[attr-defined]
    assert config["enabled"] is False


# ---------------------------------------------------------------------------
# check_dead_code — disabled path (no subprocess invoked)
# ---------------------------------------------------------------------------


def test_check_dead_code_skips_when_disabled(tmp_path: Path) -> None:
    """When enabled: false, check_dead_code still returns a Result with passed=True."""
    m = _load()
    # No meta-process.yaml → enabled defaults to False
    result = m.check_dead_code(tmp_path)  # type: ignore[attr-defined]
    # Tool is not available in the test env, so passed=True and no findings
    assert result.passed
    assert result.findings == []
