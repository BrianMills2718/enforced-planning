"""Tests for the truth-surface drift validator."""

from __future__ import annotations

import textwrap
from pathlib import Path

import yaml

from scripts.check_truth_surface_drift import _canonical_repo_name, _canonical_repo_root, run_checks


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


def test_scope_derives_canonical_name_from_worktree_repo_root() -> None:
    assert _canonical_repo_name("/tmp/projects/prompt_eval") == "prompt_eval"
    assert (
        _canonical_repo_name("/tmp/projects/prompt_eval_worktrees/plan-15-truth-surface-pilot")
        == "prompt_eval"
    )


def test_scope_derives_canonical_root_from_worktree_repo_root() -> None:
    assert _canonical_repo_root("/tmp/projects/prompt_eval") == Path("/tmp/projects/prompt_eval")
    assert _canonical_repo_root(
        "/tmp/projects/prompt_eval_worktrees/plan-15-truth-surface-pilot"
    ) == Path("/tmp/projects/prompt_eval")


def test_scope_filters_by_canonical_repo_identity(tmp_path: Path) -> None:
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [
                    {
                        "status": "active",
                        "project": "agentic_scaffolding",
                        "repo_root": "/tmp/projects/agentic_scaffolding_worktrees/plan-08-authoritative-coordination-wave9",
                        "plan": 8,
                    }
                ],
                "plan_reservations": [
                    {
                        "status": "consumed",
                        "plan": 14,
                        "project": "plan-60-prompt-eval-coordination",
                        "repo_root": "/tmp/projects/prompt_eval_worktrees/plan-60-prompt-eval-coordination",
                        "plan_file": "/tmp/projects/prompt_eval_worktrees/plan-60-prompt-eval-coordination/docs/plans/14_authoritative-coordination-wave-1-rollout.md",
                    },
                    {
                        "status": "consumed",
                        "plan": 73,
                        "project": "plan-58-authoritative-registry-rollout",
                        "repo_root": "/tmp/projects/project-meta_worktrees/plan-58-authoritative-registry-rollout",
                        "plan_file": "/tmp/projects/project-meta_worktrees/plan-58-authoritative-registry-rollout/docs/plans/73_authoritative-coordination-wave-9-rollout.md",
                    },
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
        | 8 | Example | High | ✅ Complete | None |
        | 14 | Example | High | ✅ Complete | None |
        | 73 | Example | High | ✅ Complete | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: nothing")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "scope": {"repo_names": ["prompt_eval"]},
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
    assert issues[0].code == "consumed_reservation_missing_plan_file"
    assert issues[0].evidence["canonical_repo"] == "prompt_eval"


def test_historical_unlanded_consumed_reservation_warns_by_default(tmp_path: Path) -> None:
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [],
                "plan_reservations": [
                    {
                        "status": "consumed",
                        "plan": 14,
                        "project": "plan-60-prompt-eval-coordination",
                        "repo_root": "/tmp/projects/prompt_eval_worktrees/plan-60-prompt-eval-coordination",
                        "lineage_state": "historical-unlanded",
                        "historical_plan_file": "docs/plans/14_authoritative-coordination-wave-1-rollout.md",
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
        | 14 | Example | High | ✅ Complete | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: nothing")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "scope": {"repo_names": ["prompt_eval"]},
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
    assert issues[0].code == "historical_unlanded_consumed_reservation"
    assert issues[0].severity == "warn"


def test_relative_landed_plan_file_resolves_against_canonical_repo_root(tmp_path: Path) -> None:
    canonical_repo = tmp_path / "prompt_eval"
    plan_file = canonical_repo / "docs" / "plans" / "15_semantic-truth-surface-review-pilot.md"
    plan_file.parent.mkdir(parents=True)
    plan_file.write_text("# plan\n")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [],
                "plan_reservations": [
                    {
                        "status": "consumed",
                        "plan": 15,
                        "project": "plan-16-semantic-truth-surface-pilot",
                        "repo_root": str(
                            tmp_path
                            / "prompt_eval_worktrees"
                            / "plan-16-semantic-truth-surface-pilot"
                        ),
                        "lineage_state": "landed",
                        "plan_file": "docs/plans/15_semantic-truth-surface-review-pilot.md",
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
        | 15 | Example | High | ✅ Complete | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("next action: nothing")
    config = tmp_path / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "scope": {"repo_names": ["prompt_eval"]},
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

    assert issues == []


def test_relative_surface_paths_resolve_from_config_dir(tmp_path: Path) -> None:
    config_dir = tmp_path / "pilot"
    config_dir.mkdir()
    existing_plan = config_dir / "plan-1.md"
    existing_plan.write_text("# plan")
    registry = config_dir / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [],
                "plan_reservations": [
                    {"status": "consumed", "plan": 1, "plan_file": str(existing_plan)}
                ],
            }
        )
    )
    plan_index = config_dir / "CLAUDE.md"
    _write(
        plan_index,
        """
        # Implementation Plans
        | # | Gap | Priority | Status | Blocks |
        |---|-----|----------|--------|--------|
        | 1 | Example | High | 📋 Planned | None |
        """,
    )
    tracker = config_dir / "tracker.md"
    tracker.write_text("Governed audit status: PASS")
    audit = config_dir / "audit.json"
    audit.write_text('{"status": "PASS"}')
    config = config_dir / "config.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "surfaces": {
                    "tracker_file": "tracker.md",
                    "registry_file": "registry.yaml",
                    "plan_index_file": "CLAUDE.md",
                },
                "checks": {
                    "consumed_reservations_exist": {"severity": "fail"},
                    "no_active_work_for_complete_plans": {"severity": "fail"},
                    "audit_claim_rules": {
                        "rules": [
                            {
                                "source_pattern": r"Governed audit status: (?P<claim>\\w+)",
                                "audit_file": "audit.json",
                                "audit_json_path": "status",
                                "severity": "fail",
                            }
                        ]
                    },
                },
            }
        )
    )

    issues = run_checks(config)

    assert issues == []


def test_audit_claim_mismatch_fails(tmp_path: Path) -> None:
    existing_plan = tmp_path / "plan-1.md"
    existing_plan.write_text("# plan")
    registry = tmp_path / "registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "active_work": [],
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
        | 1 | Example | High | 📋 Planned | None |
        """,
    )
    tracker = tmp_path / "tracker.md"
    tracker.write_text("agentic_scaffolding adoption state: adopted")
    audit = tmp_path / "audit.json"
    audit.write_text(
        '{"repo_results": {"agentic_scaffolding": {"coordination_adoption_state": "blocked"}}}'
    )
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
                    "audit_claim_rules": {
                        "rules": [
                            {
                                "source_pattern": r"agentic_scaffolding adoption state: (?P<claim>\w+)",
                                "audit_file": str(audit),
                                "audit_json_path": "repo_results.agentic_scaffolding.coordination_adoption_state",
                                "severity": "fail",
                            }
                        ]
                    },
                },
            }
        )
    )

    issues = run_checks(config)

    assert len(issues) == 1
    assert issues[0].code == "audit_claim_mismatch"
    assert issues[0].severity == "fail"
