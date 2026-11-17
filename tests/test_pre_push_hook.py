"""Execution tests for the portable pre-push hook template.

The hook runs only the global secret scan. The coordination-claim check was
retired (Brian, 2026-11-05), so these tests fix that a push is never blocked by
a claim check, even when one is present in the repository.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "hooks" / "git" / "pre-push"
ZERO = "0" * 40


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


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "feature")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-qm", "fixture")
    return repo


def _fake_secret_scan(tmp_path: Path) -> Path:
    """A stand-in for secret-scan.sh: records stdin and exits with PUSH_SCAN_EXIT."""
    scan = tmp_path / "secret-scan.sh"
    scan.write_text(
        "\n".join(
            [
                "#!/bin/bash",
                'cat > "$PUSH_SCAN_LOG"',
                'exit "${PUSH_SCAN_EXIT:-0}"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    scan.chmod(0o755)
    return scan


def _run_hook(
    repo: Path,
    stdin: str,
    *,
    scan: Path | None,
    log: Path,
    scan_exit: int = 0,
    chained: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PUSH_SCAN_LOG"] = str(log)
    env["PUSH_SCAN_EXIT"] = str(scan_exit)
    env.pop("_GIT_HOOK_CHAIN_ACTIVE", None)
    if scan is not None:
        env["SECRET_SCAN_HOOK"] = str(scan)
    if chained:
        env["_GIT_HOOK_CHAIN_ACTIVE"] = "1"
    return subprocess.run(
        ["bash", str(HOOK), "origin", "unused"],
        cwd=repo,
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_pre_push_passes_refs_to_secret_scan_and_allows_clean_push(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    scan = _fake_secret_scan(tmp_path)
    log = tmp_path / "scan.log"
    refs = f"refs/heads/feature {head} refs/heads/feature {ZERO}\n"

    result = _run_hook(repo, refs, scan=scan, log=log)

    assert result.returncode == 0, result.stderr
    assert log.read_text(encoding="utf-8") == refs


def test_pre_push_refuses_push_when_secret_scan_finds_a_secret(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    scan = _fake_secret_scan(tmp_path)
    log = tmp_path / "scan.log"

    result = _run_hook(
        repo,
        f"refs/heads/feature {head} refs/heads/feature {ZERO}\n",
        scan=scan,
        log=log,
        scan_exit=1,
    )

    assert result.returncode == 1
    assert log.exists()


def test_pre_push_never_runs_a_coordination_claim_check(tmp_path: Path) -> None:
    """A retired claim script that would fail must not block a push."""
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    claim_check = repo / "scripts" / "meta" / "check_push_safety.py"
    claim_check.parent.mkdir(parents=True)
    marker = tmp_path / "claim-check-ran"
    claim_check.write_text(
        "\n".join(
            [
                "import sys",
                "from pathlib import Path",
                f"Path({str(marker)!r}).write_text('ran')",
                "sys.exit(1)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    scan = _fake_secret_scan(tmp_path)
    log = tmp_path / "scan.log"

    result = _run_hook(
        repo,
        f"refs/heads/feature {head} refs/heads/feature {ZERO}\n",
        scan=scan,
        log=log,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()
    assert "claim validation" not in result.stdout + result.stderr


def test_pre_push_does_not_require_checked_out_branch(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    scan = _fake_secret_scan(tmp_path)
    log = tmp_path / "scan.log"

    result = _run_hook(
        repo,
        f"refs/heads/other {head} refs/heads/other {ZERO}\n",
        scan=scan,
        log=log,
    )

    assert result.returncode == 0, result.stderr
    assert "only supports the checked-out branch" not in result.stderr


def test_pre_push_warns_and_allows_when_secret_scan_is_missing(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    log = tmp_path / "scan.log"
    missing = tmp_path / "no-such-scan.sh"

    result = _run_hook(
        repo,
        f"refs/heads/feature {head} refs/heads/feature {ZERO}\n",
        scan=missing,
        log=log,
    )

    assert result.returncode == 0, result.stderr
    assert "warning: secret scan" in result.stderr
    assert not log.exists()


def test_pre_push_skips_scan_when_inside_a_hook_chain(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    scan = _fake_secret_scan(tmp_path)
    log = tmp_path / "scan.log"

    result = _run_hook(
        repo,
        f"refs/heads/feature {head} refs/heads/feature {ZERO}\n",
        scan=scan,
        log=log,
        scan_exit=1,
        chained=True,
    )

    assert result.returncode == 0, result.stderr
    assert not log.exists()
