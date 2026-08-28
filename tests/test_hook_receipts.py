"""Contract tests for content-free hook invocation telemetry."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.hook_receipts import (
    HookReceiptError,
    group_hook_recurrences,
    load_completed_receipts,
    start_hook_invocation,
)


def test_started_then_completed_receipts_are_correlatable(tmp_path: Path) -> None:
    invocation = start_hook_invocation(
        hook_name="example-hook",
        hook_version="7",
        script_path=Path(__file__),
        payload={
            "session_id": "secret-session-id",
            "hookRunId": "stop:18:/config.toml",
            "hook_event_name": "Stop",
            "last_assistant_message": "private report text",
        },
        receipt_root=tmp_path,
    )

    started = json.loads((invocation.receipt_dir / "started.json").read_text())
    assert started["phase"] == "started"
    assert started["hook_run_id"] == "stop:18:/config.toml"
    assert "secret-session-id" not in json.dumps(started)
    assert "private report text" not in json.dumps(started)

    invocation.complete(decision="allow", reason_code="terminal")
    completed = json.loads((invocation.receipt_dir / "completed.json").read_text())
    assert completed["receipt_id"] == started["receipt_id"]
    assert completed["decision"] == "allow"
    assert completed["elapsed_ms"] >= 0


def test_hook_feedback_report_groups_recurrence_and_steps_down(tmp_path: Path) -> None:
    for hook_run_id in ("stop:1:/config.toml", "stop:2:/config.toml"):
        invocation = start_hook_invocation(
            hook_name="coordination-lifecycle",
            hook_version="2",
            script_path=Path(__file__),
            payload={
                "session_id": "private-session",
                "hook_run_id": hook_run_id,
                "hook_event_name": "Stop",
                "last_assistant_message": "private content",
            },
            receipt_root=tmp_path,
        )
        invocation.complete(decision="block", reason_code="repository_closeout_unavailable")

    report = group_hook_recurrences(load_completed_receipts(tmp_path))

    assert report["receipt_count"] == 2
    assert report["groups"][0]["recurrent"] is True
    assert len(report["groups"][0]["receipt_ids"]) == 2
    assert "private" not in json.dumps(report)
    assert "ecosystem-feedback" in report["groups"][0]["disposition_command"]


def test_hook_feedback_report_rejects_invalid_completed_receipt(tmp_path: Path) -> None:
    invalid = tmp_path / "session" / "receipt-id" / "completed.json"
    invalid.parent.mkdir(parents=True)
    invalid.write_text('{"phase":"completed"}\n', encoding="utf-8")

    with pytest.raises(HookReceiptError, match="invalid 'schema_version'"):
        load_completed_receipts(tmp_path)
