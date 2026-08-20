#!/usr/bin/env python3
"""Require a learning disposition when an agent reports completed work.

The hook does not try to decide whether a reusable learning exists. It enforces
the observable boundary around that judgment: a completed-work report must say
either where the learning was recorded or why no cross-agent learning emerged.
Each accepted or blocked disposition leaves a small machine-local receipt. The
portable framework owns this client-neutral lifecycle adapter; Project Meta owns
the learning register and policy.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_STATE_DIR = Path("~/.claude/coordination/learning-capture-v1")
SUPPORTED_AGENTS = ("claude-code", "codex")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse the client identity and deterministic state override."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=SUPPORTED_AGENTS, required=True)
    parser.add_argument("--state-dir", type=Path, default=DEFAULT_STATE_DIR)
    return parser.parse_args(argv)


def read_event() -> dict[str, Any]:
    """Read the shared subset of native Claude Code and Codex Stop payloads."""
    payload = json.loads(sys.stdin.read())
    if not isinstance(payload, dict):
        raise TypeError("hook input must be a JSON object")
    if payload.get("hook_event_name") != "Stop":
        raise ValueError("learning capture hook requires hook_event_name=Stop")
    for field in ("session_id", "last_assistant_message"):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise ValueError(f"Stop payload requires non-empty {field!r}")
    return payload


def report_field(report: str, name: str) -> str | None:
    """Return one CommonMark closing-report bullet by bold field name."""
    pattern = rf"[-*]\s*\*\*{re.escape(name)}\*\*\s*[-—:]?\s*(.+?)(?=\n[-*]\s*\*\*|\Z)"
    match = re.search(pattern, report, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else None


def classify_report(report: str) -> tuple[str, str]:
    """Return ``(decision, detail)`` for one final assistant report."""
    if report_field(report, "Done") is None:
        return "not_completed_work", "No completed-work report was present."

    disposition = report_field(report, "Learnings")
    if disposition is None:
        return (
            "block_missing",
            (
                "Completed work requires a Learnings disposition: record a reusable finding or lesson "
                "through /learned and cite project-meta/learnings.md, or state "
                "`None — <specific reason>`. "
            ),
        )

    normalized = disposition.strip().strip("*_ ")
    if re.match(r"^recorded\b", normalized, re.IGNORECASE):
        if "learnings.md" not in normalized.casefold():
            return (
                "block_unverifiable_record",
                "A `Recorded` learning disposition must cite the canonical project-meta/learnings.md register.",
            )
        return "recorded", normalized

    none_match = re.match(r"^(none|no reusable learning)\b(?:\s*[-—:]\s*)?(.*)$", normalized, re.IGNORECASE | re.DOTALL)
    if none_match:
        reason = none_match.group(2).strip()
        if len(reason) < 20:
            return (
                "block_empty_none",
                (
                    "A `None` learning disposition requires a concrete reason of at least 20 characters; "
                    "do not use it as an empty bypass."
                ),
            )
        return "none", reason

    return (
        "block_invalid",
        (
            "Learnings must start with `Recorded` and cite project-meta/learnings.md, or start with "
            "`None` and give a concrete reason."
        ),
    )


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    """Write one private receipt atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
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


def write_receipt(
    *,
    state_dir: Path,
    agent: str,
    session_id: str,
    report: str,
    decision: str,
    detail: str,
) -> Path:
    """Persist one digest-addressed disposition without storing transcript text."""
    state_root = state_dir.expanduser().resolve()
    session_digest = hashlib.sha256(f"{agent}\0{session_id}".encode()).hexdigest()[:32]
    report_digest = hashlib.sha256(report.encode()).hexdigest()
    receipt_path = state_root / session_digest / f"{report_digest[:32]}.json"
    lock_path = state_root / f".{session_digest}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        os.chmod(lock_path, 0o600)
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
        _atomic_write(
            receipt_path,
            {
                "schema_version": 1,
                "agent": agent,
                "session_id_sha256": hashlib.sha256(session_id.encode()).hexdigest(),
                "report_sha256": report_digest,
                "decision": decision,
                "detail": detail[:500],
                "observed_at": datetime.now(UTC).isoformat(),
            },
        )
    return receipt_path


def main(argv: list[str] | None = None) -> int:
    """Block an incomplete learning disposition and record the observed result."""
    args = parse_args(argv)
    try:
        payload = read_event()
        report = payload["last_assistant_message"]
        decision, detail = classify_report(report)
        if decision != "not_completed_work":
            write_receipt(
                state_dir=args.state_dir,
                agent=args.agent,
                session_id=payload["session_id"],
                report=report,
                decision=decision,
                detail=detail,
            )
        if decision.startswith("block_"):
            print(json.dumps({"decision": "block", "reason": detail}))
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        reason = f"learning-capture gate unavailable: {type(exc).__name__}: {exc}"
        print(json.dumps({"decision": "block", "reason": reason}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
