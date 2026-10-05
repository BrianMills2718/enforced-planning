"""Real subprocess exercise of the sanctioned worktree entrypoints.

Runs ``make maintenance-worktree`` and ``make session-close`` as actual
subprocesses against this repository, using a disposable branch and a
fabricated ``codex`` native-session identity (a unique ``CODEX_THREAD_ID``)
so the run never collides with whatever session, if any, already holds this
repository's claim root.

A synthetic disposable *repository* was evaluated and rejected. The sanctioned
``make maintenance-worktree`` path is intentionally hard to fake past
``claim_bootstrap.py``'s repository-authority-provider gate
(``enforced_planning/repository_authority.py``), which requires a real
GitHub-hosted, Project-Graph-registered origin with reviewed governance
(``scripts/repository_authority_provider.py``). ``git remote get-url`` also
reflects any ``url.<base>.insteadOf`` rewrite used to redirect a fake origin
to a local bare repo, so that rewrite is visible to the same GitHub-host check
it would need to defeat -- there is no cheap local stand-in for the real
chain. Faking it would need either a persistent real GitHub fixture
repository or an SSH ``ProxyCommand``/host-alias trick that duplicates
production infrastructure just for a test. The disposable *branch* is the
real unit of throwaway state in every other real usage in this codebase
(``make maintenance-worktree BRANCH=...``), so this test disposes of a
branch/worktree/claim, not a repository -- and cleans up with
``WORKTREE_DISPOSITION=merged``, since a branch that never diverged from the
default branch is already integrated (verified: ``disposition=abandoned``
against such a branch is correctly refused as unnecessary/unsupported by
``session_lifecycle.py``'s closeout preflight, which requires ``merged`` for
an already-integrated branch).

This complements, not replaces, ``test_makefile_worktree_targets.py``'s
``make -n`` dry-run coverage and the direct-Python ``create_worktree()`` calls
elsewhere in this suite: those catch recipe/flag regressions cheaply, but
neither exercises a real worktree, branch, and coordination-claim file coming
into and going out of existence on disk.
"""

from __future__ import annotations

import json
import os
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml  # type: ignore[import-untyped]


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLAIMS_DIR = Path.home() / ".claude" / "coordination" / "claims"


def _canonical_repo_root(cwd: Path) -> Path:
    """Resolve the same canonical repo root the Makefile derives via WORKTREE_REPO_ROOT.

    ``git rev-parse --git-common-dir`` always names the *canonical* checkout's
    ``.git`` directory, even when invoked from inside one of its own linked
    worktrees (as this test file may be, before its branch merges). Deriving
    the expected worktree path from ``Path(__file__)`` instead silently
    predicts a location under whichever checkout the test happens to live in
    -- which is not where the sanctioned entrypoint actually places it.
    """
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=True,
    )
    return Path(result.stdout.strip()).parent


def _origin_reachable() -> bool:
    try:
        result = subprocess.run(
            ["git", "ls-remote", "--exit-code", "origin", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _run_make(target: str, branch: str, thread_id: str, **make_vars: str) -> subprocess.CompletedProcess[str]:
    args = ["make", target, f"BRANCH={branch}", *(f"{key}={value}" for key, value in make_vars.items())]
    env = dict(os.environ)
    env.pop("CLAUDE_CODE_SESSION_ID", None)
    env.pop("OPENCLAW_SESSION_ID", None)
    env["CODEX_THREAD_ID"] = thread_id
    return subprocess.run(
        args,
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
        env=env,
    )


def _branch_exists(branch: str, *, cwd: Path) -> bool:
    result = subprocess.run(
        ["git", "branch", "--list", branch],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    return branch in result.stdout


@pytest.mark.skipif(not _origin_reachable(), reason="origin remote is not reachable from this environment")
def test_maintenance_worktree_and_session_close_real_subprocess_roundtrip() -> None:
    """The two sanctioned entrypoints must really create and really clean up a lane."""
    branch = f"test-e2e-sanctioned-{uuid.uuid4().hex[:10]}"
    thread_id = f"pytest-e2e-{uuid.uuid4().hex[:10]}"
    canonical_root = _canonical_repo_root(PROJECT_ROOT)
    worktree_dir = canonical_root / "worktrees" / branch
    assert _lane_path_released(worktree_dir), f"stale worktree already at {worktree_dir}"
    assert not _branch_exists(branch, cwd=canonical_root), f"stale branch already named {branch}"

    create = _run_make(
        "maintenance-worktree",
        branch,
        thread_id,
        TASK="pytest-e2e-probe",
        WORKTREE_AGENT="codex",
        SESSION_GOAL="pytest e2e sanctioned entrypoints probe",
        SESSION_PHASE="probe",
        SESSION_WRITE_PATHS="README.md",
    )
    try:
        assert create.returncode == 0, create.stdout + create.stderr
        payload = json.loads(create.stdout)
        assert payload.get("ok") is True, payload
        assert worktree_dir.is_dir(), (
            f"make maintenance-worktree reported ok but {worktree_dir} does not exist"
        )
        assert _branch_exists(branch, cwd=canonical_root), (
            "make maintenance-worktree reported ok but branch was not created"
        )
        claim_files = list(CLAIMS_DIR.glob(f"*{branch}*"))
        assert claim_files, "no coordination claim file was created for the new branch"
        claim = yaml.safe_load(claim_files[0].read_text(encoding="utf-8"))
        assert claim["start_revision"] == payload["result"]["start_revision"]
        tracker = yaml.safe_load(Path(claim["tracker_path"]).read_text(encoding="utf-8"))
        assert tracker["claim"]["start_revision"] == payload["result"]["start_revision"]
    finally:
        close = _run_make(
            "session-close",
            branch,
            thread_id,
            WORKTREE_AGENT="codex",
            WORKTREE_DISPOSITION="merged",
            SESSION_NOTE="pytest e2e probe cleanup",
        )
        assert close.returncode == 0, close.stdout + close.stderr
        assert "NOT CHECKED" not in close.stdout
        assert _lane_path_released(worktree_dir), f"make session-close reported ok but {worktree_dir} still exists"
        assert not _branch_exists(branch, cwd=canonical_root), (
            "make session-close reported ok but branch still exists"
        )
        remaining_claims = list(CLAIMS_DIR.glob(f"*{branch}*"))
        assert not remaining_claims, f"claim file(s) not released: {remaining_claims}"


def _lane_path_released(path) -> bool:
    """A closed lane's path is gone or left as an empty placeholder directory."""

    return not path.exists() or (path.is_dir() and not any(path.iterdir()))
