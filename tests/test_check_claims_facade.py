"""Issue #610: the legacy claim surfaces delegate to the canonical registry.

Consumers sync these scripts from here, so a regression in this repository
reaches every governed repo (DIGIMON #386 re-imported all three).
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from enforced_planning import claim_mutation_receipts, coordination_claims, push_safety

_REPO_ROOT = Path(__file__).resolve().parents[1]

PYTHON_CLAIM_SURFACES = (
    "scripts/worktree-coordination/check_claims.py",
    "scripts/worktree-coordination/meta_status.py",
    "scripts/worktree-coordination/safe_worktree_remove.py",
    "scripts/meta/worktree-coordination/safe_worktree_remove.py",
    "scripts/parse_plan.py",
    "scripts/pr_auto.py",
)


def _load_script(relative: str, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, _REPO_ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)


@pytest.mark.parametrize("relative", PYTHON_CLAIM_SURFACES)
def test_claim_surface_has_no_active_work_yaml_reader(relative: str) -> None:
    source = (_REPO_ROOT / relative).read_text(encoding="utf-8")
    # A mention in a docstring is allowed; a path join that would open it is not.
    assert '"active-work.yaml"' not in source
    assert '.claude/active-work.yaml"' not in source


def test_legacy_check_claims_is_a_canonical_facade() -> None:
    source = (_REPO_ROOT / "scripts/worktree-coordination/check_claims.py").read_text(encoding="utf-8")
    assert "import yaml" not in source
    assert "check_coordination_claims.py" in source


def test_every_canonical_facade_exposes_release_claims_for_branch() -> None:
    assert callable(coordination_claims.release_claims_for_branch)
    for relative in ("scripts/check_coordination_claims.py", "scripts/meta/check_coordination_claims.py"):
        module = _load_script(relative, "_facade_" + relative.replace("/", "_").removesuffix(".py"))
        assert callable(module.release_claims_for_branch), relative


@pytest.fixture
def isolated_registry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    claims_dir = tmp_path / "canonical-claims"
    monkeypatch.setattr(coordination_claims, "CLAIMS_DIR", claims_dir)
    monkeypatch.setattr(claim_mutation_receipts, "DEFAULT_EVENTS_PATH", tmp_path / "events.jsonl")
    monkeypatch.setattr(
        claim_mutation_receipts,
        "DEFAULT_COMPLETED_CLAIM_ARCHIVE_PATH",
        tmp_path / "completed-claims.jsonl",
    )
    monkeypatch.setenv("CODEX_THREAD_ID", "issue-610-regression")
    return claims_dir


def _repo_on_branch(tmp_path: Path, branch: str) -> Path:
    repo = tmp_path / "claim-repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "claim-test@example.invalid")
    _git(repo, "config", "user.name", "Claim Test")
    (repo / "tracked.txt").write_text("main\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "initial")
    _git(repo, "checkout", "-b", branch)
    return repo


def _claim(claims_dir: Path, repo: Path, branch: str, *, worktree_path: Path) -> ModuleType:
    canonical = _load_script("scripts/meta/check_coordination_claims.py", "_test_canonical_cli_610")
    canonical.CLAIMS_DIR = claims_dir
    rc = canonical.main(
        [
            "--claim",
            "--agent",
            "codex",
            "--project",
            repo.name,
            "--scope",
            branch,
            "--intent",
            "prove canonical release through the legacy facade",
            "--claim-type",
            "program",
            "--branch",
            branch,
            "--worktree-path",
            str(worktree_path),
            "--session-name",
            "issue-610-regression",
            "--session-id",
            "codex:issue-610-regression",
            "--plan",
            "UNPLANNED",
        ]
    )
    assert rc == 0
    return canonical


def _live_branches(repo: Path) -> list[str | None]:
    return [claim.branch for claim in coordination_claims.check_claims(repo.name) if claim.is_live()]


def test_release_refuses_live_managed_lane_with_clear_exit(
    tmp_path: Path,
    isolated_registry: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A claim whose worktree still exists closes only via session-close: exit 1, not a crash."""
    repo = _repo_on_branch(tmp_path, "issue-610-test")
    _claim(isolated_registry, repo, "issue-610-test", worktree_path=repo)

    payload = push_safety.evaluate_push_safety(repo, project=repo.name, branch="issue-610-test")
    assert payload["branch_claim_count"] == 1

    legacy = _load_script("scripts/worktree-coordination/check_claims.py", "_test_legacy_facade_refuse_610")
    legacy._canonical.CLAIMS_DIR = isolated_registry
    assert legacy.main(["--verify-branch", "issue-610-test"]) == 0
    capsys.readouterr()

    assert legacy.main(["--release", "--id", "issue-610-test", "--force"]) == 1
    err = capsys.readouterr().err
    assert "session-close" in err
    assert "Traceback" not in err
    assert _live_branches(repo) == ["issue-610-test"]


def test_release_frees_claim_once_lane_is_gone(
    tmp_path: Path,
    isolated_registry: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After the worktree and branch are gone, --release --id releases and prints Released."""
    repo = _repo_on_branch(tmp_path, "issue-610-gone")
    _git(repo, "checkout", "main")
    _git(repo, "branch", "-D", "issue-610-gone")
    gone_worktree = tmp_path / "removed-worktree"
    _claim(isolated_registry, repo, "issue-610-gone", worktree_path=gone_worktree)
    assert _live_branches(repo) == ["issue-610-gone"]

    legacy = _load_script("scripts/worktree-coordination/check_claims.py", "_test_legacy_facade_release_610")
    legacy._canonical.CLAIMS_DIR = isolated_registry
    capsys.readouterr()

    assert legacy.main(["--release", "--id", "issue-610-gone", "--force"]) == 0
    assert "Released" in capsys.readouterr().out
    assert _live_branches(repo) == []


def test_release_of_unknown_branch_reports_no_claim(
    isolated_registry: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    isolated_registry.mkdir(parents=True, exist_ok=True)
    legacy = _load_script("scripts/worktree-coordination/check_claims.py", "_test_legacy_facade_unknown_610")
    legacy._canonical.CLAIMS_DIR = isolated_registry

    assert legacy.main(["--release", "--id", "no-such-branch"]) == 0
    out = capsys.readouterr().out
    assert "No live canonical claim found for branch: no-such-branch" in out
    assert "Released" not in out


def test_legacy_claim_creation_flags_fail_with_migration_guidance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    legacy = _load_script("scripts/worktree-coordination/check_claims.py", "_test_legacy_facade_flags_610")

    assert legacy.main(["--claim", "--feature", "ledger", "--task", "x"]) == 2
    assert "check_coordination_claims.py" in capsys.readouterr().err
