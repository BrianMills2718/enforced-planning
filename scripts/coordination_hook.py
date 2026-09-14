#!/usr/bin/env python3
"""Expose canonical mailbox requests through native Codex lifecycle hooks."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

try:
    from hook_receipts import DEFAULT_RECEIPT_ROOT, HookInvocation, start_hook_invocation
except ModuleNotFoundError:  # package-style tests import scripts.coordination_hook
    from scripts.hook_receipts import DEFAULT_RECEIPT_ROOT, HookInvocation, start_hook_invocation


def _bootstrap_package() -> None:
    """Load the local package or a governed repo's upstream bootstrap."""

    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "enforced_planning").is_dir():
            if str(parent) not in sys.path:
                sys.path.insert(0, str(parent))
            return
    for parent in current.parents:
        helper = parent / "scripts" / "_upstream_enforced_planning.py"
        if helper.is_file():
            scripts_dir = helper.parent
            if str(scripts_dir) not in sys.path:
                sys.path.insert(0, str(scripts_dir))
            from _upstream_enforced_planning import bootstrap_upstream_package  # type: ignore[import-not-found]

            bootstrap_upstream_package(current)
            return
    import importlib.util
    if importlib.util.find_spec("enforced_planning") is not None:
        return
    raise RuntimeError(
        "Unable to locate a local enforced_planning package or "
        "scripts/_upstream_enforced_planning.py"
    )


_bootstrap_package()

from enforced_planning import (
    coordination_claims,
    coordination_messages,
    mailbox_execution_identity,
    outcome_completion,
    prewrite_claim_fast,
    prewrite_claim_projection,
)

SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "PreToolUse", "Stop"}
MUTATION_TOOL_NAMES = frozenset({"bash", "apply_patch", "edit", "write"})
REPOSITORY_SCAN_MAX_WORKERS = 16
# Mid-turn events use this budget too, deliberately, and an earlier revision of
# this change did not. The reasoning for a tighter mid-turn budget was that
# PostToolUse fires on every tool call while Stop fires once, so a tool call
# should not wait as long for the global registry lock. Measurement killed it:
# the repair spawns a Python subprocess, and interpreter startup plus package
# import is 0.40-0.45s warm and 3.35s cold on this machine. The dominant cost is
# startup, not lock waiting, so a 0.5s mid-turn budget did not shorten a wait --
# it turned a repairable turn back into the lost one this change exists to stop,
# and `test_real_subprocess_secondary_posttool_preserves_root_pretool_obligation`
# went red with "claim projection repair exceeded 0.5s (last_phase=complete)".
#
# The healthy path never spawns anything: the guards in `_active_claims` only
# reach the repair when the projection is missing or genuinely behind, and one
# rebuild makes it current for the calls that follow.
TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS = 1.5
STARTUP_PROJECTION_READ_LOCK_TIMEOUT_SECONDS = 1.0
STARTUP_PROJECTION_READ_LOCK_POLL_SECONDS = 0.01


class RepositoryCloseoutError(RuntimeError):
    """Compatibility name for unavailable turn-end repository safety evidence."""


