#!/usr/bin/env python3
"""Expose canonical mailbox requests through native Codex lifecycle hooks."""

from __future__ import annotations

import argparse
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
    return parser.parse_args(argv)


def _read_hook_input() -> dict[str, Any]:
    """Read and validate the common native Codex hook fields from stdin."""

    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise ValueError("Codex hook input must be a JSON object")
    for field in ("session_id", "cwd", "hook_event_name"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"Codex hook input requires non-empty {field!r}")
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


def _session_id(raw_session_id: str) -> str:
    """Normalize the native Codex UUID into the canonical claim identity."""

    return raw_session_id if raw_session_id.startswith("codex:") else f"codex:{raw_session_id}"


def _render_result(event_name: str, summary: str) -> dict[str, Any]:
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
        payload = _read_hook_input()
        project = _canonical_project(payload["cwd"])
        session_id = _session_id(payload["session_id"])
        _updated_count, _updated_scopes, _resolved_session_id, _heartbeat_at = (
            coordination_claims.heartbeat_claims(
                agent="codex",
                project=project,
                session_id=session_id,
                claims_dir=args.claims_dir,
                require_exact_session=True,
            )
        )
        notice = coordination_messages.poll_session_inbox(
            agent="codex",
            project=project,
            session_id=session_id,
            observe=True,
            claims_dir=args.claims_dir,
            root=args.root,
            require_live_claim=False,
        )
        if notice.active_count:
            print(json.dumps(_render_result(payload["hook_event_name"], notice.summary)))
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
