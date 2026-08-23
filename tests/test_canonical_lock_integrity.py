"""Tests for canonical-lock integrity: a receipt is not a boundary.

Pinned to a failure mode that was observed on a live canonical checkout rather
than imagined. All 144 directories recorded in that repository's receipt had
drifted back to mode ``0755`` while every tracked file was still ``0444``.
Measured on that tree at the time:

- creating a new file SUCCEEDED (should have been blocked)
- hard-linking a tracked file SUCCEEDED, which is directory write access, so
  delete and rename were open too
- overwriting a tracked file in place was still correctly blocked

So the lock had silently decayed into exactly the file-only sieve the design
rejected, and ``--status`` still answered ``"locked": true`` because it only
checked that the receipt file existed. ``lock_repo`` itself was fine; nothing
ever re-measured the boundary afterwards.

Every case here therefore asserts against a *decayed* repository, and the
decayed cases prove the breach by actually writing rather than by reading mode
bits back -- a mode-bit assertion would pass against a tree that is, in fact,
wide open for some other reason.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "worktree-coordination" / "canonical_lock.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("canonical_lock_integrity_under_test", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["canonical_lock_integrity_under_test"] = module
    spec.loader.exec_module(module)
    return module


canonical_lock = _load_module()


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A real git repository. Permission behaviour cannot be mocked."""
    monkeypatch.setattr(canonical_lock, "LOCK_INDEX", tmp_path / "locks.json")
    root = tmp_path / "canonical"
    (root / "src" / "deep").mkdir(parents=True)
    (root / ".gitignore").write_text("worktrees/\n", encoding="utf-8")
    (root / "README.md").write_text("ORIGINAL\n", encoding="utf-8")
    (root / "src" / "module.py").write_text("ORIGINAL\n", encoding="utf-8")
    (root / "src" / "deep" / "nested.py").write_text("ORIGINAL\n", encoding="utf-8")
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


def _decay_directories(repo: Path) -> list[str]:
    """Reproduce the observed decay: recorded directories writable, files not.

    This is what the live checkout looked like. It deliberately leaves the file
    modes alone, because the surviving 0444 file bits are what made the decayed
    lock still *look* like it was working.
    """
    receipt = canonical_lock.read_receipt(repo)
    assert receipt is not None, "cannot decay a repository that was never locked"
    restored: list[str] = []
    # Shallowest first: a parent must be writable before a child can be chmod'd
    # through it on some filesystems, and the root must go first regardless.
    for rel in sorted(receipt.modes, key=lambda r: 0 if r == "." else len(Path(r).parts)):
        target = repo if rel == "." else repo / rel
        if target.is_dir():
            os.chmod(target, 0o755)
            restored.append(rel)
    assert restored, "fixture recorded no directories, so the decay proves nothing"
    return restored


def _can_create_file(repo: Path, name: str) -> bool:
    """Prove directory write access by using it, not by reading its mode."""
    target = repo / name
    subprocess.run(
        f"sh -c 'echo BREACH > {target}'",
        shell=True,
        capture_output=True,
        text=True,
        check=False,
    )
    created = target.exists()
    if created:
        try:
            target.unlink()
        except OSError:
            pass
    return created


def _claims_dir(tmp_path: Path, *records: dict) -> Path:
    directory = tmp_path / "claims"
    directory.mkdir(exist_ok=True)
    for index, record in enumerate(records):
        (directory / f"claim_{index}.yaml").write_text(yaml.safe_dump(record), encoding="utf-8")
    return directory


def _lane_claim(repo: Path, scope: str = "lane-a") -> dict:
    return {
        "agent": "claude-code",
        "scope": scope,
        "status": "active",
        "projects": [repo.name],
        "worktree_path": str(repo / "worktrees" / scope),
        "expires_at": "2099-01-01T00:00:00+00:00",
    }


# ------------------------------------------------------------------ verdicts


