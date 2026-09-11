from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.codex_session_integrity import create_recovery_bundle, find_session_file, inspect_session_jsonl

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


def test_interrupted_json_record_does_not_hide_later_valid_records(tmp_path: Path) -> None:
    session = tmp_path / "interrupted.jsonl"
    first = b'{"type":"session_meta"}\n'
    interrupted = b'{"type":"event_msg","payload":{"type":"item_completed","item":{"type":"CommandExecution","output":"cut off\n'
    final = b'{"type":"response_item","payload":{"type":"message"}}\n'
    session.write_bytes(first + interrupted + final)

    report = inspect_session_jsonl(session)

    assert [issue.kind for issue in report.issues] == ["invalid_json"]
    assert report.issues[0].line == 2
    assert report.records_scanned == 3


def test_hook_emits_context_and_metadata_only_report_for_corruption(tmp_path: Path) -> None:
    session = tmp_path / "rollout-session-abc.jsonl"
    session.write_bytes(b'{"type":"session_meta"}\n\0\0\n')
    report = tmp_path / "report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(HOOK),
            "--session-file",
            str(session),
            "--report",
            str(report),
            "--recovery-root",
            str(tmp_path / "recovery"),
        ],
        input=json.dumps({"session_id": "session-abc", "hook_event_name": "SessionStart"}),
        text=True,
        capture_output=True,
        check=True,
    )

    payload = json.loads(completed.stdout)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["continue"] is False
    assert payload["stopReason"].startswith("Malformed Codex session history")
    assert payload["systemMessage"] == context
    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "line 2, byte offset" in context
    assert "nul_only_record" in context
    assert "did not modify" in context
    assert "current turn was stopped" in context
    assert "Recovery bundle:" in context
    assert "READY_TO_PASTE.md" in context
    assert "Paste: Recover the interrupted Codex task" in context
    assert "Do not edit session logs or Codex SQLite databases" in context
    assert session.read_bytes() == b'{"type":"session_meta"}\n\0\0\n'
    assert json.loads(report.read_text(encoding="utf-8"))["issues"][0]["kind"] == "nul_only_record"


def test_metadata_only_diagnostic_does_not_require_hook_event(tmp_path: Path) -> None:
    session = tmp_path / "rollout-session-abc.jsonl"
    session.write_bytes(b'{"type":"session_meta"}\n\0\0\n')
    report = tmp_path / "report.json"

    completed = subprocess.run(
        [sys.executable, str(HOOK), "--session-file", str(session), "--report", str(report)],
        input="",
        text=True,
        capture_output=True,
        check=True,
    )

    assert completed.stdout == ""
    assert completed.stderr == ""
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


def test_recovery_bundle_preserves_source_and_omits_only_bad_records(tmp_path: Path) -> None:
    session = tmp_path / "rollout-session-abc.jsonl"
    source = (
        b'{"type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"hello"}]}}\n'
        b"\0\0\n"
        b'{"type":"response_item","payload":{"type":"message","role":"assistant","phase":"final_answer","content":[{"type":"output_text","text":"hi"}]}}\n'
    )
    session.write_bytes(source)

    bundle = create_recovery_bundle(session, session_id="session-abc", recovery_root=tmp_path / "recovery")

    assert bundle.name.startswith("auto-")
    assert (bundle / "original-snapshot.jsonl").read_bytes() == source
    assert b"\0" not in (bundle / "sanitized-archive.jsonl").read_bytes()
    transcript = (bundle / "transcript.md").read_text(encoding="utf-8")
    assert "## User" in transcript and "hello" in transcript
    assert "## Assistant (final_answer)" in transcript and "hi" in transcript
    assert "Do not replace the live rollout" in (bundle / "HANDOFF.md").read_text(encoding="utf-8")
    prompt = (bundle / "READY_TO_PASTE.md").read_text(encoding="utf-8")
    assert "Paste this into a fresh Codex session" in prompt
    assert str(bundle) in prompt
    assert "Do not edit session logs or Codex SQLite databases" in prompt
    report = json.loads((bundle / "integrity-report.json").read_text(encoding="utf-8"))
    assert report["issues"][0]["line"] == 2

    repeated = create_recovery_bundle(session, session_id="session-abc", recovery_root=tmp_path / "recovery")
    assert repeated == bundle


def test_recovery_bundle_reuses_stable_incident_after_rollout_growth(tmp_path: Path) -> None:
    session = tmp_path / "rollout-session-abc.jsonl"
    original = b'{"type":"session_meta"}\n\0\0\n'
    session.write_bytes(original)
    first = create_recovery_bundle(session, session_id="session-abc", recovery_root=tmp_path / "recovery")

    session.write_bytes(original + b'{"type":"response_item","payload":{}}\n')
    repeated = create_recovery_bundle(session, session_id="session-abc", recovery_root=tmp_path / "recovery")

    assert repeated == first
    assert (first / "original-snapshot.jsonl").read_bytes() == original
    assert len(list((tmp_path / "recovery" / "session-abc").glob("auto-*"))) == 1


def test_recovery_bundle_discovers_legacy_digest_named_incident(tmp_path: Path) -> None:
    session = tmp_path / "rollout-session-abc.jsonl"
    original = b'{"type":"session_meta"}\n\0\0\n'
    session.write_bytes(original)
    first = create_recovery_bundle(session, session_id="session-abc", recovery_root=tmp_path / "recovery")
    legacy = first.with_name("auto-legacydigest")
    first.rename(legacy)
    session.write_bytes(original + b'{"type":"response_item","payload":{}}\n')

    repeated = create_recovery_bundle(session, session_id="session-abc", recovery_root=tmp_path / "recovery")

    assert repeated == legacy
    assert len(list(legacy.parent.glob("auto-*"))) == 1
