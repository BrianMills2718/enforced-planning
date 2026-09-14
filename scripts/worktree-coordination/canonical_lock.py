#!/usr/bin/env python3
"""Make a canonical checkout physically read-only while a lane claim is live.

Why this exists
---------------
Implementation must happen in a linked worktree at ``<repo>/worktrees/<branch>/``
and never in the canonical checkout, because two sessions writing one checkout
silently destroy each other's edits. That has already happened here.

The enforcement that was supposed to prevent it does not cover the route agents
actually use. Every write-governing Claude Code hook in this estate is wired to
the ``Edit|Write`` tool names and none to ``Bash``, while the harness under
bypass-permissions mode instructs agents to edit with ``sed``, heredocs, and
short scripts. Those never reach an ``Edit|Write`` gate.

``run_confined_lane.py`` solved that for one process by launching it in a mount
namespace. It is route-independent but *launch-path*-dependent: it protects only
what someone remembered to start through it. Under the workspace rule that a
command is not a control, that makes it undeployed.

This module moves the boundary from the process to the resource. The canonical
working tree's own permission bits are the control, so it holds against every
writer, every tool, and every runtime -- Claude Code, Codex, a cron job, a stray
``sed -i`` typed into a terminal -- with no launch path to remember.

What is locked, and why that exact set
--------------------------------------
Established by execution (see ``--self-test``), not by inspection. Making only
the *files* read-only is a sieve: mode ``444`` blocks ``>``, ``tee``, and
``open(path, "w")``, but ``sed -i``, ``mv -f``, ``cp -f``, and ``rm && recreate``
all still land, because those write a new inode and rename over the old one,
which needs write permission on the *directory* and not on the file.

``sed -i`` is precisely the route the audit found agents using, so file-only
locking would have blocked nothing that mattered.

The lock is therefore:

``git ls-files``
    every tracked file -> ``a-w``
every directory containing a tracked file, plus the repository root
    -> ``a-w``, which is what actually blocks create, delete, and rename

Deliberately excluded:

``.git/``
    Stays writable. The lane's ``git commit``, ref updates, reflogs, and object
    writes all go here, and ``git worktree add`` writes ``.git/worktrees/``.
``<repo>/worktrees/``
    Stays writable, and is created if absent before locking. Lanes live inside
    the canonical directory, so locking the repository root would otherwise
    prevent creating the next lane. Locking the root does not restrict writes
    *inside* ``worktrees/``: a directory's mode governs only its own entries.
ignored and untracked paths
    ``.venv/``, ``node_modules/``, and similar keep their own modes. They sit
    under a locked parent, so new top-level entries cannot appear while a lane
    is live, but their interiors are untouched.

Consequences accepted, having been observed rather than assumed:

- ``git status``, ``git log``, and every read in the canonical checkout work.
- ``git checkout``, ``git pull``, and ``git merge`` in the canonical checkout
  fail while a lane is live. That is the collision this exists to prevent, and
  the lane-close path unlocks before ``finish_pr.py`` runs its canonical
  ``git pull --rebase``.
- Python imports from a locked tree still work; CPython silently skips writing
  ``__pycache__`` into a read-only directory.

Failing closed
--------------
``reconcile`` will lock on ambiguity and refuses to unlock on ambiguity. If the
claim registry is missing, or any claim file in it is unparseable, an existing
lock is *kept* and the command exits non-zero. An empty read of a registry that
cannot be trusted must never be read as "no lane is live".

Locks decay, so the receipt is not the boundary
-----------------------------------------------
A receipt on disk records that a lock was *applied*; it is not evidence that the
boundary still *holds*. Observed on a live canonical checkout: all 144 recorded
directories had drifted back to mode ``0755`` while every tracked file was still
``0444``. Creating a new file succeeded and hard-linking a tracked file
succeeded -- which is directory write access, so delete and rename were open too
-- while overwriting a tracked file in place was still correctly blocked. The
lock had decayed to the file-only sieve the design explicitly rejected, and
``--status`` still reported ``"locked": true`` because it only checked that the
receipt file existed.

``verify_lock_integrity`` closes that gap by comparing every path the receipt
recorded against its current mode, so a lock that reports healthy has actually
been measured. The verdict is three-valued: ``unlocked`` (no receipt),
``locked`` (receipt, no recorded path writable), ``degraded`` (receipt, some
recorded path writable again). ``--verify`` reports and exits non-zero on
``degraded`` without repairing anything; ``--reconcile`` repairs by re-applying
the chmod, never rewriting the receipt -- the receipt is the only record of the
pre-lock modes, so overwriting it during a repair would record the *degraded*
modes as the originals and make the eventual unlock restore the wrong state.

Recovering from a stale lock
----------------------------
A session that dies without closing leaves the checkout read-only. That is
repaired by ``reconcile``, which compares live lane claims against recorded
locks and releases any lock no live claim justifies. It is wired to session
start, so the repair is triggered by the same event as the next attempt to use
the repository: whoever is inconvenienced by the stale lock is, by construction,
starting a session, and that session clears it before their first tool call.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

RECEIPT_NAME = "canonical-lock-v1.json"
LOCK_INDEX = Path.home() / ".claude" / "coordination" / "canonical-locks-v1.json"
CLAIMS_DIR = Path.home() / ".claude" / "coordination" / "claims"
SCHEMA_VERSION = 1

# Directory names never locked, and never descended into when collecting modes.
EXCLUDED_TOP_LEVEL = ("worktrees",)

# Every write bit. Clearing all three is what "locked" means for one path.
WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH

# Three-valued integrity verdict. ``locked`` is measured, not merely recorded.
VERDICT_LOCKED = "locked"
VERDICT_DEGRADED = "degraded"
VERDICT_UNLOCKED = "unlocked"

# Exit code for ``--verify`` when the boundary has decayed. Distinct from 4
# (registry unreadable) and 5 (unlocked self-test arm).
EXIT_DEGRADED = 6


class RegistryUnreadable(RuntimeError):
    """The claim registry could not be trusted, so no unlock decision is safe."""


# --------------------------------------------------------------------------
# receipts
# --------------------------------------------------------------------------


@dataclass
class LockReceipt:
    """Durable record of one canonical lock, stored inside the repo's .git."""

    schema_version: int
    repo_root: str
    locked_at: str
    locked_by_session: str | None
    justifying_claims: list[str]
    modes: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "LockReceipt":
        data = json.loads(text)
        return cls(
            schema_version=int(data["schema_version"]),
            repo_root=str(data["repo_root"]),
            locked_at=str(data["locked_at"]),
            locked_by_session=data.get("locked_by_session"),
            justifying_claims=list(data.get("justifying_claims") or []),
            modes={str(k): int(v) for k, v in (data.get("modes") or {}).items()},
        )


def receipt_path(repo_root: Path) -> Path:
    """Return the receipt location, which lives in .git and is never locked."""
    git_dir = repo_root / ".git"
    if git_dir.is_file():  # repo_root is itself a linked worktree
        raise ValueError(f"{repo_root} is a linked worktree, not a canonical checkout")
    return git_dir / RECEIPT_NAME


def read_receipt(repo_root: Path) -> LockReceipt | None:
    path = receipt_path(repo_root)
    if not path.exists():
        return None
    return LockReceipt.from_json(path.read_text(encoding="utf-8"))


