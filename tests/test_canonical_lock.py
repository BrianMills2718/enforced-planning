"""Tests for the canonical-checkout lock.

Each case is pinned to a failure mode that was observed rather than imagined:

- File-only ``chmod`` was measured to be a sieve. ``sed -i``, ``mv -f``, and
  ``cp -f`` all wrote straight through mode ``444`` because they replace the
  inode and rename over it, which needs write permission on the directory.
  ``sed -i`` is the exact route the estate audit found agents using, so a
  file-only lock would have blocked nothing that mattered.
- ``coordination_claims._load_claims`` returns ``[]`` both for "no live claims"
  and for "the registry is missing", and silently skips any claim file it cannot
  parse. Reading an untrustworthy empty result as "no lane is live" would unlock
  a repository that is in fact claimed, which is the fail-open defect four
  existing hooks in this estate already have.
- A session that dies without closing leaves the checkout read-only forever
  unless something repairs it without being asked.
"""

from __future__ import annotations

import importlib.util
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "worktree-coordination" / "canonical_lock.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("canonical_lock", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["canonical_lock"] = module
    spec.loader.exec_module(module)
    return module


canonical_lock = _load_module()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real git repository, because permission behaviour cannot be mocked."""
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")
    root = tmp_path / "canonical"
    (root / "src").mkdir(parents=True)
    (root / ".gitignore").write_text("worktrees/\n", encoding="utf-8")
    (root / "src" / "module.py").write_text("ORIGINAL\n", encoding="utf-8")
    (root / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    os.chmod(root / "run.sh", 0o755)
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "t@e.invalid"),
        ("config", "user.name", "t"),
        ("add", "-A"),
        ("commit", "-qm", "baseline"),
    ):
        assert _git(root, *args).returncode == 0
    yield root
    # Always leave the tree removable, even if a test failed mid-lock.
    for current, dirnames, filenames in os.walk(root):
        for name in [*dirnames, *filenames]:
            target = Path(current) / name
            if not target.is_symlink():
                os.chmod(target, stat.S_IMODE(target.lstat().st_mode) | stat.S_IWUSR)
    os.chmod(root, stat.S_IMODE(root.lstat().st_mode) | stat.S_IWUSR)


def _claims_dir(tmp_path: Path, *records: dict) -> Path:
    directory = tmp_path / "claims"
    directory.mkdir(exist_ok=True)
    for index, record in enumerate(records):
        (directory / f"claim_{index}.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    return directory


def _lane_claim(repo: Path, scope: str = "lane-a", status: str = "active") -> dict:
    return {
        "agent": "claude-code",
        "scope": scope,
        "status": status,
        "projects": [repo.name],
        "worktree_path": str(repo / "worktrees" / scope),
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------- enforcement


def test_file_only_locking_is_a_sieve_which_is_why_directories_are_locked(repo: Path) -> None:
    """Pins the measurement that forced directory locking into the design."""
    target = repo / "src" / "module.py"
    os.chmod(target, 0o444)  # the naive design: files only

    subprocess.run(f"sed -i s/ORIGINAL/BREACH/ {target}", shell=True, capture_output=True, check=False)

    assert "BREACH" in target.read_text(encoding="utf-8"), (
        "sed -i is expected to defeat a file-only lock; if this ever stops being true "
        "the directory half of the lock could be reconsidered"
    )


@pytest.mark.parametrize(
    "name,command",
    [
        ("shell_redirect", "sh -c 'echo BREACH > {target}'"),
        ("sed_in_place", "sed -i s/ORIGINAL/BREACH/ {target}"),
        ("python_open_w", 'python3 -c "open(\'{target}\',\'w\').write(\'BREACH\')"'),
        ("tee", "sh -c 'echo BREACH | tee {target}'"),
        ("cp_over", "sh -c 'echo BREACH > {tmp} && cp -f {tmp} {target}'"),
        ("mv_over", "sh -c 'echo BREACH > {tmp} && mv -f {tmp} {target}'"),
        ("rm_then_recreate", "sh -c 'rm -f {target} && echo BREACH > {target}'"),
    ],
)
def test_locked_checkout_blocks_every_write_route(repo: Path, tmp_path: Path, name: str, command: str) -> None:
    """No route, tool-shaped or shell-shaped, may reach a locked canonical file."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    target = repo / "src" / "module.py"

    subprocess.run(
        command.format(target=target, tmp=tmp_path / f"tmp_{name}"),
        shell=True,
        capture_output=True,
        check=False,
    )

    assert target.exists(), f"{name} deleted a locked file"
    assert target.read_text(encoding="utf-8") == "ORIGINAL\n", f"{name} wrote through the lock"


