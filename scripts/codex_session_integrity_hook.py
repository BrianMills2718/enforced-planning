#!/usr/bin/env python3
"""Non-blocking SessionStart warning for malformed Codex session JSONL logs."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from codex_session_integrity import find_session_file, inspect_session_jsonl


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions-root", type=Path, default=Path("~/.codex/sessions"))
    parser.add_argument("--session-file", type=Path, help="Explicit file for a one-off diagnostic or focused test.")
    parser.add_argument("--report", type=Path, help="Write a metadata-only report; never writes the session log.")
    return parser.parse_args(argv)


def read_event() -> dict[str, Any]:
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "SessionStart":
        raise ValueError("integrity guard only accepts SessionStart")
    session_id = payload.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("hook input requires a non-empty session_id")
    return payload


def display_path(path: Path) -> str:
    home = Path.home().resolve()
    resolved = path.expanduser().resolve()
    try:
        return f"~/{resolved.relative_to(home)}"
    except ValueError:
        return str(resolved)


def warning_context(session_file: Path, report: Any) -> str:
    first = report.issues[0]
    suffix = "" if len(report.issues) == 1 else f"; {len(report.issues) - 1} additional malformed record(s) found"
    return (
        "CODEX SESSION INTEGRITY WARNING: "
        f"{display_path(session_file)} line {first.line}, byte offset {first.byte_offset}: {first.kind} ({first.detail}){suffix}. "
        "This guard did not modify the session log and cannot repair Codex host persistence. "
        "Do not trust resumed history after this point: preserve the original file and start a fresh session. "
        "For a metadata-only diagnostic, run scripts/codex_session_integrity_hook.py --session-file <path> --report <path>."
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        payload = read_event()
        session_file = args.session_file or find_session_file(args.sessions_root, payload["session_id"])
        if session_file is None:
            return 0
        report = inspect_session_jsonl(session_file)
        if args.report:
            report_path = args.report.expanduser().resolve()
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_path.write_text(json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n", encoding="utf-8")
        if report.is_clean:
            return 0
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": warning_context(session_file, report)}}))
        return 0
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        # A warning must not prevent Codex from starting, but it must be visible.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": f"CODEX SESSION INTEGRITY GUARD UNAVAILABLE: {type(exc).__name__}: {exc}. No session log was modified."}}))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
