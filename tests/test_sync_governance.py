"""Tests for scripts/sync_governance.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "sync_governance_module", SCRIPTS_DIR / "sync_governance.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_governance_config_loads_relationships_format(tmp_path: Path) -> None:
    """The loader should normalize relationships.yaml into governed file state."""
    module = _load()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "adr" / "0001.md").write_text("adr", encoding="utf-8")
    (tmp_path / "src" / "example.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "scripts" / "relationships.yaml").write_text(
        "adrs:\n"
        "  1:\n"
        "    title: Stable headers\n"
        "    file: 0001.md\n"
        "governance:\n"
        "  - source: src/example.py\n"
        "    adrs: [1]\n"
        "    context: |\n"
        "      ADR-0001: Stable headers\n",
        encoding="utf-8",
    )

    config = module.GovernanceConfig.load(  # type: ignore[attr-defined]
        tmp_path / "scripts" / "relationships.yaml"
    )

    assert config.files["src/example.py"] == [1]
    assert "ADR-0001: Stable headers" in config.file_context["src/example.py"]
    assert config.validate(tmp_path) == []


def test_update_file_content_inserts_after_docstring() -> None:
    """Governance blocks should slot in after a leading module docstring."""
    module = _load()
    content = '"""Example module."""\n\n\ndef run() -> None:\n    pass\n'
    block = "# --- GOVERNANCE START (do not edit) ---\n# ADR-0001: Stable\n# --- GOVERNANCE END ---"

    updated, changed = module.update_file_content(content, block)  # type: ignore[attr-defined]

    assert changed is True
    assert '"""Example module."""\n\n# --- GOVERNANCE START' in updated


def test_sync_file_applies_block_to_python_file(tmp_path: Path) -> None:
    """Applying sync should rewrite the file with the generated block."""
    module = _load()
    file_path = tmp_path / "src" / "example.py"
    file_path.parent.mkdir(parents=True)
    file_path.write_text('"""Example."""\n\n\ndef run() -> None:\n    pass\n', encoding="utf-8")
    config = module.GovernanceConfig(  # type: ignore[attr-defined]
        files={str(file_path): [1]},
        file_context={str(file_path): "ADR-0001: Stable"},
        adrs={1: {"title": "Stable", "file": "0001.md"}},
    )

    changed, message = module.sync_file(  # type: ignore[attr-defined]
        file_path, config, apply=True
    )

    assert changed is True
    assert message.startswith("UPDATED:")
    content = file_path.read_text(encoding="utf-8")
    assert "# ADR-0001: Stable" in content
    assert "def run()" in content
