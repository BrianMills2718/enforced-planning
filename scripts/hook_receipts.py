"""Private, content-free lifecycle receipts shared by portable agent hooks."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from dataclasses import field as dataclasses_field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

DEFAULT_RECEIPT_ROOT = Path("~/.claude/coordination/hook-invocations-v1")
DEFAULT_PREWRITE_EVENT_PATH = Path("~/.claude/coordination/prewrite-events-v1.jsonl")
DEFAULT_SETTINGS_PATHS = (
    Path("~/.claude/settings.json"),
    Path("~/.claude/settings.local.json"),
)
# Fraction of a declared hook timeout above which measured p95 is flagged.
DEFAULT_TIMEOUT_BUDGET_FRACTION = 0.6
# Claude Code applies this timeout (seconds) when a hook entry declares none.
HARNESS_DEFAULT_TIMEOUT_SECONDS = 60
MAX_DETAIL_FIELDS = 12
MAX_DETAIL_KEY_LENGTH = 64
MAX_DETAIL_STRING_LENGTH = 256

COMPLETED_RECEIPT_FIELDS: dict[str, type | tuple[type, ...]] = {
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


class HookReceiptError(ValueError):
    """Raised when persisted hook evidence is incomplete or malformed."""


def _normalize_details(details: dict[str, Any] | None) -> dict[str, str | int | float | bool | None] | None:
    """Validate a small, flat diagnostic map suitable for the shared index.

    Details are deliberately not an arbitrary payload escape hatch: nested
    values, long strings, and unbounded key sets would recreate the private,
    expensive source-event store inside its content-free receipt projection.
    """

    if details is None:
        return None
    if not isinstance(details, dict):
        raise HookReceiptError("receipt details must be a mapping")
    if len(details) > MAX_DETAIL_FIELDS:
        raise HookReceiptError(f"receipt details exceed {MAX_DETAIL_FIELDS} fields")
    normalized: dict[str, str | int | float | bool | None] = {}
    for key, value in details.items():
        if not isinstance(key, str) or not key or len(key) > MAX_DETAIL_KEY_LENGTH:
            raise HookReceiptError("receipt detail keys must be non-empty bounded strings")
        if not isinstance(value, (str, int, float, bool)) and value is not None:
            raise HookReceiptError(f"receipt detail {key!r} must be a scalar")
        if isinstance(value, str) and len(value) > MAX_DETAIL_STRING_LENGTH:
            raise HookReceiptError(
                f"receipt detail {key!r} exceeds {MAX_DETAIL_STRING_LENGTH} characters"
            )
        if isinstance(value, float) and not math.isfinite(value):
            raise HookReceiptError(f"receipt detail {key!r} must be finite")
        normalized[key] = value
    return normalized


PREWRITE_EVENT_FIELDS: dict[str, type] = {
    "schema_version": str,
    "receipt_id": str,
    "client": str,
    "mode": str,
    "decision": str,
    "reason_code": str,
    "recorded_at": str,
}


def scan_prewrite_events(event_path: Path = DEFAULT_PREWRITE_EVENT_PATH) -> dict[str, Any]:
    """Scan the append-only prewrite JSONL store without hiding bad lines.

    Only content-free dimensions and exact receipt IDs leave this boundary.
    Paths, command details, and session identity remain in the source receipt.
    """

    resolved = event_path.expanduser()
    events: list[dict[str, str]] = []
    malformed: list[dict[str, Any]] = []
    if not resolved.exists():
        return {
            "event_path": str(resolved),
            "event_count": 0,
            "malformed_count": 0,
            "events": events,
            "malformed": malformed,
            "missing": True,
        }
    if not resolved.is_file():
        raise HookReceiptError(f"prewrite event path is not a file: {resolved}")

    with resolved.open("r", encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError as exc:
                malformed.append({"line": line_number, "reason": f"unparseable JSON: {exc.msg}"})
                continue
            if not isinstance(payload, dict):
                malformed.append({"line": line_number, "reason": "event must be one JSON object"})
                continue
            defect = next(
                (
                    f"invalid {field!r}"
                    for field, expected in PREWRITE_EVENT_FIELDS.items()
                    if not isinstance(payload.get(field), expected) or not str(payload[field]).strip()
                ),
                None,
            )
            if defect is not None:
                malformed.append({"line": line_number, "reason": defect})
                continue
            events.append({field: str(payload[field]) for field in PREWRITE_EVENT_FIELDS})

    return {
        "event_path": str(resolved),
        "event_count": len(events),
        "malformed_count": len(malformed),
        "events": events,
        "malformed": malformed,
        "missing": False,
    }


def group_prewrite_recurrences(event_scan: dict[str, Any], *, threshold: int = 2) -> dict[str, Any]:
    """Group prewrite decisions by stable content-free failure dimensions."""

    if threshold < 1:
        raise ValueError("threshold must be at least 1")
    grouped: dict[tuple[str, str, str, str], list[str]] = {}
    for event in event_scan["events"]:
        key = (event["client"], event["mode"], event["decision"], event["reason_code"])
        grouped.setdefault(key, []).append(event["receipt_id"])
    groups = [
        {
            "client": key[0],
            "mode": key[1],
            "decision": key[2],
            "reason_code": key[3],
            "count": len(receipt_ids),
            "recurrent": len(receipt_ids) >= threshold,
            "receipt_ids": sorted(receipt_ids),
            "disposition_command": "make ecosystem-feedback ARGS='record ...'",
        }
        for key, receipt_ids in sorted(grouped.items())
    ]
    return {
        "event_path": event_scan["event_path"],
        "event_count": event_scan["event_count"],
        "malformed_count": event_scan["malformed_count"],
        "malformed": event_scan["malformed"],
        "missing": event_scan["missing"],
        "threshold": threshold,
        "groups": groups,
    }


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

    def complete(
        self,
        *,
        decision: str,
        reason_code: str,
        exit_status: int = 0,
        details: dict[str, Any] | None = None,
    ) -> Path:
        normalized_details = _normalize_details(details)
        payload = {
            **self.base_payload,
            "phase": "completed",
            "decision": decision,
            "reason_code": reason_code,
            "exit_status": exit_status,
            "elapsed_ms": round((time.monotonic_ns() - self.started_ns) / 1_000_000, 3),
            "observed_at": datetime.now(UTC).isoformat(),
        }
        if normalized_details is not None:
            payload["details"] = normalized_details
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


def validate_completed_receipt(payload: Any, path: Path) -> str | None:
    """Return a human-readable defect reason, or None when the receipt is valid.

    This is the single definition of "well formed completed receipt". Both the
    strict loader and the resilient sweep use it so a record can never be
    accepted by one and rejected by the other.
    """

    if not isinstance(payload, dict):
        return "receipt is not a JSON object"
    for field_name, expected_type in COMPLETED_RECEIPT_FIELDS.items():
        value = payload.get(field_name)
        if not isinstance(value, expected_type) or (isinstance(value, str) and not value.strip()):
            return f"invalid {field_name!r} (got {type(value).__name__})"
    if payload["record_type"] != "hook_invocation_receipt" or payload["phase"] != "completed":
        return "invalid contract identity (record_type/phase)"
    if path.parent.name != payload["receipt_id"]:
        return "path/identity mismatch (directory name != receipt_id)"
    return None


def load_completed_receipts(receipt_root: Path = DEFAULT_RECEIPT_ROOT) -> tuple[dict[str, Any], ...]:
    """Load strict content-free completion receipts in stable evidence order.

    Strict: one malformed record aborts the load. Use :func:`scan_hook_receipts`
    for a sweep that must survive a single bad record and still report it.
    """

    root = receipt_root.expanduser().resolve()
    if not root.exists():
        return ()
    loaded: list[dict[str, Any]] = []
    for path in sorted(root.rglob("completed.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HookReceiptError(f"cannot read completed hook receipt {path}: {exc}") from exc
        reason = validate_completed_receipt(payload, path)
        if reason is not None:
            if reason.startswith("invalid '"):
                field_name = reason.split("'")[1]
                raise HookReceiptError(f"completed hook receipt has invalid {field_name!r}: {path}")
            if reason.startswith("invalid contract identity"):
                raise HookReceiptError(f"completed hook receipt has invalid contract identity: {path}")
            if reason.startswith("path/identity"):
                raise HookReceiptError(f"completed hook receipt path/identity mismatch: {path}")
            raise HookReceiptError(f"completed hook receipt must be an object: {path}")
        loaded.append(payload)
    return tuple(loaded)


@dataclass(frozen=True)
class MalformedReceipt:
    """One receipt file the sweep could not trust, kept as reportable evidence."""

    path: Path
    reason: str
    hook_name: str | None
    phase: str
    # Untrusted values read off the bad record. Never counted in the health
    # table; reported only so a systematic defect class is visible instead of
    # silently subtracting real outcomes from the totals.
    salvaged: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReceiptScan:
    """Resilient sweep result: what parsed, what did not, and what never finished."""

    root: Path
    completed: tuple[dict[str, Any], ...] = ()
    malformed: tuple[MalformedReceipt, ...] = ()
    orphaned_starts: tuple[dict[str, Any], ...] = ()
    started_count: int = 0
    started_by_hook: dict[str, int] = dataclasses_field(default_factory=dict)
    receipt_dir_count: int = 0

    @property
    def malformed_count(self) -> int:
        return len(self.malformed)


def _read_json(path: Path) -> tuple[Any, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except OSError as exc:
        return None, f"unreadable file ({exc.__class__.__name__}: {exc.strerror or exc})"
    except json.JSONDecodeError as exc:
        return None, f"unparseable JSON ({exc.msg} at line {exc.lineno})"


def scan_hook_receipts(receipt_root: Path = DEFAULT_RECEIPT_ROOT) -> ReceiptScan:
    """Sweep every receipt directory without letting one bad record abort the run.

    A malformed record is *not* swallowed: it is retained in
    :attr:`ReceiptScan.malformed` with its exact path and defect reason so the
    caller must report it. A started receipt with no sibling completion is
    retained as an orphan, which the invocation contract treats as proof of
    interruption.
    """

    root = receipt_root.expanduser().resolve()
    scan_root = root
    if not root.exists():
        return ReceiptScan(root=scan_root)

    completed: list[dict[str, Any]] = []
    malformed: list[MalformedReceipt] = []
    orphans: list[dict[str, Any]] = []
    started_count = 0
    started_hooks: Counter = Counter()
    receipt_dirs: set[Path] = set()

    for started_path in sorted(root.rglob("started.json")):
        receipt_dirs.add(started_path.parent)
        payload, read_error = _read_json(started_path)
        if read_error is not None:
            malformed.append(MalformedReceipt(path=started_path, reason=read_error, hook_name=None, phase="started"))
            continue
        if not isinstance(payload, dict):
            malformed.append(
                MalformedReceipt(
                    path=started_path,
                    reason="receipt is not a JSON object",
                    hook_name=None,
                    phase="started",
                )
            )
            continue
        started_count += 1
        started_hooks[str(payload.get("hook_name") or "<unknown>")] += 1
        if not (started_path.parent / "completed.json").exists():
            orphans.append({**payload, "receipt_path": str(started_path)})

    for completed_path in sorted(root.rglob("completed.json")):
        receipt_dirs.add(completed_path.parent)
        payload, read_error = _read_json(completed_path)
        if read_error is not None:
            malformed.append(
                MalformedReceipt(path=completed_path, reason=read_error, hook_name=None, phase="completed")
            )
            continue
        reason = validate_completed_receipt(payload, completed_path)
        if reason is not None:
            hook_name = payload.get("hook_name") if isinstance(payload, dict) else None
            salvaged = None
            if isinstance(payload, dict):
                salvaged = {key: payload.get(key) for key in ("decision", "reason_code", "exit_status", "hook_version")}
            malformed.append(
                MalformedReceipt(
                    path=completed_path,
                    reason=reason,
                    hook_name=hook_name if isinstance(hook_name, str) and hook_name.strip() else None,
                    phase="completed",
                    salvaged=salvaged,
                )
            )
            continue
        completed.append({**payload, "receipt_path": str(completed_path)})

    return ReceiptScan(
        root=scan_root,
        completed=tuple(completed),
        malformed=tuple(malformed),
        orphaned_starts=tuple(orphans),
        started_count=started_count,
        started_by_hook=dict(started_hooks),
        receipt_dir_count=len(receipt_dirs),
    )


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


# --- Declared hook timeouts -------------------------------------------------


@dataclass(frozen=True)
class DeclaredHookCommand:
    """One hook command registered in a settings file, with its declared budget."""

    settings_path: Path
    event_name: str
    matcher: str | None
    command: str
    script_path: Path | None
    script_sha256: str | None
    timeout_seconds: int | None

    @property
    def effective_timeout_seconds(self) -> int:
        return self.timeout_seconds if self.timeout_seconds is not None else HARNESS_DEFAULT_TIMEOUT_SECONDS


# Only a path-like token is a hook script; a bare "origin/main:scripts/x.py"
# revspec argument inside a command is not a file to fingerprint.
_SCRIPT_IN_COMMAND = re.compile(r"(?<![\w:/.-])((?:~|\.{1,2})?/[^\s'\"]*\.py)")


def load_declared_hook_commands(
    settings_paths: tuple[Path, ...] = DEFAULT_SETTINGS_PATHS,
) -> tuple[tuple[DeclaredHookCommand, ...], tuple[str, ...]]:
    """Read hook command declarations and their timeouts from settings files.

    Returns the declarations plus non-fatal notes (missing or unreadable
    settings, hook scripts that no longer exist). Nothing here is silently
    dropped; every skipped input produces a note the caller must surface.
    """

    commands: list[DeclaredHookCommand] = []
    notes: list[str] = []
    for raw_path in settings_paths:
        path = raw_path.expanduser()
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            notes.append(f"settings unreadable, timeouts from it are unknown: {path} ({exc})")
            continue
        hooks = settings.get("hooks") if isinstance(settings, dict) else None
        if not isinstance(hooks, dict):
            notes.append(f"settings has no 'hooks' object: {path}")
            continue
        for event_name, matchers in hooks.items():
            if not isinstance(matchers, list):
                continue
            for matcher_entry in matchers:
                if not isinstance(matcher_entry, dict):
                    continue
                matcher = matcher_entry.get("matcher")
                for hook_entry in matcher_entry.get("hooks") or ():
                    if not isinstance(hook_entry, dict):
                        continue
                    command = str(hook_entry.get("command") or "")
                    timeout = hook_entry.get("timeout")
                    script_path: Path | None = None
                    script_sha: str | None = None
                    found = _SCRIPT_IN_COMMAND.search(command)
                    if found:
                        candidate = Path(os.path.expanduser(found.group(1)))
                        script_path = candidate
                        try:
                            script_sha = hashlib.sha256(candidate.read_bytes()).hexdigest()
                        except OSError:
                            script_sha = None
                            notes.append(f"hook script not readable, cannot fingerprint: {candidate} ({event_name})")
                    commands.append(
                        DeclaredHookCommand(
                            settings_path=path,
                            event_name=str(event_name),
                            matcher=str(matcher) if matcher is not None else None,
                            command=command,
                            script_path=script_path,
                            script_sha256=script_sha,
                            timeout_seconds=int(timeout) if isinstance(timeout, int) else None,
                        )
                    )
    return tuple(commands), tuple(notes)


def match_declared_timeouts(
    receipts: tuple[dict[str, Any], ...],
    declared: tuple[DeclaredHookCommand, ...],
) -> dict[str, dict[str, Any]]:
    """Bind emitting hook names to declared timeouts via recorded script digests.

    Receipts record `hook_sha256` of the script that ran, so a hook name is
    matched to a settings entry by content fingerprint rather than by a
    hand-maintained name table. A hook whose recorded digests no longer match
    any installed script is reported as unmatched, never guessed.
    """

    by_sha: dict[str, list[DeclaredHookCommand]] = {}
    for command in declared:
        if command.script_sha256:
            by_sha.setdefault(command.script_sha256, []).append(command)

    result: dict[str, dict[str, Any]] = {}
    digests: dict[str, Counter] = {}
    for receipt in receipts:
        name = str(receipt["hook_name"])
        sha = receipt.get("hook_sha256")
        digests.setdefault(name, Counter())[str(sha)] += 1

    for name, counter in digests.items():
        matches: list[DeclaredHookCommand] = []
        for sha, _count in counter.most_common():
            matches.extend(by_sha.get(sha, ()))
        if not matches:
            result[name] = {
                "matched": False,
                "declared_timeout_ms": None,
                "declared_timeouts_ms": [],
                "events": [],
                "match_basis": "no installed hook script matches any recorded script digest",
                "distinct_script_digests": len(counter),
            }
            continue
        timeouts = sorted({command.effective_timeout_seconds * 1000 for command in matches})
        result[name] = {
            "matched": True,
            # Strictest declared budget wins: that is the one that can kill the hook.
            "declared_timeout_ms": timeouts[0],
            "declared_timeouts_ms": timeouts,
            "events": sorted({command.event_name for command in matches}),
            "script": str(matches[0].script_path) if matches[0].script_path else None,
            "timeout_declared_explicitly": any(command.timeout_seconds is not None for command in matches),
            "match_basis": "recorded hook_sha256 matches installed hook script",
            "distinct_script_digests": len(counter),
        }
    return result


# --- Latency / failure summary ----------------------------------------------


def percentile_nearest_rank(values: list[float], percentile: float) -> float:
    """Nearest-rank percentile over an already-collected sample."""

    if not values:
        raise ValueError("percentile of an empty sample is undefined")
    if not 0 < percentile <= 100:
        raise ValueError("percentile must be in (0, 100]")
    ordered = sorted(values)
    rank = max(1, math.ceil(percentile / 100 * len(ordered)))
    return ordered[rank - 1]


def summarize_hook_health(
    scan: ReceiptScan,
    *,
    declared: dict[str, dict[str, Any]] | None = None,
    budget_fraction: float = DEFAULT_TIMEOUT_BUDGET_FRACTION,
) -> dict[str, Any]:
    """Per-hook invocation count, latency distribution, exits, and orphaned starts."""

    if not 0 < budget_fraction <= 1:
        raise ValueError("budget_fraction must be in (0, 1]")
    declared = declared or {}

    orphan_counts: Counter = Counter(str(payload.get("hook_name") or "<unknown>") for payload in scan.orphaned_starts)
    completed_totals: Counter = Counter()
    latencies: dict[str, list[float]] = {}
    exits: dict[str, Counter] = {}
    latency_missing: Counter = Counter()

    for receipt in scan.completed:
        name = str(receipt["hook_name"])
        completed_totals[name] += 1
        elapsed = receipt.get("elapsed_ms")
        if isinstance(elapsed, (int, float)) and not isinstance(elapsed, bool):
            latencies.setdefault(name, []).append(float(elapsed))
        else:
            latency_missing[name] += 1
        status = receipt.get("exit_status")
        if isinstance(status, int) and not isinstance(status, bool) and status != 0:
            exits.setdefault(name, Counter())[status] += 1

    malformed_per_hook: Counter = Counter(record.hook_name for record in scan.malformed if record.hook_name)
    names = sorted(set(completed_totals) | set(orphan_counts) | set(scan.started_by_hook))
    hooks: list[dict[str, Any]] = []
    for name in names:
        sample = latencies.get(name, [])
        completed_count = completed_totals[name]
        orphaned = orphan_counts[name]
        declared_entry = declared.get(name, {})
        declared_timeout = declared_entry.get("declared_timeout_ms")
        p95 = percentile_nearest_rank(sample, 95) if sample else None
        budget_ratio = None
        over_budget = None
        if p95 is not None and isinstance(declared_timeout, int) and declared_timeout > 0:
            budget_ratio = p95 / declared_timeout
            over_budget = budget_ratio > budget_fraction
        nonzero = exits.get(name, Counter())
        hooks.append(
            {
                "hook_name": name,
                # Prefer the observed started.json count; fall back to what the
                # completion side proves when no start receipt survives.
                "started_count": scan.started_by_hook.get(name, completed_count + orphaned + malformed_per_hook[name]),
                "completed_count": completed_count,
                "orphaned_start_count": orphaned,
                "malformed_receipt_count": malformed_per_hook[name],
                "latency_sample_size": len(sample),
                "latency_missing_count": latency_missing[name],
                "p50_elapsed_ms": percentile_nearest_rank(sample, 50) if sample else None,
                "p95_elapsed_ms": p95,
                "max_elapsed_ms": max(sample) if sample else None,
                "nonzero_exit_count": sum(nonzero.values()),
                "nonzero_exit_by_code": {str(code): count for code, count in sorted(nonzero.items())},
                "declared_timeout_ms": declared_timeout,
                "declared_timeout_matched": bool(declared_entry.get("matched")),
                "declared_timeout_events": declared_entry.get("events", []),
                "declared_timeout_note": declared_entry.get("match_basis"),
                "p95_fraction_of_declared_timeout": budget_ratio,
                "p95_over_budget": over_budget,
            }
        )

    malformed_by_reason: Counter = Counter()
    malformed_examples: dict[str, str] = {}
    malformed_by_hook: Counter = Counter()
    malformed_salvage: Counter = Counter()
    for record in scan.malformed:
        key = f"{record.phase}: {record.reason}"
        malformed_by_reason[key] += 1
        malformed_examples.setdefault(key, str(record.path))
        malformed_by_hook[record.hook_name or "<unidentifiable>"] += 1
        if record.salvaged:
            malformed_salvage[
                "{hook} decision={decision} reason={reason} exit={exit}".format(
                    hook=record.hook_name or "<unidentifiable>",
                    decision=record.salvaged.get("decision"),
                    reason=record.salvaged.get("reason_code"),
                    exit=record.salvaged.get("exit_status"),
                )
            ] += 1

    return {
        "schema_version": 1,
        "record_type": "hook_invocation_health_report",
        "receipt_root": str(scan.root),
        "budget_fraction": budget_fraction,
        "receipt_dir_count": scan.receipt_dir_count,
        "started_receipt_count": scan.started_count,
        "completed_receipt_count": len(scan.completed),
        "orphaned_start_count": len(scan.orphaned_starts),
        "malformed_receipt_count": scan.malformed_count,
        "malformed_by_reason": [
            {
                "reason": reason,
                "count": count,
                "example_path": malformed_examples[reason],
            }
            for reason, count in malformed_by_reason.most_common()
        ],
        "malformed_by_hook": dict(malformed_by_hook.most_common()),
        "malformed_uncounted_outcomes": [
            {"outcome": outcome, "count": count} for outcome, count in malformed_salvage.most_common()
        ],
        "hooks": hooks,
    }
