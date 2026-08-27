from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.codex_session_integrity import find_session_file, inspect_session_jsonl

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "codex_session_integrity_hook.py"


def test_clean_jsonl_has_no_issues(tmp_path: Path) -> None:
    session = tmp_path / "clean.jsonl"
    session.write_bytes(b'{"type":"session_meta"}\n{"type":"message"}\n')

    report = inspect_session_jsonl(session)

    assert report.is_clean
    assert report.records_scanned == 2
    assert report.file_size_bytes == session.stat().st_size


def test_nul_only_record_reports_exact_line_and_offset(tmp_path: Path) -> None:
    session = tmp_path / "broken.jsonl"
    first = b'{"type":"session_meta"}\n'
    session.write_bytes(first + b"\0\0\0\0\n" + b'{"type":"message"}\n')

    report = inspect_session_jsonl(session)

    assert [issue.kind for issue in report.issues] == ["nul_only_record"]
    assert report.issues[0].line == 2
    assert report.issues[0].byte_offset == len(first)
    assert report.records_scanned == 3


def test_hook_emits_context_and_metadata_only_report_for_corruption(tmp_path: Path) -> None:
    session = tmp_path / "rollout-session-abc.jsonl"
    session.write_bytes(b'{"type":"session_meta"}\n\0\0\n')
    report = tmp_path / "report.json"

    completed = subprocess.run(
        [sys.executable, str(HOOK), "--session-file", str(session), "--report", str(report)],
        input=json.dumps({"session_id": "session-abc", "hook_event_name": "SessionStart"}),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "line 2, byte offset" in context
    assert "nul_only_record" in context
    assert "did not modify" in context
    assert session.read_bytes() == b'{"type":"session_meta"}\n\0\0\n'
    assert json.loads(report.read_text(encoding="utf-8"))["issues"][0]["kind"] == "nul_only_record"


def test_hook_is_silent_for_clean_file(tmp_path: Path) -> None:
    session = tmp_path / "clean.jsonl"
    session.write_text('{"type":"session_meta"}\n', encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(HOOK), "--session-file", str(session)],
        input=json.dumps({"session_id": "clean", "hook_event_name": "SessionStart"}),
        text=True,
        capture_output=True,
        check=True,
    )

    assert completed.stdout == ""


def test_finder_uses_filename_without_reading_history_payload(tmp_path: Path) -> None:
    target = tmp_path / "2026" / "08" / "rollout-session-abc.jsonl"
    target.parent.mkdir(parents=True)
    target.write_text('{"not":"searched"}\n', encoding="utf-8")

    assert find_session_file(tmp_path, "session-abc") == target
