"""Tests for scripts/log_friction.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "log_friction_module", SCRIPTS_DIR / "log_friction.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_ensure_friction_file_uses_template(tmp_path: Path) -> None:
    """Creates FRICTION.md from the canonical template when available."""
    module = _load()
    friction_path = tmp_path / "FRICTION.md"
    template_path = tmp_path / "template.md"
    template_text = "# Governance Friction Log\n\n## Entries\n"
    template_path.write_text(template_text, encoding="utf-8")
    module.FRICTION_FILE = friction_path  # type: ignore[attr-defined]
    module.TEMPLATE = template_path  # type: ignore[attr-defined]

    result = module.ensure_friction_file()  # type: ignore[attr-defined]

    assert result == friction_path
    assert friction_path.read_text(encoding="utf-8") == template_text


def test_append_entry_writes_structured_entry(tmp_path: Path) -> None:
    """Appends one structured friction entry to the log."""
    module = _load()
    friction_path = tmp_path / "FRICTION.md"
    template_path = tmp_path / "template.md"
    template_path.write_text("# Governance Friction Log\n\n## Entries\n", encoding="utf-8")
    module.FRICTION_FILE = friction_path  # type: ignore[attr-defined]
    module.TEMPLATE = template_path  # type: ignore[attr-defined]

    module.append_entry(  # type: ignore[attr-defined]
        friction="validator blocked status-only change",
        impact="5 minutes lost",
        suggestion="allow status-only path",
        severity="medium",
        agent="codex",
        phase="implementation",
    )

    content = friction_path.read_text(encoding="utf-8")
    assert "**Friction:** validator blocked status-only change" in content
    assert "**Impact:** 5 minutes lost" in content
    assert "**Suggestion:** allow status-only path" in content
    assert "**Severity:** medium" in content


def test_summary_reports_counts_by_severity(tmp_path: Path, capsys) -> None:
    """Summarizes recorded entries by severity."""
    module = _load()
    friction_path = tmp_path / "FRICTION.md"
    template_path = tmp_path / "template.md"
    template_path.write_text("# Governance Friction Log\n\n## Entries\n", encoding="utf-8")
    module.FRICTION_FILE = friction_path  # type: ignore[attr-defined]
    module.TEMPLATE = template_path  # type: ignore[attr-defined]
    friction_path.write_text(
        "# Governance Friction Log\n\n## Entries\n"
        "### 2026-04-03 — codex — implementation\n"
        "**Friction:** one\n"
        "**Impact:** a\n"
        "**Suggestion:** b\n"
        "**Severity:** high\n"
        "### 2026-04-03 — codex — implementation\n"
        "**Friction:** two\n"
        "**Impact:** c\n"
        "**Suggestion:** d\n"
        "**Severity:** medium\n",
        encoding="utf-8",
    )

    module.summary()  # type: ignore[attr-defined]

    output = capsys.readouterr().out
    assert "Friction entries: 2" in output
    assert "high: 1" in output
    assert "medium: 1" in output
