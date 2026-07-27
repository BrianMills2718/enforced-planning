"""Execution tests for the portable canonical pre-push hook."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "git" / "pre-push"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout.strip()


def _repo_with_fake_check(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feature")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "fixture")

    check = repo / "scripts" / "meta" / "check_push_safety.py"
    check.parent.mkdir(parents=True)
    check.write_text(
        "\n".join(
            [
                "import os",
                "import sys",
                "from pathlib import Path",
                "Path(os.environ['PUSH_CHECK_LOG']).write_text(' '.join(sys.argv[1:]))",
                "raise SystemExit(int(os.environ.get('PUSH_CHECK_EXIT', '0')))",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return repo, check


def _run_hook(
    repo: Path,
    stdin: str,
    *,
    log: Path,
    exit_code: int = 0,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PUSH_CHECK_LOG"] = str(log)
    env["PUSH_CHECK_EXIT"] = str(exit_code)
    return subprocess.run(
        ["bash", str(HOOK), "origin", "unused"],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_pre_push_validates_checked_out_branch(tmp_path: Path) -> None:
    repo, _ = _repo_with_fake_check(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    log = tmp_path / "push-check.log"

    result = _run_hook(
        repo,
        f"refs/heads/feature {head} refs/heads/feature {'0' * 40}\n",
        log=log,
    )

    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8") == f"--repo-root {repo} --branch feature"


def test_pre_push_propagates_canonical_gate_failure(tmp_path: Path) -> None:
    repo, _ = _repo_with_fake_check(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    log = tmp_path / "push-check.log"

    result = _run_hook(
        repo,
        f"refs/heads/feature {head} refs/heads/feature {'0' * 40}\n",
        log=log,
        exit_code=1,
    )

    assert result.returncode == 1
    assert log.exists()


def test_pre_push_rejects_non_checked_out_branch(tmp_path: Path) -> None:
    repo, _ = _repo_with_fake_check(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    log = tmp_path / "push-check.log"

    result = _run_hook(
        repo,
        f"refs/heads/other {head} refs/heads/other {'0' * 40}\n",
        log=log,
    )

    assert result.returncode == 1
    assert "only supports the checked-out branch" in result.stderr
    assert not log.exists()


def test_pre_push_ignores_tag_only_and_branch_deletion_updates(tmp_path: Path) -> None:
    repo, _ = _repo_with_fake_check(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    log = tmp_path / "push-check.log"
    zero = "0" * 40

    result = _run_hook(
        repo,
        "\n".join(
            [
                f"refs/tags/v1 {head} refs/tags/v1 {zero}",
                f"(delete) {zero} refs/heads/old {head}",
            ]
        )
        + "\n",
        log=log,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists()