def test_locked_checkout_blocks_new_files(repo: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    subprocess.run(f"sh -c 'echo X > {repo / 'added.txt'}'", shell=True, capture_output=True, check=False)
    assert not (repo / "added.txt").exists()


def test_lane_worktree_stays_writable_under_a_lock(repo: Path) -> None:
    """The decisive concurrent-session property: locking canonical must not
    touch a lane that another session is legitimately working in."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    lane = repo / "worktrees" / "lane-a"

    assert _git(repo, "worktree", "add", "-q", "-b", "lane-a", str(lane)).returncode == 0
    subprocess.run(f"sed -i s/ORIGINAL/LANEWRITE/ {lane / 'src' / 'module.py'}", shell=True, check=False)
    assert "LANEWRITE" in (lane / "src" / "module.py").read_text(encoding="utf-8")

    _git(lane, "add", "-A")
    assert _git(lane, "commit", "-qm", "lane change").returncode == 0
    assert _git(repo, "status", "--short").returncode == 0


def test_unlock_restores_modes_including_the_executable_bit(repo: Path) -> None:
    before = {p: stat.S_IMODE((repo / p).lstat().st_mode) for p in ("src/module.py", "run.sh", "src")}

    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    canonical_lock.unlock_repo(repo)

    after = {p: stat.S_IMODE((repo / p).lstat().st_mode) for p in ("src/module.py", "run.sh", "src")}
    assert after == before
    status = _git(repo, "status", "--porcelain")
    assert status.stdout.strip() == "", "lock/unlock must leave the checkout clean"


def test_lock_creates_worktrees_dir_so_the_next_lane_can_still_be_made(repo: Path) -> None:
    """A locked root makes ``mkdir worktrees`` fail, which would block the next
    ``git worktree add`` in a repository that never hosted a lane."""
    assert not (repo / "worktrees").exists()
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    assert (repo / "worktrees").is_dir()
    assert _git(repo, "worktree", "add", "-q", "-b", "lane-a", str(repo / "worktrees" / "lane-a")).returncode == 0


def test_lock_is_idempotent(repo: Path) -> None:
    first = canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    second = canonical_lock.lock_repo(repo, justifying_claims=["lane-b"])
    assert first["action"] == "locked"
    assert second["action"] == "already_locked"
    assert second["justifying_claims"] == ["lane-a"], "a second lock must not overwrite the original receipt"


def test_unlock_without_a_receipt_is_a_noop(repo: Path) -> None:
    assert canonical_lock.unlock_repo(repo)["action"] == "not_locked"


def test_unlock_repairs_excluded_git_and_worktree_control_paths(repo: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    git_worktrees = repo / ".git" / "worktrees"
    git_worktrees.mkdir(exist_ok=True)
    mutable_admin = git_worktrees / "COMMIT_EDITMSG"
    mutable_admin.write_text("message\n", encoding="utf-8")
    for path in (mutable_admin, git_worktrees, repo / ".git", repo / "worktrees"):
        os.chmod(path, stat.S_IMODE(path.lstat().st_mode) & ~stat.S_IWUSR)

    result = canonical_lock.unlock_repo(repo)

    assert result["action"] == "unlocked"
    assert not canonical_lock.receipt_path(repo).exists()
    for path in (mutable_admin, git_worktrees, repo / ".git", repo / "worktrees"):
        assert stat.S_IMODE(path.lstat().st_mode) & stat.S_IWUSR


def test_verify_and_reconcile_repair_excluded_control_path_drift(repo: Path, tmp_path: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    git_worktrees = repo / ".git" / "worktrees"
    git_worktrees.mkdir(exist_ok=True)
    for path in (git_worktrees, repo / "worktrees"):
        os.chmod(path, stat.S_IMODE(path.lstat().st_mode) & ~stat.S_IWUSR)

    degraded = canonical_lock.verify_lock_integrity(repo)

    assert degraded["verdict"] == canonical_lock.VERDICT_DEGRADED
    assert any(".git/worktrees" in issue for issue in degraded["control_path_issues"])
    assert any(issue.startswith("worktrees:") for issue in degraded["control_path_issues"])

    report = canonical_lock.reconcile(
        repos=[repo],
        claims_dir=_claims_dir(tmp_path, _lane_claim(repo)),
    )

    assert [action["action"] for action in report["actions"]] == ["relocked"]
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED
    assert not stat.S_IMODE((repo / "src" / "module.py").lstat().st_mode) & stat.S_IWUSR


# ------------------------------------------------------------------ reconcile


def test_reconcile_locks_a_repo_with_a_live_lane(repo: Path, tmp_path: Path) -> None:
    claims = _claims_dir(tmp_path, _lane_claim(repo))
    canonical_lock.reconcile(repos=[repo], claims_dir=claims)
    assert canonical_lock.is_locked(repo)


def test_reconcile_releases_a_stale_lock_left_by_a_dead_session(repo: Path, tmp_path: Path) -> None:
    """Requirement 4: a crash must not leave the machine wedged."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    assert canonical_lock.is_locked(repo)

    empty_registry = _claims_dir(tmp_path)  # the session died; its claim is gone
    report = canonical_lock.reconcile(repos=[repo], claims_dir=empty_registry)

    assert not canonical_lock.is_locked(repo)
    assert [a["action"] for a in report["actions"]] == ["unlocked"]
    (repo / "src" / "module.py").write_text("REPAIRED\n", encoding="utf-8")


def test_reconcile_keeps_the_lock_while_any_lane_is_still_live(repo: Path, tmp_path: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    claims = _claims_dir(tmp_path, _lane_claim(repo, scope="lane-b"))
    canonical_lock.reconcile(repos=[repo], claims_dir=claims)
    assert canonical_lock.is_locked(repo), "another live lane still justifies the lock"


def test_reconcile_ignores_an_expired_claim(repo: Path, tmp_path: Path) -> None:
    expired = _lane_claim(repo)
    expired["expires_at"] = "2000-01-01T00:00:00+00:00"
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    canonical_lock.reconcile(repos=[repo], claims_dir=_claims_dir(tmp_path, expired))
    assert not canonical_lock.is_locked(repo)


# ---------------------------------------------------------------- fail closed


def test_missing_registry_refuses_to_unlock(repo: Path, tmp_path: Path) -> None:
    """An empty read of a registry that is not there must never mean 'no lane'."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])

    with pytest.raises(canonical_lock.RegistryUnreadable):
        canonical_lock.reconcile(repos=[repo], claims_dir=tmp_path / "does-not-exist")

    assert canonical_lock.is_locked(repo), "the lock must survive an untrustworthy registry read"


def test_unparseable_claim_file_refuses_to_unlock(repo: Path, tmp_path: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    claims = _claims_dir(tmp_path)
    (claims / "broken.yaml").write_text("{{{ not: valid: yaml", encoding="utf-8")

    with pytest.raises(canonical_lock.RegistryUnreadable):
        canonical_lock.reconcile(repos=[repo], claims_dir=claims)

    assert canonical_lock.is_locked(repo)


def test_cli_reports_registry_failure_loudly(repo: Path, tmp_path: Path, monkeypatch, capsys) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    monkeypatch.setattr(canonical_lock, "CLAIMS_DIR", tmp_path / "gone")

    exit_code = canonical_lock.main(["--reconcile", "--repo", str(repo), "--json"])

    assert exit_code == 4, "a registry failure must not exit 0"
    output = capsys.readouterr().out
    assert "claim_registry_unreadable" in output
    assert "existing locks preserved" in output
    assert canonical_lock.is_locked(repo)


# ----------------------------------------------------------- claim resolution


def test_repo_root_is_derived_from_the_worktree_path_not_the_repo_root_field(repo: Path) -> None:
    """Live claims routinely carry ``repo_root: null`` or ``"."``; the lane path
    is the only field that reliably identifies the canonical checkout."""
    (repo / "worktrees").mkdir(exist_ok=True)
    resolved = canonical_lock.repo_root_for_worktree(str(repo / "worktrees" / "some-branch"))
    assert resolved == repo.resolve()


def test_non_lane_paths_resolve_to_nothing() -> None:
    assert canonical_lock.repo_root_for_worktree(None) is None
    assert canonical_lock.repo_root_for_worktree("/tmp/not/a/lane") is None


# ----------------------------------------------------------------------- hook


def test_hook_explains_a_denial_against_a_locked_repo(repo: Path, monkeypatch) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    monkeypatch.setattr(canonical_lock, "locked_repo_roots", lambda: [repo])

    result = canonical_lock.hook_main(
        {
            "hook_event_name": "PostToolUse",
            "tool_input": {"command": f"sed -i s/a/b/ {repo / 'src' / 'module.py'}"},
            "tool_response": {"stderr": "sed: Permission denied"},
        }
    )

    context = result["hookSpecificOutput"]["additionalContext"]
    assert "CANONICAL CHECKOUT IS READ-ONLY" in context
    assert "--reconcile" in context, "the escape hatch must be in the message, not in documentation"
    assert "worktrees/" in context


def test_hook_stays_silent_when_the_command_succeeded(repo: Path, monkeypatch) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    monkeypatch.setattr(canonical_lock, "locked_repo_roots", lambda: [repo])

    result = canonical_lock.hook_main(
        {
            "hook_event_name": "PostToolUse",
            "tool_input": {"command": f"cat {repo / 'src' / 'module.py'}"},
            "tool_response": {"stdout": "ORIGINAL"},
        }
    )
    assert result is None


def test_hook_stays_silent_for_an_unlocked_repo(repo: Path, monkeypatch) -> None:
    monkeypatch.setattr(canonical_lock, "locked_repo_roots", list)
    result = canonical_lock.hook_main(
        {"hook_event_name": "PreToolUse", "tool_input": {"file_path": str(repo / "src" / "module.py")}}
    )
    assert result is None


def test_hook_survives_malformed_input(capsys) -> None:
    import io

    assert canonical_lock.run_hook(io.StringIO("not json")) == 0
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ self-test


def test_self_test_arms_disagree(monkeypatch, tmp_path: Path) -> None:
    """The locked arm may report a verified boundary; the unlocked arm may not.

    A check that cannot fail proves nothing, so the unlocked arm exists to show
    the probe detects real writes.
    """
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")

    locked = canonical_lock.self_test(locked=True)
    unlocked = canonical_lock.self_test(locked=False)

    assert locked["boundary_verified"] is True
    assert locked["breached"] == []
    assert locked["clean_after_unlock"] is True

    assert unlocked["boundary_verified"] is False
    assert unlocked["verdict"] == "probe_is_sound"
    assert unlocked["blocked"] == [], "with no lock every route must land, or the probe is rigged"


def test_grade_refuses_to_pass_a_rigged_probe() -> None:
    """If the unlocked arm reported BLOCKED, the probe is measuring nothing."""
    verdict = canonical_lock.grade_self_test(
        locked=False,
        writes=[{"probe": "sed_in_place", "outcome": "BLOCKED"}],
        lanes=[],
    )
    assert verdict["verdict"] == "probe_is_rigged"
    assert verdict["boundary_verified"] is False


def test_self_test_cli_exit_codes(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")
    assert canonical_lock.main(["--self-test", "--json"]) == 0
    assert canonical_lock.main(["--self-test-unlocked", "--json"]) == 5