def test_unlocked_repo_reports_unlocked(repo: Path) -> None:
    report = canonical_lock.verify_lock_integrity(repo)
    assert report["verdict"] == canonical_lock.VERDICT_UNLOCKED
    assert report["receipt_present"] is False


def test_freshly_locked_repo_reports_locked(repo: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])

    report = canonical_lock.verify_lock_integrity(repo)

    assert report["verdict"] == canonical_lock.VERDICT_LOCKED
    assert report["writable_files"] == []
    assert report["writable_directories"] == []
    assert report["paths_checked"] == report["paths_recorded"] > 0
    # Positive control for the fixture: the boundary really is there.
    assert not _can_create_file(repo, "probe_fresh.txt")


def test_decayed_directories_report_degraded_and_the_breach_is_real(repo: Path) -> None:
    """The whole point. Mode bits say degraded AND a write actually lands."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED

    decayed = _decay_directories(repo)

    report = canonical_lock.verify_lock_integrity(repo)
    assert report["verdict"] == canonical_lock.VERDICT_DEGRADED
    assert sorted(report["writable_directories"]) == sorted(decayed)
    # The files never drifted, which is exactly why this decay stayed invisible.
    assert report["writable_files"] == []
    assert _can_create_file(repo, "probe_decayed.txt"), (
        "the decayed repository must actually accept a new file; if it does not, "
        "this test is measuring mode bits that mean nothing"
    )


def test_degraded_verdict_survives_a_single_writable_directory(repo: Path) -> None:
    """One drifted directory is a breach of that directory, not a rounding error."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    os.chmod(repo / "src" / "deep", 0o755)

    report = canonical_lock.verify_lock_integrity(repo)

    assert report["verdict"] == canonical_lock.VERDICT_DEGRADED
    assert report["writable_directories"] == ["src/deep"]
    assert _can_create_file(repo / "src" / "deep", "probe_one_dir.txt")


