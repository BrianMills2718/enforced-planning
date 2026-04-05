"""Tests for truth-surface status rendering."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.check_truth_surface_drift import Issue
from scripts.render_truth_surface_status import _load_issue_payload, render_status
from scripts.truth_surface_semantic_models import SemanticReviewReport


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


def test_render_with_semantic_findings_keeps_certainty_split() -> None:
    issues = [
        Issue(
            code="consumed_reservation_missing_plan_file",
            severity="fail",
            message="Missing plan file.",
            evidence={},
        )
    ]
    semantic_report = SemanticReviewReport.model_validate(
        {
            "overview": "One advisory semantic warning remains.",
            "findings": [
                {
                    "category": "stale_prose",
                    "severity": "warn",
                    "summary": "Tracker prose is stale.",
                    "rationale": "The tracker still reads like the prior phase is active.",
                    "evidence_refs": ["docs/ops/TRACKER.md"],
                    "promotion_candidate": True,
                    "promotion_rule_hint": "active tracker should not describe a completed phase as current",
                }
            ],
        }
    )

    rendered = render_status(issues, semantic_report=semantic_report)

    assert "- Overall: fail" in rendered
    assert "- Semantic Review: warn" in rendered
    assert "- Semantic Promotion Candidates: 1" in rendered
    assert "Semantic Advisory Findings" in rendered
    assert "[WARN] stale_prose" in rendered


def test_renderer_cli_runs_outside_repo_root(tmp_path: Path) -> None:
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: nothing")
    plan_index = tmp_path / "CLAUDE.md"
    plan_index.write_text(
        "# Implementation Plans\n| # | Gap | Priority | Status | Blocks |\n|---|-----|----------|--------|--------|\n"
    )
    registry = tmp_path / "registry.yaml"
    registry.write_text("active_work: []\nplan_reservations: []\n")
    config = tmp_path / "config.yaml"
    config.write_text(
        json.dumps({
            "surfaces": {
                "tracker_file": str(tracker),
                "registry_file": str(registry),
                "plan_index_file": str(plan_index),
            },
            "checks": {
                "consumed_reservations_exist": {"severity": "fail"},
                "no_active_work_for_complete_plans": {"severity": "fail"},
            },
        })
    )

    script_path = Path(__file__).resolve().parents[1] / "scripts" / "render_truth_surface_status.py"

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--config",
            str(config),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )

    assert "Truth Surface Status" in result.stdout
    assert "- Overall: clean" in result.stdout


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
