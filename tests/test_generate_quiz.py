"""Tests for scripts/generate_quiz.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load() -> object:
    spec = importlib.util.spec_from_file_location(
        "generate_quiz_module", SCRIPTS_DIR / "generate_quiz.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


def test_load_relationships_returns_empty_without_file(tmp_path: Path) -> None:
    """Missing relationships config should produce an empty dictionary."""
    module = _load()
    assert module.load_relationships(tmp_path) == {}  # type: ignore[attr-defined]


def test_generate_quiz_surfaces_governance_coupling_and_risk(tmp_path: Path) -> None:
    """A governed file should produce constraint, coupling, and risk prompts."""
    module = _load()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "src" / "world").mkdir(parents=True)
    (tmp_path / "scripts" / "relationships.yaml").write_text(
        "adrs:\n"
        "  1:\n"
        "    title: Keep contracts stable\n"
        "governance:\n"
        "  - source: src/world/contracts.py\n"
        "    adrs: [1]\n"
        "    context: |\n"
        "      ADR-0001: Keep contracts stable\n"
        "couplings:\n"
        "  - sources: [src/world/contracts.py]\n"
        "    docs: [docs/contracts.md]\n"
        "    description: contract doc\n"
        "glossary:\n"
        "  old_term:\n"
        "    deprecated: true\n"
        "    replacement: new_term\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "world" / "contracts.py").write_text(
        "from typing import Protocol\n\n"
        "class Contract(Protocol):\n"
        "    def run(self) -> None: ...\n\n"
        "class Payload(BaseModel):\n"
        "    field: str\n",
        encoding="utf-8",
    )

    relationships = module.load_relationships(tmp_path)  # type: ignore[attr-defined]
    quiz = module.generate_quiz(  # type: ignore[attr-defined]
        "src/world/contracts.py", tmp_path, relationships
    )

    categories = {question["category"] for question in quiz["questions"]}
    assert {"constraint", "structure", "coupling", "terminology", "risk"} <= categories
    assert quiz["governance"]["adrs"][0]["title"] == "Keep contracts stable"

    markdown = module.format_quiz_markdown(quiz)  # type: ignore[attr-defined]
    assert "Understanding Quiz: src/world/contracts.py" in markdown
    assert "Governing ADRs" in markdown

