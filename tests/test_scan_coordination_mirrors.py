"""Tests for coordination mirror scanning."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCAN_SCRIPT = PROJECT_ROOT / "scripts" / "scan_coordination_mirrors.py"
COORDINATION_DIR = Path("docs/meta-patterns/worktree-coordination")


def _init_repo(repo_root: Path) -> None:
    (repo_root / ".git").mkdir(parents=True, exist_ok=True)


def _write_stub_tree(repo_root: Path) -> None:
    tree = repo_root / COORDINATION_DIR
    tree.mkdir(parents=True, exist_ok=True)
    content = (
        "# Mirror\n\n"
        "This repo-local file is an explicit mirror stub.\n\n"
        "- [Pattern](../../../../enforced-planning/patterns/worktree-coordination/README.md)\n"
        "- [Guide](../../../../enforced-planning/docs/guides/WORKTREE_COORDINATION_OPERATOR_GUIDE.md)\n"
    )
    for name in (
        "README.md",
        "18_claim-system.md",
        "19_worktree-enforcement.md",
        "20_rebase-workflow.md",
        "21_pr-coordination.md",
        "26_ownership-respect.md",
    ):
        (tree / name).write_text(content, encoding="utf-8")


def _write_copied_tree(repo_root: Path) -> None:
    tree = repo_root / COORDINATION_DIR
    tree.mkdir(parents=True, exist_ok=True)
    for name in (
        "README.md",
        "18_claim-system.md",
        "19_worktree-enforcement.md",
        "20_rebase-workflow.md",
        "21_pr-coordination.md",
        "26_ownership-respect.md",
    ):
        (tree / name).write_text("# Local copy\n\nFull local content.\n", encoding="utf-8")


def test_scan_coordination_mirrors_classifies_stub_and_copied_repos(
    tmp_path: Path,
) -> None:
    """The scanner should distinguish explicit mirror stubs from copied docs."""
    enforced = tmp_path / "enforced-planning"
    stub_repo = tmp_path / "stub-repo"
    copied_repo = tmp_path / "copied-repo"
    absent_repo = tmp_path / "absent-repo"
    for repo in (enforced, stub_repo, copied_repo, absent_repo):
        _init_repo(repo)
    _write_stub_tree(stub_repo)
    _write_copied_tree(copied_repo)

    result = subprocess.run(
        [
            sys.executable,
            str(SCAN_SCRIPT),
            "--workspace-root",
            str(tmp_path),
            "--json",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    by_repo = {entry["repo_name"]: entry for entry in payload["repos"]}
    assert by_repo["enforced-planning"]["status"] == "canonical-source"
    assert by_repo["stub-repo"]["status"] == "mirror-stub"
    assert by_repo["copied-repo"]["status"] == "copied-or-custom"
    assert by_repo["absent-repo"]["status"] == "absent"
    assert payload["copied_or_custom_repos"] == ["copied-repo"]


def test_scan_coordination_mirrors_fail_on_copied(
    tmp_path: Path,
) -> None:
    """--fail-on-copied should exit non-zero when copied docs remain."""
    copied_repo = tmp_path / "copied-repo"
    _init_repo(copied_repo)
    _write_copied_tree(copied_repo)

    result = subprocess.run(
        [
            sys.executable,
            str(SCAN_SCRIPT),
            "--workspace-root",
            str(tmp_path),
            "--fail-on-copied",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert "copied-repo" in result.stdout
