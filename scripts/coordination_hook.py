#!/usr/bin/env python3
"""Expose canonical mailbox requests through native Codex lifecycle hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
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

from enforced_planning import coordination_claims, coordination_messages

SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse", "PreToolUse", "Stop"}
MUTATION_TOOL_NAMES = frozenset({"bash", "apply_patch", "edit", "write"})
REPOSITORY_SCAN_SKIP_DIRS = frozenset(
    {".git", ".venv", "node_modules", "worktrees", ".recovery-worktrees"}
)
REPOSITORY_SCAN_MAX_DEPTH = 5
REPOSITORY_SCAN_MAX_WORKERS = 16


class RepositoryCloseoutError(RuntimeError):
    """Raised when repository closeout evidence cannot be collected safely."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse test and rollout overrides without changing the hook wire format."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
    parser.add_argument("--closeout-ledger-dir", type=Path)
    parser.add_argument("--hook-receipt-dir", type=Path, default=DEFAULT_RECEIPT_ROOT)
    parser.add_argument("--agent", choices=("codex", "claude-code"), default="codex")
    parser.add_argument("--project", help="Canonical project override supplied by a repository compatibility hook.")
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


def _discover_repositories(scan_root: Path) -> tuple[Path, ...]:
    """Discover canonical repositories without descending into linked worktrees."""

    if not scan_root.is_dir():
        raise RepositoryCloseoutError(f"repository scan root is not a directory: {scan_root}")
    repositories: set[Path] = set()
    for current, directory_names, file_names in os.walk(scan_root):
        current_path = Path(current)
        depth = len(current_path.relative_to(scan_root).parts)
        if ".git" in directory_names or (
            current_path == scan_root and ".git" in file_names
        ):
            repositories.add(current_path.resolve())
        if depth >= REPOSITORY_SCAN_MAX_DEPTH:
            directory_names[:] = []
            continue
        directory_names[:] = [
            name for name in directory_names if name not in REPOSITORY_SCAN_SKIP_DIRS
        ]
    return tuple(sorted(repositories))


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