def test_drifted_file_is_reported_as_a_file_not_a_directory(repo: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    # The root must be writable to chmod nothing here -- chmod on the file only
    # needs ownership, so this works against the locked directory.
    os.chmod(repo / "README.md", 0o644)

    report = canonical_lock.verify_lock_integrity(repo)

    assert report["verdict"] == canonical_lock.VERDICT_DEGRADED
    assert report["writable_files"] == ["README.md"]
    assert report["writable_directories"] == []


def test_missing_recorded_path_is_reported_as_missing_not_drift(repo: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    # Unlock one directory just enough to delete a recorded file, then relock it,
    # simulating a path that vanished while the receipt still names it.
    os.chmod(repo / "src" / "deep", 0o755)
    (repo / "src" / "deep" / "nested.py").unlink()
    os.chmod(repo / "src" / "deep", 0o555)

    report = canonical_lock.verify_lock_integrity(repo)

    assert report["missing_paths"] == ["src/deep/nested.py"]
    assert "src/deep/nested.py" not in report["writable_files"]
    assert report["verdict"] == canonical_lock.VERDICT_LOCKED, (
        "a deleted path is not a writable path; grading it as drift would make "
        "every repair loop forever on something chmod cannot fix"
    )


# ----------------------------------------------------------------- --verify


def test_verify_cli_exits_zero_when_locked(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])

    code = canonical_lock.main(["--verify", str(repo)])

    assert code == 0
    assert f'"{canonical_lock.VERDICT_LOCKED}"' in capsys.readouterr().out


def test_verify_cli_exits_non_zero_when_degraded(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    _decay_directories(repo)

    code = canonical_lock.main(["--verify", str(repo)])

    assert code != 0
    assert f'"{canonical_lock.VERDICT_DEGRADED}"' in capsys.readouterr().out


def test_verify_repairs_nothing(repo: Path) -> None:
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    _decay_directories(repo)

    canonical_lock.main(["--verify", str(repo)])

    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_DEGRADED
    assert _can_create_file(repo, "probe_after_verify.txt"), "--verify must observe, not repair"


# ----------------------------------------------------------------- --status


def test_status_keeps_the_legacy_locked_boolean_and_adds_a_verdict(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Existing callers read ``locked``; it must keep meaning "receipt present"."""
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    _decay_directories(repo)

    canonical_lock.main(["--status", str(repo)])

    payload = json.loads(capsys.readouterr().out)
    assert payload["locked"] is True
    assert payload["integrity"] == canonical_lock.VERDICT_DEGRADED
    assert payload["writable_directories"]


# ---------------------------------------------------------------- reconcile


def test_reconcile_repairs_drift_and_the_boundary_actually_returns(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canonical_lock, "CLAIMS_DIR", _claims_dir(tmp_path, _lane_claim(repo)))
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    _decay_directories(repo)
    assert _can_create_file(repo, "probe_before_repair.txt"), "precondition: the breach is open"

    report = canonical_lock.reconcile(repos=[repo])

    relocks = [a for a in report["actions"] if a.get("action") == "relocked"]
    assert len(relocks) == 1, report
    assert relocks[0]["repo_root"] == str(repo.resolve())
    assert "drift" in relocks[0]["reason"]
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_LOCKED
    assert not _can_create_file(repo, "probe_after_repair.txt"), (
        "repair must restore the real boundary, not just the mode bits it reads back"
    )


def test_reconcile_dry_run_reports_drift_without_repairing_it(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canonical_lock, "CLAIMS_DIR", _claims_dir(tmp_path, _lane_claim(repo)))
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    _decay_directories(repo)

    report = canonical_lock.reconcile(repos=[repo], dry_run=True)

    assert [a["action"] for a in report["actions"]] == ["relock"]
    assert canonical_lock.verify_lock_integrity(repo)["verdict"] == canonical_lock.VERDICT_DEGRADED
    assert _can_create_file(repo, "probe_after_dry_run.txt"), "--dry-run must not touch the tree"


def test_reconcile_leaves_an_intact_lock_alone(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(canonical_lock, "CLAIMS_DIR", _claims_dir(tmp_path, _lane_claim(repo)))
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])

    report = canonical_lock.reconcile(repos=[repo])

    assert [a for a in report["actions"] if a.get("action") in ("relock", "relocked")] == []


def test_repair_preserves_the_receipts_recorded_original_modes(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The receipt is the only record of the pre-lock state.

    If a repair rewrote it, it would record the *degraded* modes as the
    originals and the eventual unlock would restore the wrong state -- the exact
    failure being repaired, made permanent.
    """
    monkeypatch.setattr(canonical_lock, "CLAIMS_DIR", _claims_dir(tmp_path, _lane_claim(repo)))
    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    receipt_file = canonical_lock.receipt_path(repo)
    before = receipt_file.read_bytes()

    _decay_directories(repo)
    canonical_lock.reconcile(repos=[repo])

    assert receipt_file.read_bytes() == before, "the repair rewrote the pre-lock mode record"


def test_unlock_after_a_repair_restores_the_original_modes(repo: Path) -> None:
    """End to end: decay, repair, unlock -- and the executable bit survives."""
    original = stat.S_IMODE((repo / "run.sh").lstat().st_mode)
    assert original & stat.S_IXUSR, "fixture must carry a non-default mode to be worth checking"

    canonical_lock.lock_repo(repo, justifying_claims=["lane-a"])
    _decay_directories(repo)
    canonical_lock.relock_repo(repo)
    canonical_lock.unlock_repo(repo)

    assert stat.S_IMODE((repo / "run.sh").lstat().st_mode) == original
    assert _can_create_file(repo, "probe_after_unlock.txt")


def test_relock_on_an_unlocked_repo_is_a_no_op(repo: Path) -> None:
    result = canonical_lock.relock_repo(repo)
    assert result["action"] == "not_locked"
    assert result["ok"] is False
