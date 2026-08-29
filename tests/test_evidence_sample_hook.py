"""The gate must be a real detector in both directions.

A gate not observed failing on known-bad input is not evidence; a gate not
observed passing on known-good input is not evidence either. The hook carries
its cases inline so the check travels with it into any installed repo.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / "scripts" / "evidence_sample_hook.py"


def _run(report: str, *, stop_hook_active: bool = False) -> subprocess.CompletedProcess:
    payload = {
        "hook_event_name": "Stop",
        "session_id": "test",
        "last_assistant_message": report,
        "stop_hook_active": stop_hook_active,
    }
    return subprocess.run(
        [sys.executable, str(HOOK), "--agent", "claude-code"],
        input=json.dumps(payload), capture_output=True, text=True,
    )


def test_the_built_in_self_test_passes():
    done = subprocess.run(
        [sys.executable, str(HOOK), "--self-test"], capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr


def test_it_blocks_the_report_that_produced_a_wrong_diagnosis():
    """Verbatim shape of the ac16 report of 2026-08-25 whose conclusion was withdrawn."""
    result = _run(
        "- **Done** — measured the rate at 0 of 4.\n"
        "- **Concerns** — 20 mismatches in m3, 16 in m1.\n"
        "- **Next** — report the dominant class."
    )
    assert result.returncode == 2
    assert "does not show what any of them looked like" in result.stderr


def test_it_allows_the_same_report_once_a_sample_is_shown():
    result = _run(
        "- **Done** — measured the rate at 0 of 4.\n"
        "- **Concerns** — 20 mismatches in m3. One example: case bad-ts, "
        "expected detail 'now is not a valid timestamp', actual 'invalid timestamp format'.\n"
        "- **Next** — the comparator is grading free text."
    )
    assert result.returncode == 0, result.stderr


def test_a_refired_stop_is_never_blocked_again():
    report = (
        "- **Done** — measured it.\n"
        "- **Concerns** — 20 mismatches remain without a sample."
    )

    first = _run(report)
    repeated = _run(report, stop_hook_active=True)

    assert first.returncode == 2
    assert repeated.returncode == 0
    assert repeated.stderr == ""


def test_a_malformed_payload_fails_open():
    """This gate must never strand a session."""
    result = subprocess.run(
        [sys.executable, str(HOOK)], input="not json", capture_output=True, text=True
    )
    assert result.returncode == 0