def _repository_snapshot(
    scan_root: Path,
    *,
    excluded_repositories: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Capture status fingerprints for every canonical repository in scope."""

    excluded = excluded_repositories or set()
    repositories = tuple(
        repository
        for repository in _discover_repositories(scan_root)
        if str(repository) not in excluded
    )
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
        "repositories": _repository_snapshot(scan_root),
    }
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = ledger_path.with_suffix(".tmp")
    temporary.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(ledger_path)


def _repositories_with_foreign_live_claims(session_id: str) -> set[str]:
    """Repository roots a DIFFERENT live session currently holds a claim on.

    The closeout check compares a whole-repository fingerprint against a
    baseline taken at session start, so any concurrent writer's uncommitted
    edit is attributed to whichever session closes out first. That session
    cannot commit the change (not its work), cannot discard it (destructive),
    and has no way to disclaim it - so it is blocked by someone else's work
    with no available remedy.

    A live claim owned by another session is exactly the evidence that a repo
    has a second writer. Returning those roots lets closeout skip them. This
    narrows the check rather than weakening it: a repository with no other
    live writer is still fully enforced, which is the case the check is for.
    """

    try:
        from enforced_planning import coordination_claims
    except ImportError:  # pragma: no cover - claim surface optional in some installs
        return set()
    roots: set[str] = set()
    try:
        claims = coordination_claims.list_claims()
    except Exception:  # noqa: BLE001 - an unreadable claim registry must not block closeout
        return set()
    for claim in claims:
        if getattr(claim, "session_id", None) == session_id:
            continue
        repo_root = getattr(claim, "repo_root", None)
        if repo_root:
            roots.add(str(Path(str(repo_root)).expanduser().resolve()))
    return roots


def _repository_closeout_failure(
    *,
    agent: str,
    session_id: str,
    ledger_dir: Path,
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
    scan_root = Path(str(payload.get("scan_root", ""))).expanduser().resolve()
    baseline = payload["repositories"]
    foreign = _repositories_with_foreign_live_claims(session_id)
    current = _repository_snapshot(scan_root, excluded_repositories=foreign)
    dirty_changes: list[tuple[str, int]] = []
    for repository, status in current.items():
        prior = baseline.get(repository)
        if str(Path(repository).expanduser().resolve()) in foreign:
            # Another live session is writing here; its uncommitted work is not
            # this session's to commit, discard, or answer for.
            continue
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
        "Repository closeout blocked: this session changed repository state and left it dirty: "
        f"{rendered}. Commit and push the coherent work, restore it to the recorded baseline, "
        "or use the sanctioned session-close dirty-handoff path before sending a final response."
    )


def _claimed_projects(*, agent: str, session_id: str, claims_dir: Path | None) -> tuple[str, ...]:
    """Return exact-session live claim projects without adopting another lane."""

    claims = coordination_claims.check_claims(claims_dir=claims_dir)
    return tuple(
        sorted(
            {
                project
                for claim in claims
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
            token = f"sessionstart-bucket:{int(time.time() // 30)}"
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
    if Path(interpreter).name not in {"python", "python3"}:
        return False
    if not script.replace("\\", "/").endswith("scripts/meta/coordination_messages.py"):
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
    invocation: HookInvocation | None = None
    telemetry_decision = "warn"
    telemetry_reason = "hook_unavailable"
    try:
        payload = _read_hook_input(project_supplied=args.project is not None)
        invocation = start_hook_invocation(
            hook_name="coordination-lifecycle",
            hook_version="2",
            script_path=Path(__file__).resolve(),
            payload=payload,
            receipt_root=args.hook_receipt_dir,
        )
        telemetry_decision = "allow"
        telemetry_reason = "no_active_boundary"
        session_id = _session_id(args.agent, payload["session_id"])
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
        delivery_event_id = _delivery_event_id(payload, agent=args.agent, session_id=session_id)
        project = args.project or _canonical_project(payload["cwd"])
        heartbeat_projects = (project,) if project is not None else _claimed_projects(
            agent=args.agent,
            session_id=session_id,
            claims_dir=args.claims_dir,
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
            )
        boundary_event: Literal["PreToolUse", "Stop"] | None = None
        if (notice.active_count or closeout_failure) and payload["hook_event_name"] == "Stop":
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
                    root=args.root or coordination_messages.default_message_root(args.claims_dir),
                    claims_dir=args.claims_dir,
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
                "repository_closeout_dirty" if closeout_failure else "active_mailbox_request"
            )
            denial_parts = [part for part in (notice.summary, closeout_failure) if part]
            denial_parts.append(f"Hook receipt: {invocation.receipt_id}.")
            print(json.dumps(_render_boundary_denial(boundary_event, "\n\n".join(denial_parts))))
            return 0
        if notice.active_count or notice.acknowledgement_count:
            if args.agent == "codex":
                print(json.dumps(_render_codex_result(payload["hook_event_name"], notice.summary)))
            else:
                print(notice.summary)
    except (
        RepositoryCloseoutError,
        coordination_messages.CoordinationMessageError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        prefix = (
            "repository closeout unavailable"
            if isinstance(exc, RepositoryCloseoutError)
            else "coordination mailbox unavailable"
        )
        warning = f"{prefix}: {type(exc).__name__}: {exc}"
        telemetry_decision = "block" if isinstance(exc, RepositoryCloseoutError) else "warn"
        telemetry_reason = (
            "repository_closeout_unavailable"
            if isinstance(exc, RepositoryCloseoutError)
            else "coordination_mailbox_unavailable"
        )
        if (
            isinstance(exc, RepositoryCloseoutError)
            and "payload" in locals()
            and payload.get("hook_event_name") == "Stop"
        ):
            print(json.dumps(_render_boundary_denial("Stop", warning)))
        else:
            print(json.dumps({"systemMessage": warning}))
    finally:
        if invocation is not None:
            invocation.complete(decision=telemetry_decision, reason_code=telemetry_reason)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
