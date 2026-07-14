"""Verify the generated docstring wiki remains derivative, exhaustive, and fresh."""

from __future__ import annotations

from pathlib import Path
import subprocess

from enforced_planning.docstring_wiki import DEFAULT_OUTPUT
from enforced_planning.docstring_wiki import check_docstring_wiki
from enforced_planning.docstring_wiki import main
from enforced_planning.docstring_wiki import render_docstring_wiki


def _write(path: Path, content: str) -> None:
    """Create one real source artifact for generated-wiki verification."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo(tmp_path: Path) -> Path:
    """Create a Git fixture with code, docs, tests, and one undocumented file."""

    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-b", "main", str(repo)], check=True, capture_output=True)
    _write(
        repo / "src/service.py",
        '''"""Serve project knowledge."""

class Service:
    """Coordinate project-level knowledge operations."""

    def run(self, goal: str) -> str:
        """Run one governed project goal."""
        return goal
''',
    )
    _write(repo / "docs/decision.md", "# Decision\n\n## Decision\n\nUse source-local summaries.\n")
    _write(repo / "tests/test_service.py", "def test_service() -> None:\n    pass\n")
    _write(repo / "data.json", "{}\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    return repo


def _track_generated_wiki(repo: Path) -> Path:
    """Generate once, track the output, then regenerate its stable self entry."""

    assert main(["--repo-root", str(repo), "--write"]) == 0
    output = repo / DEFAULT_OUTPUT
    subprocess.run(["git", "-C", str(repo), "add", output.relative_to(repo).as_posix()], check=True)
    assert main(["--repo-root", str(repo), "--write"]) == 0
    return output


def test_wiki_lists_every_tracked_artifact_and_actual_symbol_docstrings(tmp_path: Path) -> None:
    """The compressed view remains complete while prose comes from real sources."""

    repo = _repo(tmp_path)
    output = _track_generated_wiki(repo)

    rendered = output.read_text(encoding="utf-8")
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    for path in tracked:
        assert f"`{path}`" in rendered
    assert "Serve project knowledge." in rendered
    assert "Coordinate project-level knowledge operations." in rendered
    assert "Run one governed project goal." in rendered
    assert "Use source-local summaries." in rendered
    assert "python-docstring-missing" in rendered
    assert "Generated wiki projection; self-content intentionally omitted." in rendered
    assert str(repo) not in rendered


def test_wiki_is_deterministic_and_check_detects_hand_edit(tmp_path: Path) -> None:
    """Generated output is byte-stable and manual edits fail the sync check."""

    repo = _repo(tmp_path)
    output = _track_generated_wiki(repo)

    first = render_docstring_wiki(repo)
    second = render_docstring_wiki(repo)
    assert first == second == output.read_text(encoding="utf-8")
    assert check_docstring_wiki(repo) == (True, f"docstring wiki current: {output}")
    output.write_text(first + "manual drift\n", encoding="utf-8")

    ok, message = check_docstring_wiki(repo)

    assert not ok
    assert "stale or hand-edited" in message


def test_source_docstring_change_makes_wiki_stale_until_regenerated(tmp_path: Path) -> None:
    """Changing local semantic truth invalidates the derived projection."""

    repo = _repo(tmp_path)
    output = _track_generated_wiki(repo)
    _write(repo / "src/service.py", '"""Serve newly described knowledge."""\n')

    assert check_docstring_wiki(repo)[0] is False
    assert main(["--repo-root", str(repo), "--write"]) == 0
    assert check_docstring_wiki(repo)[0] is True
    assert "Serve newly described knowledge." in output.read_text(encoding="utf-8")


def test_check_fails_when_wiki_is_missing(tmp_path: Path) -> None:
    """A missing generated navigation surface is not a successful empty state."""

    repo = _repo(tmp_path)

    ok, message = check_docstring_wiki(repo)

    assert not ok
    assert "missing" in message
