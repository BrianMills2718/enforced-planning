"""Private, content-free lifecycle receipts shared by portable agent hooks."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RECEIPT_ROOT = Path("~/.claude/coordination/hook-invocations-v1")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


@dataclass(frozen=True)
class HookInvocation:
    """One hook invocation whose missing completion receipt proves interruption."""

    receipt_dir: Path
    base_payload: dict[str, Any]
    started_ns: int

    @property
    def receipt_id(self) -> str:
        return str(self.base_payload["receipt_id"])

    def complete(self, *, decision: str, reason_code: str, exit_status: int = 0) -> Path:
        payload = {
            **self.base_payload,
            "phase": "completed",
            "decision": decision,
            "reason_code": reason_code,
            "exit_status": exit_status,
            "elapsed_ms": round((time.monotonic_ns() - self.started_ns) / 1_000_000, 3),
            "observed_at": datetime.now(UTC).isoformat(),
        }
        path = self.receipt_dir / "completed.json"
        _atomic_write(path, payload)
        return path


def start_hook_invocation(
    *,
    hook_name: str,
    hook_version: str,
    script_path: Path,
    payload: dict[str, Any],
    receipt_root: Path = DEFAULT_RECEIPT_ROOT,
) -> HookInvocation:
    """Write a started receipt before expensive work or semantic classification."""

    started_ns = time.monotonic_ns()
    session_id = str(payload.get("session_id") or "unknown")
    correlation_id = str(
        payload.get("hook_run_id")
        or payload.get("hookRunId")
        or payload.get("event_id")
        or payload.get("turn_id")
        or ""
    )
    receipt_id = uuid.uuid4().hex
    session_digest = _digest(session_id)[:32]
    receipt_dir = receipt_root.expanduser().resolve() / session_digest / receipt_id
    report = payload.get("last_assistant_message")
    input_digest = _digest(json.dumps(payload, sort_keys=True, default=str))
    try:
        hook_digest = hashlib.sha256(script_path.read_bytes()).hexdigest()
    except OSError:
        hook_digest = None
    base = {
        "schema_version": 1,
        "record_type": "hook_invocation_receipt",
        "receipt_id": receipt_id,
        "hook_name": hook_name,
        "hook_version": hook_version,
        "hook_sha256": hook_digest,
        "session_id_sha256": _digest(session_id),
        "input_sha256": input_digest,
        "report_sha256": _digest(report) if isinstance(report, str) else None,
        "hook_run_id": correlation_id or None,
        "event_name": payload.get("hook_event_name"),
    }
    started = {
        **base,
        "phase": "started",
        "decision": None,
        "reason_code": None,
        "exit_status": None,
        "elapsed_ms": 0.0,
        "observed_at": datetime.now(UTC).isoformat(),
    }
    _atomic_write(receipt_dir / "started.json", started)
    return HookInvocation(receipt_dir=receipt_dir, base_payload=base, started_ns=started_ns)