class TurnEndProjectionError(RepositoryCloseoutError):
    """Raised when derived claim state cannot be repaired within the Stop budget."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse test and rollout overrides without changing the hook wire format."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--closeout-ledger-dir", type=Path)
    parser.add_argument("--hook-receipt-dir", type=Path)
    parser.add_argument("--agent", choices=("codex", "claude-code"), default="codex")
    parser.add_argument("--project", help="Canonical project override supplied by a repository compatibility hook.")
    parser.add_argument("--repair-projection-only", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args(argv)


def _read_hook_input(*, project_supplied: bool) -> dict[str, Any]:
    """Read and validate the common native lifecycle-hook fields from stdin."""

    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("Lifecycle hook input must be a JSON object")
    required_fields = ("session_id", "hook_event_name") if project_supplied else ("session_id", "cwd", "hook_event_name")
    for field in required_fields:
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"Lifecycle hook input requires non-empty {field!r}")
    if payload["hook_event_name"] not in SUPPORTED_EVENTS:
        raise ValueError(f"Unsupported Codex hook event: {payload['hook_event_name']}")
    return payload


def _canonical_project(cwd: str) -> str | None:
    """Resolve a worktree cwd, or return no project for a non-Git workspace path."""

    repository = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if repository.returncode == 128:
        return None
    repository.check_returncode()
    top = repository.stdout.strip()
    worktrees = subprocess.run(
        ["git", "-C", top, "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    canonical_root = next(
        (line.removeprefix("worktree ") for line in worktrees if line.startswith("worktree ")),
        top,
    )
    return Path(canonical_root).name


def _worktree_root(cwd: str) -> Path | None:
    """Resolve the exact checkout containing cwd, preserving worktree identity."""

    result = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 128:
        return None
    result.check_returncode()
    return Path(result.stdout.strip()).resolve()


def _outcome_stop_decisions(
    *,
    payload: dict[str, Any],
    agent: str,
    session_id: str,
    cwd_project: str | None,
    active_claims: tuple[Any, ...],
) -> tuple[outcome_completion.OutcomeCompletionStopDecisionV1, ...]:
    """Evaluate every exact-session claimed worktree plus the callback cwd."""

    candidates: dict[Path, str] = {}
    for claim in active_claims:
        if (
            claim.agent == agent
            and claim.session_id == session_id
            and claim.worktree_path
            and claim.projects
        ):
            candidates[Path(claim.worktree_path).expanduser().resolve()] = claim.projects[0]
    cwd_root = _worktree_root(payload["cwd"])
    if cwd_root is not None and cwd_project is not None:
        candidates.setdefault(cwd_root, cwd_project)
    return tuple(
        outcome_completion.evaluate_stop_for_session(
            repo_root=repo_root,
            agent=agent,
            project=project,
            session_id=session_id,
            active_claims=active_claims,
        )
        for repo_root, project in sorted(candidates.items(), key=lambda item: str(item[0]))
    )


def _repository_scan_root(cwd: str) -> Path:
    """Use one Git root locally, or the non-Git workspace root for a fleet scan."""

    resolved = Path(cwd).expanduser().resolve()
    repository = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=False,
    )
    if repository.returncode == 0:
        return Path(repository.stdout.strip()).resolve()
    if repository.returncode != 128:
        raise RepositoryCloseoutError(
            f"cannot resolve repository scope for {resolved}: {repository.stderr.strip()}"
        )
    return resolved


def _repository_status(repository: Path) -> dict[str, Any]:
    """Return a stable fingerprint of one repository's complete working-tree state."""

    result = subprocess.run(
        [
            "git",
            "-C",
            str(repository),
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise RepositoryCloseoutError(f"git status failed for {repository}: {detail}")
    fingerprint = hashlib.sha256()
    fingerprint.update(result.stdout)
    for raw_status_path in result.stdout.split(b"\0"):
        if not raw_status_path:
            continue
        # Porcelain v1 -z prefixes ordinary records with ``XY ``. A rename's
        # second NUL field is the source path without that prefix.
        raw_relative_path = (
            raw_status_path[3:]
            if len(raw_status_path) >= 3 and raw_status_path[2:3] == b" "
            else raw_status_path
        )
        relative_path = raw_relative_path.decode("utf-8", errors="surrogateescape")
        path = repository / relative_path
        fingerprint.update(raw_relative_path)
        fingerprint.update(b"\0")
        if path.is_symlink():
            fingerprint.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif not path.exists():
            fingerprint.update(b"<missing>")
        elif path.is_dir():
            # Nested repositories and linked worktrees can be represented as
            # one untracked directory by their parent. Their own canonical
            # roots are scanned separately; do not recursively adopt them.
            fingerprint.update(b"<directory>")
        else:
            try:
                with path.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        fingerprint.update(chunk)
            except OSError as exc:
                raise RepositoryCloseoutError(
                    f"cannot fingerprint untracked file {path}: {exc}"
                ) from exc
    return {
        "fingerprint": fingerprint.hexdigest(),
        "dirty": bool(result.stdout),
        "entry_count": result.stdout.count(b"\0"),
    }


def _repository_statuses(
    repositories: tuple[Path, ...],
) -> dict[str, dict[str, Any]]:
    """Capture status fingerprints concurrently for exact attributed repositories."""

    if not repositories:
        return {}
    worker_count = min(REPOSITORY_SCAN_MAX_WORKERS, len(repositories))
    with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="repo-closeout") as executor:
        statuses = executor.map(_repository_status, repositories)
        return {
            str(repository): status
            for repository, status in zip(repositories, statuses, strict=True)
        }


def _closeout_ledger_path(
    *,
    ledger_dir: Path,
    agent: str,
    session_id: str,
) -> Path:
    identity = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:24]
    return ledger_dir.expanduser().resolve() / f"{agent}-{identity}.json"


def _write_closeout_baseline(
    *,
    payload: dict[str, Any],
    agent: str,
    session_id: str,
    ledger_dir: Path,
) -> None:
    """Persist the session's initial repository state once, before mutation."""

    ledger_path = _closeout_ledger_path(
        ledger_dir=ledger_dir,
        agent=agent,
        session_id=session_id,
    )
    if ledger_path.is_file():
        return
    cwd = payload.get("cwd")
    scan_root = _repository_scan_root(cwd if isinstance(cwd, str) and cwd.strip() else os.getcwd())
    baseline = {
        "schema_version": "1.0",
        "agent": agent,
        "session_id": session_id,
        "scan_root": str(scan_root),
        "repositories": {},
        "touched_repositories": [],
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)


def _projection_has_registry_change(projection_path: Path, claims_dir: Path) -> bool:
    """Cheaply detect atomic writes, additions, or deletions since projection."""

    try:
        projection_mtime = projection_path.stat().st_mtime_ns
        if not claims_dir.exists():
            return False
        if claims_dir.stat().st_mtime_ns > projection_mtime:
            return True
        return any(path.stat().st_mtime_ns > projection_mtime for path in claims_dir.glob("*.yaml"))
    except OSError as exc:
        raise TurnEndProjectionError(f"cannot inspect derived claim state: {exc}") from exc


def _repair_phase(output: str | bytes | None) -> str:
    """Return the last content-free phase marker emitted by the repair worker."""

    if output is None:
        return "startup"
    text = output.decode("utf-8", errors="replace") if isinstance(output, bytes) else output
    prefix = "projection_repair_phase="
    phases = [line.removeprefix(prefix) for line in text.splitlines() if line.startswith(prefix)]
    return phases[-1] if phases else "startup"