def refresh_lock_justifications(
    repo_root: Path,
    *,
    justifying_claims: list[str],
    session_id: str | None = None,
) -> dict[str, Any]:
    """Atomically refresh claim metadata without changing recorded modes."""

    repo_root = repo_root.resolve()
    receipt = read_receipt(repo_root)
    if receipt is None:
        return {"ok": False, "action": "not_locked", "repo_root": str(repo_root)}
    scopes = sorted(set(justifying_claims))
    if receipt.justifying_claims == scopes:
        return {
            "ok": True,
            "action": "justifications_current",
            "repo_root": str(repo_root),
            "justifying_claims": scopes,
        }
    receipt.justifying_claims = scopes
    receipt.locked_by_session = session_id
    target = receipt_path(repo_root)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{RECEIPT_NAME}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(receipt.to_json())
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "ok": True,
        "action": "justifications_refreshed",
        "repo_root": str(repo_root),
        "justifying_claims": scopes,
    }


def is_locked(repo_root: Path) -> bool:
    try:
        return read_receipt(repo_root) is not None
    except (ValueError, OSError, json.JSONDecodeError):
        return False


# --------------------------------------------------------------------------
# path selection
# --------------------------------------------------------------------------


def _git(repo_root: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo_root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def tracked_files(repo_root: Path) -> list[Path]:
    """Return tracked files, excluding anything under an excluded top-level dir."""
    result = _git(repo_root, ["ls-files", "-z"])
    if result.returncode != 0:
        raise RuntimeError(f"git ls-files failed in {repo_root}: {result.stderr.strip()}")
    files: list[Path] = []
    for rel in result.stdout.split("\0"):
        if not rel:
            continue
        parts = Path(rel).parts
        if parts and parts[0] in EXCLUDED_TOP_LEVEL:
            continue
        candidate = repo_root / rel
        if candidate.is_symlink() or not candidate.is_file():
            continue
        files.append(candidate)
    return files


def lockable_paths(repo_root: Path) -> tuple[list[Path], list[Path]]:
    """Return (files, directories) to lock.

    Directories are the load-bearing half: they are what blocks ``sed -i``,
    ``mv``, ``cp``, and delete-then-recreate.
    """
    files = tracked_files(repo_root)
    directories: set[Path] = {repo_root}
    for path in files:
        parent = path.parent
        while parent != repo_root and repo_root in parent.parents:
            directories.add(parent)
            parent = parent.parent
        if parent == repo_root:
            directories.add(repo_root)
    ordered_dirs = sorted(directories, key=lambda p: len(p.parts), reverse=True)
    return files, ordered_dirs


# --------------------------------------------------------------------------
# lock / unlock
# --------------------------------------------------------------------------


def _ensure_worktrees_dir(repo_root: Path) -> None:
    """Guarantee ``worktrees/`` exists before the root becomes read-only.

    Without this, locking a repository that has never hosted a lane makes the
    next ``git worktree add`` fail at mkdir, because creating ``worktrees/``
    requires write permission on the now read-only repository root.
    """
    worktrees = repo_root / "worktrees"
    if not worktrees.exists():
        worktrees.mkdir(parents=True, exist_ok=True)


def _control_paths(repo_root: Path) -> tuple[Path, ...]:
    """Return excluded control paths that must stay user-writable.

    Git object files are intentionally omitted: immutable loose/packed objects
    are commonly read-only.  Everything else under ``.git`` is mutable Git
    administration, while only the top-level ``worktrees/`` container is ours
    to repair; linked worktree contents remain owned by their lane.
    """

    git_dir = repo_root / ".git"
    paths: list[Path] = []
    if git_dir.is_dir():
        for current, dirnames, filenames in os.walk(git_dir):
            current_path = Path(current)
            if current_path == git_dir:
                dirnames[:] = [name for name in dirnames if name != "objects"]
            paths.append(current_path)
            paths.extend(current_path / name for name in dirnames)
            paths.extend(current_path / name for name in filenames)
    paths.append(repo_root / "worktrees")
    return tuple(dict.fromkeys(paths))


def _control_path_issues(repo_root: Path) -> list[str]:
    """Report excluded control paths that cannot support sanctioned Git work."""

    issues: list[str] = []
    for path in _control_paths(repo_root):
        relative = str(path.relative_to(repo_root))
        try:
            info = path.lstat()
        except FileNotFoundError:
            # Git creates and removes transient administration files (for
            # example index.lock) while another sanctioned process runs. A
            # path disappearing after enumeration is already reconciled.
            continue
        except OSError:
            issues.append(f"{relative}: missing or unreadable")
            continue
        if path.is_symlink():
            continue
        if not stat.S_IMODE(info.st_mode) & stat.S_IWUSR:
            issues.append(f"{relative}: not user-writable")
    return issues


def _restore_control_path_write_access(repo_root: Path) -> dict[str, Any]:
    """Repair only excluded control paths, never canonical or lane contents."""

    _ensure_worktrees_dir(repo_root)
    restored: list[str] = []
    failures: list[str] = []
    for path in _control_paths(repo_root):
        relative = str(path.relative_to(repo_root))
        try:
            if path.is_symlink():
                continue
            mode = stat.S_IMODE(path.lstat().st_mode)
            if not mode & stat.S_IWUSR:
                os.chmod(path, mode | stat.S_IWUSR)
                restored.append(relative)
        except FileNotFoundError:
            # A transient Git administration entry can disappear between
            # _control_paths() and this repair. There is nothing left to make
            # writable, so this is success rather than a durable failure.
            continue
        except OSError as exc:
            failures.append(f"{relative}: {exc}")
    return {"restored": restored, "failures": failures}


def lock_repo(
    repo_root: Path,
    *,
    justifying_claims: list[str] | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Make the canonical working tree read-only. Idempotent."""
    repo_root = repo_root.resolve()
    control_repair = _restore_control_path_write_access(repo_root)
    if control_repair["failures"]:
        raise OSError("control-path repair failed: " + "; ".join(control_repair["failures"]))
    existing = read_receipt(repo_root)
    if existing is not None:
        return {
            "ok": True,
            "action": "already_locked",
            "repo_root": str(repo_root),
            "locked_at": existing.locked_at,
            "justifying_claims": existing.justifying_claims,
        }

    _ensure_worktrees_dir(repo_root)
    files, directories = lockable_paths(repo_root)

    modes: dict[str, int] = {}
    for path in files:
        modes[str(path.relative_to(repo_root))] = stat.S_IMODE(path.lstat().st_mode)
    for path in directories:
        rel = "." if path == repo_root else str(path.relative_to(repo_root))
        modes[rel] = stat.S_IMODE(path.lstat().st_mode)

    receipt = LockReceipt(
        schema_version=SCHEMA_VERSION,
        repo_root=str(repo_root),
        locked_at=datetime.now(timezone.utc).isoformat(),
        locked_by_session=session_id,
        justifying_claims=sorted(justifying_claims or []),
        modes=modes,
    )
    # Write the receipt BEFORE chmod. A crash between the two leaves a receipt
    # with nothing locked, which reconcile repairs harmlessly. The reverse order
    # would leave a locked tree with no record of the original modes.
    receipt_path(repo_root).write_text(receipt.to_json(), encoding="utf-8")

    for path in files:
        os.chmod(path, stat.S_IMODE(path.lstat().st_mode) & ~WRITE_BITS)
    # Deepest first, so each directory is still writable while its children are
    # being changed.
    for path in directories:
        os.chmod(path, stat.S_IMODE(path.lstat().st_mode) & ~WRITE_BITS)

    _index_record(repo_root, locked=True)
    return {
        "ok": True,
        "action": "locked",
        "repo_root": str(repo_root),
        "files_locked": len(files),
        "directories_locked": len(directories),
        "justifying_claims": receipt.justifying_claims,
    }


def unlock_repo(repo_root: Path) -> dict[str, Any]:
    """Restore recorded modes and drop the receipt. Idempotent."""
    repo_root = repo_root.resolve()
    control_repair = _restore_control_path_write_access(repo_root)
    if control_repair["failures"]:
        raise OSError("control-path repair failed: " + "; ".join(control_repair["failures"]))
    receipt = read_receipt(repo_root)
    if receipt is None:
        return {
            "ok": True,
            "action": "not_locked",
            "repo_root": str(repo_root),
            "control_paths_restored": control_repair["restored"],
        }

    restored = 0
    fallback = 0
    # Shallowest first: a directory must be writable before its children can be
    # changed, which is the exact reverse of the locking order.
    for rel in sorted(receipt.modes, key=lambda r: len(Path(r).parts)):
        target = repo_root if rel == "." else repo_root / rel
        if not target.exists() or target.is_symlink():
            continue
        try:
            os.chmod(target, receipt.modes[rel])
            restored += 1
        except OSError:
            fallback += 1

    # Anything the receipt did not cover, or failed to restore, gets user-write
    # back so a partial receipt can never leave the tree wedged.
    for current, dirnames, filenames in os.walk(repo_root):
        current_path = Path(current)
        if current_path == repo_root:
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_TOP_LEVEL and d != ".git"]
        for name in [*dirnames, *filenames]:
            target = current_path / name
            if target.is_symlink():
                continue
            try:
                mode = stat.S_IMODE(target.lstat().st_mode)
                if not mode & stat.S_IWUSR:
                    os.chmod(target, mode | stat.S_IWUSR)
            except OSError:
                continue
    root_mode = stat.S_IMODE(repo_root.lstat().st_mode)
    if not root_mode & stat.S_IWUSR:
        os.chmod(repo_root, root_mode | stat.S_IWUSR)

    receipt_path(repo_root).unlink(missing_ok=True)
    _index_record(repo_root, locked=False)
    return {
        "ok": True,
        "action": "unlocked",
        "repo_root": str(repo_root),
        "modes_restored": restored,
        "modes_fallback": fallback,
        "control_paths_restored": control_repair["restored"],
    }


# --------------------------------------------------------------------------
# lock integrity
# --------------------------------------------------------------------------


def _expected_locked_mode(recorded_mode: int) -> int:
    """The mode ``lock_repo`` would have produced for a path recorded as this."""
    return recorded_mode & ~WRITE_BITS


def _receipt_paths_deepest_first(receipt: LockReceipt) -> list[str]:
    """Recorded relative paths, deepest first with the repository root last."""
    return sorted(receipt.modes, key=lambda rel: 0 if rel == "." else len(Path(rel).parts), reverse=True)


def verify_lock_integrity(repo_root: Path) -> dict[str, Any]:
    """Measure whether a recorded lock still holds, path by path.

    A receipt proves a lock was applied. It does not prove the boundary is still
    there: modes can be restored afterwards by a restore, an installer, a
    ``chmod -R``, or a checkout, and the receipt is unchanged by any of them.
    This reads the current mode of every recorded path and reports the ones that
    have write access again, separating files from directories because they fail
    differently -- a writable directory permits create, delete, and rename even
    while every file in it is still ``444``.

    Recorded paths that no longer exist are not drift. They are reported under
    ``missing_paths`` so a deleted-while-locked path is visible without being
    graded as a breach.
    """
    repo_root = repo_root.resolve()
    receipt = read_receipt(repo_root)
    if receipt is None:
        control_path_issues = _control_path_issues(repo_root)
        return {
            "repo_root": str(repo_root),
            "verdict": VERDICT_UNLOCKED,
            "receipt_present": False,
            "paths_recorded": 0,
            "paths_checked": 0,
            "writable_files": [],
            "writable_directories": [],
            "missing_paths": [],
            "control_path_issues": control_path_issues,
        }

    writable_files: list[str] = []
    writable_directories: list[str] = []
    missing: list[str] = []
    checked = 0

    for rel in sorted(receipt.modes):
        target = repo_root if rel == "." else repo_root / rel
        try:
            info = target.lstat()
        except OSError:
            missing.append(rel)
            continue
        if stat.S_ISLNK(info.st_mode):
            # Never locked in the first place; its mode says nothing about the
            # boundary. lock_repo filters symlinks out before recording.
            continue
        checked += 1
        if stat.S_IMODE(info.st_mode) & WRITE_BITS:
            if stat.S_ISDIR(info.st_mode):
                writable_directories.append(rel)
            else:
                writable_files.append(rel)

    control_path_issues = _control_path_issues(repo_root)
    drifted = bool(writable_files or writable_directories or control_path_issues)
    return {
        "repo_root": str(repo_root),
        "verdict": VERDICT_DEGRADED if drifted else VERDICT_LOCKED,
        "receipt_present": True,
        "locked_at": receipt.locked_at,
        "justifying_claims": receipt.justifying_claims,
        "paths_recorded": len(receipt.modes),
        "paths_checked": checked,
        "writable_file_count": len(writable_files),
        "writable_directory_count": len(writable_directories),
        "writable_files": writable_files,
        "writable_directories": writable_directories,
        "missing_paths": missing,
        "control_path_issues": control_path_issues,
    }


def relock_repo(repo_root: Path) -> dict[str, Any]:
    """Re-apply the lock's chmod to paths that drifted writable.

    The receipt is deliberately left untouched. It is the only record of the
    pre-lock modes, so rewriting it here would capture the *degraded* modes as
    the originals and make the eventual ``unlock_repo`` restore the wrong state
    -- the failure this repair exists to fix, made permanent.
    """
    repo_root = repo_root.resolve()
    receipt = read_receipt(repo_root)
    if receipt is None:
        return {"ok": False, "action": "not_locked", "repo_root": str(repo_root)}

    integrity = verify_lock_integrity(repo_root)
    drifted = set(integrity["writable_files"]) | set(integrity["writable_directories"])
    control_path_issues = list(integrity["control_path_issues"])
    if not drifted and not control_path_issues:
        return {
            "ok": True,
            "action": "already_intact",
            "repo_root": str(repo_root),
            "verdict": integrity["verdict"],
        }

    files_relocked = 0
    directories_relocked = 0
    failures: list[str] = []
    control_repair = _restore_control_path_write_access(repo_root)
    failures.extend(control_repair["failures"])
    # Deepest first with the root last, matching lock_repo: a directory stays
    # writable while its own children are being changed.
    for rel in _receipt_paths_deepest_first(receipt):
        if rel not in drifted:
            continue
        target = repo_root if rel == "." else repo_root / rel
        try:
            is_dir = target.is_dir()
            os.chmod(target, _expected_locked_mode(receipt.modes[rel]))
        except OSError as exc:
            failures.append(f"{rel}: {exc}")
            continue
        if is_dir:
            directories_relocked += 1
        else:
            files_relocked += 1

    after = verify_lock_integrity(repo_root)
    return {
        "ok": after["verdict"] == VERDICT_LOCKED,
        "action": "relocked",
        "repo_root": str(repo_root),
        "files_relocked": files_relocked,
        "directories_relocked": directories_relocked,
        "control_paths_restored": control_repair["restored"],
        "chmod_failures": failures,
        "verdict": after["verdict"],
    }


# --------------------------------------------------------------------------
# lock index
# --------------------------------------------------------------------------


def _read_index() -> list[str]:
    if not LOCK_INDEX.exists():
        return []
    try:
        data = json.loads(LOCK_INDEX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [str(entry) for entry in (data.get("locked_repos") or [])]


def _index_record(repo_root: Path, *, locked: bool) -> None:
    """Track which repositories hold a lock, so stale ones can be found.

    This is a convenience index, not the authority. The per-repository receipt
    under ``.git`` is authoritative; losing this file costs discovery, not
    correctness.
    """
    entries = set(_read_index())
    if locked:
        entries.add(str(repo_root))
    else:
        entries.discard(str(repo_root))
    try:
        LOCK_INDEX.parent.mkdir(parents=True, exist_ok=True)
        LOCK_INDEX.write_text(
            json.dumps({"schema_version": SCHEMA_VERSION, "locked_repos": sorted(entries)}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


# --------------------------------------------------------------------------
# claim reading (fails closed)
# --------------------------------------------------------------------------

LIVE_STATUSES = {"active", "in_progress", "paused", "blocked"}


def load_live_lane_claims(claims_dir: Path | None = None) -> list[dict[str, Any]]:
    """Return live claims, or raise if the registry cannot be trusted.

    ``_load_claims`` in ``coordination_claims`` silently skips a claim file it
    cannot parse and returns ``[]`` for a missing directory. Both read as "no
    lane is live", which would unlock a repository that is in fact claimed. This
    reader raises instead.
    """
    resolved = claims_dir or CLAIMS_DIR
    if not resolved.exists():
        raise RegistryUnreadable(f"claim registry directory does not exist: {resolved}")

    claims: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for claim_file in sorted(resolved.glob("*.yaml")):
        try:
            data = yaml.safe_load(claim_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - the reason is reported, not swallowed
            raise RegistryUnreadable(f"unparseable claim file {claim_file}: {exc}") from exc
        if not isinstance(data, dict):
            raise RegistryUnreadable(f"claim file is not a mapping: {claim_file}")
        if str(data.get("status") or "") not in LIVE_STATUSES:
            continue
        expires = data.get("expires_at")
        if expires:
            try:
                if datetime.fromisoformat(str(expires)) < now:
                    continue
            except ValueError as exc:
                raise RegistryUnreadable(f"unparseable expires_at in {claim_file}: {exc}") from exc
        claims.append(data)
    return claims


def repo_root_for_worktree(worktree_path: str | None) -> Path | None:
    """Derive the canonical repository root from a claimed lane path.

    Purely path-shaped: ``<repo>/worktrees/<branch>`` -> ``<repo>``. This does
    not depend on the claim's ``repo_root`` field, which is routinely ``null``
    or ``"."`` in live records.
    """
    if not worktree_path:
        return None
    path = Path(worktree_path)
    for parent in path.parents:
        if parent.name == "worktrees":
            repo = parent.parent
            if (repo / ".git").is_dir():
                return repo.resolve()
            return None
    return None


def live_lanes_by_repo(claims_dir: Path | None = None) -> dict[Path, list[str]]:
    """Map canonical repository root -> scopes of live lane claims against it."""
    lanes: dict[Path, list[str]] = {}
    for claim in load_live_lane_claims(claims_dir):
        repo = repo_root_for_worktree(claim.get("worktree_path"))
        if repo is None:
            continue
        lanes.setdefault(repo, []).append(str(claim.get("scope") or "?"))
    return lanes


# --------------------------------------------------------------------------
# reconcile
# --------------------------------------------------------------------------


def reconcile(
    *,
    repos: list[Path] | None = None,
    claims_dir: Path | None = None,
    dry_run: bool = False,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Bring lock state into agreement with live lane claims.

    Locks a repository that has a live lane and no lock; unlocks one that holds
    a lock no live lane justifies; re-applies the chmod on a repository whose
    lock is still justified but has decayed writable. Raises
    ``RegistryUnreadable`` rather than unlocking on a registry it cannot trust.
    """
    lanes = live_lanes_by_repo(claims_dir)

    candidates: set[Path] = set(lanes)
    for recorded in _read_index():
        path = Path(recorded)
        if (path / ".git").is_dir():
            candidates.add(path.resolve())
    for extra in repos or []:
        resolved = extra.resolve()
        if (resolved / ".git").is_dir():
            candidates.add(resolved)

    actions: list[dict[str, Any]] = []
    for repo in sorted(candidates):
        scopes = lanes.get(repo, [])
        locked = is_locked(repo)
        if scopes and not locked:
            actions.append(
                {"repo_root": str(repo), "action": "lock", "reason": f"live lane claim(s): {', '.join(sorted(scopes))}"}
                if dry_run
                else {**lock_repo(repo, justifying_claims=scopes, session_id=session_id), "reason": "live lane claim"}
            )
        elif not scopes and locked:
            actions.append(
                {"repo_root": str(repo), "action": "unlock", "reason": "no live lane claim (stale lock)"}
                if dry_run
                else {**unlock_repo(repo), "reason": "no live lane claim (stale lock)"}
            )
        elif scopes and locked:
            receipt = read_receipt(repo)
            if receipt is not None and receipt.justifying_claims != sorted(set(scopes)):
                actions.append(
                    {**refresh_lock_justifications(
                        repo,
                        justifying_claims=scopes,
                        session_id=session_id,
                    ), "reason": "live lane claim set changed"}
                )
            # The lock is still justified, but a receipt is not a boundary: the
            # modes it applied can be undone afterwards without touching it.
            try:
                integrity = verify_lock_integrity(repo)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                actions.append(
                    {
                        "repo_root": str(repo),
                        "action": "integrity_unknown",
                        "reason": f"could not verify lock integrity: {exc}",
                    }
                )
                continue
            if integrity["verdict"] != VERDICT_DEGRADED:
                continue
            reason = (
                "lock drifted writable: "
                f"{integrity['writable_file_count']} file(s), "
                f"{integrity['writable_directory_count']} director(ies)"
            )
            actions.append(
                {
                    "repo_root": str(repo),
                    "action": "relock",
                    "reason": reason,
                    "writable_file_count": integrity["writable_file_count"],
                    "writable_directory_count": integrity["writable_directory_count"],
                }
                if dry_run
                else {**relock_repo(repo), "reason": reason}
            )
    return {"ok": True, "dry_run": dry_run, "repos_considered": len(candidates), "actions": actions}


# --------------------------------------------------------------------------
# recovery message
# --------------------------------------------------------------------------


RESIDUE_RECEIPT_DIR = Path.home() / ".local" / "state" / "canonical-residue"


def _blob_at(repo_root: Path, ref: str, path: str) -> str | None:
    done = _git(repo_root, ["rev-parse", "--verify", "--quiet", f"{ref}:{path}"])
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def _worktree_blob(repo_root: Path, path: str) -> str | None:
    target = repo_root / path
    if not target.is_file() or target.is_symlink():
        return None
    done = _git(repo_root, ["hash-object", "--", path])
    return done.stdout.strip() if done.returncode == 0 else None


def _index_blob(repo_root: Path, path: str) -> str | None:
    done = _git(repo_root, ["ls-files", "-s", "--", path])
    fields = done.stdout.split()
    return fields[1] if done.returncode == 0 and len(fields) >= 2 else None


ANCESTOR_HISTORY_LIMIT = 200


def _committed_ancestor(repo_root: Path, path: str, blob: str | None) -> str | None:
    """Return a commit reachable from HEAD whose version of ``path`` is ``blob``.

    Content already committed to this branch's history is recoverable from the
    object store by definition, so discarding an uncommitted copy of it loses
    nothing. Bounded to the most recent ANCESTOR_HISTORY_LIMIT commits touching
    the path so a pathological history cannot stall a freshness sweep.
    """
    if not blob:
        return None
    done = _git(repo_root, ["log", f"-n{ANCESTOR_HISTORY_LIMIT}", "--format=commit %H", "--raw",
                            "--no-abbrev", "--no-renames", "HEAD", "--", path])
    if done.returncode != 0:
        return None
    commit = None
    for line in done.stdout.splitlines():
        if line.startswith("commit "):
            commit = line.split()[1]
        elif line.startswith(":") and commit:
            fields = line.split("\t", 1)[0].split()
            if len(fields) >= 4 and fields[3] == blob:  # blob this commit wrote
                return commit
    return None


def classify_dirty_entries(repo_root: Path, upstream: str) -> dict[str, Any]:
    """Split working-tree changes into upstream residue, benign untracked, and real work.

    Why this exists: a session edits a canonical checkout, the pre-commit guard
    refuses the commit, the session moves the same change to a worktree and
    merges it, and the canonical copy is left behind byte-identical to what
    ``origin`` now holds. Every automatic freshness path then treats that
    leftover as unrelated work and refuses to advance, forever: on 2026-09-14
    three such files kept project-meta 69 commits behind while a feedback
    runtime ran stale code all night. Content already in ``upstream`` is not
    local work; discarding the local copy loses nothing.

    Conservative by construction. An entry is residue only when its working
    file hashes to exactly the upstream blob (or is absent where upstream has
    no such path) and its index entry is HEAD's or upstream's blob. Renames,
    copies, conflicts, symlinks, and anything unreadable are real work.
    Untracked files upstream does not contain cannot block a fast-forward and
    are reported separately, never touched.
    """
    status = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain=v1", "-z", "--untracked-files=all"],
        capture_output=True,
        check=False,
    )
    result: dict[str, Any] = {"residue": [], "benign_untracked": [], "real": [], "error": None}
    if status.returncode != 0:
        result["error"] = status.stderr.decode(errors="replace").strip() or "git status failed"
        return result
    fields = status.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    index = 0
    while index < len(fields):
        entry = fields[index]
        index += 1
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if "R" in code or "C" in code:
            index += 1  # skip the rename/copy source path
            result["real"].append({"path": path, "code": code, "why": "rename or copy"})
            continue
        if "U" in code or code in {"AA", "DD"}:
            result["real"].append({"path": path, "code": code, "why": "unmerged"})
            continue
        upstream_blob = _blob_at(repo_root, upstream, path)
        worktree_blob = _worktree_blob(repo_root, path)
        worktree_exists = (repo_root / path).exists() or (repo_root / path).is_symlink()
        if code == "??":
            if upstream_blob is None:
                result["benign_untracked"].append(path)
            elif worktree_blob is not None and worktree_blob == upstream_blob:
                result["residue"].append({"path": path, "code": code, "blob": upstream_blob})
            else:
                result["real"].append({"path": path, "code": code, "why": "untracked path differs from upstream"})
            continue
        if worktree_exists:
            content_matches = worktree_blob is not None and worktree_blob == upstream_blob
        else:
            content_matches = upstream_blob is None
        index_blob = _index_blob(repo_root, path)
        head_blob = _blob_at(repo_root, "HEAD", path)
        index_matches = index_blob in {head_blob, upstream_blob}
        if content_matches and index_matches:
            result["residue"].append({"path": path, "code": code, "blob": upstream_blob})
        elif content_matches and index_blob is not None:
            # The working file already equals upstream; the index holds an
            # earlier staged draft the same writer later superseded (observed
            # on the 2026-09-14 project-meta incident: `MM` on a policy JSON).
            # Residue, but the draft blob is copied out before anything moves.
            result["residue"].append(
                {"path": path, "code": code, "blob": upstream_blob, "preserve_index_blob": index_blob}
            )
        elif (
            worktree_blob is not None
            and index_blob in {worktree_blob, head_blob}
            and (ancestor := _committed_ancestor(repo_root, path, worktree_blob)) is not None
            and worktree_blob != head_blob
        ):
            # The uncommitted copy is byte-identical to an older committed
            # version of the same file: a stale revert, not new work. Observed
            # 2026-09-14 in ~/projects/.claude: CLAUDE.md staged and on disk as
            # the parent commit's version, silently undoing merged PR #37 and
            # holding the shared instructions 3 commits behind.
            result["residue"].append(
                {"path": path, "code": code, "blob": upstream_blob, "ancestor_blob": worktree_blob,
                 "ancestor_commit": ancestor}
            )
        else:
            result["real"].append({"path": path, "code": code, "why": "content differs from upstream"})
    return result


def _upstream_of(repo_root: Path) -> str | None:
    done = _git(repo_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
    return done.stdout.strip() if done.returncode == 0 and done.stdout.strip() else None


def _restore_residue(repo_root: Path, residue: list[dict[str, Any]]) -> None:
    """Return residue paths to HEAD so a fast-forward can bring upstream's identical copy."""
    tracked = [item["path"] for item in residue if item["code"] != "??" and _blob_at(repo_root, "HEAD", item["path"])]
    if tracked:
        done = _git(repo_root, ["restore", "--source=HEAD", "--staged", "--worktree", "--", *tracked])
        if done.returncode != 0:
            raise RuntimeError(f"git restore failed: {done.stderr.strip()}")
    for item in residue:
        path = item["path"]
        if item["code"] != "??" and _blob_at(repo_root, "HEAD", path):
            continue
        # Absent from HEAD: staged addition or untracked copy of an upstream file.
        _git(repo_root, ["rm", "--cached", "--quiet", "--ignore-unmatch", "--", path])
        target = repo_root / path
        if target.is_file() and not target.is_symlink():
            target.unlink()


def clear_upstream_residue(repo_root: Path, *, upstream: str | None = None) -> dict[str, Any]:
    """Discard working-tree changes that are byte-identical to upstream; never touch real work.

    Writes a receipt (paths and upstream blob ids, which remain in the object
    store) before changing anything. A locked checkout is unlocked only for the
    restore and re-locked in ``finally`` with its original justifying claims.
    """
    repo_root = repo_root.resolve()
    upstream = upstream or _upstream_of(repo_root)
    if upstream is None:
        return {"ok": False, "action": "residue_skipped", "repo_root": str(repo_root),
                "reason": "checkout has no upstream branch"}
    # Callers fetch first; classification compares against the upstream ref as observed.
    classified = classify_dirty_entries(repo_root, upstream)
    base = {"repo_root": str(repo_root), "upstream": upstream,
            "benign_untracked": classified["benign_untracked"], "real": classified["real"]}
    if classified["error"]:
        return {**base, "ok": False, "action": "residue_skipped", "reason": classified["error"]}
    if classified["real"]:
        return {**base, "ok": False, "action": "residue_not_cleared", "cleared": [],
                "reason": f"{len(classified['real'])} change(s) are real local work; nothing touched"}
    residue = classified["residue"]
    if not residue:
        return {**base, "ok": True, "action": "no_residue", "cleared": []}

    RESIDUE_RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    receipt_file = RESIDUE_RECEIPT_DIR / f"{repo_root.name}-{stamp}.json"
    drafts_dir = RESIDUE_RECEIPT_DIR / f"{repo_root.name}-{stamp}-staged-drafts"
    for item in residue:
        blob = item.get("preserve_index_blob")
        if not blob:
            continue
        content = subprocess.run(
            ["git", "-C", str(repo_root), "cat-file", "blob", blob], capture_output=True, check=False
        )
        if content.returncode != 0:
            return {**base, "ok": False, "action": "residue_not_cleared", "cleared": [],
                    "reason": f"could not preserve staged draft {blob} for {item['path']}; nothing touched"}
        saved = drafts_dir / item["path"]
        saved.parent.mkdir(parents=True, exist_ok=True)
        saved.write_bytes(content.stdout)
        item["preserved_at"] = str(saved)
    head = _git(repo_root, ["rev-parse", "HEAD"]).stdout.strip()
    receipt_file.write_text(json.dumps({
        "schema_version": 1, "repo_root": str(repo_root), "head": head, "upstream": upstream,
        "upstream_revision": _git(repo_root, ["rev-parse", upstream]).stdout.strip(),
        "cleared": residue, "benign_untracked": classified["benign_untracked"],
        "cleared_at": datetime.now(timezone.utc).isoformat(),
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    lock = read_receipt(repo_root)
    justifying = list(lock.justifying_claims) if lock else []
    if lock is not None:
        unlock_repo(repo_root)
    try:
        _restore_residue(repo_root, residue)
    finally:
        if lock is not None:
            lock_repo(repo_root, justifying_claims=justifying, session_id="residue")
    after = classify_dirty_entries(repo_root, upstream)
    ok = not after["residue"] and not after["real"] and not after["error"]
    return {**base, "ok": ok, "action": "residue_cleared" if ok else "residue_clear_incomplete",
            "cleared": residue, "receipt": str(receipt_file)}


def sync_repo(repo_root: Path, *, ref_args: list[str] | None = None) -> dict[str, Any]:
    """Fast-forward a locked canonical checkout, restoring the lock afterwards.

    Git writes through the working tree as an ordinary process, so a POSIX-mode
    lock cannot tell its writes apart from an agent's. Worse, ``git pull`` under
    the lock fails *halfway*: it advances the remote-tracking ref and prints
    "Updating ..." before dying on the first ``unable to unlink old`` error,
    leaving a partially updated tree. Refusing the pull outright is therefore
    safer than making the lock permeable, and this is the sanctioned way to
    take the update: drop the lock, fast-forward, put the lock back.

    The re-lock runs in ``finally``. A crashed or non-fast-forwardable pull must
    never leave the canonical checkout writable behind a live lane.
    """
    repo_root = repo_root.resolve()
    sync_lock_path = repo_root / ".git" / "canonical-sync.lock"
    with sync_lock_path.open("a+", encoding="utf-8") as sync_lock:
        fcntl.flock(sync_lock.fileno(), fcntl.LOCK_EX)
        receipt = read_receipt(repo_root)
        if receipt is None:
            return {
                "ok": False,
                "action": "sync_skipped",
                "repo_root": str(repo_root),
                "reason": "no lock receipt; this checkout is not locked, pull it directly",
            }

        status = _git(repo_root, ["status", "--porcelain"])
        residue_report: dict[str, Any] | None = None
        if status.returncode != 0:
            return {
                "ok": False,
                "action": "sync_skipped",
                "repo_root": str(repo_root),
                "reason": "canonical checkout status is unreadable; lock preserved",
            }
        if status.stdout.strip():
            # Already-merged leftovers identical to upstream must not pin the
            # checkout forever; real local work still refuses the sync.
            residue_report = clear_upstream_residue(repo_root)
            if not residue_report["ok"]:
                return {
                    "ok": False,
                    "action": "sync_skipped",
                    "repo_root": str(repo_root),
                    "reason": "canonical checkout has uncommitted changes; lock preserved",
                    "residue": residue_report,
                }
        branch = _git(repo_root, ["rev-parse", "--abbrev-ref", "HEAD"])
        upstream = _git(repo_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"])
        expected_branch = upstream.stdout.strip().removeprefix("origin/")
        if branch.returncode != 0 or upstream.returncode != 0 or branch.stdout.strip() != expected_branch:
            return {
                "ok": False,
                "action": "sync_skipped",
                "repo_root": str(repo_root),
                "reason": "canonical checkout is not on its upstream default branch; lock preserved",
            }

        justifying = list(receipt.justifying_claims)
        unlock_repo(repo_root)
        pull: subprocess.CompletedProcess[str] | None = None
        relocked: dict[str, Any] = {"action": "not_attempted"}
        integrity: dict[str, Any] = {"verdict": VERDICT_UNLOCKED}
        try:
            pull = subprocess.run(
                ["git", "-C", str(repo_root), "pull", "--ff-only", *(ref_args or [])],
                capture_output=True,
                text=True,
                check=False,
            )
        finally:
            relocked = lock_repo(repo_root, justifying_claims=justifying, session_id="sync")
            integrity = verify_lock_integrity(repo_root)

        ok = bool(
            pull
            and pull.returncode == 0
            and read_receipt(repo_root) is not None
            and integrity["verdict"] == VERDICT_LOCKED
        )
        return {
            "ok": ok,
            "action": "synced" if ok else "sync_failed",
            "repo_root": str(repo_root),
            "returncode": pull.returncode if pull else None,
            "stdout": (pull.stdout or "").strip() if pull else "",
            "stderr": (pull.stderr or "").strip() if pull else "",
            "relock": relocked.get("action"),
            "lock_integrity": integrity.get("verdict"),
            "justifying_claims": justifying,
            "residue": residue_report,
        }


def recovery_message(repo_root: Path) -> str:
    """The escape hatch, printed at the moment of blocking rather than filed."""
    receipt = None
    try:
        receipt = read_receipt(repo_root)
    except Exception:  # noqa: BLE001 - a broken receipt must still explain itself
        pass
    scopes = ", ".join(receipt.justifying_claims) if receipt and receipt.justifying_claims else "unknown"
    script = Path(__file__).resolve()
    return (
        f"\nCANONICAL CHECKOUT IS READ-ONLY: {repo_root}\n"
        f"  A lane claim is live against this repository ({scopes}), so its tracked\n"
        f"  files and directories were made read-only. Writes here would silently\n"
        f"  destroy the lane's work, which is why they fail.\n"
        f"\n"
        f"  Work in the lane worktree instead:  {repo_root}/worktrees/<branch>/\n"
        f"\n"
        f"  If git itself failed here (pull/merge/checkout), that is this lock.\n"
        f"  Do not retry the raw command: a pull dies partway through, after it\n"
        f"  has already moved the remote-tracking ref. Take the update with:\n"
        f"      python3 {script} --sync {repo_root}\n"
        f"\n"
        f"  If the lane is finished and this lock is stale, clear it with:\n"
        f"      python3 {script} --reconcile\n"
        f"  To release this one repository explicitly (this permits canonical\n"
        f"  writes again and is the wrong answer while a lane is genuinely live):\n"
        f"      python3 {script} --unlock {repo_root}\n"
    )


# --------------------------------------------------------------------------
# hook mode
# --------------------------------------------------------------------------


def locked_repo_roots() -> list[Path]:
    """Return repositories currently holding a lock, cheaply.

    Uses the index for discovery and the per-repository receipt for truth, so a
    stale index entry never reports a lock that is not there.
    """
    roots: list[Path] = []
    for recorded in _read_index():
        path = Path(recorded)
        try:
            if is_locked(path):
                roots.append(path)
        except (OSError, ValueError):
            continue
    return roots


def _hook_text(payload: dict[str, Any]) -> str:
    """Flatten the parts of a hook payload that can name a blocked path."""
    parts: list[str] = []
    tool_input = payload.get("tool_input")
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "path", "notebook_path"):
            value = tool_input.get(key)
            if isinstance(value, str):
                parts.append(value)
    response = payload.get("tool_response")
    if isinstance(response, str):
        parts.append(response)
    elif isinstance(response, dict):
        for value in response.values():
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


DENIAL_MARKERS = ("Permission denied", "Read-only file system", "EACCES", "Errno 13")


def hook_main(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one hook event.

    This hook never blocks. The permission bits do the blocking; this only
    supplies the escape hatch at the moment of blocking, which is the whole
    point -- an EACCES from the kernel carries no instructions, and nobody goes
    looking for documentation after a failed write.
    """
    event = str(payload.get("hook_event_name") or "")

    if event == "SessionStart":
        try:
            report = reconcile(session_id=str(payload.get("session_id") or "") or None)
        except RegistryUnreadable as exc:
            return {
                "systemMessage": (
                    "Canonical checkout locks could NOT be reconciled: "
                    f"{exc}. Existing locks were preserved (fail-closed). If a checkout "
                    "is stuck read-only, fix the named claim file then run: "
                    f"python3 {Path(__file__).resolve()} --reconcile"
                )
            }
        actions = report.get("actions") or []
        if not actions:
            return None
        locked = [a["repo_root"] for a in actions if a.get("action") == "locked"]
        unlocked = [a["repo_root"] for a in actions if a.get("action") == "unlocked"]
        relocked = [a["repo_root"] for a in actions if a.get("action") == "relocked"]
        lines: list[str] = []
        if relocked:
            lines.append(
                "Repaired canonical lock(s) whose permission bits had drifted writable "
                f"while a lane claim was still live: {', '.join(relocked)}. The read-only "
                "boundary has been re-applied; the recorded pre-lock modes were preserved."
            )
        if locked:
            lines.append(
                "Canonical checkout(s) made read-only because a lane claim is live "
                f"against them: {', '.join(locked)}. Implement in the lane worktree."
            )
        if unlocked:
            lines.append(
                "Released stale canonical lock(s) whose lane claim is gone: "
                f"{', '.join(unlocked)}. These are writable again."
            )
        return {"systemMessage": " ".join(lines)}

    text = _hook_text(payload)
    if not text:
        return None
    roots = locked_repo_roots()
    if not roots:
        return None

    hit = next((root for root in roots if str(root) in text), None)
    if hit is None:
        return None

    # PostToolUse: only speak up when something actually failed, so the hook is
    # silent during the normal case of reading a locked tree.
    if event == "PostToolUse" and not any(marker in text for marker in DENIAL_MARKERS):
        return None

    return {
        "hookSpecificOutput": {
            "hookEventName": event or "PreToolUse",
            "additionalContext": recovery_message(hit),
        }
    }


def run_hook(stream: Any = None) -> int:
    """Read a hook payload and emit guidance. Always exits 0; never blocks."""
    source = stream if stream is not None else sys.stdin
    try:
        raw = source.read()
    except Exception:  # noqa: BLE001 - a hook must not take the session down
        return 0
    try:
        payload = json.loads(raw or "{}")
    except json.JSONDecodeError:
        return 0
    if not isinstance(payload, dict):
        return 0
    try:
        result = hook_main(payload)
    except Exception as exc:  # noqa: BLE001
        # Loud, but non-fatal: the enforcement is the permission bits, not this.
        print(json.dumps({"systemMessage": f"canonical-lock hook error (enforcement unaffected): {exc}"}))
        return 0
    if result:
        print(json.dumps(result))
    return 0


# --------------------------------------------------------------------------
# self-test: both controls
# --------------------------------------------------------------------------

_WRITE_PROBES = (
    ("shell_redirect", "sh -c 'echo BREACH > {target}'"),
    ("sed_in_place", "sed -i s/ORIGINAL/BREACH/ {target}"),
    ("python_open_w", "python3 -c \"open('{target}','w').write('BREACH')\""),
    ("tee", "sh -c 'echo BREACH | tee {target}'"),
    ("cp_over", "sh -c 'echo BREACH > {tmp} && cp -f {tmp} {target}'"),
    ("mv_over", "sh -c 'echo BREACH > {tmp} && mv -f {tmp} {target}'"),
    ("rm_recreate", "sh -c 'rm -f {target} && echo BREACH > {target}'"),
    ("create_new_file", "sh -c 'echo BREACH > {newfile}'"),
)


def _build_probe_repo(base: Path) -> Path:
    repo = base / "canonical"
    (repo / "src").mkdir(parents=True)
    (repo / "worktrees").mkdir(parents=True)
    (repo / ".gitignore").write_text("worktrees/\n", encoding="utf-8")
    (repo / "src" / "module.py").write_text("ORIGINAL\n", encoding="utf-8")
    (repo / "README.md").write_text("ORIGINAL\n", encoding="utf-8")
    for args in (
        ["init", "-q", "-b", "main"],
        ["config", "user.email", "probe@example.invalid"],
        ["config", "user.name", "probe"],
        ["add", "-A"],
        ["commit", "-qm", "probe baseline"],
    ):
        result = _git(repo, args)
        if result.returncode != 0:
            raise RuntimeError(f"probe repo setup failed: git {args}: {result.stderr}")
    return repo


def _run_probes(repo: Path, base: Path) -> list[dict[str, Any]]:
    target = repo / "src" / "module.py"
    results: list[dict[str, Any]] = []
    for name, template in _WRITE_PROBES:
        # Restore the target so each probe starts from the same known content.
        try:
            if not target.exists():
                results.append({"probe": name, "outcome": "BREACH", "detail": "target missing before probe"})
                continue
        except OSError:
            pass
        command = template.format(
            target=target,
            tmp=base / f"tmp_{name}",
            newfile=repo / f"new_{name}.txt",
        )
        proc = subprocess.run(command, shell=True, capture_output=True, text=True, check=False)
        if name == "create_new_file":
            created = (repo / f"new_{name}.txt").exists()
            outcome = "BREACH" if created else "BLOCKED"
        else:
            content = target.read_text(encoding="utf-8") if target.exists() else ""
            outcome = "BREACH" if "BREACH" in content or not target.exists() else "BLOCKED"
        results.append(
            {
                "probe": name,
                "outcome": outcome,
                "returncode": proc.returncode,
                "stderr": (proc.stderr or "").strip()[:200],
            }
        )
    return results


def _lane_probes(repo: Path) -> list[dict[str, Any]]:
    """Positive controls: the lane must still be fully usable."""
    results: list[dict[str, Any]] = []
    lane = repo / "worktrees" / "probe-lane"
    add = _git(repo, ["worktree", "add", "-q", "-b", "probe-lane", str(lane)])
    results.append({"probe": "git_worktree_add", "outcome": "OK" if add.returncode == 0 else "FAILED",
                    "stderr": (add.stderr or "").strip()[:200]})
    if add.returncode != 0:
        return results

    edit = subprocess.run(
        f"sed -i s/ORIGINAL/LANEWRITE/ {lane / 'src' / 'module.py'}",
        shell=True, capture_output=True, text=True, check=False,
    )
    wrote = "LANEWRITE" in (lane / "src" / "module.py").read_text(encoding="utf-8")
    results.append({"probe": "lane_edit", "outcome": "OK" if wrote else "FAILED",
                    "stderr": (edit.stderr or "").strip()[:200]})

    _git(lane, ["add", "-A"])
    commit = _git(lane, ["commit", "-qm", "lane change"])
    results.append({"probe": "lane_commit", "outcome": "OK" if commit.returncode == 0 else "FAILED",
                    "stderr": (commit.stderr or "").strip()[:200]})

    status = _git(repo, ["status", "--short"])
    results.append({"probe": "canonical_git_status", "outcome": "OK" if status.returncode == 0 else "FAILED",
                    "stderr": (status.stderr or "").strip()[:200]})
    return results


def grade_self_test(*, locked: bool, writes: list[dict[str, Any]], lanes: list[dict[str, Any]]) -> dict[str, Any]:
    """Grade a probe run. Only the locked arm can ever report boundary_verified.

    The unlocked arm exists so a green locked arm means something. If the probe
    reported BLOCKED with no lock in place, the probe is measuring nothing and
    this says so instead of passing.
    """
    breaches = [r["probe"] for r in writes if r["outcome"] == "BREACH"]
    blocked = [r["probe"] for r in writes if r["outcome"] == "BLOCKED"]
    lane_failures = [r["probe"] for r in lanes if r["outcome"] != "OK"]

    if not locked:
        verdict = "probe_is_sound" if not blocked else "probe_is_rigged"
        return {
            "arm": "unlocked",
            "boundary_verified": False,
            "verdict": verdict,
            "detail": (
                "every write route landed with no lock, so the probe detects real writes"
                if not blocked
                else f"routes reported BLOCKED with no lock in place: {blocked} -- the probe cannot be trusted"
            ),
            "breached": breaches,
            "blocked": blocked,
            "lane_failures": lane_failures,
        }

    verified = not breaches and not lane_failures
    return {
        "arm": "locked",
        "boundary_verified": verified,
        "verdict": "boundary_holds" if verified else "boundary_failed",
        "detail": (
            "all write routes blocked and lane operations still work"
            if verified
            else f"breaches={breaches} lane_failures={lane_failures}"
        ),
        "breached": breaches,
        "blocked": blocked,
        "lane_failures": lane_failures,
    }


def self_test(*, locked: bool) -> dict[str, Any]:
    base = Path(tempfile.mkdtemp(prefix="canonical-lock-selftest-"))
    try:
        repo = _build_probe_repo(base)
        if locked:
            lock_repo(repo, justifying_claims=["self-test"], session_id="self-test")
        writes = _run_probes(repo, base)
        lanes = _lane_probes(repo)
        report = grade_self_test(locked=locked, writes=writes, lanes=lanes)
        report["write_probes"] = writes
        report["lane_probes"] = lanes
        if locked:
            unlock_repo(repo)
            after = _git(repo, ["status", "--porcelain"])
            report["clean_after_unlock"] = after.returncode == 0 and after.stdout.strip() == ""
            report["status_after_unlock"] = after.stdout.strip()[:400]
            if not report["clean_after_unlock"]:
                report["boundary_verified"] = False
                report["verdict"] = "unlock_did_not_restore_modes"
        return report
    finally:
        for current, dirnames, filenames in os.walk(base):
            for name in [*dirnames, *filenames]:
                target = Path(current) / name
                try:
                    if not target.is_symlink():
                        os.chmod(target, stat.S_IMODE(target.lstat().st_mode) | stat.S_IWUSR)
                except OSError:
                    continue
        shutil.rmtree(base, ignore_errors=True)
        _index_record(base / "canonical", locked=False)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Make a canonical checkout read-only while a lane claim is live.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--lock", metavar="REPO_ROOT", help="Lock one canonical checkout")
    mode.add_argument("--unlock", metavar="REPO_ROOT", help="Unlock one canonical checkout")
    mode.add_argument("--status", metavar="REPO_ROOT", help="Report lock state for one checkout")
    mode.add_argument(
        "--verify",
        metavar="REPO_ROOT",
        help=(
            "Measure whether a recorded lock still holds. Exits "
            f"{EXIT_DEGRADED} if it has drifted writable. Repairs nothing."
        ),
    )
    mode.add_argument(
        "--sync",
        metavar="REPO_ROOT",
        help=(
            "Fast-forward a locked canonical checkout: unlock, git pull --ff-only, "
            "re-lock. The re-lock always runs, including when the pull fails."
        ),
    )
    mode.add_argument(
        "--clear-residue",
        metavar="REPO_ROOT",
        help=(
            "Discard uncommitted changes that are byte-identical to the upstream branch "
            "(merged-work leftovers), with a receipt. Real local work is never touched."
        ),
    )
    mode.add_argument("--reconcile", action="store_true", help="Sync lock state with live lane claims")
    mode.add_argument("--explain", metavar="REPO_ROOT", help="Print the recovery message for a locked checkout")
    mode.add_argument("--hook", action="store_true", help="Run as a Claude Code / Codex hook, reading JSON on stdin")
    mode.add_argument("--self-test", action="store_true", help="Prove the boundary in a throwaway repository")
    mode.add_argument(
        "--self-test-unlocked",
        action="store_true",
        help="Run the identical probe with no lock, proving the probe is not rigged",
    )
    parser.add_argument("--repo", action="append", default=[], help="Extra repo root to consider during --reconcile")
    parser.add_argument("--dry-run", action="store_true", help="Report reconcile actions without applying them")
    parser.add_argument("--session-id", default=None, help="Session identity recorded on a lock receipt")
    parser.add_argument("--json", action="store_true", help="Emit JSON")
    parser.add_argument("--quiet", action="store_true", help="Suppress output when there is nothing to report")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    def emit(payload: dict[str, Any]) -> None:
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(json.dumps(payload, indent=2, sort_keys=True))

    if args.hook:
        return run_hook()

    if args.self_test or args.self_test_unlocked:
        report = self_test(locked=bool(args.self_test))
        emit(report)
        if args.self_test:
            return 0 if report.get("boundary_verified") else 1
        # The unlocked arm must never be mistakable for a pass.
        return 5 if report.get("verdict") == "probe_is_sound" else 1

    if args.lock:
        emit(lock_repo(Path(args.lock), session_id=args.session_id))
        return 0

    if args.unlock:
        emit(unlock_repo(Path(args.unlock)))
        return 0

    if args.status:
        repo = Path(args.status).resolve()
        receipt = read_receipt(repo)
        integrity = verify_lock_integrity(repo)
        emit(
            {
                "repo_root": str(repo),
                # Unchanged meaning for existing callers: a receipt is present.
                # It says the lock was applied, not that the boundary holds --
                # read "integrity" for that.
                "locked": receipt is not None,
                "integrity": integrity["verdict"],
                "locked_at": receipt.locked_at if receipt else None,
                "justifying_claims": receipt.justifying_claims if receipt else [],
                "paths_recorded": integrity["paths_recorded"],
                "paths_checked": integrity["paths_checked"],
                "writable_files": integrity["writable_files"],
                "writable_directories": integrity["writable_directories"],
                "missing_paths": integrity["missing_paths"],
                "control_path_issues": integrity["control_path_issues"],
            }
        )
        return 0

    if args.verify:
        integrity = verify_lock_integrity(Path(args.verify))
        emit(integrity)
        return EXIT_DEGRADED if integrity["verdict"] == VERDICT_DEGRADED else 0

    if args.sync:
        result = sync_repo(Path(args.sync))
        emit(result)
        return 0 if result["ok"] else 1

    if args.clear_residue:
        result = clear_upstream_residue(Path(args.clear_residue))
        emit(result)
        return 0 if result["ok"] else 1

    if args.explain:
        print(recovery_message(Path(args.explain).resolve()))
        return 0

    try:
        report = reconcile(
            repos=[Path(p) for p in args.repo],
            dry_run=args.dry_run,
            session_id=args.session_id,
        )
    except RegistryUnreadable as exc:
        # Fail closed: existing locks stay, and this is loud.
        payload = {
            "ok": False,
            "error": "claim_registry_unreadable",
            "detail": str(exc),
            "action_taken": "none -- existing locks preserved, nothing unlocked",
        }
        emit(payload)
        return 4

    if args.quiet and not report["actions"]:
        return 0
    emit(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
