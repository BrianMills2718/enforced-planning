"""Tests for truth-surface status rendering."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.check_truth_surface_drift import Issue
from scripts.render_truth_surface_status import _load_issue_payload, render_status


def test_render_nonempty_summary() -> None:
    issues = [
        Issue(
            code="audit_claim_mismatch",
            severity="fail",
            message="Claimed adopted does not match blocked.",
            evidence={},
        ),
        Issue(
            code="tracker_next_action_already_active",
            severity="warn",
            message="Tracker says create worktree but one is already active.",
            evidence={},
        ),
    ]

    rendered = render_status(issues)

    assert "Truth Surface Status" in rendered
    assert "- Overall: fail" in rendered
    assert "- Issues: 2" in rendered
    assert "- Fail: 1" in rendered
    assert "- Warn: 1" in rendered
    assert "[FAIL] audit_claim_mismatch" in rendered
    assert "[WARN] tracker_next_action_already_active" in rendered


def test_render_clean_summary() -> None:
    rendered = render_status([])

    assert rendered == "Truth Surface Status\n- Overall: clean\n- Issues: 0\n"


def test_load_issue_payload(tmp_path: Path) -> None:
    payload = tmp_path / "issues.json"
    payload.write_text(
        json.dumps(
            {
                "issues": [
                    {
                        "code": "consumed_reservation_missing_plan_file",
                        "severity": "fail",
                        "message": "Missing plan file.",
                        "evidence": {"plan": 73},
                    }
                ]
            }
        )
    )

    issues = _load_issue_payload(payload)

    assert len(issues) == 1
    assert issues[0].code == "consumed_reservation_missing_plan_file"
    assert issues[0].severity == "fail"