def _repair_turn_end_projection(
    claims_dir: Path,
    *,
    timeout: float = TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Run the lock-owning projection repair in a killable, bounded subprocess."""

    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--claims-dir",
        str(claims_dir),
        "--repair-projection-only",
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        last_phase = _repair_phase(exc.stderr)
        raise TurnEndProjectionError(
            f"claim projection repair exceeded {timeout:g}s "
            f"(last_phase={last_phase})"
        ) from exc
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "repair process failed"
        raise TurnEndProjectionError(detail)
    try:
        result = json.loads(completed.stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise TurnEndProjectionError("projection repair returned invalid timing evidence") from exc
    if not isinstance(result, dict) or result.get("last_phase") != "complete":
        raise TurnEndProjectionError("projection repair returned incomplete timing evidence")
    return result


def _projection_is_current(claims_dir: Path) -> bool:
    """Check the derived projection against one lock-owned registry state."""

    projection_path = prewrite_claim_fast.projection_path_for(claims_dir)
    try:
        projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1.model_validate_json(
            projection_path.read_text(encoding="utf-8")
        )
        return (
            projection.claims_dir == str(claims_dir)
            and projection.registry_digest == prewrite_claim_fast.registry_digest(claims_dir)
        )
    except (OSError, ValueError):
        return False


def _repair_projection_under_lock(claims_dir: Path) -> dict[str, Any]:
    """Recheck after writer contention and rebuild only genuinely stale state."""

    started = time.monotonic()
    print("projection_repair_phase=lock_wait", file=sys.stderr, flush=True)

    with coordination_claims.claim_registry_lock(claims_dir):
        lock_acquired = time.monotonic()
        print("projection_repair_phase=registry_check", file=sys.stderr, flush=True)
        if _projection_is_current(claims_dir):
            action = "already_current"
        else:
            print("projection_repair_phase=rebuild", file=sys.stderr, flush=True)
            coordination_claims.refresh_prewrite_authority_projection(claims_dir)
            action = "rebuilt"
    completed = time.monotonic()
    print("projection_repair_phase=complete", file=sys.stderr, flush=True)
    return {
        "action": action,
        "last_phase": "complete",
        "lock_wait_ms": round((lock_acquired - started) * 1000, 3),
        "total_ms": round((completed - started) * 1000, 3),
    }


def _active_claims(claims_dir: Path | None, *, turn_end: bool = False) -> tuple[Any, ...]:
    """Load active claims strictly, or repair derived state for ordinary turn end."""

    resolved = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    projection_path = prewrite_claim_fast.projection_path_for(resolved)
    def load_projection() -> Any:
        try:
            projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1.model_validate_json(
                projection_path.read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            error_type = TurnEndProjectionError if turn_end else RepositoryCloseoutError
            raise error_type(f"cannot read active-claim projection {projection_path}: {exc}") from exc
        if projection.claims_dir != str(resolved):
            error_type = TurnEndProjectionError if turn_end else RepositoryCloseoutError
            raise error_type(f"active-claim projection targets {projection.claims_dir}, expected {resolved}")
        return projection

    # The bounded repair used to be reachable only from `Stop`. Every other event
    # that loads claims -- PostToolUse in practice -- refused on the first digest
    # mismatch, and the caller then discarded the claims notice and the mailbox
    # summary it had already assembled. "active-claim projection is stale relative
    # to the canonical claim registry" appears 1,972 times in one machine's
    # transcripts, and it was 164 of 171 recorded blocks across three runs.
    #
    # Refusing was never the safe half of that trade. The registry is the
    # authority and the projection is derived from it; the mismatch is a race
    # between a writer's atomic projection write and this reader, not a claim
    # conflict. The repair takes the registry lock and rebuilds only what is
    # genuinely stale -- run against a settled registry it returns
    # `already_current` -- so attempting it converts a lost turn into a correct
    # one, and a repair that cannot close the gap still raises exactly as before.
    #
    # Cost is bounded on both axes. The guards below mean a healthy projection
    # never acquires the lock, and `_repair_turn_end_projection` is capped at
    # TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS. PreToolUse, the latency
    # boundary, does not call this function at all.
    repaired = False
    if not projection_path.is_file() or _projection_has_registry_change(projection_path, resolved):
        _repair_turn_end_projection(resolved)
        repaired = True
    if projection_path.is_file():
        try:
            projection = load_projection()
        except TurnEndProjectionError:
            if repaired:
                raise
            _repair_turn_end_projection(resolved)
            repaired = True
            projection = load_projection()
        registry_digest = prewrite_claim_fast.registry_digest(resolved)
        if projection.registry_digest != registry_digest:
            if not repaired:
                _repair_turn_end_projection(resolved)
                repaired = True
                projection = load_projection()
                registry_digest = prewrite_claim_fast.registry_digest(resolved)
            if projection.registry_digest != registry_digest:
                error_type = TurnEndProjectionError if turn_end else RepositoryCloseoutError
                raise error_type(
                    "active-claim projection is stale relative to the canonical claim registry"
                )
        now = datetime.now(UTC)
        return tuple(
            claim
            for claim in projection.claims
            if claim.status in coordination_claims.LIVE_STATUSES
            and (
                claim.expires_at is None
                or datetime.fromisoformat(claim.expires_at) >= now
            )
        )
    if resolved == coordination_claims.CLAIMS_DIR.expanduser().resolve():
        error_type = TurnEndProjectionError if turn_end else RepositoryCloseoutError
        raise error_type(
            f"active-claim projection is missing: {projection_path}"
        )
    return tuple(coordination_claims.check_claims(claims_dir=resolved))


def _startup_claims(claims_dir: Path | None) -> tuple[tuple[Any, ...], str | None]:
    """Read one current projection without scanning or repairing claim YAML."""

    resolved = (claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
    projection_path = prewrite_claim_fast.projection_path_for(resolved)
    if not projection_path.is_file():
        return (), None
    try:
        with _startup_registry_read_lock(resolved):
            projection = prewrite_claim_projection.PreWriteAuthorityProjectionV1.model_validate_json(
                projection_path.read_text(encoding="utf-8")
            )
            if (
                projection.claims_dir != str(resolved)
                or projection.registry_digest != prewrite_claim_fast.registry_digest(resolved)
            ):
                return (), "Startup claim context unavailable: canonical projection is stale; no assignment was adopted."
    except (OSError, ValueError, TurnEndProjectionError) as exc:
        return (), f"Startup claim context unavailable: {exc}; no assignment was adopted."
    now = datetime.now(UTC)
    return (
        tuple(
            claim
            for claim in projection.claims
            if claim.status in coordination_claims.LIVE_STATUSES
            and (claim.expires_at is None or datetime.fromisoformat(claim.expires_at) >= now)
        ),
        None,
    )


@contextmanager
def _startup_registry_read_lock(claims_dir: Path) -> Iterator[None]:
    """Observe claims and their projection under the writer's lock, without mutation."""

    lock_path = claims_dir.parent / f".{claims_dir.name}.lock"
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        lock_fd = os.open(lock_path, flags)
    except FileNotFoundError:
        # An initialized sanctioned registry always has the writer lock. For a
        # test or first-run empty registry, the digest check below still makes
        # adoption fail closed if canonical state changes during observation.
        yield
        return
    deadline = time.monotonic() + STARTUP_PROJECTION_READ_LOCK_TIMEOUT_SECONDS
    try:
        while True:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TurnEndProjectionError(
                        "timed out waiting for the canonical claim registry writer"
                    )
                time.sleep(STARTUP_PROJECTION_READ_LOCK_POLL_SECONDS)
        try:
            yield
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
    finally:
        os.close(lock_fd)


def _startup_claim_summary(
    *, agent: str, session_id: str, project: str | None, claims: tuple[Any, ...]
) -> str | None:
    """Label exact-session ownership separately from other live project claims."""

    owned = [claim for claim in claims if claim.agent == agent and claim.session_id == session_id]
    global_context = [
        claim
        for claim in claims
        if project is not None
        and project in claim.projects
        and not (claim.agent == agent and claim.session_id == session_id)
    ]
    lines = [
        f"Current session ownership: project={','.join(claim.projects)}; scope={claim.scope}; status={claim.status}; session={claim.session_id}"
        for claim in owned
    ]
    lines.extend(
        f"Global context (not your current work): project={','.join(claim.projects)}; scope={claim.scope}; status={claim.status}; owner={claim.agent}; session={claim.session_id}"
        for claim in global_context
    )
    return "\n".join(lines) or None


def _canonical_repository_root(cwd: str) -> Path | None:
    """Resolve a linked worktree cwd to the canonical repository checkout."""

    result = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 128:
        return None
    if result.returncode:
        raise RepositoryCloseoutError(
            f"cannot resolve canonical repository for {cwd}: {result.stderr.strip()}"
        )
    common_dir = Path(result.stdout.strip()).resolve()
    return common_dir.parent if common_dir.name == ".git" else common_dir


def _git_path(repository: Path, option: str) -> Path:
    """Resolve one Git administrative path or fail closeout loudly."""

    completed = subprocess.run(
        ["git", "-C", str(repository), "rev-parse", option],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode:
        raise RepositoryCloseoutError(
            completed.stderr.strip() or f"cannot resolve {option} for {repository}"
        )
    value = Path(completed.stdout.strip())
    return (value if value.is_absolute() else repository / value).resolve()


def _is_linked_worktree(repository: Path) -> bool:
    """Return whether one checkout has session-attributable Git custody."""

    return _git_path(repository, "--absolute-git-dir") != _git_path(
        repository, "--git-common-dir"
    )


def _record_touched_repositories(
    *,
    payload: dict[str, Any],
    agent: str,
    session_id: str,
    ledger_dir: Path,
    active_claims: tuple[Any, ...],
) -> None:
    """Persist only repositories this exact session had evidence of touching."""

    ledger_path = _closeout_ledger_path(
        ledger_dir=ledger_dir,
        agent=agent,
        session_id=session_id,
    )
    if not ledger_path.is_file():
        return
    try:
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RepositoryCloseoutError(f"cannot read repository closeout ledger {ledger_path}: {exc}") from exc
    prior_touched = {
        str(Path(path).expanduser().resolve())
        for path in ledger.get("touched_repositories", [])
        if isinstance(path, str) and path.strip()
    }
    touched = set(prior_touched)
    candidates: set[Path] = set()
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd.strip() and _canonical_repository_root(cwd) is not None:
        candidates.add(_repository_scan_root(cwd))
    for claim in active_claims:
        if claim.agent == agent and claim.session_id == session_id and claim.worktree_path:
            candidates.add(Path(claim.worktree_path).expanduser().resolve())
    for repository in candidates:
        if repository.is_dir() and _is_linked_worktree(repository):
            touched.add(str(repository))
    baselines = ledger.get("repositories")
    if not isinstance(baselines, dict):
        raise RepositoryCloseoutError(f"invalid repository closeout ledger: {ledger_path}")
    for repository in sorted(touched - prior_touched):
        repository_path = Path(repository)
        if repository_path.is_dir():
            baselines[repository] = _repository_status(repository_path)
    ledger["touched_repositories"] = sorted(touched)
    temporary = ledger_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)


# One Stop hook, two unrelated jobs: deliver coordination messages the session
# has not seen, and refuse a turn end that left a repository dirty. They were
# bundled because they share a shape -- do not let the agent walk away -- but
# they do not share a failure mode.
#
# On 2026-09-03 the dirty-repository half blocked turn end wrongly, and the fix
# was to replace the whole hook command in ~/.claude/settings.json with `true`.
# That also disabled message delivery for every claude-code session on the host,
# and it stayed disabled for six days: the only visible symptom was one warning
# line when somebody sent a message, saying persistence is not delivery.
#
# The hook command shape is pinned -- coordination_messages validates the Stop
# entry as exactly `<python> coordination_hook.py --agent <client>`, so a
# `--no-closeout` flag would make the command six tokens and report delivery
# unavailable all over again. The toggle therefore lives beside the claims
# registry rather than on the command line.
CLOSEOUT_GATE_DISABLE_MARKER = Path(
    # Override for subprocess tests: a host whose real marker disables the gate
    # otherwise makes gate tests pass or fail by machine, not by code.
    os.environ.get("ENFORCED_PLANNING_CLOSEOUT_GATE_DISABLE_MARKER")
    or Path.home() / ".claude" / "coordination" / "closeout-gate-disabled"
)


def _repository_closeout_gate_disabled() -> bool:
    """Whether the dirty-repository turn-end gate is switched off.

    Fails safe: any error reading the marker leaves the gate ENABLED, because a
    silently-skipped closeout check is how uncommitted work gets lost, and an
    unreadable file is not consent.

    Message delivery is deliberately unaffected by this. Turning off the
    dirty-tree gate must never again take cross-session delivery with it.
    """
    try:
        return CLOSEOUT_GATE_DISABLE_MARKER.is_file()
    except OSError:
        return False


def _repository_closeout_failure(
    *,
    agent: str,
    session_id: str,
    ledger_dir: Path,
    active_claims: tuple[Any, ...],
) -> str | None:
    """Explain session-created dirty repositories, or return a clean closeout."""

    ledger_path = _closeout_ledger_path(
        ledger_dir=ledger_dir,
        agent=agent,
        session_id=session_id,
    )
    if not ledger_path.is_file():
        return None
    try:
        payload = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RepositoryCloseoutError(f"cannot read repository closeout ledger {ledger_path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("repositories"), dict):
        raise RepositoryCloseoutError(f"invalid repository closeout ledger: {ledger_path}")
    baseline = payload["repositories"]
    touched = {
        str(Path(path).expanduser().resolve())
        for path in payload.get("touched_repositories", [])
        if isinstance(path, str) and path.strip()
    }
    touched.update(
        str(Path(claim.worktree_path).expanduser().resolve())
        for claim in active_claims
        if claim.agent == agent
        and claim.session_id == session_id
        and claim.worktree_path
        and Path(claim.worktree_path).expanduser().resolve().is_dir()
        and _is_linked_worktree(Path(claim.worktree_path).expanduser().resolve())
    )
    repositories = tuple(
        Path(repository)
        for repository in sorted(touched)
        if Path(repository).is_dir()
    )
    if repositories:
        current = _repository_statuses(repositories)
    else:
        current = {}
    dirty_changes: list[tuple[str, int]] = []
    for repository, status in current.items():
        prior = baseline.get(repository)
        if status["dirty"] and (
            not isinstance(prior, dict) or prior.get("fingerprint") != status["fingerprint"]
        ):
            dirty_changes.append((repository, int(status["entry_count"])))
    if not dirty_changes:
        return None
    rendered = ", ".join(
        f"{repository} ({count} change{'s' if count != 1 else ''})"
        for repository, count in dirty_changes[:10]
    )
    if len(dirty_changes) > 10:
        rendered += f", and {len(dirty_changes) - 10} more"
    return (
        "Turn end blocked: this session changed repository state and left it dirty: "
        f"{rendered}. Commit and push the coherent work, restore it to the recorded baseline, "
        "or use the sanctioned session-close dirty-handoff path before sending a final response."
    )


def _claimed_projects(
    *, agent: str, session_id: str, active_claims: tuple[Any, ...]
) -> tuple[str, ...]:
    """Return exact-session live claim projects without adopting another lane."""

    return tuple(
        sorted(
            {
                project
                for claim in active_claims
                if claim.agent == agent and claim.session_id == session_id
                for project in claim.projects
            }
        )
    )


def _session_id(agent: str, raw_session_id: str) -> str:
    """Normalize one native client session UUID into canonical claim identity."""

    return raw_session_id if raw_session_id.startswith(f"{agent}:") else f"{agent}:{raw_session_id}"


def _delivery_event_id(payload: dict[str, Any], *, agent: str, session_id: str) -> str:
    """Derive one client-neutral identity for a native lifecycle callback.

    Native turn/event IDs are preferred. A timestamp is only a compatibility
    fallback because it is weaker: adapters that receive neither must fail
    before they can create observation evidence.
    """

    # Claude Code's UserPromptSubmit payload identifies the native prompt with
    # ``prompt_id``.  It is an event identity, not a session identity, so it
    # preserves the same duplicate-suppression boundary as the turn/tool IDs
    # above.  Do not substitute a session ID when an event lacks one.
    for field in ("event_id", "turn_id", "prompt_id", "tool_use_id", "tool_call_id", "timestamp"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            token = f"{field}:{value.strip()}"
            break
    else:
        # Native SessionStart payloads from Claude Code and Codex can omit both
        # an event ID and a timestamp. A short-lived bucket preserves duplicate
        # suppression for concurrently configured host/repository hooks without
        # pretending the session ID is a unique lifecycle event. Claude Stop
        # payloads likewise omit an event ID, but do provide the exact final
        # assistant message; its digest is a duplicate-safe boundary identity.
        if payload["hook_event_name"] == "SessionStart":
            # Five minutes is still bounded while avoiding a duplicate pair
            # straddling a short 30-second wall-clock bucket boundary.
            token = f"sessionstart-bucket:{int(time.time() // 300)}"
        elif payload["hook_event_name"] == "Stop" and isinstance(
            payload.get("last_assistant_message"), str
        ):
            message_digest = hashlib.sha256(
                payload["last_assistant_message"].encode("utf-8")
            ).hexdigest()
            token = f"stop-message:{message_digest}"
        else:
            raise ValueError("Lifecycle hook requires a native event ID or timestamp for duplicate-safe delivery")
    material = "\0".join((agent, session_id, payload["hook_event_name"], token))
    return f"event_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def _render_codex_result(event_name: str, summary: str) -> dict[str, Any]:
    """Render the event-specific output accepted by the native Codex client."""

    if event_name == "SessionStart":
        return {
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": summary,
            }
        }
    return {"systemMessage": summary}


def _tool_command(payload: dict[str, Any]) -> str | None:
    """Return the direct shell command from one native tool payload, when present."""

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return None
    for field in ("command", "cmd"):
        command = tool_input.get(field)
        if isinstance(command, str) and command.strip():
            return command
    return None


def _is_exact_acknowledgement_command(
    payload: dict[str, Any],
    *,
    session_id: str,
    active_message_ids: tuple[str, ...],
) -> bool:
    """Allow only one structurally exact mailbox acknowledgement shell command."""

    command = _tool_command(payload)
    if command is None:
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) != 5:
        return False
    interpreter, script, action, flag, raw_request = tokens
    if interpreter != "/usr/bin/python3":
        return False
    canonical_script = Path(__file__).resolve().parent / "coordination_messages.py"
    if Path(script).expanduser().resolve() != canonical_script.resolve():
        return False
    if action != "acknowledge" or flag != "--request-json":
        return False
    try:
        request = json.loads(raw_request)
    except json.JSONDecodeError:
        return False
    if not isinstance(request, dict) or set(request) - {
        "current_session_id",
        "message_id",
        "disposition",
        "note",
        "response_ref",
    }:
        return False
    return (
        request.get("current_session_id") == session_id
        and request.get("message_id") in active_message_ids
        and request.get("disposition") in {"accepted", "declined", "deferred", "information_only"}
        and isinstance(request.get("note"), str)
        and bool(request["note"].strip())
    )


def _is_mutation_boundary(payload: dict[str, Any]) -> bool:
    """Return whether a PreToolUse callback represents a common mutation tool."""

    tool_name = payload.get("tool_name")
    return isinstance(tool_name, str) and tool_name.strip().lower() in MUTATION_TOOL_NAMES


def _render_boundary_denial(event_name: str, summary: str) -> dict[str, Any]:
    """Render a native blocking decision for mutation or final-response boundaries."""

    if event_name == "Stop":
        return {"decision": "block", "reason": summary}
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": summary,
        }
    }


