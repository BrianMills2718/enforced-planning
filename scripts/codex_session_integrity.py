"""Read-only integrity checks for Codex JSONL session records.

The Codex host owns session persistence.  This module deliberately never
rewrites, truncates, or moves a session file: it only reports records that a
normal JSONL reader cannot safely consume.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_RECORD_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class SessionIntegrityIssue:
    """One malformed JSONL record with its safe, reproducible location."""

    line: int
    byte_offset: int
    kind: str
    detail: str


@dataclass(frozen=True)
class SessionIntegrityReport:
    """Portable report that contains metadata, never conversation content."""

    schema_version: int
    session_file: str
    records_scanned: int
    file_size_bytes: int
    issues: tuple[SessionIntegrityIssue, ...]

    @property
    def is_clean(self) -> bool:
        return not self.issues

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "session_file": self.session_file,
            "records_scanned": self.records_scanned,
            "file_size_bytes": self.file_size_bytes,
            "issues": [asdict(issue) for issue in self.issues],
        }


def inspect_session_jsonl(session_file: Path) -> SessionIntegrityReport:
    """Inspect ``session_file`` without modifying it or reading it as text.

    Binary iteration preserves the byte offset even when a record is invalid
    UTF-8 or made solely of NUL bytes.  The result intentionally omits record
    contents because hook output becomes model context.
    """

    resolved = session_file.expanduser().resolve()
    issues: list[SessionIntegrityIssue] = []
    records_scanned = 0
    offset = 0
    with resolved.open("rb") as handle:
        for line_number, raw_record in enumerate(handle, start=1):
            records_scanned += 1
            record_offset = offset
            offset += len(raw_record)
            record = raw_record.rstrip(b"\r\n")
            if not record:
                issues.append(SessionIntegrityIssue(line_number, record_offset, "blank_record", "record is empty"))
                continue
            if len(record) > MAX_RECORD_BYTES:
                issues.append(
                    SessionIntegrityIssue(
                        line_number,
                        record_offset,
                        "oversized_record",
                        f"record exceeds {MAX_RECORD_BYTES} bytes",
                    )
                )
                continue
            if all(value == 0 for value in record):
                issues.append(SessionIntegrityIssue(line_number, record_offset, "nul_only_record", "record contains only NUL bytes"))
                continue
            if b"\0" in record:
                issues.append(SessionIntegrityIssue(line_number, record_offset, "nul_byte", "record contains a NUL byte"))
                continue
            try:
                decoded = record.decode("utf-8")
            except UnicodeDecodeError as exc:
                issues.append(SessionIntegrityIssue(line_number, record_offset, "invalid_utf8", str(exc)))
                continue
            try:
                payload = json.loads(decoded)
            except json.JSONDecodeError as exc:
                issues.append(SessionIntegrityIssue(line_number, record_offset, "invalid_json", exc.msg))
                continue
            if not isinstance(payload, dict):
                issues.append(SessionIntegrityIssue(line_number, record_offset, "non_object_record", "JSONL record is not an object"))
    return SessionIntegrityReport(
        schema_version=1,
        session_file=str(resolved),
        records_scanned=records_scanned,
        file_size_bytes=offset,
        issues=tuple(issues),
    )


def find_session_file(sessions_root: Path, session_id: str) -> Path | None:
    """Find a host session file by the session ID appearing in its filename.

    This does not search conversation payloads.  A missing filename match is
    intentionally inconclusive rather than an excuse to scan every history
    record at SessionStart.
    """

    if not session_id or any(character in session_id for character in "/\\\0"):
        raise ValueError("session ID is not a safe filename token")
    root = sessions_root.expanduser().resolve()
    if not root.is_dir():
        return None
    matches = sorted(path for path in root.rglob("*.jsonl") if session_id in path.name)
    return matches[-1] if matches else None
