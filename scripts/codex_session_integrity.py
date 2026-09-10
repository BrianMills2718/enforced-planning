"""Read-only integrity checks for Codex JSONL session records.

The Codex host owns session persistence.  This module deliberately never
rewrites, truncates, or moves a session file: it only reports records that a
normal JSONL reader cannot safely consume.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write_once(path: Path, data: bytes) -> None:
    """Create ``path`` atomically, or verify an identical existing artifact."""

    if path.exists():
        if path.read_bytes() != data:
            raise FileExistsError(f"recovery artifact already exists with different contents: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if path.read_bytes() != data:
                raise FileExistsError(f"recovery artifact concurrently created with different contents: {path}")
    finally:
        temporary.unlink(missing_ok=True)


def _message_text(payload: dict[str, object]) -> str:
    content = payload.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())
    return "\n\n".join(parts)


def _render_transcript(session_id: str, sanitized_records: list[dict[str, object]], issue_lines: set[int]) -> str:
    lines = [
        "# Recovered Codex transcript",
        "",
        f"Session: `{session_id}`",
        "",
        "This readable projection contains surviving user and assistant messages only.",
        f"Malformed physical record lines omitted: {', '.join(str(line) for line in sorted(issue_lines))}.",
        "",
    ]
    for record in sanitized_records:
        if record.get("type") != "response_item":
            continue
        payload = record.get("payload")
        if not isinstance(payload, dict) or payload.get("type") != "message":
            continue
        role = payload.get("role")
        if role not in {"user", "assistant"}:
            continue
        text = _message_text(payload)
        if not text:
            continue
        label = "User" if role == "user" else "Assistant"
        phase = payload.get("phase")
        if role == "assistant" and isinstance(phase, str):
            label += f" ({phase})"
        lines.extend((f"## {label}", "", text, ""))
    return "\n".join(lines)


def _matching_existing_bundle(
    *,
    session_root: Path,
    issue: SessionIntegrityIssue,
) -> Path | None:
    """Find a complete legacy digest-named bundle for the same corruption incident."""

    required_artifacts = {
        "original-snapshot.jsonl",
        "sanitized-archive.jsonl",
        "transcript.md",
        "integrity-report.json",
        "HANDOFF.md",
        "READY_TO_PASTE.md",
    }
    for report_path in sorted(session_root.glob("auto-*/integrity-report.json")):
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        issues = payload.get("issues") if isinstance(payload, dict) else None
        first = issues[0] if isinstance(issues, list) and issues else None
        if not isinstance(first, dict):
            continue
        identity = (first.get("line"), first.get("byte_offset"), first.get("kind"))
        if identity != (issue.line, issue.byte_offset, issue.kind):
            continue
        bundle = report_path.parent
        if all((bundle / artifact).is_file() for artifact in required_artifacts):
            return bundle
    return None


def create_recovery_bundle(
    session_file: Path,
    *,
    session_id: str,
    recovery_root: Path,
) -> Path:
    """Preserve a corrupt rollout and derive safe create-once artifacts."""

    resolved = session_file.expanduser().resolve()
    live_report = inspect_session_jsonl(resolved)
    if live_report.is_clean:
        raise ValueError("recovery bundle requires at least one malformed record")
    first_issue = live_report.issues[0]
    session_root = recovery_root.expanduser().resolve() / session_id
    existing = _matching_existing_bundle(session_root=session_root, issue=first_issue)
    if existing is not None:
        return existing
    incident_material = "\0".join(
        (
            session_id,
            str(first_issue.line),
            str(first_issue.byte_offset),
            first_issue.kind,
        )
    )
    incident_id = hashlib.sha256(incident_material.encode("utf-8")).hexdigest()[:12]
    bundle = session_root / f"auto-{incident_id}"
    bundle.mkdir(parents=True, exist_ok=True)

    snapshot = bundle / "original-snapshot.jsonl"
    if not snapshot.exists():
        live_source_sha256 = _sha256(resolved)
        temporary = bundle / f".original-snapshot.{os.getpid()}.tmp"
        shutil.copyfile(resolved, temporary)
        if _sha256(temporary) != live_source_sha256:
            temporary.unlink(missing_ok=True)
            raise OSError("session rollout changed while the recovery snapshot was being created")
        try:
            os.link(temporary, snapshot)
        except FileExistsError:
            pass
        finally:
            temporary.unlink(missing_ok=True)
    # The first snapshot is immutable incident evidence. A growing host rollout
    # for the same malformed physical record reuses it instead of copying each
    # successively larger file into a new bundle.
    source_sha256 = _sha256(snapshot)

    report = inspect_session_jsonl(snapshot)
    if report.is_clean:
        raise ValueError("recovery bundle requires at least one malformed record")
    issue_lines = {issue.line for issue in report.issues}
    sanitized_bytes: list[bytes] = []
    sanitized_records: list[dict[str, object]] = []
    with snapshot.open("rb") as handle:
        for line_number, raw_record in enumerate(handle, start=1):
            if line_number in issue_lines:
                continue
            sanitized_bytes.append(raw_record)
            decoded = raw_record.rstrip(b"\r\n").decode("utf-8")
            payload = json.loads(decoded)
            if isinstance(payload, dict):
                sanitized_records.append(payload)

    _atomic_write_once(bundle / "sanitized-archive.jsonl", b"".join(sanitized_bytes))
    transcript = _render_transcript(session_id, sanitized_records, issue_lines)
    _atomic_write_once(bundle / "transcript.md", transcript.encode("utf-8"))

    report_payload = report.as_dict()
    report_payload.update(
        {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "session_id": session_id,
            "incident_id": incident_id,
            "source_sha256": source_sha256,
            "sanitized_records": len(sanitized_records),
        }
    )
    report_path = bundle / "integrity-report.json"
    if not report_path.exists():
        report_bytes = (json.dumps(report_payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
        _atomic_write_once(report_path, report_bytes)

    handoff = (
        "# Codex session recovery handoff\n\n"
        f"Session `{session_id}` contains malformed JSONL records and must not be trusted after reload.\n\n"
        "- `original-snapshot.jsonl` is the untouched evidence copy.\n"
        "- `sanitized-archive.jsonl` omits only the malformed physical records.\n"
        "- `transcript.md` is a readable user/assistant projection.\n"
        "- `integrity-report.json` records exact line, offset, category, and source digest.\n\n"
        "Continue in a fresh Codex thread. Do not replace the live rollout or manually edit Codex SQLite databases.\n"
    )
    _atomic_write_once(bundle / "HANDOFF.md", handoff.encode("utf-8"))
    ready_to_paste = (
        "# Paste this into a fresh Codex session\n\n"
        f"Recover the interrupted Codex task from `{bundle}`.\n\n"
        "Read `HANDOFF.md` first, then `integrity-report.json` and `transcript.md`. "
        "Treat the original session log and `original-snapshot.jsonl` as immutable evidence. "
        "Do not edit session logs or Codex SQLite databases. Reconstruct the current task state "
        "from the handoff, repository instructions, active plan/worktree, and transcript. "
        "State what is known and unknown, then continue the unfinished task without repeating "
        f"completed work. The interrupted session ID is `{session_id}`.\n"
    )
    _atomic_write_once(bundle / "READY_TO_PASTE.md", ready_to_paste.encode("utf-8"))
    return bundle
