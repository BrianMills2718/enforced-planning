"""Contract tests for content-free hook invocation telemetry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts.hook_feedback_report import build_report
from scripts.hook_receipts import (
    HookReceiptError,
    group_hook_recurrences,
    group_prewrite_recurrences,
    load_completed_receipts,
    load_declared_hook_commands,
    match_declared_timeouts,
    percentile_nearest_rank,
    scan_hook_receipts,
    scan_prewrite_events,
    start_hook_invocation,
    summarize_hook_health,
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


def test_completed_receipt_accepts_bounded_scalar_details(tmp_path: Path) -> None:
    invocation = start_hook_invocation(
        hook_name="example-hook",
        hook_version="7",
        script_path=Path(__file__),
        payload={"session_id": "private-session", "hook_event_name": "PostToolUse"},
        receipt_root=tmp_path,
    )

    invocation.complete(
        decision="allow",
        reason_code="no_exact_session_target",
        details={"status": "not_applicable", "attempt": 1, "visible": False},
    )

    completed = json.loads((invocation.receipt_dir / "completed.json").read_text())
    assert completed["details"] == {
        "status": "not_applicable",
        "attempt": 1,
        "visible": False,
    }


@pytest.mark.parametrize(
    "details, message",
    [
        ({"nested": {"raw": "payload"}}, "must be a scalar"),
        ({"long": "x" * 257}, "exceeds 256 characters"),
        ({f"key-{index}": index for index in range(13)}, "exceed 12 fields"),
    ],
)
def test_completed_receipt_rejects_unbounded_details(
    tmp_path: Path, details: dict[str, object], message: str
) -> None:
    invocation = start_hook_invocation(
        hook_name="example-hook",
        hook_version="7",
        script_path=Path(__file__),
        payload={"session_id": "private-session", "hook_event_name": "PostToolUse"},
        receipt_root=tmp_path,
    )

    with pytest.raises(HookReceiptError, match=message):
        invocation.complete(decision="allow", reason_code="test", details=details)


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


def test_hook_feedback_report_includes_recurrent_prewrite_failures(tmp_path: Path) -> None:
    receipts = tmp_path / "hook-receipts"
    prewrite = tmp_path / "prewrite-events.jsonl"
    _write_receipt(receipts, "session", "a" * 32)
    events = [
        {
            "schema_version": "1.0",
            "receipt_id": f"prewrite_{index}",
            "client": "codex",
            "mode": "enforce",
            "decision": "deny",
            "reason_code": "bash_runtime_workdir_unattested",
            "recorded_at": f"2026-09-01T00:00:0{index}Z",
            "details": ["private path must stay in the source receipt"],
            "session_id": "private-session",
        }
        for index in (1, 2)
    ]
    prewrite.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    report = build_report(
        receipt_root=receipts,
        prewrite_event_path=prewrite,
        threshold=2,
        settings_paths=(),
        budget_fraction=0.6,
    )

    recurrence = report["prewrite_recurrence"]
    assert recurrence["event_count"] == 2
    assert recurrence["groups"] == [
        {
            "client": "codex",
            "mode": "enforce",
            "decision": "deny",
            "reason_code": "bash_runtime_workdir_unattested",
            "count": 2,
            "recurrent": True,
            "receipt_ids": ["prewrite_1", "prewrite_2"],
            "disposition_command": "make ecosystem-feedback ARGS='record ...'",
        }
    ]
    assert "private path" not in json.dumps(report)
    assert "private-session" not in json.dumps(report)


def test_prewrite_scan_reports_malformed_lines_without_hiding_valid_events(tmp_path: Path) -> None:
    prewrite = tmp_path / "prewrite-events.jsonl"
    valid = {
        "schema_version": "1.0",
        "receipt_id": "prewrite_valid",
        "client": "codex",
        "mode": "enforce",
        "decision": "deny",
        "reason_code": "no_exact_session_target",
        "recorded_at": "2026-09-01T00:00:00Z",
    }
    prewrite.write_text(json.dumps(valid) + "\n{not json\n", encoding="utf-8")

    scan = scan_prewrite_events(prewrite)
    grouped = group_prewrite_recurrences(scan, threshold=1)

    assert grouped["event_count"] == 1
    assert grouped["malformed_count"] == 1
    assert grouped["groups"][0]["receipt_ids"] == ["prewrite_valid"]
    assert grouped["malformed"][0]["line"] == 2
    assert "unparseable JSON" in grouped["malformed"][0]["reason"]


def _write_receipt(root: Path, session: str, receipt_id: str, **overrides: object) -> Path:
    """Write one completed receipt directly so defects can be injected exactly."""

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
    directory = root / session / receipt_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "completed.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory / "completed.json"


def _write_start(root: Path, session: str, receipt_id: str, **overrides: object) -> Path:
    payload: dict[str, object] = {
        "schema_version": 1,
        "record_type": "hook_invocation_receipt",
        "receipt_id": receipt_id,
        "hook_name": "example-hook",
        "hook_version": "2",
        "hook_sha256": "0" * 64,
        "phase": "started",
        "decision": None,
        "reason_code": None,
        "event_name": "Stop",
        "exit_status": None,
        "elapsed_ms": 0.0,
        "observed_at": "2026-08-31T00:00:00+00:00",
    }
    payload.update(overrides)
    directory = root / session / receipt_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "started.json").write_text(json.dumps(payload), encoding="utf-8")
    return directory / "started.json"


def test_scan_counts_malformed_receipt_instead_of_aborting(tmp_path: Path) -> None:
    """The regression that made this tool useless: one bad record killed the sweep."""

    _write_receipt(tmp_path, "session-a", "a" * 32)
    _write_receipt(tmp_path, "session-a", "b" * 32)
    bad_null = _write_receipt(tmp_path, "session-a", "c" * 32, event_name=None)
    bad_json = tmp_path / "session-a" / ("d" * 32) / "completed.json"
    bad_json.parent.mkdir(parents=True)
    bad_json.write_text("{not json", encoding="utf-8")

    # The strict loader still refuses the whole store...
    with pytest.raises(HookReceiptError):
        load_completed_receipts(tmp_path)

    # ...but the sweep completes and reports the defects.
    scan = scan_hook_receipts(tmp_path)
    assert len(scan.completed) == 2
    assert scan.malformed_count == 2
    reasons = {record.path: record.reason for record in scan.malformed}
    assert reasons[bad_null].startswith("invalid 'event_name'")
    assert "unparseable JSON" in reasons[bad_json]


def test_scan_reports_malformed_outcomes_it_refused_to_count(tmp_path: Path) -> None:
    """A malformed record must not silently subtract a real failure from the totals."""

    _write_receipt(tmp_path, "s", "a" * 32, exit_status=0)
    _write_receipt(
        tmp_path,
        "s",
        "b" * 32,
        event_name=None,
        decision="block",
        reason_code="substantive_next_without_human",
        exit_status=2,
    )

    scan = scan_hook_receipts(tmp_path)
    summary = summarize_hook_health(scan)

    assert summary["malformed_receipt_count"] == 1
    assert summary["malformed_by_hook"] == {"example-hook": 1}
    uncounted = summary["malformed_uncounted_outcomes"]
    assert uncounted[0]["count"] == 1
    assert "decision=block" in uncounted[0]["outcome"]
    assert "exit=2" in uncounted[0]["outcome"]
    hook = summary["hooks"][0]
    assert hook["nonzero_exit_count"] == 0
    assert hook["malformed_receipt_count"] == 1
    # No started.json in this fixture, so the start count falls back to what the
    # completion side proves: the good record plus the malformed one.
    assert hook["started_count"] == 2


def test_scan_counts_orphaned_starts_as_interruption_evidence(tmp_path: Path) -> None:
    _write_start(tmp_path, "s", "a" * 32)
    _write_receipt(tmp_path, "s", "a" * 32)
    _write_start(tmp_path, "s", "b" * 32)  # never completed

    scan = scan_hook_receipts(tmp_path)
    assert scan.started_count == 2
    assert len(scan.orphaned_starts) == 1
    summary = summarize_hook_health(scan)
    hook = summary["hooks"][0]
    assert hook["started_count"] == 2
    assert hook["completed_count"] == 1
    assert hook["orphaned_start_count"] == 1


def test_summarize_reports_latency_and_nonzero_exit_breakdown(tmp_path: Path) -> None:
    for index, (elapsed, status) in enumerate([(1.0, 0), (2.0, 0), (3.0, 1), (4.0, 1), (100.0, 2)]):
        _write_receipt(
            tmp_path,
            "s",
            f"{index:032d}",
            elapsed_ms=elapsed,
            exit_status=status,
        )

    hook = summarize_hook_health(scan_hook_receipts(tmp_path))["hooks"][0]
    assert hook["completed_count"] == 5
    assert hook["p50_elapsed_ms"] == 3.0
    assert hook["p95_elapsed_ms"] == 100.0
    assert hook["max_elapsed_ms"] == 100.0
    assert hook["nonzero_exit_count"] == 3
    assert hook["nonzero_exit_by_code"] == {"1": 2, "2": 1}


def test_percentile_nearest_rank_is_exact() -> None:
    sample = [float(value) for value in range(1, 101)]
    assert percentile_nearest_rank(sample, 50) == 50.0
    assert percentile_nearest_rank(sample, 95) == 95.0
    assert percentile_nearest_rank([7.0], 95) == 7.0
    with pytest.raises(ValueError):
        percentile_nearest_rank([], 50)


def test_declared_timeout_binds_by_script_digest_and_flags_budget(tmp_path: Path) -> None:
    script = tmp_path / "some_hook.py"
    script.write_text("print('hook')\n", encoding="utf-8")
    digest = hashlib.sha256(script.read_bytes()).hexdigest()
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "Stop": [
                        {"matcher": "*", "hooks": [{"type": "command", "command": f"python3 {script}", "timeout": 3}]}
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    receipts = tmp_path / "receipts"
    for index, elapsed in enumerate([10.0, 20.0, 2500.0]):
        _write_receipt(receipts, "s", f"{index:032d}", elapsed_ms=elapsed, hook_sha256=digest)

    commands, notes = load_declared_hook_commands((settings,))
    assert notes == ()
    declared = match_declared_timeouts(scan_hook_receipts(receipts).completed, commands)
    assert declared["example-hook"]["declared_timeout_ms"] == 3000
    assert declared["example-hook"]["events"] == ["Stop"]

    hook = summarize_hook_health(scan_hook_receipts(receipts), declared=declared, budget_fraction=0.6)["hooks"][0]
    assert hook["declared_timeout_ms"] == 3000
    assert hook["p95_elapsed_ms"] == 2500.0
    assert hook["p95_over_budget"] is True


def test_declared_timeout_unmatched_is_reported_not_guessed(tmp_path: Path) -> None:
    _write_receipt(tmp_path, "s", "a" * 32)
    declared = match_declared_timeouts(scan_hook_receipts(tmp_path).completed, ())
    assert declared["example-hook"]["matched"] is False
    assert declared["example-hook"]["declared_timeout_ms"] is None
    hook = summarize_hook_health(scan_hook_receipts(tmp_path), declared=declared)["hooks"][0]
    assert hook["p95_over_budget"] is None