def _is_completion_shaped_stop(payload: dict[str, Any]) -> bool:
    """Classify an explicit completion protocol without interpreting free prose.

    New adapters may supply ``completion_attempt`` directly.  The Codex Stop
    payload currently lacks that field, so retain two bounded compatibility
    shapes: a whole-message completion token and the workspace closing
    report's explicit ``Recommended next`` field.  Status updates and questions
    have neither shape and therefore remain unaffected.
    """

    explicit = payload.get("completion_attempt")
    if isinstance(explicit, bool):
        return explicit
    message = payload.get("last_assistant_message")
    if not isinstance(message, str):
        return False
    normalized_message = " ".join(message.casefold().split()).rstrip(".!:")
    if normalized_message in {"done", "complete", "completed"}:
        return True
    fence: tuple[str, int] | None = None
    for raw_line in message.splitlines():
        line = raw_line.strip()
        fence_character = line[0] if line.startswith(("`", "~")) else None
        fence_length = 0
        if fence_character is not None:
            fence_length = len(line) - len(line.lstrip(fence_character))
        if fence is None and fence_length >= 3:
            fence = (fence_character, fence_length)
            continue
        if fence is not None:
            opener_character, opener_length = fence
            if (
                fence_character == opener_character
                and fence_length >= opener_length
                and not line[fence_length:].strip()
            ):
                fence = None
            continue
        if line.startswith(("- ", "* ")):
            line = line[2:].lstrip()
        value: str | None = None
        if line.startswith("**"):
            closing = line.find("**", 2)
            if closing != -1:
                raw_label = line[2:closing].strip()
                label = raw_label.rstrip(":").strip().casefold()
                remainder = line[closing + 2 :]
                if label == "recommended next" and (
                    raw_label.endswith(":")
                    or remainder.startswith((" ", "\t", ":", "—", "-"))
                ):
                    value = remainder.lstrip(" \t:—-")
        else:
            for delimiter in (":", "—", " - "):
                if delimiter not in line:
                    continue
                label, candidate = line.split(delimiter, 1)
                if label.strip().casefold() == "recommended next":
                    value = candidate.strip()
                break
        if value is None:
            continue
        stripped_value = value.strip()
        if stripped_value.startswith("**") and stripped_value.endswith("**"):
            stripped_value = stripped_value[2:-2].strip()
        normalized_value = " ".join(stripped_value.casefold().split()).rstrip(".!:")
        return normalized_value in {
            "complete",
            "completed",
            "clear this goal",
            "goal complete",
        }
    return False


