#!/usr/bin/env python3
"""Expose canonical mailbox requests through native Codex lifecycle hooks."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any


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
    raise RuntimeError(
        "Unable to locate a local enforced_planning package or "
        "scripts/_upstream_enforced_planning.py"
    )


_bootstrap_package()

from enforced_planning import coordination_claims, coordination_messages  # noqa: E402


SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit", "PostToolUse"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse test and rollout overrides without changing the hook wire format."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claims-dir", type=Path)
    parser.add_argument("--root", type=Path)
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


def _canonical_project(cwd: str) -> str:
    """Resolve a worktree cwd to the canonical repository project name."""

    top = subprocess.run(
        ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
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


def _session_id(agent: str, raw_session_id: str) -> str:
    """Normalize one native client session UUID into canonical claim identity."""

    return raw_session_id if raw_session_id.startswith(f"{agent}:") else f"{agent}:{raw_session_id}"


def _delivery_event_id(payload: dict[str, Any], *, agent: str, session_id: str) -> str:
    """Derive one client-neutral identity for a native lifecycle callback.

    Native turn/event IDs are preferred. A timestamp is only a compatibility
    fallback because it is weaker: adapters that receive neither must fail
    before they can create observation evidence.
    """

    for field in ("event_id", "turn_id", "tool_use_id", "tool_call_id", "timestamp"):
        value = payload.get(field)
        if isinstance(value, str) and value.strip():
            token = f"{field}:{value.strip()}"
            break
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


def main(argv: list[str] | None = None) -> int:
    """Refresh matching claim state and expose requests to the native session."""

    args = parse_args(argv)
    try:
        payload = _read_hook_input(project_supplied=args.project is not None)
        project = args.project or _canonical_project(payload["cwd"])
        session_id = _session_id(args.agent, payload["session_id"])
        delivery_event_id = _delivery_event_id(payload, agent=args.agent, session_id=session_id)
        _updated_count, _updated_scopes, _resolved_session_id, _heartbeat_at = (
            coordination_claims.heartbeat_claims(
                agent=args.agent,
                project=project,
                session_id=session_id,
                claims_dir=args.claims_dir,
                require_exact_session=True,
            )
        )
        notice = coordination_messages.poll_session_inbox(
            agent=args.agent,
            project=project,
            session_id=session_id,
            observe=True,
            claims_dir=args.claims_dir,
            root=args.root,
            delivery_event_id=delivery_event_id,
            require_live_claim=False,
        )
        if notice.active_count:
            if args.agent == "codex":
                print(json.dumps(_render_codex_result(payload["hook_event_name"], notice.summary)))
            else:
                print(notice.summary)
    except (
        coordination_messages.CoordinationMessageError,
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        warning = f"coordination mailbox unavailable: {type(exc).__name__}: {exc}"
        print(json.dumps({"systemMessage": warning}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
