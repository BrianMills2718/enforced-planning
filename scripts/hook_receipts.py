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


class HookReceiptError(ValueError):
    """Raised when persisted hook evidence is incomplete or malformed."""


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


def load_completed_receipts(receipt_root: Path = DEFAULT_RECEIPT_ROOT) -> tuple[dict[str, Any], ...]:
    """Load strict content-free completion receipts in stable evidence order."""

    root = receipt_root.expanduser().resolve()
    if not root.exists():
        return ()
    required = {
        "schema_version": int,
        "record_type": str,
        "receipt_id": str,
        "hook_name": str,
        "hook_version": str,
        "phase": str,
        "decision": str,
        "reason_code": str,
        "event_name": str,
        "observed_at": str,
    }
    loaded: list[dict[str, Any]] = []
    for path in sorted(root.rglob("completed.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HookReceiptError(f"cannot read completed hook receipt {path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise HookReceiptError(f"completed hook receipt must be an object: {path}")
        for field, expected_type in required.items():
            value = payload.get(field)
            if not isinstance(value, expected_type) or (isinstance(value, str) and not value.strip()):
                raise HookReceiptError(f"completed hook receipt has invalid {field!r}: {path}")
        if payload["record_type"] != "hook_invocation_receipt" or payload["phase"] != "completed":
            raise HookReceiptError(f"completed hook receipt has invalid contract identity: {path}")
        if path.parent.name != payload["receipt_id"]:
            raise HookReceiptError(f"completed hook receipt path/identity mismatch: {path}")
        loaded.append(payload)
    return tuple(loaded)


def group_hook_recurrences(
    receipts: tuple[dict[str, Any], ...],
    *,
    threshold: int = 2,
) -> dict[str, Any]:
    """Group content-free episodes and retain exact receipt step-down evidence."""

    if threshold < 1:
        raise ValueError("recurrence threshold must be at least 1")
    grouped: dict[tuple[str, str, str, str, str], list[str]] = {}
    for receipt in receipts:
        key = (
            str(receipt["hook_name"]),
            str(receipt["hook_version"]),
            str(receipt["event_name"]),
            str(receipt["decision"]),
            str(receipt["reason_code"]),
        )
        grouped.setdefault(key, []).append(str(receipt["receipt_id"]))
    groups = []
    for key, receipt_ids in sorted(grouped.items()):
        hook_name, hook_version, event_name, decision, reason_code = key
        groups.append(
            {
                "hook_name": hook_name,
                "hook_version": hook_version,
                "event_name": event_name,
                "decision": decision,
                "reason_code": reason_code,
                "count": len(receipt_ids),
                "recurrent": len(receipt_ids) >= threshold,
                "receipt_ids": sorted(receipt_ids),
                "disposition_command": "make ecosystem-feedback ARGS='record ...'",
            }
        )
    return {
        "schema_version": 1,
        "record_type": "hook_feedback_recurrence_report",
        "threshold": threshold,
        "receipt_count": len(receipts),
        "groups": groups,
    }
