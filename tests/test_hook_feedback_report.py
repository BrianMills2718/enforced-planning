"""CLI contract for the hook feedback report.

The bug this file exists for: one malformed receipt aborted the entire sweep,
so the report had never once run against the live store.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.hook_feedback_report import build_report, main


def _receipt(root: Path, receipt_id: str, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "record_type": "hook_invocation_receipt",
        "receipt_id": receipt_id,
        "hook_name": "example-hook",
        "hook_version": "2",
        "hook_sha256": "0" * 64,
        "phase": "completed",
        "decision": "allow",
        "reason_code": "ok",
        "event_name": "Stop",
        "exit_status": 0,
        "elapsed_ms": 5.0,
        "observed_at": "2026-08-31T00:00:00+00:00",
    }
    payload.update(overrides)
    directory = root / "session" / receipt_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "completed.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_reports_malformed_receipts_without_aborting(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipts = tmp_path / "receipts"
    _receipt(receipts, "a" * 32)
    _receipt(receipts, "b" * 32)
    _receipt(receipts, "c" * 32, event_name=None, decision="block", exit_status=2)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    exit_code = main(["--receipt-root", str(receipts), "--settings", str(settings), "--format", "text"])
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "1 receipts skipped as malformed" in output
    assert "invalid 'event_name'" in output
    assert "example-hook" in output
    # The record it refused to trust is still visible as an outcome, not erased.
    assert "decision=block" in output


def test_cli_strict_mode_exits_nonzero_on_malformed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipts = tmp_path / "receipts"
    _receipt(receipts, "a" * 32)
    _receipt(receipts, "b" * 32, event_name=None)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    exit_code = main(["--receipt-root", str(receipts), "--settings", str(settings), "--strict"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "1 receipts skipped as malformed" in captured.out
    assert "strict mode" in captured.err


def test_cli_json_format_carries_health_and_recurrence(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    receipts = tmp_path / "receipts"
    _receipt(receipts, "a" * 32)
    _receipt(receipts, "b" * 32)
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")

    exit_code = main(["--receipt-root", str(receipts), "--settings", str(settings), "--format", "json"])
    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["record_type"] == "hook_feedback_report"
    assert report["health"]["completed_receipt_count"] == 2
    assert report["health"]["hooks"][0]["p95_elapsed_ms"] == 5.0
    assert report["recurrence"]["groups"][0]["count"] == 2


def test_report_on_absent_receipt_root_is_empty_not_an_error(tmp_path: Path) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    report = build_report(
        receipt_root=tmp_path / "missing",
        threshold=2,
        settings_paths=(settings,),
        budget_fraction=0.6,
    )
    assert report["health"]["completed_receipt_count"] == 0
    assert report["health"]["malformed_receipt_count"] == 0
    assert report["health"]["hooks"] == []


def test_report_never_contains_private_payload_content(tmp_path: Path) -> None:
    receipts = tmp_path / "receipts"
    _receipt(receipts, "a" * 32, reason_code="ok")
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({"hooks": {}}), encoding="utf-8")
    report = build_report(
        receipt_root=receipts,
        threshold=2,
        settings_paths=(settings,),
        budget_fraction=0.6,
    )
    assert "last_assistant_message" not in json.dumps(report)
    assert "session_id" not in json.dumps(report)
