"""Tests for the truth-surface drift validator."""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from scripts.check_truth_surface_drift import run_checks


def _write(path: Path, content: str) -> None:
    path.write_text(textwrap.dedent(content).lstrip())


def test_missing_plan_file_for_consumed_reservation_fails(tmp_path: Path) -> None:
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [],
                "plan_reservations": [
                    {
                        "status": "consumed",
                        "plan": 73,
                        "plan_file": str(tmp_path / "missing-plan.md"),
                    }
                ],
            }
        )
    )
    plan_index = tmp_path / "CLAUDE.md"
    _write(
        plan_index,
        """
        # Implementation Plans
        | # | Gap | Priority | Status | Blocks |
        |---|-----|----------|--------|--------|
        | 73 | Example | High | 📋 Planned | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: nothing")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "surfaces": {
                    "tracker_file": str(tracker),
                    "registry_file": str(registry),
                    "plan_index_file": str(plan_index),
                },
                "checks": {
                    "consumed_reservations_exist": {"severity": "fail"},
                    "no_active_work_for_complete_plans": False,
                },
            }
        )
    )

    issues = run_checks(config)

    assert len(issues) == 1
    assert issues[0].code == "consumed_reservation_missing_plan_file"
    assert issues[0].severity == "fail"


def test_active_work_for_complete_plan_fails(tmp_path: Path) -> None:
    existing_plan = tmp_path / "plan-1.md"
    existing_plan.write_text("# plan")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [
                    {
                        "status": "active",
                        "project": "demo",
                        "scope": "wave-x",
                        "plan": 2,
                    }
                ],
                "plan_reservations": [
                    {"status": "consumed", "plan": 1, "plan_file": str(existing_plan)}
                ],
            }
        )
    )
    plan_index = tmp_path / "CLAUDE.md"
    _write(
        plan_index,
        """
        # Implementation Plans
        | # | Gap | Priority | Status | Blocks |
        |---|-----|----------|--------|--------|
        | 2 | Example | High | ✅ Complete | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: nothing")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "surfaces": {
                    "tracker_file": str(tracker),
                    "registry_file": str(registry),
                    "plan_index_file": str(plan_index),
                },
                "checks": {
                    "consumed_reservations_exist": {"severity": "fail"},
                    "no_active_work_for_complete_plans": {"severity": "fail"},
                },
            }
        )
    )

    issues = run_checks(config)

    assert len(issues) == 1
    assert issues[0].code == "active_work_references_complete_plan"
    assert issues[0].severity == "fail"


def test_tracker_pattern_conflict_warns(tmp_path: Path) -> None:
    existing_plan = tmp_path / "plan-1.md"
    existing_plan.write_text("# plan")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [
                    {
                        "status": "active",
                        "project": "agentic_scaffolding",
                        "scope": "authoritative-coordination-wave9",
                        "plan": 8,
                    }
                ],
                "plan_reservations": [
                    {"status": "consumed", "plan": 1, "plan_file": str(existing_plan)}
                ],
            }
        )
    )
    plan_index = tmp_path / "CLAUDE.md"
    _write(
        plan_index,
        """
        # Implementation Plans
        | # | Gap | Priority | Status | Blocks |
        |---|-----|----------|--------|--------|
        | 8 | Example | High | 🚧 In Progress | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("Next action: create the agentic_scaffolding worktree and begin rollout.")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "surfaces": {
                    "tracker_file": str(tracker),
                    "registry_file": str(registry),
                    "plan_index_file": str(plan_index),
                },
                "checks": {
                    "consumed_reservations_exist": {"severity": "fail"},
                    "no_active_work_for_complete_plans": {"severity": "fail"},
                    "tracker_next_action_claim_conflicts": {
                        "rules": [
                            {
                                "tracker_pattern": "create the agentic_scaffolding worktree",
                                "project": "agentic_scaffolding",
                                "scope": "authoritative-coordination-wave9",
                                "severity": "warn",
                            }
                        ]
                    },
                },
            }
        )
    )

    issues = run_checks(config)

    assert len(issues) == 1
    assert issues[0].code == "tracker_next_action_already_active"
    assert issues[0].severity == "warn"
