"""The closeout must recognise its own repo's squash merges without a hand-supplied SHA.

_squash_merge_matches_branch has always been able to prove a squash merge, but it
only ran when the operator passed --merge-claim... --merge-commit. Nobody knows a
squash SHA offhand, so in practice `make session-close` refused every squash-merged
lane, in repos that squash by default. On 2026-09-09 the claim bootstrap then
refused to open any new lane, naming two lanes whose work was already merged and
which the preflight would not let anyone close.

These tests pin the discovery, in both directions: it must find a real squash merge
and it must NOT find one for a branch whose work never landed.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "enforced_planning" / "session_lifecycle.py"


def _load():
    spec = importlib.util.spec_from_file_location("session_lifecycle_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    ).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    (repo / "f.txt").write_text("base\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    return repo


def _lane(repo: Path, branch: str, content: str) -> None:
    _git(repo, "checkout", "-qb", branch)
    (repo / "f.txt").write_text(content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", f"work on {branch}")
    _git(repo, "checkout", "-q", "main")


def test_a_real_squash_merge_is_discovered(tmp_path: Path) -> None:
    module = _load()
    repo = _repo(tmp_path)
    _lane(repo, "feat", "base\nlane work\n")
    _git(repo, "merge", "--quiet", "--squash", "feat")
    _git(repo, "commit", "-qm", "squash of feat (#1)")
    expected = _git(repo, "rev-parse", "HEAD")

    found = module._discover_squash_merge_commit(repo, branch_ref="feat", default_ref="main")
    assert found == expected, found


def test_it_is_still_found_after_main_moves_on(tmp_path: Path) -> None:
    """A lane is usually closed some commits later, not immediately."""
    module = _load()
    repo = _repo(tmp_path)
    _lane(repo, "feat", "base\nlane work\n")
    _git(repo, "merge", "--quiet", "--squash", "feat")
    _git(repo, "commit", "-qm", "squash of feat (#1)")
    expected = _git(repo, "rev-parse", "HEAD")
    for n in range(3):
        (repo / f"later{n}.txt").write_text("later\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", f"unrelated {n}")

    assert module._discover_squash_merge_commit(repo, branch_ref="feat", default_ref="main") == expected


def test_an_unmerged_branch_finds_nothing(tmp_path: Path) -> None:
    """The whole point: discovery must not manufacture approval for unlanded work."""
    module = _load()
    repo = _repo(tmp_path)
    _lane(repo, "feat", "base\nUNMERGED WORK\n")
    (repo / "other.txt").write_text("unrelated\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "unrelated main move")

    assert module._discover_squash_merge_commit(repo, branch_ref="feat", default_ref="main") is None


def test_a_near_miss_on_the_same_file_is_not_accepted(tmp_path: Path) -> None:
    """Touching the same path is not evidence; only patch equality is."""
    module = _load()
    repo = _repo(tmp_path)
    _lane(repo, "feat", "base\nlane work\n")
    (repo / "f.txt").write_text("base\nSOMETHING ELSE ENTIRELY\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "different change to the same file")

    assert module._discover_squash_merge_commit(repo, branch_ref="feat", default_ref="main") is None
