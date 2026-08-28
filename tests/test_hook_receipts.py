"""Contract tests for content-free hook invocation telemetry."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.hook_receipts import start_hook_invocation


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
