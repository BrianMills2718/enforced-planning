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
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator, Literal

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
    prewrite_claim_fast,
    prewrite_claim_projection,
)

SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "PreToolUse", "Stop"}
MUTATION_TOOL_NAMES = frozenset({"bash", "apply_patch", "edit", "write"})
REPOSITORY_SCAN_MAX_WORKERS = 16
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
        raise ValueError("Lifecycle hook input must be a JSON object")
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


def _repair_turn_end_projection(claims_dir: Path) -> dict[str, Any]:
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
            timeout=TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        last_phase = _repair_phase(exc.stderr)
        raise TurnEndProjectionError(
            f"claim projection repair exceeded {TURN_END_PROJECTION_REPAIR_TIMEOUT_SECONDS:g}s "
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

    repaired = False
    if turn_end and (not projection_path.is_file() or _projection_has_registry_change(projection_path, resolved)):
        _repair_turn_end_projection(resolved)
        repaired = True
    if projection_path.is_file():
        try:
            projection = load_projection()
        except TurnEndProjectionError:
            if not turn_end or repaired:
                raise
            _repair_turn_end_projection(resolved)
            repaired = True
            projection = load_projection()
        registry_digest = prewrite_claim_fast.registry_digest(resolved)
        if projection.registry_digest != registry_digest:
            if turn_end and not repaired:
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
    if isinstance(cwd, str) and cwd.strip():
        if _canonical_repository_root(cwd) is not None:
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


def main(argv: list[str] | None = None) -> int:
    """Refresh matching claim state and expose requests to the native session."""

    args = parse_args(argv)
    emitted_output: list[str] = []

    def emit(value: str) -> None:
        emitted_output.append(value + "\n")
        print(value)

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
        if payload["hook_event_name"] == "Stop" and payload.get("stop_hook_active"):
            # A re-fired Stop must be infallibly allowed. Run this before
            # receipts, projections, mailbox access, or repository closeout so
            # no stale or unavailable state can recreate the refusal loop.
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
        if payload["hook_event_name"] == "SessionStart" or (
            payload["hook_event_name"] == "PreToolUse" and _is_mutation_boundary(payload)
        ):
            _write_closeout_baseline(
                payload=payload,
                agent=args.agent,
                session_id=session_id,
                ledger_dir=closeout_ledger_dir,
            )
        if payload["hook_event_name"] == "PreToolUse" and _is_mutation_boundary(payload):
            _record_touched_repositories(
                payload=payload,
                agent=args.agent,
                session_id=session_id,
                ledger_dir=closeout_ledger_dir,
                active_claims=active_claims,
            )
        delivery_event_id = _delivery_event_id(payload, agent=args.agent, session_id=session_id)
        project = args.project or _canonical_project(payload["cwd"])
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
        heartbeat_projects = () if payload["hook_event_name"] in {"SessionStart", "PreToolUse", "Stop"} else (
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
        notice = coordination_messages.poll_session_inbox(
            agent=args.agent,
            project=project,
            session_id=session_id,
            observe=True,
            claims_dir=args.claims_dir,
            root=args.root,
            # Gate events must re-read canonical active state on every callback.
            # Native display suppression is appropriate only for advisory events.
            delivery_event_id=(
                None if payload["hook_event_name"] in {"PreToolUse", "Stop"} else delivery_event_id
            ),
            require_live_claim=False,
        )
        closeout_failure = None
        if payload["hook_event_name"] == "Stop":
            closeout_failure = _repository_closeout_failure(
                agent=args.agent,
                session_id=session_id,
                ledger_dir=closeout_ledger_dir,
                active_claims=active_claims,
            )
        boundary_event: Literal["PreToolUse", "Stop"] | None = None
        if (
            (notice.active_count or closeout_failure)
            and payload["hook_event_name"] == "Stop"
            and not payload.get("stop_hook_active")
        ):
            # The harness re-fires Stop after a block. Refusing again cannot
            # change the condition, so a second refusal only deadlocks the
            # session: on 2026-08-28 this gate blocked one session ~20
            # consecutive times on 11 files written by sessions that had
            # already ended. Block once; the bookkeeping above still runs.
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
                "turn_end_repository_dirty" if closeout_failure else "active_mailbox_request"
            )
            denial_parts = [part for part in (notice.summary, closeout_failure) if part]
            denial_parts.append(f"Hook receipt: {invocation.receipt_id}.")
            emit(json.dumps(_render_boundary_denial(boundary_event, "\n\n".join(denial_parts))))
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
                emit(json.dumps(_render_codex_result(payload["hook_event_name"], summary)))
            else:
                emit(summary)
    except (
        RepositoryCloseoutError,
        coordination_messages.CoordinationMessageError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        prefix = (
            "turn-end repository safety unavailable"
            if isinstance(exc, RepositoryCloseoutError)
            else "coordination mailbox unavailable"
        )
        warning = f"{prefix}: {type(exc).__name__}: {exc}"
        telemetry_decision = "block" if isinstance(exc, RepositoryCloseoutError) else "warn"
        telemetry_reason = (
            "turn_end_repository_safety_unavailable"
            if isinstance(exc, RepositoryCloseoutError)
            else "coordination_mailbox_unavailable"
        )
        if (
            isinstance(exc, RepositoryCloseoutError)
            and "payload" in locals()
            and payload.get("hook_event_name") == "Stop"
        ):
            emit(json.dumps(_render_boundary_denial("Stop", warning)))
        else:
            emit(json.dumps({"systemMessage": warning}))
    finally:
        if invocation is not None:
            invocation.complete(
                decision=telemetry_decision,
                reason_code=telemetry_reason,
                output="".join(emitted_output),
                client=args.agent,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
