#!/usr/bin/env python3
# scope: global_by_design - the pace/course-check pulse applies to every
# agent session regardless of which project it is working in; SUPPORTED_EVENTS
# deliberately spans SessionStart/UserPromptSubmit/PreToolUse/PostToolUse/Stop
"""Inject a periodic non-blocking goal-equivalence pulse into agent sessions."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

DEFAULT_INTERVAL_SECONDS = 45 * 60
MESSAGE = (
    "COURSE CHECK (advisory, non-blocking): What user-visible result changed in the last 45 minutes, "
    "and what single next action best advances the accepted outcome? If the current work is deliberate "
    "maintenance, diagnosis, or waiting, continue without ceremony. Otherwise, change reversible tactics "
    "when the honest answer is 'none'. Do not create a plan, report, or approval pause solely for this check."
)
SUPPORTED_EVENTS = {"SessionStart", "UserPromptSubmit", "PreToolUse", "PostToolUse", "Stop"}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse client and deterministic test overrides."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=("codex", "claude-code"), required=True)
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=Path("~/.claude/coordination/juice-checkpoints-v1"),
    )
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--now-epoch", type=float, help="Deterministic clock override for focused tests.")
    return parser.parse_args(argv)


def read_event() -> dict[str, Any]:
    """Read the minimal lifecycle fields shared by Codex and Claude hooks."""

    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("hook input must be a JSON object")
    for field in ("session_id", "hook_event_name"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"hook input requires non-empty {field!r}")
    if payload["hook_event_name"] not in SUPPORTED_EVENTS:
        raise ValueError(f"unsupported hook event: {payload['hook_event_name']}")
    return payload


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Replace one tiny session record without exposing a partial write."""

    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def checkpoint_due(
    *,
    agent: str,
    payload: dict[str, Any],
    state_dir: Path,
    interval_seconds: int,
    now_epoch: float,
) -> bool:
    """Advance state and report whether this natural boundary needs a reminder."""

    if interval_seconds <= 0:
        raise ValueError("interval must be positive")
    event_name = payload["hook_event_name"]
    if event_name not in {"SessionStart", "PostToolUse"}:
        return False

    resolved_state_dir = state_dir.expanduser().resolve()
    resolved_state_dir.mkdir(parents=True, exist_ok=True)
    key_material = f"{agent}\0{payload['session_id']}"
    session_key = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:32]
    state_path = resolved_state_dir / f"{session_key}.json"
    lock_path = resolved_state_dir / f".{session_key}.lock"

    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        if state_path.exists():
            state = json.loads(state_path.read_text(encoding="utf-8"))
            last_checkpoint_at = state.get("last_checkpoint_at")
            if not isinstance(last_checkpoint_at, int | float):
                raise ValueError(f"invalid checkpoint state: {state_path}")
        else:
            last_checkpoint_at = None

        if event_name == "SessionStart" or last_checkpoint_at is None or now_epoch < last_checkpoint_at:
            atomic_write_json(state_path, {"schema_version": 1, "last_checkpoint_at": now_epoch})
            return False
        if now_epoch - last_checkpoint_at < interval_seconds:
            return False

        atomic_write_json(state_path, {"schema_version": 1, "last_checkpoint_at": now_epoch})
        return True


def render(agent: str, event_name: str, message: str) -> str:
    """Render the client-native context injection envelope."""

    if agent == "codex":
        if event_name == "SessionStart":
            return json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "SessionStart",
                        "additionalContext": message,
                    }
                }
            )
        return json.dumps({"systemMessage": message})
    return json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": event_name,
                "additionalContext": message,
            }
        }
    )


def main(argv: list[str] | None = None) -> int:
    """Inject only when due; make state failures visible without blocking work."""

    args = parse_args(argv)
    event_name = "PostToolUse"
    try:
        payload = read_event()
        event_name = payload["hook_event_name"]
        if checkpoint_due(
            agent=args.agent,
            payload=payload,
            state_dir=args.state_dir,
            interval_seconds=args.interval_seconds,
            now_epoch=args.now_epoch if args.now_epoch is not None else time.time(),
        ):
            print(render(args.agent, event_name, MESSAGE))
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        warning = f"juice checkpoint unavailable: {type(exc).__name__}: {exc}"
        print(render(args.agent, event_name, warning))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
