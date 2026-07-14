"""Verify exhaustive, static, and deterministic relationship-context inventory."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest

from enforced_planning.relationship_context import RelationshipContextError
from enforced_planning.relationship_context import inventory_repository


def _write(path: Path, content: str | bytes) -> None:
    """Create one fixture artifact without hiding its exact source content."""

    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")


def _git_repo(tmp_path: Path) -> Path:
    """Create a real Git repository whose tracked set is the inventory oracle."""

    repo = tmp_path / "fixture-repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test User"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.com"], check=True)
    return repo


def _track_all(repo: Path) -> tuple[str, ...]:
    """Track fixture files and return Git's exact NUL-safe path set."""

    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    raw = subprocess.run(
        ["git", "-C", str(repo), "ls-files", "-z"],
        check=True,
        capture_output=True,
    ).stdout
    return tuple(sorted(item.decode("utf-8") for item in raw.split(b"\0") if item))


def test_inventory_exactly_matches_git_and_never_imports_target_code(tmp_path: Path) -> None:
    """A module that explodes at import remains safely inventoryable via AST."""

    repo = _git_repo(tmp_path)
    _write(
        repo / "src/danger.py",
        '''"""Explain why the dangerous module exists.

        A second paragraph is intentionally excluded from the compact summary.
        """

raise RuntimeError("inventory imported target code")

class Worker:
    """Coordinate one unit of work."""

    async def run(self, item: str, *, retries: int = 2) -> bool:
        """Run the item under the configured retry policy."""
        return True

def public(value: int | None = None) -> str:
    """Convert a value for the public boundary."""
    return str(value)

def _private() -> None:
    pass
''',
    )
    _write(repo / "README.md", "# Fixture\n\n## Purpose\n\nProve actual Markdown summary extraction.\n")
    _write(repo / "odd name.txt", "tracked too\n")
    expected = _track_all(repo)

    report = inventory_repository(repo)

    assert tuple(artifact.path for artifact in report.artifacts) == expected
    assert report.tracked_count == len(expected)
    danger = next(artifact for artifact in report.artifacts if artifact.path == "src/danger.py")
    assert danger.summary == "Explain why the dangerous module exists."
    assert danger.summary_source == "python:module-docstring"
    symbols = {symbol.qualified_name: symbol for symbol in danger.symbols}
    assert set(symbols) == {"<module>", "Worker", "Worker.run", "public"}
    assert symbols["Worker.run"].signature == "async run(self, item: str, *, retries: int = 2) -> bool"
    assert symbols["Worker.run"].docstring == "Run the item under the configured retry policy."
    assert symbols["public"].symbol_id == "src/danger.py::public"


def test_missing_and_invalid_python_context_is_explicit(tmp_path: Path) -> None:
    """Missing docstrings and syntax errors remain visible as stable diagnostics."""

    repo = _git_repo(tmp_path)
    _write(
        repo / "src/missing.py",
        "class Public:\n    def run(self) -> None:\n        return None\n",
    )
    _write(repo / "src/invalid.py", "def broken(:\n")
    _track_all(repo)

    report = inventory_repository(repo)
    by_path = {artifact.path: artifact for artifact in report.artifacts}

    missing = by_path["src/missing.py"]
    missing_findings = {(item.code, item.symbol) for item in missing.diagnostics}
    assert missing_findings == {
        ("python-docstring-missing", "<module>"),
        ("python-docstring-missing", "Public"),
        ("python-docstring-missing", "Public.run"),
    }
    invalid = by_path["src/invalid.py"]
    assert invalid.symbols == ()
    assert [item.code for item in invalid.diagnostics] == ["python-parse-error"]
    assert invalid.diagnostics[0].line == 1


def test_markdown_prefers_semantic_section_and_labels_fallback(tmp_path: Path) -> None:
    """Markdown context comes from real sections with a transparent fallback."""

    repo = _git_repo(tmp_path)
    _write(
        repo / "docs/decision.md",
        "# Decision Record\n\nOpening context is not the decision.\n\n## Decision\n\nUse actual source prose.\n",
    )
    _write(repo / "README.md", "# Demo\n\nFirst real paragraph is the compact overview.\n\nMore detail.\n")
    _write(repo / "docs/empty.md", "## Notes\n\n- only a list\n")
    _track_all(repo)

    report = inventory_repository(repo)
    by_path = {artifact.path: artifact for artifact in report.artifacts}

    decision = by_path["docs/decision.md"]
    assert decision.summary == "Use actual source prose."
    assert decision.summary_source == "markdown:section:Decision"
    readme = by_path["README.md"]
    assert readme.summary == "First real paragraph is the compact overview."
    assert readme.summary_source == "markdown:first-paragraph"
    empty = by_path["docs/empty.md"]
    assert [item.code for item in empty.diagnostics] == ["markdown-title-missing"]


def test_inventory_json_is_byte_deterministic_and_workspace_neutral(tmp_path: Path) -> None:
    """Repeated output is identical and contains no volatile or absolute root data."""

    repo = _git_repo(tmp_path)
    _write(repo / "module.py", '"""Stable summary."""\n')
    _write(repo / "data.json", '{"b": 2, "a": 1}\n')
    _track_all(repo)

    first = inventory_repository(repo).to_json(pretty=True)
    second = inventory_repository(repo).to_json(pretty=True)

    assert first == second
    assert str(repo) not in first
    payload = json.loads(first)
    assert payload["tracked_count"] == 2
    assert [item["path"] for item in payload["artifacts"]] == ["data.json", "module.py"]
    assert "generated_at" not in payload


def test_non_git_root_fails_loudly(tmp_path: Path) -> None:
    """A missing Git inventory is an error, never an empty successful report."""

    with pytest.raises(RelationshipContextError, match="cannot inventory Git repository"):
        inventory_repository(tmp_path)


def test_deleted_tracked_file_remains_explicitly_represented(tmp_path: Path) -> None:
    """Working-tree deletion must not crash or masquerade as a present artifact."""

    repo = _git_repo(tmp_path)
    path = repo / "src/deleted.py"
    _write(path, '"""This file exists in the Git index."""\n')
    _track_all(repo)
    path.unlink()

    report = inventory_repository(repo)

    assert report.tracked_count == 1
    artifact = report.artifacts[0]
    assert artifact.path == "src/deleted.py"
    assert artifact.working_tree_state == "missing"
    assert [item.code for item in artifact.diagnostics] == ["tracked-file-missing"]
