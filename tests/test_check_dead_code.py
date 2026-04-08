"""Tests for check_dead_code.py — dead code detection wrapper.

Covers the pure helpers: _parse_vulture_line and _load_config.
The check_dead_code() integration function is tested with a minimal
project root that has the tool disabled so no subprocess is invoked.
"""

from __future__ import annotations

import importlib.util
import builtins
import sys
from pathlib import Path
from types import SimpleNamespace


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


def test_load_config_falls_back_without_pyyaml(
    tmp_path: Path, monkeypatch
) -> None:
    """The dead-code block still loads when PyYAML is unavailable."""
    m = _load()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n"
        "      strict: true\n"
        "      min_confidence: 90\n"
        "      paths:\n"
        "        - \"enforced_planning\"\n",
        encoding="utf-8",
    )

    original_import = builtins.__import__

    def fake_import(name, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "yaml":
            raise ImportError("yaml intentionally unavailable for this test")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    config = m._load_config(tmp_path)  # type: ignore[attr-defined]
    assert config["enabled"] is True
    assert config["strict"] is True
    assert config["min_confidence"] == 90
    assert config["paths"] == ["enforced_planning"]


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


def test_run_vulture_fails_loud_when_module_missing(tmp_path: Path, monkeypatch) -> None:
    """Missing vulture is a hard failure when the check is enabled."""
    m = _load()

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="/usr/bin/python: No module named vulture",
        )

    monkeypatch.setattr(m.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    result = m._run_vulture(tmp_path, [], 80, ".vulture_whitelist.py")  # type: ignore[attr-defined]
    assert not result.passed
    assert not result.tool_available
    assert "required" in result.error


def test_check_dead_code_strict_fails_on_vulture_findings(
    tmp_path: Path, monkeypatch
) -> None:
    """Strict mode fails when vulture reports findings."""
    m = _load()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n"
        "      strict: true\n",
        encoding="utf-8",
    )

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            returncode=3,
            stdout="src/mod.py:12: unused function 'orphan' (90% confidence)\n",
            stderr="",
        )

    monkeypatch.setattr(m.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    result = m.check_dead_code(tmp_path)  # type: ignore[attr-defined]
    assert not result.passed
    assert len(result.findings) == 1
    assert result.findings[0].name == "orphan"


def test_run_knip_parses_json_findings(tmp_path: Path, monkeypatch) -> None:
    """Knip JSON findings are normalized into the shared Finding shape."""
    m = _load()

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            returncode=1,
            stdout=(
                '{"files":["src/unused.ts"],'
                '"issues":[{"file":"src/app.ts","exports":[{"name":"deadExport","line":9}]}]}'
            ),
            stderr="",
        )

    monkeypatch.setattr(m.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    result = m._run_knip(tmp_path)  # type: ignore[attr-defined]
    assert result.passed
    assert [finding.kind for finding in result.findings] == ["unused-file", "exports"]
    assert result.findings[0].file == "src/unused.ts"
    assert result.findings[1].name == "deadExport"
    assert result.findings[1].line == 9


def test_check_dead_code_enabled_fails_when_knip_output_is_invalid(
    tmp_path: Path, monkeypatch
) -> None:
    """Invalid knip output fails loudly instead of silently passing."""
    m = _load()
    (tmp_path / "meta-process.yaml").write_text(
        "meta_process:\n"
        "  quality:\n"
        "    dead_code:\n"
        "      enabled: true\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        return SimpleNamespace(returncode=2, stdout="not-json", stderr="knip exploded")

    monkeypatch.setattr(m.subprocess, "run", fake_run)  # type: ignore[attr-defined]
    result = m.check_dead_code(tmp_path)  # type: ignore[attr-defined]
    assert not result.passed
    assert "valid JSON" in result.error
