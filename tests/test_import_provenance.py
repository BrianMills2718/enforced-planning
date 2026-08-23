"""Contract tests for the worktree import-provenance check.

Each test is pinned to an observed defect. The check exists because a linked
worktree isolates the git checkout but not the Python import path, so a suite
run inside a worktree can pass against the canonical checkout's code.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "worktree-coordination"
    / "import_provenance.py"
)
sys.path.insert(0, str(MODULE_PATH.parent))

from import_provenance import (  # noqa: E402
    ImportProvenanceError,
    check_import_provenance,
    declared_packages,
)


def _make_tree(root: Path, *, package: str, src_layout: bool) -> Path:
    """Build a minimal repository that declares one importable package."""
    root.mkdir(parents=True, exist_ok=True)
    location = root / "src" / package if src_layout else root / package
    location.mkdir(parents=True)
    (location / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
    declared = f"src/{package}" if src_layout else package
    (root / "pyproject.toml").write_text(
        "[project]\n"
        f'name = "{package.replace("_", "-")}"\n'
        "\n"
        "[tool.hatch.build.targets.wheel]\n"
        f'packages = ["{declared}"]\n',
        encoding="utf-8",
    )
    return location


def _run_cli(worktree: Path, *, pythonpath: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the check in a subprocess so import resolution is real, not patched."""
    env = {"PATH": "/usr/bin:/bin"}
    if pythonpath is not None:
        env["PYTHONPATH"] = str(pythonpath)
    return subprocess.run(
        [sys.executable, str(MODULE_PATH), "--worktree", str(worktree)],
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_flat_and_src_layouts_are_both_discovered(tmp_path: Path) -> None:
    """A directory scan misses src/ layouts, and that produced a false pass.

    The first version of this check discovered packages by scanning top-level
    directories for __init__.py. graph_application_toolkit keeps its package in
    src/, so the check never examined the package that was leaking, reported ok
    on three unrelated ones, and exited 0 on the known-bad worktree.
    """
    flat = tmp_path / "flat"
    _make_tree(flat, package="flatpkg", src_layout=False)
    assert declared_packages(flat) == ["flatpkg"]

    nested = tmp_path / "nested"
    _make_tree(nested, package="srcpkg", src_layout=True)
    assert declared_packages(nested) == ["srcpkg"], "src/ layout must be discovered"


def test_package_resolving_outside_the_worktree_is_a_leak(tmp_path: Path) -> None:
    """A worktree whose package resolves to another checkout greens the wrong code.

    Reproduces the observed graph_application_toolkit failure: the worktree has
    the source on disk, but the interpreter resolves the package from the
    canonical checkout, so the worktree's suite validates a different revision.
    """
    canonical = tmp_path / "canonical"
    _make_tree(canonical, package="leakpkg", src_layout=False)
    worktree = tmp_path / "worktree"
    _make_tree(worktree, package="leakpkg", src_layout=False)

    result = _run_cli(worktree, pythonpath=canonical)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "LEAK" in result.stdout
    assert "validate the canonical checkout" in result.stderr
    assert str(canonical) in result.stdout


def test_package_resolving_inside_the_worktree_passes(tmp_path: Path) -> None:
    """The positive control. Without it, a check that always fails looks correct."""
    worktree = tmp_path / "worktree"
    _make_tree(worktree, package="goodpkg", src_layout=False)

    result = _run_cli(worktree, pythonpath=worktree)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ok  " in result.stdout
    assert "LEAK" not in result.stdout


def test_undiscoverable_packages_fail_rather_than_pass_vacuously(tmp_path: Path) -> None:
    """A check that cannot identify its subject must not report success.

    This is the failure mode the check replaces: reporting ok on packages that
    were never the ones at risk.
    """
    empty = tmp_path / "empty"
    empty.mkdir()

    with pytest.raises(ImportProvenanceError, match="cannot determine which packages"):
        check_import_provenance(empty)

    result = _run_cli(empty)
    assert result.returncode == 2
    assert "FAIL" in result.stderr


def test_unimportable_package_is_not_treated_as_sound(tmp_path: Path) -> None:
    """A package the interpreter cannot resolve proves nothing either way."""
    worktree = tmp_path / "worktree"
    _make_tree(worktree, package="missingpkg", src_layout=False)

    result = _run_cli(worktree)

    assert result.returncode == 2, result.stdout + result.stderr
    assert "MISS" in result.stdout
    assert "not importable" in result.stderr


def test_check_does_not_mutate_sys_path(tmp_path: Path) -> None:
    """Stacking sys.path would manufacture the pass the check exists to detect.

    The first version inserted the worktree at sys.path[0], which guarantees an
    inside-the-worktree resolution regardless of the real environment.
    """
    worktree = tmp_path / "worktree"
    _make_tree(worktree, package="stablepkg", src_layout=False)
    before = list(sys.path)

    with pytest.raises(ImportProvenanceError):
        check_import_provenance(tmp_path / "does-not-exist")
    try:
        check_import_provenance(worktree)
    except ImportProvenanceError:  # pragma: no cover - discovery succeeds here
        pass

    assert sys.path == before, "the check must not alter import resolution"