def main(argv: list[str] | None = None) -> int:
    """Refresh matching claim state and expose requests to the native session."""

    args = parse_args(argv)
    if args.repair_projection_only:
        result = _repair_projection_under_lock(
            (args.claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve()
        )
        print(json.dumps(result, sort_keys=True))
        return 0
    invocation: HookInvocation | None = None
    telemetry_decision = "warn"
    telemetry_reason = "hook_unavailable"
    try:
        payload = _read_hook_input(project_supplied=args.project is not None)
        completion_attempt = _is_completion_shaped_stop(payload)
        if (
            payload["hook_event_name"] == "Stop"
            and payload.get("stop_hook_active")
            and not completion_attempt
        ):
            # A non-completion re-fire must be infallibly allowed. Run this
            # before receipts, projections, mailbox access, or repository
            # closeout so stale state cannot recreate the refusal loop. An
            # explicit completion attempt remains criterion-bound below.
            print("{}")
            return 0
        hook_receipt_dir = args.hook_receipt_dir or (
            args.root.expanduser().resolve().parent / "hook-invocations-v1"
            if args.root is not None
            else DEFAULT_RECEIPT_ROOT
        )
        invocation = start_hook_invocation(
            hook_name="coordination-lifecycle",
            hook_version="2",
            script_path=Path(__file__).resolve(),
            payload=payload,
            receipt_root=hook_receipt_dir,
        )
        telemetry_decision = "allow"
        telemetry_reason = "no_active_boundary"
        session_id = _session_id(args.agent, payload["session_id"])
        event_name = payload["hook_event_name"]
        execution_decision = mailbox_execution_identity.classify_hook_execution(
            payload,
            client=args.agent,
        )
        primary_execution = execution_decision.role == "primary"
        if not primary_execution:
            telemetry_reason = "secondary_execution_callback"
        projection_warning: str | None = None
        if event_name == "SessionStart":
            # Startup and the latency-sensitive pre-tool boundary are advisory.
            # Neither may synchronously scan, heartbeat, or rebuild a
            # completed-claim-heavy registry.
            active_claims, projection_warning = _startup_claims(args.claims_dir)
        elif event_name == "PreToolUse":
            active_claims = ()
        elif event_name == "Stop":
            try:
                active_claims = _active_claims(args.claims_dir, turn_end=True)
            except TurnEndProjectionError as exc:
                active_claims = ()
                projection_warning = f"turn-end claim projection unavailable after bounded repair: {exc}"
        else:
            active_claims = _active_claims(args.claims_dir)
        closeout_ledger_dir = args.closeout_ledger_dir or (
            (args.claims_dir or coordination_claims.CLAIMS_DIR).expanduser().resolve().parent
            / "repository-closeout-ledgers"
        )
        if primary_execution and (payload["hook_event_name"] == "SessionStart" or (
            payload["hook_event_name"] == "PreToolUse" and _is_mutation_boundary(payload)
        )):
            _write_closeout_baseline(
                payload=payload,
                agent=args.agent,
                session_id=session_id,
                ledger_dir=closeout_ledger_dir,
            )
        if (
            primary_execution
            and payload["hook_event_name"] == "PreToolUse"
            and _is_mutation_boundary(payload)
        ):
            _record_touched_repositories(
                payload=payload,
                agent=args.agent,
                session_id=session_id,
                ledger_dir=closeout_ledger_dir,
                active_claims=active_claims,
            )
        project = args.project or _canonical_project(payload["cwd"])
        outcome_stop_decisions = ()
        if primary_execution and event_name == "Stop" and completion_attempt:
            # Resolve activation and the canonical decision before ancillary
            # mailbox/closeout work. If those later fail, the exception path
            # can fail closed only for a repository where completion
            # enforcement is actually applicable.
            outcome_stop_decisions = _outcome_stop_decisions(
                payload=payload,
                agent=args.agent,
                session_id=session_id,
                cwd_project=project,
                active_claims=active_claims,
            )
        delivery_event_id = _delivery_event_id(payload, agent=args.agent, session_id=session_id)
        startup_claim_summary = (
            _startup_claim_summary(
                agent=args.agent,
                session_id=session_id,
                project=project,
                claims=active_claims,
            )
            if event_name == "SessionStart"
            else None
        )
        # PreToolUse is a latency-sensitive decision boundary. Heartbeat writes
        # take the registry lock and refresh the full projection; lifecycle
        # events keep leases fresh without putting that work before every tool.
        heartbeat_projects = () if not primary_execution or payload["hook_event_name"] in {"SessionStart", "PreToolUse", "Stop"} else (
            (project,)
            if project is not None
            else _claimed_projects(
                agent=args.agent,
                session_id=session_id,
                active_claims=active_claims,
            )
        )
        for heartbeat_project in heartbeat_projects:
            coordination_claims.heartbeat_claims(
                agent=args.agent,
                project=heartbeat_project,
                session_id=session_id,
                claims_dir=args.claims_dir,
                require_exact_session=True,
            )
        if primary_execution:
            notice = coordination_messages.poll_session_inbox(
                agent=args.agent,
                project=project,
                session_id=session_id,
                # PostToolUse output is advisory hook emission, not evidence
                # that the model-visible primary execution observed it.
                observe=payload["hook_event_name"] != "PostToolUse",
                claims_dir=args.claims_dir,
                root=args.root,
                # Gate events must re-read canonical active state on every callback.
                # Native display suppression is appropriate only for advisory events.
                delivery_event_id=(
                    None if payload["hook_event_name"] in {"PreToolUse", "Stop"} else delivery_event_id
                ),
                require_live_claim=False,
            )
        else:
            # A same-session secondary execution must not inspect, observe, or
            # block the primary execution's inbox.
            notice = coordination_messages.SessionInboxNotice(
                session_id=session_id,
                project=project,
                active_count=0,
                message_ids=(),
                summary="",
            )
        closeout_failure = None
        if (
            primary_execution
            and payload["hook_event_name"] == "Stop"
            and not _repository_closeout_gate_disabled()
        ):
            closeout_failure = _repository_closeout_failure(
                agent=args.agent,
                session_id=session_id,
                ledger_dir=closeout_ledger_dir,
                active_claims=active_claims,
            )
        outcome_stop_denials = tuple(
            decision for decision in outcome_stop_decisions if not decision.allow_stop
        )
        boundary_event: Literal["PreToolUse", "Stop"] | None = None
        if (
            (
                notice.active_count
                or closeout_failure
                or outcome_stop_denials
            )
            and payload["hook_event_name"] == "Stop"
            and (not payload.get("stop_hook_active") or outcome_stop_denials)
        ):
            # Mailbox and closeout denials retain the one-block safeguard: the
            # harness re-fires Stop after a block, and refusing those unchanged
            # bookkeeping states only deadlocks the session. Criterion-bound
            # completion is different: every explicit completion attempt must
            # remain unavailable until the accepted transition exists.
            boundary_event = "Stop"
        elif (
            notice.active_count
            and payload["hook_event_name"] == "PreToolUse"
            and _is_mutation_boundary(payload)
            and not _is_exact_acknowledgement_command(
                payload,
                session_id=session_id,
                active_message_ids=notice.message_ids,
            )
        ):
            boundary_event = "PreToolUse"
        if boundary_event is not None:
            if notice.message_ids:
                store = coordination_messages.CoordinationMessageStore(
                    root=args.root or coordination_messages.default_message_root(args.claims_dir or coordination_claims.CLAIMS_DIR),
                    claims_dir=args.claims_dir or coordination_claims.CLAIMS_DIR,
                )
                tool_name = payload.get("tool_name") if boundary_event == "PreToolUse" else None
                store.record_boundary_block(
                    current_session_id=session_id,
                    message_ids=notice.message_ids,
                    hook_event_name=boundary_event,
                    delivery_event_id=delivery_event_id,
                    tool_name=tool_name if isinstance(tool_name, str) else None,
                )
            telemetry_decision = "block"
            telemetry_reason = (
                "turn_end_repository_dirty"
                if closeout_failure
                else (
                    outcome_stop_denials[0].reason_code
                    if outcome_stop_denials
                    else "active_mailbox_request"
                )
            )
            denial_parts = [
                part
                for part in (
                    notice.summary,
                    closeout_failure,
                    *(decision.summary for decision in outcome_stop_denials),
                )
                if part
            ]
            denial_parts.append(f"Hook receipt: {invocation.receipt_id}.")
            print(json.dumps(_render_boundary_denial(boundary_event, "\n\n".join(denial_parts))))
            return 0
        if projection_warning:
            telemetry_decision = "warn"
            telemetry_reason = "turn_end_projection_unavailable"
        summaries = [notice.summary] if notice.active_count or notice.acknowledgement_count else []
        if startup_claim_summary:
            summaries.append(startup_claim_summary)
        if projection_warning:
            summaries.append(projection_warning)
        if summaries:
            summary = "\n\n".join(summaries)
            if args.agent == "codex":
                print(json.dumps(_render_codex_result(payload["hook_event_name"], summary)))
            else:
                print(summary)
    except (
        RepositoryCloseoutError,
        coordination_messages.CoordinationMessageError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        closeout_failure = isinstance(exc, RepositoryCloseoutError)
        prefix = (
            "turn-end repository safety unavailable"
            if closeout_failure
            else "coordination mailbox unavailable"
        )
        warning = f"{prefix}: {type(exc).__name__}: {exc}"
        telemetry_reason = (
            "turn_end_repository_safety_unavailable"
            if closeout_failure
            else "coordination_mailbox_unavailable"
        )
        # One condition now decides both what is emitted and what is recorded.
        # They used to be computed separately, and the receipt said `block` for
        # every closeout failure while only `Stop` rendered a denial -- so a
        # PostToolUse failure printed a warning, returned 0, blocked nothing, and
        # was filed as a block. 164 of the 171 blocks across three runs read on
        # 2026-09-06 were that, and a governance record that overstates what it
        # refused is worse than none: it is the number someone quotes.
        stop_failure = (
            "payload" in locals() and payload.get("hook_event_name") == "Stop"
        )
        denies = bool(
            stop_failure
            and (
                closeout_failure
                or (
                    "completion_attempt" in locals()
                    and completion_attempt
                    and "outcome_stop_decisions" in locals()
                    and any(
                        decision.applicable for decision in outcome_stop_decisions
                    )
                )
            )
        )
        telemetry_decision = "block" if denies else "warn"
        if denies:
            print(json.dumps(_render_boundary_denial("Stop", warning)))
        else:
            print(json.dumps({"systemMessage": warning}))
    finally:
        if invocation is not None:
            invocation.complete(decision=telemetry_decision, reason_code=telemetry_reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
